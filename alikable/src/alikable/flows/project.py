"""
One project from the intake form to the deploy guide (Step B1 in Documents/PLAN.md),
and the functions the UI calls for it.

A ProjectSession joins the project's two halves: its intake flow (flows/intake.py),
up to the approved spec, and its ChatSession (flows/change_router.py), which runs its
jobs, gates and chat from then on.

  spec approved (HITL #1)   -> design job; then the design gate waits
  design revised            -> design job again, with the change
  design approved (HITL #2) -> first build job (implementation, then polish); then the build gate waits
  build approved (HITL #3)  -> deploy job
  build rejected            -> rollback job, or the first build again if nothing was approved yet

Each function returns a ProjectView: the stage, the intake state, the chat, the jobs
and the gate waiting for the user. stage() is the one rule for where a project is.

The project's session.json is saved after every user action and every job update, so
a project reopens where it was after the app restarts. Jobs that were queued or running
then come back as interrupted, and the UI offers Retry.
"""

import threading
import uuid
from collections.abc import Callable

from alikable.flows.change_router import ChatSession
from alikable.flows.intake import IntakeFlow
from alikable.flows.phases import save_styles
from alikable.models import IntakeForm, IntakeState, Job, ProjectView, SessionRecord, Stage
from alikable.projects import Project, list_projects  # noqa: F401  list_projects is part of the UI API

OnStep = Callable[[str], None] | None
INTAKE_STAGES: dict[str, Stage] = {"form": "form", "interview": "interview", "review": "spec_review"}
PIPELINE_JOBS = ("design", "change", "deploy", "rollback")   # every kind but check


class ProjectSession:
    def __init__(self, chat_id: str):
        self.project = Project(chat_id)
        self.intake = IntakeState(chat_id=chat_id)
        self.chat = ChatSession(chat_id, on_change=self.save)
        self._intake_flow = IntakeFlow()
        self._restored: dict = {}   # the saved intake state, passed on the next intake kickoff
        self._action_lock = threading.Lock()   # one intake or gate action at a time
        self._save_lock = threading.Lock()

    # ------------------------------------------------------------------- stage

    def stage(self) -> Stage:
        """Where the project is, from the intake, the gate waiting and the newest job."""
        if self.intake.stage != "approved":
            return INTAKE_STAGES[self.intake.stage]
        if self.chat.awaiting == "design":
            return "design_review"
        if self.chat.awaiting == "build":
            return "build_review"
        job = self.chat.jobs.latest(*PIPELINE_JOBS)
        if job is None or job.kind == "design":
            return "designing"
        if job.kind == "deploy":
            return "deployed" if job.status == "done" else "deploying"
        if job.kind == "rollback" and job.status == "done":
            return "deployed"
        return "building"

    def view(self, reply: str = "", problems: list[str] | None = None) -> ProjectView:
        stage = self.stage()
        return ProjectView(
            chat_id=self.project.chat_id, title=self.project.title, stage=stage,
            awaiting="spec" if stage == "spec_review" else self.chat.awaiting,
            intake=self.intake.model_copy(deep=True), reply=reply, messages=self.chat.messages(),
            jobs=self.chat.jobs.all(), problems=problems or [],
        )

    # ------------------------------------------------------------------ intake

    def _intake_action(self, action: str, on_step: OnStep, **inputs) -> None:
        flow = self._intake_flow
        flow._on_step = on_step
        flow.kickoff(inputs={**self._restored, "chat_id": self.project.chat_id, "action": action,
                             "replies": [], "request": "", **inputs})
        self._restored = {}
        self.intake = flow.state.model_copy(deep=True)
        self.save()

    def start_intake(self, form: IntakeForm, on_step: OnStep = None) -> ProjectView:
        with self._action_lock:
            self._intake_action("form", on_step, form=form.model_dump())
        return self.view()

    def answer_interview(self, replies: list[str], on_step: OnStep = None) -> ProjectView:
        with self._action_lock:
            self._intake_action("answers", on_step, replies=replies)
        return self.view()

    def revise_spec(self, request: str, on_step: OnStep = None) -> ProjectView:
        with self._action_lock:
            self._intake_action("changes", on_step, request=request)
        return self.view()

    def approve_spec(self, site_spec: str, on_step: OnStep = None) -> ProjectView:
        """HITL #1: saves the spec (the user may have edited it) and starts the design job."""
        with self._action_lock:
            self._intake_action("approve", on_step, site_spec=site_spec)
            if self.intake.stage == "approved" and not self.intake.problems:
                self.chat.start_design()
        return self.view()

    # ------------------------------------------------------------------- gates

    def approve_design(self, styles_css: str | None = None) -> ProjectView:
        """HITL #2: keeps a hand edit of styles.css, then starts the first build."""
        with self._action_lock:
            if not self.chat.take_gate("design"):
                return self.view(problems=["No design is waiting for approval."])
            if styles_css is not None and styles_css != self._styles():
                try:
                    save_styles(self.project, styles_css)
                except (OSError, ValueError) as e:
                    self.chat.open_gate("design")
                    return self.view(problems=[f"Couldn't save your styles.css edit ({e})."])
            self.chat.start_first_build()
        return self.view()

    def revise_design(self, request: str) -> ProjectView:
        """HITL #2 edit: the Design crew designs again with the change."""
        if not request.strip():
            return self.view(problems=["Describe what to change first."])
        with self._action_lock:
            if not self.chat.take_gate("design"):
                return self.view(problems=["No design is waiting for approval."])
            self.chat.start_design(request.strip())
        return self.view()

    def approve_build(self, host: str, detail: str) -> ProjectView:
        """HITL #3: the deploy job."""
        if not self.chat.approve(host, detail):
            return self.view(problems=["No build is waiting for approval."])
        return self.view()

    def reject_build(self) -> ProjectView:
        """HITL #3 reject: back to the last approved build."""
        if not self.chat.reject():
            return self.view(problems=["No build is waiting for approval."])
        return self.view()

    def retry(self, job_id: str) -> ProjectView:
        if self.chat.retry(job_id) is None:
            return self.view(problems=["Only a failed or interrupted job can be retried."])
        return self.view()

    def send(self, message: str) -> ProjectView:
        if self.intake.stage != "approved":
            return self.view(problems=["The chat opens once the spec is approved."])
        return self.view(reply=self.chat.send(message))

    def _styles(self) -> str:
        path = self.project.design_dir / "styles.css"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ------------------------------------------------------------- persistence

    def save(self) -> None:
        """Write session.json. Nothing until the intake form is accepted and the folder exists."""
        if not self.project.dir.exists():
            return
        record = SessionRecord(
            stage=self.stage(), awaiting=self.chat.awaiting,
            # what the user typed before the input guardrail may hold secrets it removed
            intake=self.intake.model_copy(update={"form": None, "replies": [], "request": ""}),
            history=list(self.chat.flow.state.history), jobs=self.chat.jobs.all(),
        )
        with self._save_lock:
            temp = self.project.session.with_suffix(".tmp")
            temp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
            temp.replace(self.project.session)

    @classmethod
    def load(cls, chat_id: str) -> "ProjectSession | None":
        """The project as session.json left it. None if it can't continue: no session.json,
        and it stopped before its spec was approved."""
        session = cls(chat_id)
        project = session.project
        if project.session.exists():
            record = SessionRecord.model_validate_json(project.session.read_text(encoding="utf-8"))
            session._restore_intake(record.intake)
            session.chat.flow.state.history = record.history
            session.chat.jobs.restore(record.jobs)
            session.chat.awaiting = record.awaiting
            return session
        if not project.site_spec.exists():
            return None
        # Made before session.json existed: open it at the gate its files reached
        session._restore_intake(IntakeState(chat_id=chat_id, stage="approved",
                                            site_spec=project.site_spec.read_text(encoding="utf-8")))
        if any(project.site_dir.glob("*.html")):
            session.chat.awaiting = "build"
        elif project.design_json.exists():
            session.chat.awaiting = "design"
        else:
            session.chat.jobs.restore([Job(kind="design", title="Design", status="interrupted")])
        return session

    def _restore_intake(self, state: IntakeState) -> None:
        # Passed as kickoff inputs without an id, so CrewAI doesn't treat the kickoff as a restore
        self.intake = state
        self._restored = state.model_dump(exclude={"id"})


# ----------------------------------------------------------------------- UI API

_sessions: dict[str, ProjectSession] = {}
_sessions_lock = threading.Lock()


def _session(chat_id: str) -> ProjectSession:
    """The open project. Raises LookupError if it can't be opened."""
    with _sessions_lock:
        if chat_id not in _sessions:
            session = ProjectSession.load(chat_id)
            if session is None:
                raise LookupError(f"Project {chat_id} stopped before its spec was approved and can't continue.")
            _sessions[chat_id] = session
        return _sessions[chat_id]


def new_project(form: IntakeForm, on_step: OnStep = None) -> ProjectView:
    """Submit the intake form. A refused form leaves no project behind; the next try starts a new one."""
    session = ProjectSession(uuid.uuid4().hex)
    view = session.start_intake(form, on_step)
    if not view.intake.problems:
        with _sessions_lock:
            _sessions[view.chat_id] = session
    return view


def open_project(chat_id: str) -> ProjectView | None:
    """The project's view, or None if there is no such project or it can't continue."""
    try:
        return _session(chat_id).view()
    except (LookupError, ValueError):   # ValueError: not a valid project id (projects.py)
        return None


def status(chat_id: str) -> ProjectView:
    """The project's view without doing anything (for UI polling)."""
    return _session(chat_id).view()


def answer_interview(chat_id: str, replies: list[str], on_step: OnStep = None) -> ProjectView:
    """One reply per question of the last round, "" to let the agents decide."""
    return _session(chat_id).answer_interview(replies, on_step)


def revise_spec(chat_id: str, request: str, on_step: OnStep = None) -> ProjectView:
    """HITL #1 edit: the Planning crew rewrites the spec with these changes."""
    return _session(chat_id).revise_spec(request, on_step)


def approve_spec(chat_id: str, site_spec: str, on_step: OnStep = None) -> ProjectView:
    return _session(chat_id).approve_spec(site_spec, on_step)


def approve_design(chat_id: str, styles_css: str | None = None) -> ProjectView:
    return _session(chat_id).approve_design(styles_css)


def revise_design(chat_id: str, request: str) -> ProjectView:
    return _session(chat_id).revise_design(request)


def approve_build(chat_id: str, host: str, detail: str) -> ProjectView:
    return _session(chat_id).approve_build(host, detail)


def reject_build(chat_id: str) -> ProjectView:
    return _session(chat_id).reject_build()


def retry(chat_id: str, job_id: str) -> ProjectView:
    return _session(chat_id).retry(job_id)


def run_chat(message: str, chat_id: str) -> ProjectView:
    """Send one chat message; the reply is in the view, and in its messages."""
    return _session(chat_id).send(message)
