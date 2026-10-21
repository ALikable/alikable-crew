"""
A project after its spec is approved: its background jobs, the gate waiting for the
user, and the chat (the Change Router part of Documents/Agent_Diagram.png).

The jobs, run by a ChatSession:
  design   -> the Design crew designs the site from the spec; then HITL #2 waits
  change   -> the crew a change was routed to and every crew after it:
                planning -> design -> implementation -> polish
              then HITL #3 waits. The first build is a change that starts at the
              implementation crew.
  deploy   -> HITL #3 approved: packages site.zip and writes DEPLOY.md for the host
              and detail the user picked (flows/create_deploy_guide.py)
  rollback -> HITL #3 rejected: restores the last approved build (site_files.py)
  check    -> a read-only reviewer reports on the project

The UI starts the gates' jobs directly (flows/project.py). In the chat, for each message
the Chat Agent picks one action:
  reply   -> answer in the chat
  check   -> start reviewers as check jobs
  change  -> the Change Router picks the crew where the rework starts, and a change job runs
  approve -> as the build gate's Approve
  reject  -> as the build gate's Reject

Before it runs, a change job saves a checkpoint of the build unless one is already
kept, so the checkpoint is always the last approved build. Approving clears it. The
first build saves none: there is no approved build to go back to, so rejecting it
builds it again.

The chat_id is the chat's memory scope, /chat/<chat_id> (crew.py). Only the Chat Agent
saves memories; the Change Router and check jobs only recall them.

Each project works in its own folder, output/projects/<chat_id>/ (projects.py). Its
design, change, deploy and rollback jobs run one at a time in the order they were
started, so two jobs never edit its files at once; each project has its own runner,
so different projects build at the same time. Check jobs only report, so they run in
parallel on a shared runner.
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
from alikable.flows.intake import run_planning_phase, save_site_spec
from alikable.flows.jobs import Jobs
from alikable.flows.phases import run_design_phase, run_implementation_phase
from alikable.flows.polish import run_polish_phase
from alikable.models import HOST_NAMES, ChatReply, ChatState, Gate, Job, PipelineState, RouteDecision
from alikable.projects import Project
from alikable.site_files import clear_checkpoint, restore_checkpoint, save_checkpoint

HISTORY_LIMIT = 20   # chat lines passed to the Chat Agent
SPEAKERS = {"User: ": "user", "Assistant: ": "assistant"}   # history line prefix -> chat role

_check_runner = ThreadPoolExecutor(max_workers=3, thread_name_prefix="check")   # shared by every project


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
        summary = f"The current site spec:\n{self.state.site_spec}\n\nChange it as the user asked: {self.state.change_request}"
        site_spec, approved = run_planning_phase(self.project, summary)
        try:
            save_site_spec(self.project, site_spec)
        except ValueError as e:
            self.state.notes.append(f"The Planning crew's spec was not valid JSON ({e}); kept the old spec.")
            return
        self.state.site_spec = _read(self.project.site_spec)
        self.state.notes.append("Spec approved by the Spec Critic." if approved
                                else "Spec not approved after 2 rounds; kept the last version.")

    @listen(or_("design", run_planning))
    def run_design(self):
        self._step("design crew")
        if not self.state.site_spec:
            self.state.notes.append(f"Design skipped: no site spec at {self.project.site_spec}.")
            return
        spec = self.state.site_spec
        if self.state.route == "design":   # a planning change is already in the spec
            spec += f"\n\nRequested change: {self.state.change_request}"
        self.state.design, approved = run_design_phase(self.project, spec)
        self.state.notes.append(
            "Design approved by the Design Critic." if approved
            else "Design not approved after 3 rounds; kept the last version."
        )

    @listen(or_("implementation", run_design))
    def run_implementation(self):
        self._step("implementation crew")
        # crews before this one already made the change; the builders build their result
        approved = run_implementation_phase(
            self.project, self.state.site_spec, self.state.design,
            change_request=self.state.change_request if self.state.route == "implementation" else "",
        )
        self.state.notes.append("Build approved by the Code Reviewer." if approved
                                else "Build not approved after 3 rounds; kept the last version.")

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
    """A project after its spec is approved: its jobs, the gate waiting for the user, and its chat."""

    def __init__(self, chat_id: str, on_change: Callable[[], None] = lambda: None):
        self.id = chat_id
        self.project = Project(chat_id)
        self.on_change = on_change          # anything the project saves changed (flows/project.py)
        self.jobs = Jobs(on_change)
        # design, change, deploy and rollback jobs of this project, one at a time
        self.build_runner = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"build-{chat_id[:8]}")
        self.awaiting: Gate | None = None
        self.flow = ChatFlow()
        self.flow._session = self
        self.turn_lock = threading.Lock()   # one message at a time
        self._gate_lock = threading.Lock()

    # ------------------------------------------------------------------- gates

    def open_gate(self, gate: Gate | None) -> None:
        with self._gate_lock:
            self.awaiting = gate
        self.on_change()

    def take_gate(self, gate: Gate) -> bool:
        """Close the gate if it is the one waiting. False if it isn't, so a double click acts once."""
        with self._gate_lock:
            if self.awaiting != gate:
                return False
            self.awaiting = None
        self.on_change()
        return True

    def approve(self, host: str, detail: str) -> bool:
        """HITL #3 approve: the deploy job. False if no build is waiting for approval."""
        if not self.take_gate("build"):
            return False
        self.start_deploy(host, detail)
        return True

    def reject(self) -> bool:
        """HITL #3 reject: back to the last approved build, or a new first build if none was
        approved yet. False if no build is waiting for approval."""
        if not self.take_gate("build"):
            return False
        if self.project.checkpoint.exists():
            self.start_rollback()
        else:
            self.start_first_build(title="Build again")
        return True

    # -------------------------------------------------------------------- jobs

    def start_design(self, request: str = "") -> Job:
        """The Design crew designs the site from the spec, plus a change the user asked for at HITL #2."""
        def work(job: Job) -> str:
            self.jobs.update(job, step="design crew")
            spec = _read(self.project.site_spec)
            if request:
                spec += f"\n\nRequested change: {request}"
            _, approved = run_design_phase(self.project, spec)
            self.open_gate("design")
            return ("Design approved by the Design Critic." if approved
                    else "Design not approved after 3 rounds; kept the last version.") + " Waiting for approval."

        title = f"Design change: {request}" if request else "Design"
        return self.jobs.start("design", title, work, self.build_runner, request=request)

    def start_first_build(self, title: str = "First build") -> Job:
        """Build the approved design: implementation, then polish. No checkpoint: nothing was approved yet."""
        return self.start_change("implementation", "", title=title, checkpoint=False)

    def start_change(self, route: str, request: str, title: str = "", checkpoint: bool = True) -> Job:
        """Runs the crew the change was routed to and every crew after it, then HITL #3 waits."""
        self.open_gate(None)   # a new change replaces the build waiting for approval

        def work(job: Job) -> str:
            if checkpoint:
                save_checkpoint(self.project)
            pipeline = ChangePipelineFlow()
            pipeline._on_step = lambda step: self.jobs.update(job, step=step)
            pipeline.kickoff(inputs={"chat_id": self.id, "route": route, "change_request": request})
            self.open_gate("build")
            return " ".join(pipeline.state.notes) + " Waiting for approval or a change."

        return self.jobs.start("change", title or f"Change from the {route} crew: {request}", work,
                               self.build_runner, route=route, request=request, title=title, checkpoint=checkpoint)

    def start_deploy(self, host: str, detail: str) -> Job:
        def work(job: Job) -> str:
            clear_checkpoint(self.project)   # this build is approved
            result = run_deploy_guide_phase(self.project, host, detail,
                                            on_step=lambda step: self.jobs.update(job, step=step))
            return result.summary()

        return self.jobs.start("deploy", f"Deploy guide for {HOST_NAMES[host]}", work, self.build_runner,
                               host=host, detail=detail)

    def start_rollback(self) -> Job:
        def work(job: Job) -> str:
            restored = restore_checkpoint(self.project)
            if not self.project.guide.exists():   # the restored build was never approved
                self.open_gate("build")
            if restored:
                return "Restored the last approved build; every change since was undone."
            return "There was no checkpoint to restore, so nothing changed."

        return self.jobs.start("rollback", "Undo changes since the last approval", work, self.build_runner)

    def start_check(self, agent: str, question: str) -> Job:
        role = Alikable(self.project).agents_config[agent]["role"].strip()  # type: ignore[index]
        return self.jobs.start("check", f"{role} check", lambda job: _run_check(agent, question, self.project),
                               _check_runner, agent=agent, question=question)

    def retry(self, job_id: str) -> Job | None:
        """Start a failed or interrupted job again. None if there is no such job to retry."""
        job = self.jobs.get(job_id)
        if job is None or job.status not in ("failed", "interrupted"):
            return None
        starters: dict[str, Callable[..., Job]] = {
            "design": self.start_design, "change": self.start_change, "deploy": self.start_deploy,
            "rollback": self.start_rollback, "check": self.start_check,
        }
        return starters[job.kind](**job.params)

    # -------------------------------------------------------------------- chat

    def messages(self) -> list[dict[str, str]]:
        """The chat so far as {role, content} messages, oldest first, for the UI."""
        lines = list(self.flow.state.history)
        return [{"role": role, "content": line.removeprefix(prefix)}
                for line in lines for prefix, role in SPEAKERS.items() if line.startswith(prefix)]

    def send(self, message: str) -> str:
        """Answer one user message; returns the reply."""
        with self.turn_lock:
            self.flow.kickoff(inputs={"message": message, "reply": ""})
            reply = self.flow.state.reply
        self.on_change()
        return reply


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
            "awaiting_approval": "yes" if session.awaiting == "build" else "no",
            "jobs": session.jobs.for_chat(),
        })

        decision = result.pydantic
        if not isinstance(decision, ChatReply):   # unstructured answer: treat it as a reply
            decision = ChatReply(action="reply", message=result.raw)
        if decision.action in ("approve", "reject") and session.awaiting != "build":
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
        for agent in self.state.check_agents:
            self._session.start_check(agent, self.state.check_question)

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
        self._session.start_change(self.state.route, self.state.change_request)

    @listen("approve")
    def start_deploy(self):
        self._session.approve(self.state.deploy_host, self.state.deploy_detail)

    @listen("reject")
    def start_rollback(self):
        self._session.reject()


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
