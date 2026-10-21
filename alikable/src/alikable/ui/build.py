"""
Jobs panel: the project's background jobs (change, check, deploy, rollback), the details
of the one selected, and a notice when a build waits for approval (HITL #3).

Approving, undoing and changing a build all go through the chat for now: the Chat Agent
turns "approve" or "undo that" into the deploy or rollback job. Direct Approve and
Reject buttons come with the gates of Step B1 in Documents/PLAN.md.
"""

import gradio as gr

from alikable.flows import change_router
from alikable.models import ChatResponse, Job, PolishReport
from alikable.projects import Project

HEADERS = ["Status", "Job", "Step", "Id"]
ID_COLUMN = HEADERS.index("Id")
STATUS_ICONS = {"queued": "⏳ queued", "running": "🔄 running", "done": "✅ done", "failed": "❌ failed"}
NO_JOBS = "_No jobs yet. Changes, checks and deploys you ask for in the chat run here._"
APPROVAL_HELP = ("Say **approve** in the chat to package it and write the deploy guide (name the host, Netlify, Vercel, "
                 "GitHub Pages or S3, and a quick, standard or detailed guide if you like), **undo** to go back to the "
                 "last approved build, or describe another change.")


class BuildPanel:
    def __init__(self, chat_id: gr.BrowserState):
        self.chat_id = chat_id
        self.notice = gr.Markdown(visible=False)
        gr.Markdown("### Jobs")
        self.jobs = gr.Dataframe(headers=HEADERS, interactive=False, wrap=True)
        self.empty = gr.Markdown(NO_JOBS)
        self.details = gr.Markdown()
        self.jobs.select(self._show_job, self.chat_id, self.details)

    @property
    def outputs(self) -> list:
        return [self.notice, self.jobs, self.empty]

    def render(self, project: Project, response: ChatResponse) -> dict:
        newest_first = sorted(response.jobs, key=lambda j: j.created_at, reverse=True)
        rows = [[STATUS_ICONS[j.status], j.title, j.step, j.id] for j in newest_first]
        return {self.notice: gr.Markdown(self._notice(project) if response.awaiting_approval else "",
                                         visible=response.awaiting_approval),
                self.jobs: gr.Dataframe(value={"data": rows, "headers": HEADERS}, visible=bool(rows)),
                self.empty: gr.Markdown(visible=not rows)}

    @staticmethod
    def signature(response: ChatResponse) -> str:
        """Changes whenever render would draw something different."""
        jobs = ",".join(f"{j.id}:{j.status}:{j.step}" for j in response.jobs)
        return f"{response.awaiting_approval}|{jobs}"

    @staticmethod
    def _notice(project: Project) -> str:
        try:
            polish = PolishReport.model_validate_json(project.polish_report.read_text(encoding="utf-8")).summary()
        except (OSError, ValueError):
            polish = ""
        return "\n\n".join(part for part in ("### The build is ready for your approval", polish, APPROVAL_HELP) if part)

    @staticmethod
    def _show_job(chat_id: str, evt: gr.SelectData) -> str:
        job_id = str(evt.row_value[ID_COLUMN])
        job = next((j for j in change_router.chat_status(chat_id).jobs if j.id == job_id), None)
        return describe(job) if job else ""


def describe(job: Job) -> str:
    """The details of one job, in Markdown."""
    lines = [f"#### {job.title}", f"Job `{job.id}`, {job.kind}: {STATUS_ICONS[job.status]}"
             + (f", on the {job.step}" if job.step else "")]
    if job.result:
        lines.append(f"**Result:** {job.result}")
    if job.error:
        lines.append(f"**Error:** {job.error}")
    return "\n\n".join(lines)
