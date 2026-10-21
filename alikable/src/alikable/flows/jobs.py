"""
A project's background jobs: their status for the UI, and their results for the Chat
Agent, which passes each one on once (flows/change_router.py).

A job runs on the runner it is given. Every change to a job calls on_change, which the
project uses to save its session.json (flows/project.py).
"""

import threading
from collections.abc import Callable
from concurrent.futures import Executor
from typing import Any

from alikable.models import Job, JobKind, utc_now


class Jobs:
    def __init__(self, on_change: Callable[[], None] = lambda: None):
        self.on_change = on_change
        self._jobs: list[Job] = []
        self._unreported: list[str] = []   # finished job results the Chat Agent has not passed on
        self._lock = threading.Lock()      # guards _jobs and _unreported

    def start(self, kind: JobKind, title: str, work: Callable[[Job], str], runner: Executor,
              params: dict[str, Any] | None = None) -> Job:
        """Queue work on the runner. params are what started it, so retry can start it again."""
        job = Job(kind=kind, title=title, params=params or {})
        with self._lock:
            self._jobs.append(job)
        self.on_change()
        runner.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[[Job], str]) -> None:
        self.update(job, status="running")
        try:
            result = work(job)
        except Exception as e:
            self.update(job, status="failed", step="", error=str(e))
            report = f"{job.title} (job {job.id}) failed: {e}"
        else:
            self.update(job, status="done", step="", result=result)
            report = f"{job.title} (job {job.id}) finished: {result}"
        with self._lock:
            self._unreported.append(report)

    def update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for field, value in changes.items():
                setattr(job, field, value)
            job.updated_at = utc_now()
        self.on_change()

    def all(self) -> list[Job]:
        """Copies of every job, oldest first."""
        with self._lock:
            return [j.model_copy() for j in self._jobs]

    def get(self, job_id: str) -> Job | None:
        return next((j for j in self.all() if j.id == job_id), None)

    def latest(self, *kinds: JobKind) -> Job | None:
        """The newest job of one of these kinds."""
        return next((j for j in reversed(self.all()) if j.kind in kinds), None)

    def restore(self, jobs: list[Job]) -> None:
        """Jobs saved in an earlier app run. Open ones can't continue, so they become interrupted."""
        with self._lock:
            self._jobs = [j.model_copy(update={"status": "interrupted", "step": ""}) if j.is_open else j
                          for j in jobs]

    def for_chat(self) -> str:
        """Open jobs and new results, as text for the Chat Agent. New results count as reported."""
        with self._lock:
            open_jobs = [f"- {j.title} (job {j.id}): {j.status}" + (f", now on the {j.step}" if j.step else "")
                         for j in self._jobs if j.is_open]
            finished, self._unreported = self._unreported, []
        parts = []
        if open_jobs:
            parts.append("Still open:\n" + "\n".join(open_jobs))
        if finished:
            parts.append("Finished since the last message:\n" + "\n\n".join(finished))
        return "\n\n".join(parts) or "None"
