"""
Build screen panels: the build gate (HITL #3) and the jobs panel.

BuildGate says what the build is doing and, when a build waits for approval, shows the
polish summary, the host and detail of the deploy guide, and Approve and Reject. The
chat can do the same ("approve", "undo that"); these buttons skip the Chat Agent.

JobsPanel lists the project's background jobs (design, change, check, deploy,
rollback), newest first, and the details of the one selected, with Retry when it
failed or was interrupted.

Their buttons only act; app.py then redraws every live panel from the project's view.
"""

import gradio as gr

from alikable.flows import project as projects_api
from alikable.models import HOST_NAMES, Job, PolishReport, ProjectView
from alikable.projects import Project
from alikable.ui import warn

HOSTS = [("Netlify", "netlify"), ("Vercel", "vercel"), ("GitHub Pages", "github_pages"), ("AWS S3", "s3")]
DETAILS = [("Quick", "quick"), ("Standard", "standard"), ("Detailed", "detailed")]
STATUS_ICONS = {"queued": "⏳ queued", "running": "🔄 running", "done": "✅ done", "failed": "❌ failed",
                "interrupted": "⚠️ interrupted"}
RETRYABLE = ("failed", "interrupted")
HEADERS = ["Status", "Job", "Step", "Id"]
ID_COLUMN = HEADERS.index("Id")
NO_JOBS = "_No jobs yet. Changes, checks and deploys you ask for in the chat run here._"
GATE_HELP = ("**Approve** packages the site and writes the deploy guide for the host you pick. **Reject** goes back "
             "to the last approved build, or builds again if none was approved yet. Or ask for another change in "
             "the chat.")


class BuildGate:
    def __init__(self, chat_id: gr.BrowserState):
        self.status = gr.Markdown()
        with gr.Group(visible=False) as self.gate:
            self.notice = gr.Markdown(padding=True)
            with gr.Row():
                host = gr.Dropdown(HOSTS, value="netlify", label="Host")
                detail = gr.Radio(DETAILS, value="standard", label="Deploy guide")
            with gr.Row():
                approve = gr.Button("Approve", variant="primary")
                reject = gr.Button("Reject", variant="stop")
        # each finishes once its job started, or the action was refused; app.py then redraws the panels
        self.acted = [approve.click(self._approve, [chat_id, host, detail]),
                      reject.click(self._reject, chat_id)]

    @property
    def outputs(self) -> list:
        return [self.status, self.gate, self.notice]

    def render(self, view: ProjectView) -> dict:
        waiting = view.awaiting == "build"
        return {self.status: self._status(view),
                self.gate: gr.Group(visible=waiting),
                self.notice: self._notice(Project(view.chat_id)) if waiting else ""}

    @staticmethod
    def _status(view: ProjectView) -> str:
        job = next((j for j in reversed(view.jobs) if j.kind != "check"), None)
        if view.stage in ("building", "deploying") and job:
            if job.is_open:
                return f"🔄 **{job.title}**" + (f": now on the {job.step}" if job.step else "")
            if job.status in RETRYABLE:
                return f"{STATUS_ICONS[job.status]}: **{job.title}**. Select it under Jobs to see why and retry it."
        if view.stage == "deployed":
            return "✅ **Approved.** The deploy guide and package are below."
        return ""

    @staticmethod
    def _notice(project: Project) -> str:
        try:
            polish = PolishReport.model_validate_json(project.polish_report.read_text(encoding="utf-8")).summary()
        except (OSError, ValueError):
            polish = ""
        return "\n\n".join(part for part in ("### The build is ready for your approval", polish, GATE_HELP) if part)

    @staticmethod
    def _approve(chat_id: str, host: str, detail: str) -> None:
        warn(projects_api.approve_build(chat_id, host, detail))

    @staticmethod
    def _reject(chat_id: str) -> None:
        warn(projects_api.reject_build(chat_id))


class JobsPanel:
    def __init__(self, chat_id: gr.BrowserState):
        self.jobs = gr.Dataframe(headers=HEADERS, interactive=False, wrap=True)
        self.empty = gr.Markdown(NO_JOBS)
        selected = gr.State("")   # the id of the job whose details show
        self.details = gr.Markdown()
        self.retry = gr.Button("Retry this job", visible=False)
        self.jobs.select(self._select, chat_id, [selected, self.details, self.retry])
        # finishes once the job started again, or the retry was refused; app.py then redraws the panels
        self.acted = [self.retry.click(self._retry, [chat_id, selected], [self.details, self.retry])]

    @property
    def outputs(self) -> list:
        return [self.jobs, self.empty]

    def render(self, view: ProjectView) -> dict:
        newest_first = sorted(view.jobs, key=lambda j: j.created_at, reverse=True)
        rows = [[STATUS_ICONS[j.status], j.title, j.step, j.id] for j in newest_first]
        return {self.jobs: gr.Dataframe(value={"data": rows, "headers": HEADERS}, visible=bool(rows)),
                self.empty: gr.Markdown(visible=not rows)}

    def _select(self, chat_id: str, evt: gr.SelectData) -> tuple:
        job_id = str(evt.row_value[ID_COLUMN])
        job = next((j for j in projects_api.status(chat_id).jobs if j.id == job_id), None)
        if job is None:
            return "", "", gr.Button(visible=False)
        return job_id, describe(job), gr.Button(visible=job.status in RETRYABLE)

    @staticmethod
    def _retry(chat_id: str, job_id: str) -> tuple:
        warn(projects_api.retry(chat_id, job_id))
        return "", gr.Button(visible=False)


def describe(job: Job) -> str:
    """The details of one job, in Markdown."""
    lines = [f"#### {job.title}", f"Job `{job.id}`, {job.kind}: {STATUS_ICONS[job.status]}"
             + (f", on the {job.step}" if job.step else "")]
    if job.result:
        lines.append(f"**Result:** {job.result}")
    if job.error:
        lines.append(f"**Error:** {job.error}")
    if job.status == "interrupted":
        lines.append("The app stopped while this job was open. Retry starts it again.")
    return "\n\n".join(lines)
