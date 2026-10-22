"""
Previews of a project's design and build: a page picker and a link that opens the
page in a new browser tab.

Gradio serves the page (main() passes allowed_paths=[PROJECTS] to launch()), so the
link works wherever the app runs, a Hugging Face Space included. The page's relative
links (styles.css, js/app.js) resolve next to it, because they are relative to its URL.
"""

from collections.abc import Callable
from pathlib import Path

import gradio as gr

from alikable.projects import Project

NOTE = ("_Opens in a new tab, served by this app. Pages that call your real API may be blocked by CORS "
        "there; mock data always works._")


class OpenInBrowser:
    def __init__(self, chat_id: gr.BrowserState, folder: Callable[[Project], Path], first: str, note: bool = False):
        """folder: which folder of the project to open pages from. first: the page listed first, if there is one."""
        self.folder, self.first = folder, first
        with gr.Row(equal_height=True):
            self.page = gr.Dropdown(label="Page", choices=[], interactive=True, scale=3)
            self.link = gr.HTML(scale=1)
        if note:
            gr.Markdown(NOTE)
        self.page.change(self._link, [chat_id, self.page], self.link)

    @property
    def outputs(self) -> list:
        return [self.page, self.link]

    def render(self, project: Project) -> dict:
        pages = self._pages(project)
        page = pages[0] if pages else None
        return {self.page: gr.Dropdown(choices=pages, value=page), self.link: self._link(project.chat_id, page)}

    def _pages(self, project: Project) -> list[str]:
        folder = self.folder(project)
        pages = sorted(p.name for p in folder.glob("*.html")) if folder.exists() else []
        return sorted(pages, key=lambda name: name != self.first)   # the first page first, the rest by name

    def _link(self, chat_id: str, page: str | None) -> str:
        path = self.folder(Project(chat_id)) / page if chat_id and page else None
        if path is None or not path.exists():
            return "<em>There is no page to open yet.</em>"
        url = f"/gradio_api/file={path.resolve().as_posix()}"
        return f'<a href="{url}" target="_blank" rel="noopener">Open {page} in a new tab</a>'
