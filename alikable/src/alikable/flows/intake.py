"""
Intake and planning phase (Intake form, Input guardrail, Planning crew and HITL #1 in
Documents/Agent_Diagram.png).

The flow runs once per user action and keeps its state between them, like the chat
(change_router.py); the project's session holds it (flows/project.py). After each
action the IntakeState's stage says what to show:
  form    -> the input guardrail checks the intake form, then the first interview round
  answers -> the answers are added to the interview, then the next round
  changes -> HITL #1 edit: the Planning crew rewrites the spec with the user's changes
  approve -> HITL #1 approve: the spec is saved to the project's site_spec.json

Each round the Discovery Interviewer asks up to MAX_QUESTIONS questions, as options to
pick from. When nothing important is unclear, or after max_rounds rounds, the Planning
crew writes the spec (max 2 rounds with the Spec Critic).

Submitting the form starts a chat: its chat_id is the chat's memory scope (crew.py)
and names the project folder, output/projects/<chat_id>/ (projects.py). The folder
is made only once the input guardrail accepts the form. Before planning, the form and the interview answers are saved to that memory, so the
Chat Agent knows what the user asked for. The interview and planning crews have no
memory of their own.

After approval a design job runs the Design crew on the saved spec (flows/project.py).
"""

import json
from collections.abc import Callable
from typing import Literal

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import PrivateAttr

from alikable.crew import Alikable, chat_memory
from alikable.flows.phases import run_review_loop
from alikable.guardrails import SECRET_WARNING, check_intake, redact_secrets
from alikable.models import IntakeState, Interview
from alikable.projects import Project

MAX_QUESTIONS = 4   # matches the interview task's limit
NO_ANSWER = "No answer, choose a sensible default"
# The stages each action is allowed at
ACTION_STAGES = {"form": ("form",), "answers": ("interview",), "changes": ("review",), "approve": ("review",)}


def run_interview(project: Project, intake_form: str, answers: str) -> Interview:
    """One interview round: the questions to ask next (none when done) and the summary so far."""
    result = Alikable(project).interview_crew().kickoff(
        inputs={"intake_form": intake_form, "answers": answers}
    )
    return result.pydantic or Interview(questions=[], summary=result.raw)   # unstructured: treat as done


def run_planning_phase(project: Project, interview_summary: str, max_rounds: int = 2) -> tuple[str, bool]:
    """Returns (site_spec, approved)."""
    result, approved = run_review_loop(
        "Spec", lambda: Alikable(project).planning_crew(),
        {"interview_summary": interview_summary, "chat_id": project.chat_id},   # chat_id places the draft (tasks.yaml)
        max_rounds, project.spec_review_log,
    )
    return result.tasks_output[1].raw, approved       # Copywriter's output is the complete spec


def save_site_spec(project: Project, site_spec: str) -> None:
    """HITL #1 approved: saves the project's site_spec.json. Raises ValueError if it is not valid JSON."""
    spec = json.loads(site_spec.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))
    project.dir.mkdir(parents=True, exist_ok=True)
    project.site_spec.write_text(json.dumps(spec, indent=2), encoding="utf-8")


class IntakeFlow(Flow[IntakeState]):
    """Handles one user action per kickoff, from the intake form to the approved spec."""

    _on_step: Callable[[str], None] | None = PrivateAttr(default=None)   # set by the caller

    @property
    def project(self) -> Project:
        return Project(self.state.chat_id)

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
        self.project.save_info(title=(form.description.strip().splitlines() or ["Untitled"])[0][:80])
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
        result = run_interview(self.project, self.state.intake, self.state.answers or "None")
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
        self.state.site_spec, self.state.spec_approved = run_planning_phase(self.project, self.state.summary)
        self.state.stage = "review"

    @listen("approve")
    def save_spec(self):
        self._step("saving the approved spec")
        try:
            save_site_spec(self.project, self.state.site_spec)
        except ValueError as e:
            self.state.problems = [f"The spec is not valid JSON ({e}). Fix it or ask for changes."]
            return
        self.state.site_spec = self.project.site_spec.read_text(encoding="utf-8")
        self.state.stage = "approved"
