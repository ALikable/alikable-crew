"""
Main chat after the first build (the Change Router part of Documents/Agent_Diagram.png).

The UI calls run_chat(message, chat_id) for every message the user sends, and
chat_status(chat_id) to refresh job statuses without sending one. Both return a
ChatResponse: the reply, whether a build is waiting for approval (HITL #3), and the
status of every background job in the session.

The chat_id is made when the intake form is submitted (flows/intake.py) and is the
chat's memory scope, /chat/<chat_id> (crew.py). Only the Chat Agent saves memories; the
Change Router and background checks only recall them.

For each message the Chat Agent picks one action:
  reply   -> answer in the chat
  check   -> start read-only reviewers as background jobs
  change  -> the Change Router picks the crew where the rework starts, and a change
             job runs that crew and every crew after it:
               planning -> design -> implementation -> polish
             after which the build waits for approval
  approve -> a deploy job packages site.zip and writes DEPLOY.md for the host and
             detail the user asked for (flows/create_deploy_guide.py)
  reject  -> a rollback job restores the last approved build (site_files.py)

Before it runs, a change job saves a checkpoint of the build unless one is already
kept, so the checkpoint is always the last approved build. Approving clears it.

Each chat works on its own project folder, output/projects/<chat_id>/ (projects.py).
A chat's change, deploy and rollback jobs run one at a time in the order they were
sent, so two jobs never edit its site at once; each chat has its own runner, so
different projects build at the same time. Check jobs only report, so they run in
parallel on a shared runner.

The intake flow (flows/intake.py) writes the approved spec and hands its chat_id over
to this chat (the UI opens it). Not built yet (placeholders below, marked TODO):
  - the first build between the intake flow and this chat (only the design runs)
  - the planning and implementation crews in the change pipeline
Until then the chat reads whatever spec, design and site its project folder holds.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Literal

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import PrivateAttr

from alikable.crew import Alikable, chat_memory_read_only
from alikable.flows.create_deploy_guide import run_deploy_guide_phase
from alikable.flows.phases import run_design_phase
from alikable.flows.polish import run_polish_phase
from alikable.models import (HOST_NAMES, ChatReply, ChatResponse, ChatState, Job, PipelineState, RouteDecision,
                             utc_now)
from alikable.projects import Project
from alikable.site_files import clear_checkpoint, restore_checkpoint, save_checkpoint

HISTORY_LIMIT = 20   # chat lines passed to the Chat Agent
SPEAKERS = {"User: ": "user", "Assistant: ": "assistant"}   # history line prefix -> chat role

_check_runner = ThreadPoolExecutor(max_workers=3, thread_name_prefix="check")   # shared by every chat


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


# --------------------------------------------------------------- Change pipeline

class ChangePipelineFlow(Flow[PipelineState]):
    """Runs the crew a change was routed to, then every crew after it."""

    _on_step: Callable[[str], None] | None = PrivateAttr(default=None)   # set by the change job

    @property
    def project(self) -> Project:
        return Project(self.state.chat_id)

    def _step(self, step: str) -> None:
        if self._on_step:
            self._on_step(step)

    @start()
    def load_files(self):
        self.state.site_spec = _read(self.project.site_spec)
        self.state.design = _read(self.project.design_json)

    @router(load_files)
    def start_at(self) -> Literal["planning", "design", "implementation", "polish"]:
        return self.state.route  # type: ignore[return-value]

    @listen("planning")
    def run_planning(self):
        self._step("planning crew")
        # TODO(planning crew): call run_planning_phase (flows/intake.py) with the current
        # spec and the change as its summary, then reload site_spec from project.site_spec.
        self.state.notes.append("Planning crew not built yet; skipped.")

    @listen(or_("design", run_planning))
    def run_design(self):
        self._step("design crew")
        if not self.state.site_spec:
            self.state.notes.append(f"Design skipped: no site spec at {self.project.site_spec}.")
            return
        spec = self.state.site_spec
        if self.state.route in ("planning", "design"):   # the change is not in the spec yet
            spec += f"\n\nRequested change: {self.state.change_request}"
        self.state.design, approved = run_design_phase(self.project, spec)
        self.state.notes.append(
            "Design approved by the Design Critic." if approved
            else "Design not approved after 3 rounds; kept the last version."
        )

    @listen(or_("implementation", run_design))
    def run_implementation(self):
        self._step("implementation crew")
        # TODO(implementation crew): not built yet. Kick it off with site_spec and design.
        self.state.notes.append("Implementation crew not built yet; skipped.")

    @listen(or_("polish", run_implementation))
    def run_polish(self):
        self._step("polish crew")
        report = run_polish_phase(
            self.project,
            self.state.site_spec,
            self.state.design,
            # larger changes were already made by the crews above, so polish just re-checks them
            change_request=self.state.change_request if self.state.route == "polish" else "",
            max_rounds=self.state.polish_rounds,
            on_step=self._step,
        )
        self.state.notes.append(report.summary())


# ---------------------------------------------------------------------- Session

class ChatSession:
    """One user's chat: the flow that answers their messages and the jobs it started."""

    def __init__(self, chat_id: str):
        self.id = chat_id
        self.project = Project(chat_id)
        # changes, deploys and rollbacks of this project, one at a time
        self.build_runner = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"build-{chat_id[:8]}")
        self.awaiting_approval = False
        self.jobs: list[Job] = []
        self.flow = ChatFlow()
        self.flow._session = self
        self.turn_lock = threading.Lock()   # one message at a time
        self._lock = threading.Lock()       # guards jobs and _unreported
        self._unreported: list[str] = []    # finished job results the Chat Agent has not passed on

    def start_job(self, kind: str, title: str, work: Callable[[Job], str],
                  runner: ThreadPoolExecutor) -> Job:
        job = Job(kind=kind, title=title)  # type: ignore[arg-type]
        with self._lock:
            self.jobs.append(job)
        runner.submit(self._run_job, job, work)
        return job

    def _run_job(self, job: Job, work: Callable[[Job], str]) -> None:
        self.update(job, status="running")
        try:
            result = work(job)
        except Exception as e:
            self.update(job, status="failed", step="", error=str(e))
            report = f"{job.title} (job {job.id}) failed: {e}"
        else:
            self.update(job, status="done", step="", result=result)
            report = f"{job.title} (job {job.id}) finished: {result}"
        with self._lock:
            self._unreported.append(report)

    def update(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for field, value in changes.items():
                setattr(job, field, value)
            job.updated_at = utc_now()

    def jobs_for_chat(self) -> str:
        """Open jobs and new results, as text for the Chat Agent. New results count as reported."""
        with self._lock:
            open_jobs = [
                f"- {j.title} (job {j.id}): {j.status}" + (f", now on the {j.step}" if j.step else "")
                for j in self.jobs if j.status in ("queued", "running")
            ]
            finished, self._unreported = self._unreported, []
        parts = []
        if open_jobs:
            parts.append("Still open:\n" + "\n".join(open_jobs))
        if finished:
            parts.append("Finished since the last message:\n" + "\n\n".join(finished))
        return "\n\n".join(parts) or "None"

    def messages(self) -> list[dict[str, str]]:
        """The chat so far as {role, content} messages, oldest first, for the UI."""
        lines = list(self.flow.state.history)
        return [{"role": role, "content": line.removeprefix(prefix)}
                for line in lines for prefix, role in SPEAKERS.items() if line.startswith(prefix)]

    def response(self, reply: str = "") -> ChatResponse:
        with self._lock:
            jobs = [j.model_copy() for j in self.jobs]
        return ChatResponse(chat_id=self.id, reply=reply,
                            awaiting_approval=self.awaiting_approval, jobs=jobs)


# ------------------------------------------------------------------------- Chat

class ChatFlow(Flow[ChatState]):
    """Answers one message per kickoff. The ChatSession keeps it between messages."""

    _session: Any = PrivateAttr(default=None)

    @start()
    def chat(self):
        session: ChatSession = self._session
        result = Alikable(session.project).chat_crew(session.id).kickoff(inputs={
            "message": self.state.message,
            "history": "\n".join(self.state.history[-HISTORY_LIMIT:]) or "None",
            "site_spec": _read(session.project.site_spec) or "None yet",
            "awaiting_approval": "yes" if session.awaiting_approval else "no",
            "jobs": session.jobs_for_chat(),
        })

        decision = result.pydantic
        if not isinstance(decision, ChatReply):   # unstructured answer: treat it as a reply
            decision = ChatReply(action="reply", message=result.raw)
        if decision.action in ("approve", "reject") and not session.awaiting_approval:
            decision.action = "reply"             # nothing is waiting for approval

        self.state.action = decision.action
        self.state.reply = decision.message
        self.state.change_request = decision.change_request or self.state.message
        self.state.check_agents = list(decision.check_agents)
        self.state.check_question = decision.check_question or self.state.message
        self.state.deploy_host, self.state.deploy_detail = decision.deploy_host, decision.deploy_detail
        self.state.history += [f"User: {self.state.message}", f"Assistant: {decision.message}"]

    @router(chat)
    def decide(self) -> Literal["reply", "change", "check", "approve", "reject"]:
        return self.state.action  # type: ignore[return-value]

    @listen("check")
    def start_checks(self):
        session: ChatSession = self._session
        roles = Alikable(session.project).agents_config
        for name in self.state.check_agents:
            role = roles[name]["role"].strip()  # type: ignore[index]
            session.start_job(
                "check", f"{role} check",
                lambda job, name=name, question=self.state.check_question: _run_check(name, question, session.project),
                _check_runner,
            )

    @router("change")
    def route_change(self) -> Literal["routed", "clarify"]:
        session: ChatSession = self._session
        result = Alikable(session.project).change_router_crew(session.id).kickoff(inputs={
            "change_request": self.state.change_request,
            "site_spec": _read(session.project.site_spec) or "None yet",
        })
        route = result.pydantic
        if not isinstance(route, RouteDecision):   # unstructured answer: ask the user instead
            route = RouteDecision(crew="clarify", request=result.raw)

        if route.crew == "clarify":
            self.state.reply = route.request
            self.state.history.append(f"Assistant: {route.request}")
            return "clarify"
        self.state.route = route.crew
        self.state.change_request = route.request
        return "routed"

    @listen("routed")
    def start_change(self):
        session: ChatSession = self._session
        route, request = self.state.route, self.state.change_request
        session.awaiting_approval = False   # a new change replaces the build waiting for approval

        def work(job: Job) -> str:
            save_checkpoint(session.project)
            pipeline = ChangePipelineFlow()
            pipeline._on_step = lambda step: session.update(job, step=step)
            pipeline.kickoff(inputs={"chat_id": session.id, "route": route, "change_request": request})
            session.awaiting_approval = True
            return " ".join(pipeline.state.notes) + " Waiting for approval or a change."

        session.start_job("change", f"Change from the {route} crew: {request}", work, session.build_runner)

    @listen("approve")
    def start_deploy(self):
        session: ChatSession = self._session
        session.awaiting_approval = False

        host, detail = self.state.deploy_host, self.state.deploy_detail

        def work(job: Job) -> str:
            clear_checkpoint(session.project)   # this build is approved
            result = run_deploy_guide_phase(session.project, host, detail,
                                            on_step=lambda step: session.update(job, step=step))
            return result.summary()

        session.start_job("deploy", f"Deploy guide for {HOST_NAMES[host]}", work, session.build_runner)

    @listen("reject")
    def start_rollback(self):
        session: ChatSession = self._session
        session.awaiting_approval = False

        def work(job: Job) -> str:
            if restore_checkpoint(session.project):
                return "Restored the last approved build; every change since was undone."
            return "There was no checkpoint to restore, so nothing changed."

        session.start_job("rollback", "Undo changes since the last approval", work, session.build_runner)


def _run_check(agent_name: str, question: str, project: Project) -> str:
    """Run one reviewer on its own, outside any crew. Read-only: it reports, never edits,
    and it recalls the chat's memories but saves none."""
    # Recalled here rather than set as agent memory: Agent.kickoff() saves its result to
    # memory even when the memory is read-only.
    recalled = chat_memory_read_only(project.chat_id).recall(question, limit=5)
    preferences = "\n".join(f"- {m.record.content}" for m in recalled) or "None"
    reviewer = getattr(Alikable(project), agent_name)()
    result = reviewer.kickoff(
        f"{question}\n\nReport your findings only; do not change any files."
        f"\n\nWhat the user has said in this chat: {preferences}"
        f"\n\nSite spec: {_read(project.site_spec) or 'None yet'}\n\nDesign: {_read(project.design_json) or 'None yet'}"
    )
    return result.raw


# ----------------------------------------------------------------------- UI API

_sessions: dict[str, ChatSession] = {}
_sessions_lock = threading.Lock()


def _get_session(chat_id: str) -> ChatSession:
    with _sessions_lock:
        if chat_id not in _sessions:
            _sessions[chat_id] = ChatSession(chat_id)
        return _sessions[chat_id]


def run_chat(message: str, chat_id: str) -> ChatResponse:
    """Send one user message and return the reply. chat_id comes from the intake form
    (flows/intake.py) and is the same for every message in the chat."""
    session = _get_session(chat_id)
    with session.turn_lock:
        session.flow.kickoff(inputs={"message": message, "reply": ""})
        return session.response(session.flow.state.reply)


def chat_status(chat_id: str) -> ChatResponse:
    """Job statuses and the approval state, without sending a message (for UI polling)."""
    return _get_session(chat_id).response()


def chat_messages(chat_id: str) -> list[dict[str, str]]:
    """The chat so far as {role, content} messages, for the UI's chat panel."""
    return _get_session(chat_id).messages()
