"""
Previews of a project's design and build, in an iframe.

server() serves the project folders, output/projects/, at /preview, so a page's relative
links (styles.css, js/app.js) resolve next to it; app.py mounts the UI on it. Gradio's
own file URLs serve single files only.

PreviewFrame is a page picker and an iframe for one folder of a project: design/ on the
design gate, site/ on the build screen. The ?v= query changes with the folder, so a new
design or build reloads.
"""

from collections.abc import Callable
from html import escape
from pathlib import Path

import gradio as gr
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from alikable.projects import PROJECTS, Project

PREVIEW = "/preview"
NOTE = ("_Pages that call your real API may be blocked here by CORS unless the API allows this app's origin; "
        "mock data always works._")


def server() -> FastAPI:
    """The web app: the project folders at /preview. app.py mounts the UI at /."""
    PROJECTS.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.mount(PREVIEW, StaticFiles(directory=PROJECTS, html=True), name="preview")
    return app


class PreviewFrame:
    def __init__(self, chat_id: gr.BrowserState, folder: Callable[[Project], Path], first: str, note: bool = False):
        """folder: which folder of the project to preview. first: the page shown first, if there is one."""
        self.folder, self.first = folder, first
        self.page = gr.Dropdown(label="Page", choices=[], interactive=True)
        self.frame = gr.HTML()
        if note:
            gr.Markdown(NOTE)
        self.page.input(self._show, [chat_id, self.page], self.frame)

    @property
    def outputs(self) -> list:
        return [self.page, self.frame]

    def render(self, project: Project) -> dict:
        pages = self._pages(project)
        page = pages[0] if pages else None
        return {self.page: gr.Dropdown(choices=pages, value=page),
                self.frame: self._iframe(project, page)}

    def _show(self, chat_id: str, page: str) -> str:
        return self._iframe(Project(chat_id), page)

    def _pages(self, project: Project) -> list[str]:
        folder = self.folder(project)
        pages = sorted(p.name for p in folder.glob("*.html")) if folder.exists() else []
        return sorted(pages, key=lambda name: name != self.first)   # the first page first, the rest by name

    def _iframe(self, project: Project, page: str | None) -> str:
        path = self.folder(project) / page if page else None
        if path is None or not path.exists():
            return "<p><em>Nothing to preview yet.</em></p>"
        version = max(p.stat().st_mtime_ns for p in path.parent.rglob("*") if p.is_file())
        src = f"{PREVIEW}/{path.relative_to(PROJECTS).as_posix()}?v={version}"
        return (f'<iframe src="{escape(src)}" title="Preview of {escape(page)}" '
                'style="width:100%;height:560px;border:1px solid #d0d0d0;border-radius:8px;background:#fff"></iframe>')
