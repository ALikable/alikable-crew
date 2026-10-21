"""
Intake and planning phase (Intake form, Input guardrail, Planning crew and HITL #1 in
Documents/Agent_Diagram.png).

The flow runs once per user action and keeps its state between them, like the chat
(change_router.py). Each action returns the IntakeState, whose stage says what to show:
  form    -> the input guardrail checks the intake form, then the first interview round
  answers -> the answers are added to the interview, then the next round
  changes -> HITL #1 edit: the Planning crew rewrites the spec with the user's changes
  approve -> HITL #1 approve: the spec is saved to output/site_spec.json

Each round the Discovery Interviewer asks up to MAX_QUESTIONS questions, as options to
pick from. When nothing important is unclear, or after max_rounds rounds, the Planning
crew writes the spec (max 2 rounds with the Spec Critic).

Submitting the form starts a chat: its chat_id is the chat's memory scope (crew.py).
Before planning, the form and the interview answers are saved to that memory, so the
Chat Agent knows what the user asked for. The interview and planning crews have no
memory of their own.

After approval the Design crew runs on the saved spec (app.py, main.py).
"""

import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import PrivateAttr

from alikable.crew import Alikable, chat_memory
from alikable.flows.phases import SITE_SPEC, run_review_loop
from alikable.guardrails import SECRET_WARNING, check_intake, redact_secrets
from alikable.models import IntakeForm, IntakeState, Interview

SPEC_REVIEW_LOG = Path("output/spec_review_log.md")
MAX_QUESTIONS = 4   # matches the interview task's limit
NO_ANSWER = "No answer, choose a sensible default"
# The stages each action is allowed at
ACTION_STAGES = {"form": ("form",), "answers": ("interview",), "changes": ("review",),
                 "approve": ("review", "approved")}

# Sample intake form for terminal runs (main.py). The UI collects real ones: uv run ui
SAMPLE_FORM = IntakeForm(
    description="Task manager UI. Users log in, see their tasks, add and delete them.",
    audience="Small teams tracking their own work",
    look_and_feel="Clean, light theme, blue accent",
    qualities=["Intuitive", "Responsive"],
    endpoints=["POST /api/auth/login", "GET /api/tasks", "POST /api/tasks", "DELETE /api/tasks/:id"],
)


def run_interview(intake_form: str, answers: str) -> Interview:
    """One interview round: the questions to ask next (none when done) and the summary so far."""
    result = Alikable().interview_crew().kickoff(
        inputs={"intake_form": intake_form, "answers": answers}
    )
    return result.pydantic or Interview(questions=[], summary=result.raw)   # unstructured: treat as done


def run_planning_phase(interview_summary: str, max_rounds: int = 2) -> tuple[str, bool]:
    """Returns (site_spec, approved)."""
    result, approved = run_review_loop(
        "Spec", lambda: Alikable().planning_crew(), {"interview_summary": interview_summary},
        max_rounds, SPEC_REVIEW_LOG,
    )
    return result.tasks_output[1].raw, approved       # Copywriter's output is the complete spec


def save_site_spec(site_spec: str) -> None:
    """HITL #1 approved: saves the spec to SITE_SPEC. Raises ValueError if it is not valid JSON."""
    spec = json.loads(site_spec.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    SITE_SPEC.parent.mkdir(parents=True, exist_ok=True)
    SITE_SPEC.write_text(json.dumps(spec, indent=2), encoding="utf-8")


class IntakeFlow(Flow[IntakeState]):
    """Handles one user action per kickoff, from the intake form to the approved spec."""

    _on_step: Callable[[str], None] | None = PrivateAttr(default=None)   # set by the caller

    def _step(self, step: str) -> None:
        print(f"\n===== INTAKE: {step} =====\n")
        if self._on_step:
            self._on_step(step)

    def _clean(self, text: str) -> str:
        """Input guardrail for typed text: removes secrets and warns the user once."""
        if (redacted := redact_secrets(text)) != text and SECRET_WARNING not in self.state.warnings:
            self.state.warnings.append(SECRET_WARNING)
        return redacted

    @start()
    def receive(self):
        self.state.warnings, self.state.problems = [], []

    @router(receive)
    def dispatch(self) -> Literal["form", "answers", "changes", "approve", "refused"]:
        if self.state.stage not in ACTION_STAGES.get(self.state.action, ()):
            self.state.problems = [f"Can't {self.state.action} now; the intake is at the {self.state.stage} step."]
            return "refused"
        return self.state.action  # type: ignore[return-value]

    @router("form")
    def check_form(self) -> Literal["interview", "refused"]:
        self._step("input guardrail")
        try:
            form, self.state.warnings = check_intake(self.state.form)
        except ValueError as e:
            self.state.problems = str(e).splitlines()
            return "refused"
        self.state.intake = form.model_dump_json(indent=2)
        return "interview"

    @router("answers")
    def add_answers(self) -> Literal["interview"]:
        replies = self.state.replies + [""] * len(self.state.questions)
        qa = "\n".join(f"Q: {q.question}\nA: {r.strip() or NO_ANSWER}"
                       for q, r in zip(self.state.questions, replies))
        self.state.answers = f"{self.state.answers}\n{self._clean(qa)}".strip()
        return "interview"

    @router("interview")
    def interview_round(self) -> Literal["ask", "plan"]:
        self._step("discovery interviewer")
        result = run_interview(self.state.intake, self.state.answers or "None")
        self.state.summary = result.summary
        questions = result.questions[:MAX_QUESTIONS]
        if questions and self.state.round < self.state.max_rounds:
            self.state.round += 1
            self.state.questions = questions
            self.state.stage = "interview"
            return "ask"
        self.state.questions = []
        # Once per chat, not in write_spec: changes plan again. Both are already free
        # of secrets: the input guardrail and redact_secrets ran on them.
        chat_memory(self.state.chat_id).remember(
            f"Intake form:\n{self.state.intake}\n\nInterview answers:\n{self.state.answers or 'None'}",
            source="intake",
        )
        return "plan"

    @router("changes")
    def add_changes(self) -> Literal["replan", "refused"]:
        if not self.state.request.strip():
            self.state.problems = ["Describe what to change first."]
            return "refused"
        self.state.summary += f"\n\nChanges the user asked for after reading the spec:\n{self._clean(self.state.request)}"
        return "replan"

    @listen(or_("plan", "replan"))
    def write_spec(self):
        self._step("planning crew")
        self.state.site_spec, self.state.spec_approved = run_planning_phase(self.state.summary)
        self.state.stage = "review"

    @listen("approve")
    def save_spec(self):
        self._step("saving the approved spec")
        try:
            save_site_spec(self.state.site_spec)
        except ValueError as e:
            self.state.problems = [f"The spec is not valid JSON ({e}). Fix it or ask for changes."]
            return
        self.state.site_spec = SITE_SPEC.read_text(encoding="utf-8")
        self.state.stage = "approved"


# ----------------------------------------------------------------------- UI API

_flows: dict[str, IntakeFlow] = {}
_flows_lock = threading.Lock()


def _kickoff(chat_id: str, action: str, on_step: Callable[[str], None] | None, **inputs) -> IntakeState:
    with _flows_lock:
        if chat_id not in _flows:
            _flows[chat_id] = IntakeFlow()
        flow = _flows[chat_id]
    flow._on_step = on_step
    flow.kickoff(inputs={"chat_id": chat_id, "action": action, "replies": [], "request": "", **inputs})
    return flow.state.model_copy(deep=True)


def start_intake(form: IntakeForm, on_step: Callable[[str], None] | None = None) -> IntakeState:
    """Submit the intake form. Starts a new chat; its chat_id is in the returned state."""
    chat_id = uuid.uuid4().hex
    state = _kickoff(chat_id, "form", on_step, form=form.model_dump())
    if state.problems:   # refused by the input guardrail: the next try starts a new chat
        with _flows_lock:
            _flows.pop(chat_id, None)
    return state


def answer_interview(chat_id: str, replies: list[str],
                     on_step: Callable[[str], None] | None = None) -> IntakeState:
    """One reply per question of the last round, "" to let the agents decide."""
    return _kickoff(chat_id, "answers", on_step, replies=replies)


def revise_spec(chat_id: str, request: str, on_step: Callable[[str], None] | None = None) -> IntakeState:
    """HITL #1 edit: the Planning crew rewrites the spec with these changes."""
    return _kickoff(chat_id, "changes", on_step, request=request)


def approve_spec(chat_id: str, site_spec: str, on_step: Callable[[str], None] | None = None) -> IntakeState:
    """HITL #1 approve: saves site_spec (the user may have edited it) to SITE_SPEC."""
    return _kickoff(chat_id, "approve", on_step, site_spec=site_spec)


def run_in_terminal(form: IntakeForm = SAMPLE_FORM) -> IntakeState:
    """Terminal stand-in for the intake screen. Returns the state at approved, or the refused form."""
    state = start_intake(form)
    while True:
        for line in state.warnings + state.problems:
            print(f"! {line}")
        if state.stage == "interview":
            replies = []
            for q in state.questions:
                print(f"\n{q.header}: {q.question}")
                for i, option in enumerate(q.options, 1):
                    print(f"  {i}. {option.label} - {option.description}")
                pick = input("Number, your own answer, or Enter to let the agents decide: ").strip()
                chosen = int(pick) if pick.isdigit() and 0 < int(pick) <= len(q.options) else 0
                replies.append(q.options[chosen - 1].label if chosen else pick)
            state = answer_interview(state.chat_id, replies)
        elif state.stage == "review":
            print(f"\n{state.site_spec}\n")
            print("The Spec Critic approved it." if state.spec_approved
                  else "The Spec Critic still had fixes after 2 rounds, so check it carefully.")
            reply = input("Type 'approve', or describe what to change: ").strip()
            state = approve_spec(state.chat_id, state.site_spec) if reply.lower() == "approve" \
                else revise_spec(state.chat_id, reply)
        else:
            return state


if __name__ == "__main__":
    # Test run with the sample form:  uv run python -m alikable.flows.intake
    from dotenv import load_dotenv

    load_dotenv()
    final = run_in_terminal()
    print(f"\nStage: {final.stage}. " + (f"Spec saved to {SITE_SPEC}." if final.stage == "approved" else ""))
