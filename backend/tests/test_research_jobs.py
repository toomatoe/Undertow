import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import main
from app.research_jobs import JobBusy, ResearchJobs, atomic_json


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
    manager = ResearchJobs(tmp_path)
    monkeypatch.setattr(main, "research_jobs", manager)
    client = TestClient(main.app)
    response = client.post("/api/research/jobs/backtest")
    assert response.status_code == 202
    assert client.get("/api/research/jobs").json()["active"]["id"] == response.json()["id"]
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
