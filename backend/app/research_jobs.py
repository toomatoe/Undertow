"""One research subprocess at a time, with durable, bounded public status.

Designed for the application's single API process. CLI output stays in server
logs; commands and arguments cannot be supplied by clients.
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

log = logging.getLogger(__name__)
MODULES = {"backtest": "app.backtest.report", "event_study": "app.research.eventstudy"}


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
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                saved = json.load(f)
            self.latest.update({k: saved.get(k) for k in MODULES})
        interrupted = False
        for job in self.latest.values():
            if job and job["status"] == "running":
                job.update(status="interrupted", finished_at=now(),
                           message="The API restarted before this run finished. You can retry.")
                interrupted = True
        if interrupted:
            self._save()

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
                job["message"] = ("Loading SEC filings and cached prices; running portfolio simulations."
                                  if job["kind"] == "backtest" else
                                  "Loading SEC filings and cached prices; measuring event-study results.")
                self._save()
            code = process.wait()
            if code == 0:
                if job["kind"] == "event_study" and self.on_study_success:
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
