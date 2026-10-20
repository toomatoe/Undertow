import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import main
from app.research_jobs import MODULES, JobBusy, ResearchJobs, atomic_json


class Worker:
    def __init__(self):
        self.done = threading.Event()
        self.started = threading.Event()
        self.code = 0
        self.calls = []
        self.terminated = False

    def launch(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.started.set()
        return self

    def wait(self, timeout=None):
        if not self.done.wait(timeout=timeout if timeout is not None else 5):
            raise subprocess.TimeoutExpired("mock", timeout)
        return self.code

    def poll(self):
        return self.code if self.done.is_set() else None

    def terminate(self):
        self.terminated = True
        self.code = -15
        self.done.set()


@pytest.fixture
def worker(monkeypatch):
    worker = Worker()
    monkeypatch.setattr("app.research_jobs.subprocess.Popen", worker.launch)
    return worker


def finish(manager, worker, code=0):
    worker.code = code
    worker.done.set()
    manager.thread.join(timeout=3)
    assert not manager.thread.is_alive()


def test_success_persists_and_refreshes_study(tmp_path, worker):
    refreshed = []
    manager = ResearchJobs(tmp_path, lambda: refreshed.append(True))
    job = manager.start("event_study")
    assert worker.started.wait(2)
    assert manager.snapshot()["active"]["id"] == job["id"]
    finish(manager, worker)
    assert refreshed == [True]
    saved = ResearchJobs(tmp_path).snapshot()
    assert saved["active"] is None
    assert saved["latest"]["event_study"]["status"] == "succeeded"
    args, kwargs = worker.calls[0]
    assert args[0] == [sys.executable, "-m", "app.research.eventstudy"]
    assert kwargs["env"]["DATA_DIR"] == str(tmp_path.resolve())
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_concurrent_cross_kind_runs_rejected(tmp_path, worker):
    manager = ResearchJobs(tmp_path)
    barrier = threading.Barrier(2)

    def start(kind):
        barrier.wait()
        try:
            return manager.start(kind)
        except JobBusy:
            return None

    with ThreadPoolExecutor(2) as pool:
        jobs = list(pool.map(start, ["backtest", "event_study"]))
    assert sum(job is not None for job in jobs) == 1
    finish(manager, worker)
    assert len(worker.calls) == 1


def test_failure_then_retry(tmp_path, worker):
    manager = ResearchJobs(tmp_path)
    first = manager.start("backtest")
    finish(manager, worker, code=1)
    assert manager.snapshot()["latest"]["backtest"]["status"] == "failed"
    worker.done.clear()
    second = manager.start("backtest")
    assert first["id"] != second["id"]
    finish(manager, worker)
    assert manager.snapshot()["latest"]["backtest"]["status"] == "succeeded"


def test_restart_marks_unfinished_interrupted(tmp_path):
    atomic_json(tmp_path / "research_jobs.json", {
        "backtest": dict(id="old", kind="backtest", status="running", started_at="2026-01-01T00:00:00Z",
                         finished_at=None, message="running"), "event_study": None,
    })
    manager = ResearchJobs(tmp_path)
    assert manager.snapshot()["active"] is None
    job = manager.snapshot()["latest"]["backtest"]
    assert job["status"] == "interrupted" and job["finished_at"]
    assert ResearchJobs(tmp_path).snapshot() == manager.snapshot()


def test_shutdown_terminates_child(tmp_path, worker):
    manager = ResearchJobs(tmp_path)
    manager.start("backtest")
    assert worker.started.wait(2)
    manager.shutdown()
    assert worker.terminated
    assert manager.snapshot()["latest"]["backtest"]["status"] == "interrupted"
    with pytest.raises(JobBusy):
        manager.start("event_study")


def test_spawn_failure_is_safe_and_retryable(tmp_path, monkeypatch, worker):
    def fail(*args, **kwargs):
        raise OSError("private server detail")

    monkeypatch.setattr("app.research_jobs.subprocess.Popen", fail)
    manager = ResearchJobs(tmp_path)
    manager.start("backtest")
    manager.thread.join(2)
    job = manager.snapshot()["latest"]["backtest"]
    assert job["status"] == "failed"
    assert "private" not in job["message"]
    monkeypatch.setattr("app.research_jobs.subprocess.Popen", worker.launch)
    manager.start("backtest")
    finish(manager, worker)


def test_api_start_poll_conflict_and_invalid_kind(tmp_path, worker, monkeypatch):
    launch_settings(monkeypatch)
    manager = ResearchJobs(tmp_path)
    monkeypatch.setattr(main, "research_jobs", manager)
    client = TestClient(main.app)
    response = client.post("/api/research/jobs/backtest")
    assert response.status_code == 202
    status = client.get("/api/research/jobs").json()
    assert status["active"]["id"] == response.json()["id"]
    assert status["enabled"] is True and status["requires_token"] is False
    assert client.post("/api/research/jobs/event_study").status_code == 409
    assert client.post("/api/research/jobs/arbitrary-command").status_code == 422
    finish(manager, worker)
    assert client.get("/api/research/jobs").json()["latest"]["backtest"]["status"] == "succeeded"


def test_atomic_write_preserves_previous_report_on_error(tmp_path, monkeypatch):
    path = tmp_path / "report.json"
    atomic_json(path, {"previous": True})

    def fail(*args):
        raise OSError("replace failed")

    monkeypatch.setattr("app.research_jobs.os.replace", fail)
    with pytest.raises(OSError):
        atomic_json(path, {"new": True})
    assert json.loads(path.read_text()) == {"previous": True}
    assert list(tmp_path.iterdir()) == [path]


def test_persistence_failure_after_spawn_reaps_child(tmp_path, worker, monkeypatch):
    manager = ResearchJobs(tmp_path)
    save = manager._save
    calls = []

    def fail_second_save():
        calls.append(True)
        if len(calls) == 2:
            raise OSError("disk full")
        save()

    monkeypatch.setattr(manager, "_save", fail_second_save)
    manager.start("backtest")
    manager.thread.join(2)
    assert worker.terminated
    assert manager.snapshot()["latest"]["backtest"]["status"] == "failed"
    assert manager.process is None


def test_thread_start_failure_does_not_leave_active_job(tmp_path, monkeypatch):
    def fail(*args):
        raise RuntimeError("cannot start")

    monkeypatch.setattr("app.research_jobs.threading.Thread.start", fail)
    manager = ResearchJobs(tmp_path)
    with pytest.raises(RuntimeError):
        manager.start("backtest")
    assert manager.snapshot()["active"] is None
    assert manager.snapshot()["latest"]["backtest"]["status"] == "failed"


def test_partial_json_serialization_preserves_existing(tmp_path):
    path = tmp_path / "report.json"
    atomic_json(path, {"previous": True})
    recursive = {}
    recursive["cycle"] = recursive
    with pytest.raises(ValueError):
        atomic_json(path, {"partial": "written", "bad": recursive})
    assert json.loads(path.read_text()) == {"previous": True}
    assert list(tmp_path.iterdir()) == [path]


def test_failed_study_does_not_refresh_evidence(tmp_path, worker):
    refreshed = []
    manager = ResearchJobs(tmp_path, lambda: refreshed.append(True))
    manager.start("event_study")
    finish(manager, worker, 1)
    assert refreshed == []


def test_new_study_kinds_have_fixed_modules():
    assert MODULES["event_study_oos"] == "app.research.oos"
    assert MODULES["insider_study"] == "app.insiders.study"
    assert MODULES["event_study"] == "app.research.eventstudy" and MODULES["backtest"] == "app.backtest.report"


@pytest.mark.parametrize("kind", ["event_study_oos", "insider_study", "backtest"])
def test_only_event_study_success_reloads_evidence(tmp_path, worker, kind):
    refreshed = []
    manager = ResearchJobs(tmp_path, lambda: refreshed.append(True))
    manager.start(kind)
    assert worker.started.wait(2)
    finish(manager, worker)
    assert refreshed == []
    assert manager.snapshot()["latest"][kind]["status"] == "succeeded"
    args, _ = worker.calls[0]
    assert args[0] == [sys.executable, "-m", MODULES[kind]]
    # Persisted status of the new kinds survives a restart
    assert ResearchJobs(tmp_path).snapshot()["latest"][kind]["status"] == "succeeded"


def test_unknown_kind_still_rejected(tmp_path, worker):
    with pytest.raises(ValueError):
        ResearchJobs(tmp_path).start("app.research.oos")
    assert worker.calls == []


def test_shutdown_reaps_child_even_when_status_write_fails(tmp_path, worker, monkeypatch):
    manager = ResearchJobs(tmp_path)
    manager.start("backtest")
    assert worker.started.wait(2)
    # Wait for the running phase to be saved before failing shutdown persistence.
    manager.snapshot()

    def fail():
        raise OSError("disk full")

    monkeypatch.setattr(manager, "_save", fail)
    manager.shutdown()
    assert worker.terminated
    assert manager.snapshot()["active"] is None


def launch_settings(monkeypatch, token=None, enabled=None, public="http://localhost:3000"):
    monkeypatch.setattr(main, "research_launch", main.ResearchLaunchSettings(
        _env_file=None, research_admin_token=token, research_jobs_enabled=enabled))
    monkeypatch.setattr(main.settings, "public_base_url", public)


@pytest.mark.parametrize("content", [
    b"\xff\xfe\x00garbage{{",          # undecodable bytes
    b'{"backtest": {"id": "x", "st',     # truncated JSON
    b"[1, 2, 3]",                       # wrong top-level shape
    b'"just a string"',
])
def test_corrupt_state_file_does_not_crash_startup(tmp_path, content):
    path = tmp_path / "research_jobs.json"
    path.write_bytes(content)
    manager = ResearchJobs(tmp_path)
    assert manager.snapshot() == {"active": None, "latest": dict.fromkeys(MODULES)}
    assert not path.exists()
    assert len(list(tmp_path.glob("research_jobs.json.corrupt-*"))) == 1


def test_unreadable_state_path_does_not_crash_startup(tmp_path):
    (tmp_path / "research_jobs.json").mkdir()  # reading a directory raises OSError
    manager = ResearchJobs(tmp_path)
    assert manager.snapshot()["latest"] == dict.fromkeys(MODULES)


def test_invalid_saved_jobs_are_dropped_and_valid_ones_kept(tmp_path):
    good = dict(id="ok", kind="event_study", status="succeeded", started_at="2026-01-01T00:00:00Z",
                finished_at="2026-01-01T00:20:00Z", message="x" * 5000, extra="ignored")
    (tmp_path / "research_jobs.json").write_text(json.dumps({
        "backtest": {"id": "no-status", "kind": "backtest"}, "event_study": good, "rm -rf": {"status": "running"},
    }))
    manager = ResearchJobs(tmp_path)
    latest = manager.snapshot()["latest"]
    assert latest["backtest"] is None
    assert set(latest) == set(MODULES)
    assert latest["event_study"]["id"] == "ok" and "extra" not in latest["event_study"]
    assert len(latest["event_study"]["message"]) == 500
    assert json.loads((tmp_path / "research_jobs.json").read_text())["backtest"] is None


@pytest.mark.parametrize("job", [
    "not a dict",
    {"id": "a", "kind": "event_study", "status": "running", "started_at": "2026-01-01T00:00:00Z",
     "finished_at": None, "message": "kind mismatch"},
    {"id": "a", "kind": "backtest", "status": "exploded", "started_at": "2026-01-01T00:00:00Z",
     "finished_at": None, "message": "bad status"},
    {"id": "a", "kind": "backtest", "status": "failed", "started_at": "not a date",
     "finished_at": None, "message": "bad date"},
])
def test_wrong_shape_jobs_are_dropped(tmp_path, job):
    (tmp_path / "research_jobs.json").write_text(json.dumps({"backtest": job}))
    assert ResearchJobs(tmp_path).snapshot()["latest"]["backtest"] is None


def test_api_launch_disabled_on_public_deployment_without_token(tmp_path, worker, monkeypatch):
    launch_settings(monkeypatch, public="https://undertow.example.com")
    monkeypatch.setattr(main, "research_jobs", ResearchJobs(tmp_path))
    client = TestClient(main.app)
    status = client.get("/api/research/jobs").json()
    assert status["enabled"] is False and status["requires_token"] is False
    assert client.post("/api/research/jobs/backtest").status_code == 403
    assert worker.calls == []


def test_api_explicit_disable_wins_on_local_deployment(tmp_path, worker, monkeypatch):
    launch_settings(monkeypatch, enabled=False)
    monkeypatch.setattr(main, "research_jobs", ResearchJobs(tmp_path))
    assert TestClient(main.app).post("/api/research/jobs/backtest").status_code == 403


def test_api_admin_token_required_when_configured(tmp_path, worker, monkeypatch):
    launch_settings(monkeypatch, token="s3cret-token", public="https://undertow.example.com")
    manager = ResearchJobs(tmp_path)
    monkeypatch.setattr(main, "research_jobs", manager)
    client = TestClient(main.app)
    status = client.get("/api/research/jobs").json()
    assert status["enabled"] is True and status["requires_token"] is True
    assert "s3cret" not in json.dumps(status)
    assert client.post("/api/research/jobs/backtest").status_code == 401
    assert client.post("/api/research/jobs/backtest", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/api/research/jobs/backtest", headers={"Authorization": "s3cret-token"}).status_code == 401
    assert worker.calls == []
    ok = client.post("/api/research/jobs/backtest", headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 202
    finish(manager, worker)


def test_launch_settings_read_environment(monkeypatch):
    monkeypatch.setenv("RESEARCH_JOBS_ENABLED", "")
    monkeypatch.setenv("RESEARCH_ADMIN_TOKEN", "")
    blank = main.ResearchLaunchSettings(_env_file=None)
    assert blank.research_jobs_enabled is None
    monkeypatch.setenv("RESEARCH_JOBS_ENABLED", "true")
    monkeypatch.setenv("RESEARCH_ADMIN_TOKEN", "abc")
    loaded = main.ResearchLaunchSettings(_env_file=None)
    assert loaded.research_jobs_enabled is True
    assert loaded.research_admin_token.get_secret_value() == "abc"
    assert "abc" not in repr(loaded)
