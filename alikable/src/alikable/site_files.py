"""
The built site on disk, and the undo for it.

The project's site/ folder holds the build. The implementation crew writes it and
the Fixer edits it. Agents never write files themselves: they return FileChange
objects and apply_changes() writes them inside the project's site/, keeping the old
contents so the caller can put them back.

The checkpoint is what HITL #3 rejects back to. A change job saves one before it
runs, unless one is already there, so the checkpoint always holds the last approved
build: approving clears it, rejecting restores it and so undoes every change since.
Each project has its own checkpoint, so rejecting in one never touches another.
"""

import shutil
from pathlib import Path

from alikable.models import FileChange
from alikable.projects import Project

CHECKPOINTED = ["site", "design", "site_spec.json"]   # everything a change job can edit, in the project folder
TEXT_SUFFIXES = {".html", ".css", ".js", ".mjs", ".json", ".svg", ".md", ".txt"}


def site_path(project: Project, rel: str) -> Path:
    """The file at rel inside the project's site/. Raises ValueError for paths outside it."""
    root = project.site_dir.resolve()
    path = (root / rel.strip().lstrip("/")).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f"{rel} is outside {project.site_dir}/")
    return path


def read_site(project: Project) -> str:
    """Every text file of the site, each under a '=== path ===' header, for the agents."""
    site_dir = project.site_dir
    if not site_dir.exists():
        return "None yet"
    parts = [
        f"=== {p.relative_to(site_dir).as_posix()} ===\n{p.read_text(encoding='utf-8')}"
        for p in sorted(site_dir.rglob("*")) if p.is_file() and p.suffix in TEXT_SUFFIXES
    ]
    return "\n\n".join(parts) or "None yet"


def apply_changes(project: Project, changes: list[FileChange]) -> dict[Path, str | None]:
    """Write the changes and return the old contents (None for new files) for restore()."""
    targets = [(site_path(project, c.path), c.content) for c in changes]   # check every path before writing any
    backup: dict[Path, str | None] = {}
    for path, content in targets:
        if path not in backup:
            backup[path] = path.read_text(encoding="utf-8") if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return backup


def restore(backup: dict[Path, str | None]) -> None:
    """Undo apply_changes()."""
    for path, content in backup.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(content, encoding="utf-8")


def save_checkpoint(project: Project) -> None:
    """Save the current build, unless a checkpoint of the last approved build is kept."""
    if project.checkpoint.exists():
        return
    project.checkpoint.mkdir(parents=True)
    for name in CHECKPOINTED:
        source = project.dir / name
        if source.is_dir():
            shutil.copytree(source, project.checkpoint / name)
        elif source.exists():
            shutil.copy2(source, project.checkpoint / name)


def restore_checkpoint(project: Project) -> bool:
    """Put the checkpointed build back. False if there is no checkpoint."""
    if not project.checkpoint.exists():
        return False
    for name in CHECKPOINTED:
        current, saved = project.dir / name, project.checkpoint / name
        if current.is_dir():
            shutil.rmtree(current)
        elif current.exists():
            current.unlink()
        if saved.is_dir():
            shutil.copytree(saved, current)
        elif saved.exists():
            shutil.copy2(saved, current)
    clear_checkpoint(project)
    return True


def clear_checkpoint(project: Project) -> None:
    """Forget the checkpoint: the current build is approved."""
    shutil.rmtree(project.checkpoint, ignore_errors=True)
