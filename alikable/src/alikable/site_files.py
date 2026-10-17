"""
The built site on disk, and the undo for it.

output/site/ holds the build. The implementation crew will write it (not built yet)
and the Fixer edits it. Agents never write files themselves: they return
FileChange objects and apply_changes() writes them inside output/site/, keeping the
old contents so the caller can put them back.

The checkpoint is what HITL #3 rejects back to. A change job saves one before it
runs, unless one is already there, so the checkpoint always holds the last approved
build: approving clears it, rejecting restores it and so undoes every change since.
"""

import shutil
from pathlib import Path

from alikable.models import FileChange

OUTPUT = Path("output")
SITE_DIR = OUTPUT / "site"
CHECKPOINT = OUTPUT / ".checkpoint"
CHECKPOINTED = ["site", "design", "site_spec.json"]   # everything a change job can edit
TEXT_SUFFIXES = {".html", ".css", ".js", ".mjs", ".json", ".svg", ".md", ".txt"}


def site_path(rel: str) -> Path:
    """The file at rel inside output/site/. Raises ValueError for paths outside it."""
    root = SITE_DIR.resolve()
    path = (root / rel.strip().lstrip("/")).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f"{rel} is outside {SITE_DIR}/")
    return path


def read_site() -> str:
    """Every text file of the site, each under a '=== path ===' header, for the agents."""
    if not SITE_DIR.exists():
        return "None yet"
    parts = [
        f"=== {p.relative_to(SITE_DIR).as_posix()} ===\n{p.read_text(encoding='utf-8')}"
        for p in sorted(SITE_DIR.rglob("*")) if p.is_file() and p.suffix in TEXT_SUFFIXES
    ]
    return "\n\n".join(parts) or "None yet"


def apply_changes(changes: list[FileChange]) -> dict[Path, str | None]:
    """Write the changes and return the old contents (None for new files) for restore()."""
    targets = [(site_path(c.path), c.content) for c in changes]   # check every path before writing any
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


def save_checkpoint() -> None:
    """Save the current build, unless a checkpoint of the last approved build is kept."""
    if CHECKPOINT.exists():
        return
    CHECKPOINT.mkdir(parents=True)
    for name in CHECKPOINTED:
        source = OUTPUT / name
        if source.is_dir():
            shutil.copytree(source, CHECKPOINT / name)
        elif source.exists():
            shutil.copy2(source, CHECKPOINT / name)


def restore_checkpoint() -> bool:
    """Put the checkpointed build back. False if there is no checkpoint."""
    if not CHECKPOINT.exists():
        return False
    for name in CHECKPOINTED:
        current, saved = OUTPUT / name, CHECKPOINT / name
        if current.is_dir():
            shutil.rmtree(current)
        elif current.exists():
            current.unlink()
        if saved.is_dir():
            shutil.copytree(saved, current)
        elif saved.exists():
            shutil.copy2(saved, current)
    clear_checkpoint()
    return True


def clear_checkpoint() -> None:
    """Forget the checkpoint: the current build is approved."""
    shutil.rmtree(CHECKPOINT, ignore_errors=True)
