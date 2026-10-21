"""
Previews of a project's design and build: a page picker and a button that opens the
page in the browser, from its file.

The app opens it (webbrowser.open): a web page can't link to a file:// path. So it
opens on the computer running the app, which is the user's own (one local user,
Documents/PLAN.md). From file:// the page's relative links (styles.css, js/app.js)
resolve next to it, and the builders write plain scripts, not modules, so they run.
"""

import webbrowser
from collections.abc import Callable
from pathlib import Path

import gradio as gr

from alikable.projects import Project

NOTE = ("_Opens in your browser from the project folder. Pages that call your real API may be blocked by CORS "
        "there; mock data always works._")


class OpenInBrowser:
    def __init__(self, chat_id: gr.BrowserState, folder: Callable[[Project], Path], first: str, note: bool = False):
        """folder: which folder of the project to open pages from. first: the page listed first, if there is one."""
        self.folder, self.first = folder, first
        with gr.Row(equal_height=True):
            self.page = gr.Dropdown(label="Page", choices=[], interactive=True, scale=3)
            button = gr.Button("Open in browser", scale=1)
        if note:
            gr.Markdown(NOTE)
        button.click(self._open, [chat_id, self.page])

    @property
    def outputs(self) -> list:
        return [self.page]

    def render(self, project: Project) -> dict:
        pages = self._pages(project)
        return {self.page: gr.Dropdown(choices=pages, value=pages[0] if pages else None)}

    def _pages(self, project: Project) -> list[str]:
        folder = self.folder(project)
        pages = sorted(p.name for p in folder.glob("*.html")) if folder.exists() else []
        return sorted(pages, key=lambda name: name != self.first)   # the first page first, the rest by name

    def _open(self, chat_id: str, page: str | None) -> None:
        path = self.folder(Project(chat_id)) / page if page else None
        if path is None or not path.exists():
            gr.Warning("There is no page to open yet.")
            return
        webbrowser.open(path.resolve().as_uri())
