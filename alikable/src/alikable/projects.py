"""
One folder per project (Step A in Documents/PLAN.md).

A project is one website the user builds. It and its chat share one id, the chat_id,
made when the intake form is submitted. Every file the project writes lives in
output/projects/<chat_id>/, so several projects never share a spec, design, build
or checkpoint. Project is the only place that knows those paths; every other module
takes a Project and asks it where a file goes.

Chat memory stays shared in output/memory/, one scope per chat (crew.py).
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from alikable.models import utc_now

PROJECTS = Path("output/projects")
CHAT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")   # also keeps a chat_id from leaving PROJECTS


@dataclass(frozen=True)
class Project:
    chat_id: str

    def __post_init__(self):
        if not CHAT_ID.fullmatch(self.chat_id):
            raise ValueError(f"Not a valid project id: {self.chat_id!r}")

    @property
    def dir(self) -> Path:
        return PROJECTS / self.chat_id

    @property
    def info(self) -> Path:             # title and creation time, for the project picker
        return self.dir / "project.json"

    @property
    def spec_draft(self) -> Path:       # the Spec Writer and Copywriter's output_file (tasks.yaml)
        return self.dir / "site_spec_draft.json"

    @property
    def site_spec(self) -> Path:        # approved at HITL #1; every later crew reads it
        return self.dir / "site_spec.json"

    @property
    def spec_review_log(self) -> Path:
        return self.dir / "spec_review_log.md"

    @property
    def design_dir(self) -> Path:
        return self.dir / "design"

    @property
    def design_json(self) -> Path:      # the Design System Designer's output_file (tasks.yaml)
        return self.design_dir / "design.json"

    @property
    def design_review_log(self) -> Path:
        return self.dir / "design_review_log.md"

    @property
    def site_dir(self) -> Path:         # the build
        return self.dir / "site"

    @property
    def code_review_log(self) -> Path:
        return self.dir / "code_review_log.md"

    @property
    def polish_report(self) -> Path:
        return self.dir / "polish_report.json"

    @property
    def release_zip(self) -> Path:
        return self.dir / "site.zip"

    @property
    def guide(self) -> Path:
        return self.dir / "DEPLOY.md"

    @property
    def checkpoint(self) -> Path:       # the last approved build (site_files.py)
        return self.dir / ".checkpoint"

    def save_info(self, title: str) -> None:
        """Name the project, once, when its intake form is accepted."""
        if self.info.exists():
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        self.info.write_text(json.dumps({"title": title, "created_at": utc_now().isoformat()}, indent=2),
                             encoding="utf-8")

    @property
    def title(self) -> str:
        try:
            return json.loads(self.info.read_text(encoding="utf-8")).get("title") or "Untitled"
        except (OSError, ValueError):
            return "Untitled"

    @property
    def progress(self) -> str:
        """How far the project got, from the files it has written."""
        if self.guide.exists():
            return "deploy guide written"
        if any(self.site_dir.glob("*.html")):
            return "built"
        if self.design_json.exists():
            return "designed"
        if self.site_spec.exists():
            return "spec approved"
        return "intake"

    @property
    def updated_at(self) -> datetime:
        times = [p.stat().st_mtime for p in (self.info, self.site_spec, self.design_json, self.site_dir,
                                             self.polish_report, self.guide) if p.exists()]
        return datetime.fromtimestamp(max(times, default=0), tz=timezone.utc)


class ProjectSummary(BaseModel):
    """One row of the project picker."""

    chat_id: str
    title: str
    progress: str
    updated_at: datetime


def list_projects() -> list[ProjectSummary]:
    """Every project folder, most recently updated first."""
    if not PROJECTS.exists():
        return []
    projects = [Project(d.name) for d in PROJECTS.iterdir() if d.is_dir() and CHAT_ID.fullmatch(d.name)]
    rows = [ProjectSummary(chat_id=p.chat_id, title=p.title, progress=p.progress, updated_at=p.updated_at)
            for p in projects]
    return sorted(rows, key=lambda r: r.updated_at, reverse=True)
