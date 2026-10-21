"""
Design screen: the design job's progress, then the design gate (HITL #2).

At the gate the user previews components.html and each page layout, may edit
styles.css by hand, and approves (the first build starts; app.py then opens the build
screen) or describes changes for the Design crew. A failed or interrupted design job
can be retried.

One browser session reuses these components for every project it opens, so render sets
every property that differs between stages, never only the ones that changed.
"""

import gradio as gr

from alikable.flows import project as projects_api
from alikable.models import Job, ProjectView
from alikable.projects import Project
from alikable.ui.preview import PreviewFrame


class DesignScreen:
    def __init__(self, chat_id: gr.BrowserState):
        self.chat_id = chat_id
        self.title = gr.Markdown()
        self.status = gr.Markdown()
        self.retry = gr.Button("Retry the design", visible=False)
        with gr.Column(visible=False) as self.review:
            with gr.Row():
                with gr.Column(scale=3):
                    self.preview = PreviewFrame(chat_id, lambda p: p.design_dir, first="components.html")
                with gr.Column(scale=2):
                    self.styles = gr.Code(language="css", label="styles.css (you can edit it before approving)",
                                          interactive=True, max_lines=28)
            self.changes = gr.Textbox(label="Or describe what to change", lines=2,
                                      info="The Design crew designs again with these changes; "
                                           "hand edits to styles.css are not kept.")
            with gr.Row():
                approve = gr.Button("Approve design", variant="primary")
                revise = gr.Button("Request changes")

        # finishes when the design was approved, or the approval refused; app.py then opens the build screen
        self.approved = approve.click(self._approve, [chat_id, self.styles], self.outputs)
        revise.click(self._revise, [chat_id, self.changes], self.outputs)
        self.retry.click(self._retry, chat_id, self.outputs)

    @property
    def outputs(self) -> list:
        return [self.title, self.status, self.retry, self.review, self.styles, self.changes, *self.preview.outputs]

    def render(self, view: ProjectView) -> dict:
        project = Project(view.chat_id)
        job = latest_design(view)
        reviewing = view.stage == "design_review"
        styles = project.design_dir / "styles.css"
        return {self.title: f"## {view.title}",
                self.status: self._status(view, job),
                self.retry: gr.Button(visible=job is not None and job.status in ("failed", "interrupted")),
                self.review: gr.Column(visible=reviewing),
                self.styles: styles.read_text(encoding="utf-8") if reviewing and styles.exists() else "",
                self.changes: "",
                **(self.preview.render(project) if reviewing else {})}

    @staticmethod
    def _status(view: ProjectView, job: Job | None) -> str:
        if view.stage == "design_review":
            return (f"### Your design is ready\n{job.result if job else ''} Approve it to build the site, "
                    "or ask for changes.")
        if job is None or job.is_open:
            return "_The Design crew is designing your site. This takes a few minutes..._"
        if job.status == "failed":
            return f"**The design failed** ({job.error}). Retry it."
        return "**The design was interrupted** when the app stopped. Retry it."

    # ---------------------------------------------------------------- handlers

    def _approve(self, chat_id: str, styles_css: str) -> dict:
        return self.render(warn(projects_api.approve_design(chat_id, styles_css)))

    def _revise(self, chat_id: str, request: str) -> dict:
        return self.render(warn(projects_api.revise_design(chat_id, request)))

    def _retry(self, chat_id: str) -> dict:
        job = latest_design(projects_api.status(chat_id))
        return self.render(warn(projects_api.retry(chat_id, job.id if job else "")))


def latest_design(view: ProjectView) -> Job | None:
    return next((j for j in reversed(view.jobs) if j.kind == "design"), None)


def warn(view: ProjectView) -> ProjectView:
    """Shows why the action was refused, if it was."""
    for problem in view.problems:
        gr.Warning(problem)
    return view
