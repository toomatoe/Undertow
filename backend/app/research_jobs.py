"""One research subprocess at a time, with durable, bounded public status.

Designed for the application's single API process. CLI output stays in server
logs; commands and arguments cannot be supplied by clients. Saved status is
validated on load: an unreadable or corrupt state file is moved aside
(research_jobs.json.corrupt-<timestamp>) and the API starts with empty status.
Who may start a run is decided by the API layer (see research_launch_policy in
app/main.py).
"""

import copy
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from typing import Literal

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
# Fixed command per kind; clients choose a kind, never a command. Only a successful
# "event_study" run reloads the live evidence (on_study_success): the OOS study writes
# event_study_oos.json and the insider study its own file, neither is served as evidence.
MODULES = {
    "backtest": "app.backtest.report",
    "event_study": "app.research.eventstudy",
    "event_study_oos": "app.research.oos",
    "insider_study": "app.insiders.study",
}
EVIDENCE_KIND = "event_study"
RUNNING_MESSAGES = {
    "backtest": "Loading SEC filings and cached prices; running portfolio simulations.",
    "event_study": "Loading SEC filings and cached prices; measuring event-study results.",
    "event_study_oos": "Loading SEC filings and cached prices; measuring the pre-registered out-of-sample study.",
    "insider_study": "Loading insider filings and cached prices; measuring insider-study results.",
}
JOB_FIELDS = ("id", "kind", "status", "started_at", "finished_at", "message")
MAX_MESSAGE = 500


class SavedJob(BaseModel):
    """Shape check for persisted jobs. Mirrors schemas.ResearchJob but accepts every kind in MODULES
    (the API schema may list fewer kinds than this runner supports)."""

    id: str
    kind: str
    status: Literal["running", "succeeded", "failed", "interrupted"]
    started_at: datetime
    finished_at: datetime | None
    message: str


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            temporary = f.name
            json.dump(value, f, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def now():
    return datetime.now(timezone.utc).isoformat()


class JobBusy(Exception):
    pass


class ResearchJobs:
    def __init__(self, data_dir, on_study_success=None):
        self.data_dir = str(Path(data_dir).resolve())
        self.path = Path(self.data_dir) / "research_jobs.json"
        self.on_study_success = on_study_success
        self.lock = threading.Lock()
        self.process = None
        self.thread = None
        self.closing = False
        self.latest = dict.fromkeys(MODULES)
        dirty = self._load()
        for job in self.latest.values():
            if job and job["status"] == "running":
                job.update(status="interrupted", finished_at=now(),
                           message="The API restarted before this run finished. You can retry.")
                dirty = True
        if dirty:
            try:
                self._save()
            except (OSError, ValueError):
                log.exception("Could not persist research status at startup")

    def _load(self):
        """Fill self.latest from disk. Returns True when the file should be rewritten."""
        try:
            with self.path.open(encoding="utf-8") as f:
                saved = json.load(f)
        except FileNotFoundError:
            return False
        except (OSError, ValueError) as exc:  # ValueError covers JSON and Unicode decode errors
            log.warning("Ignoring unreadable research status file %s: %s", self.path, exc)
            self._quarantine()
            return False
        if not isinstance(saved, dict):
            log.warning("Ignoring research status file %s: expected a JSON object", self.path)
            self._quarantine()
            return False
        dirty = False
        for kind in MODULES:
            raw = saved.get(kind)
            if raw is None:
                continue
            job = self._clean(kind, raw)
            if job is None:
                log.warning("Dropping invalid saved %s research status", kind)
                dirty = True
            else:
                self.latest[kind] = job
        return dirty

    @staticmethod
    def _clean(kind, raw):
        """Return a bounded copy of a saved job, or None when it is not a valid job of this kind."""
        if not isinstance(raw, dict) or raw.get("kind") != kind:
            return None
        try:
            SavedJob.model_validate(raw)
        except ValidationError:
            return None
        job = {k: raw.get(k) for k in JOB_FIELDS}
        job["message"] = job["message"][:MAX_MESSAGE]
        return job

    def _quarantine(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            os.replace(self.path, target)
            log.warning("Moved unreadable research status file to %s", target)
        except OSError:
            log.exception("Could not move unreadable research status file aside")

    def _save(self):
        atomic_json(self.path, self.latest)

    def snapshot(self):
        with self.lock:
            active = next((j for j in self.latest.values() if j and j["status"] == "running"), None)
            return copy.deepcopy({"active": active, "latest": self.latest})

    def start(self, kind):
        if kind not in MODULES:
            raise ValueError("Unknown research kind")
        with self.lock:
            if self.closing or any(j and j["status"] == "running" for j in self.latest.values()):
                raise JobBusy("A research run is already active or the API is stopping.")
            job = dict(id=uuid.uuid4().hex, kind=kind, status="running", started_at=now(),
                       finished_at=None, message="Starting research worker.")
            previous = self.latest[kind]
            self.latest[kind] = job
            try:
                self._save()
            except Exception:
                self.latest[kind] = previous
                raise
            self.thread = threading.Thread(target=self._run, args=(job,), daemon=True)
            try:
                self.thread.start()
            except Exception:
                self.thread = None
                job.update(status="failed", finished_at=now(), message="Could not start research. You can retry.")
                self._save()
                raise
            return copy.deepcopy(job)

    def _run(self, job):
        process = None
        status, message = "failed", "Research failed. Check the backend logs, then retry."
        try:
            with self.lock:
                if self.closing:
                    return
                env = os.environ.copy()
                env["DATA_DIR"] = self.data_dir
                self.process = subprocess.Popen(
                    [sys.executable, "-m", MODULES[job["kind"]]],
                    cwd=str(Path(__file__).resolve().parent.parent), env=env,
                    stdin=subprocess.DEVNULL,
                )
                process = self.process
                job["message"] = RUNNING_MESSAGES[job["kind"]]
                self._save()
            code = process.wait()
            if code == 0:
                if job["kind"] == EVIDENCE_KIND and self.on_study_success:
                    self.on_study_success()
                status, message = "succeeded", "Research finished. Results are ready."
        except Exception:
            log.exception("Research worker failed")
            if process and process.poll() is None:
                self._stop_process(process)
        finally:
            with self.lock:
                # Shutdown owns interruption state and must not be overwritten.
                if job["status"] == "running":
                    job.update(status=status, finished_at=now(), message=message)
                    try:
                        self._save()
                    except OSError:
                        log.exception("Could not persist final research status")
                self.process = None

    @staticmethod
    def _stop_process(process):
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def shutdown(self):
        with self.lock:
            self.closing = True
            process, thread = self.process, self.thread
            for job in self.latest.values():
                if job and job["status"] == "running":
                    job.update(status="interrupted", finished_at=now(),
                               message="The API stopped before this run finished. You can retry.")
            try:
                self._save()
            except OSError:
                log.exception("Could not persist interrupted research status")
        if process and process.poll() is None:
            self._stop_process(process)
        if thread:
            thread.join(timeout=6)
