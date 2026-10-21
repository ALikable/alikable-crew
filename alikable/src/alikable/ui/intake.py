"""
Intake screens: intake form -> input guardrail -> interview rounds -> spec gate (HITL #1).

The intake flow (flows/intake.py) does the work up to HITL #1; this screen only draws
it. The Discovery Interviewer asks its questions one tab each, as options to pick from,
plus Other for a custom answer. Then the user approves the spec, edits it by hand, or
describes changes for the Planning crew. Approving saves the project's site_spec.json
and starts the design job; app.py then opens the design screen.

One browser session reuses these components for every project it opens, so render sets
every property that differs between stages, never only the ones that changed.
"""

import queue
from concurrent.futures import ThreadPoolExecutor

import gradio as gr

from alikable.flows import project as projects_api
from alikable.flows.intake import MAX_QUESTIONS
from alikable.models import IntakeForm, IntakeState

OTHER = "Other"
QUALITIES = ["Intuitive", "Responsive", "Accessible", "Fast"]
STEP_STATUS = {   # the intake flow's steps that take long enough to show
    "discovery interviewer": "_The Discovery Interviewer is reading your answers..._",
    "planning crew": "_The Planning crew is writing the plan specification. This takes a few minutes..._",
}


class IntakeScreen:
    def __init__(self, chat_id: gr.BrowserState):
        self.chat_id = chat_id
        self.state = gr.State(IntakeState())

        with gr.Column() as self.form:
            self.description = gr.Textbox(label="What should the app do?", lines=3,
                                          placeholder="Users log in, see their tasks, add and delete them.")
            self.audience = gr.Textbox(label="Who will use it?")
            self.look_and_feel = gr.Textbox(label="How should it look?", placeholder="Clean, light theme, blue accent")
            self.qualities = gr.CheckboxGroup(QUALITIES, label="What matters most?")
            self.api_base_url = gr.Textbox(label="API base URL",
                                           info="Leave empty if there is no backend yet; the pages will use mock data.")
            self.endpoints = gr.Textbox(label="Endpoints", lines=4,
                                        info="One per line: method and path. Never paste tokens or passwords.",
                                        placeholder="POST /api/auth/login\nGET /api/tasks")
            start = gr.Button("Start", variant="primary")

        with gr.Column(visible=False) as self.interview:
            gr.Markdown("### The Discovery Interviewer has a few questions\nAnswer each tab: pick an option, or Other "
                        "to type your own. Leave any blank to let the agents decide.")
            with gr.Tabs() as self.question_tabs:
                slots = []
                for i in range(MAX_QUESTIONS):
                    with gr.Tab(f"Question {i + 1}", id=i, visible=False) as tab:
                        slots.append((tab, gr.Radio(), gr.Textbox(label="Your answer", visible=False)))
            submit = gr.Button("Submit answers", variant="primary")
        self.tabs, self.radios, self.others = (list(c) for c in zip(*slots))

        self.status = gr.Markdown()
        with gr.Column(visible=False) as self.review:
            self.spec = gr.Code(language="json", label="Plan specification (you can edit it before approving)",
                                interactive=True)
            with gr.Column() as self.actions:
                self.changes = gr.Textbox(label="Or describe what to change", lines=2,
                                          info="The Planning crew rewrites the spec with these changes; "
                                               "hand edits above are not kept.")
                with gr.Row():
                    approve = gr.Button("Approve spec", variant="primary")
                    revise = gr.Button("Request changes")

        fields = [self.description, self.audience, self.look_and_feel, self.qualities, self.api_base_url,
                  self.endpoints]
        outputs = self.outputs
        start.click(self._begin, fields, outputs)
        submit.click(self._answer, [self.state, *self.radios, *self.others], outputs)
        revise.click(self._request_changes, [self.state, self.changes], outputs)
        # finishes when the spec was approved, or the approval refused; app.py then opens the design screen
        self.approved = approve.click(self._approve, [self.state, self.spec], outputs)
        for radio, other in zip(self.radios, self.others):
            radio.change(lambda choice: gr.Textbox(visible=choice == OTHER), radio, other)

    @property
    def outputs(self) -> list:
        return [self.chat_id, self.state, self.form, self.interview, self.question_tabs, self.status, self.review,
                self.spec, self.changes, self.actions, *self.tabs, *self.radios, *self.others,
                self.description, self.audience, self.look_and_feel, self.qualities, self.api_base_url,
                self.endpoints]

    # ------------------------------------------------------------------ render

    def render(self, s: IntakeState, notify: bool = True) -> dict:
        """The screen for the flow's stage. notify shows this action's warnings; reopening a project doesn't."""
        if notify:
            for warning in s.warnings:
                gr.Warning(warning)
        asking = s.questions if s.stage == "interview" else []
        hidden = MAX_QUESTIONS - len(asking)
        screen = {
            self.state: s,
            self.form: gr.Column(visible=s.stage == "form"),
            self.interview: gr.Column(visible=s.stage == "interview"),
            self.review: gr.Column(visible=s.stage in ("review", "approved")),
            self.question_tabs: gr.Tabs(selected=0),
            **dict(zip(self.tabs, [gr.Tab(q.header, visible=True) for q in asking] + [gr.Tab(visible=False)] * hidden)),
            **dict(zip(self.radios, [gr.Radio([(f"{o.label} — {o.description}", o.label) for o in q.options]
                                              + [(f"{OTHER} — type your own answer", OTHER)],
                                              value=None, label=q.question) for q in asking]
                       + [gr.Radio(choices=[], value=None, label=None)] * hidden)),
            **{o: gr.Textbox(value="", visible=False) for o in self.others},
            self.spec: gr.Code(value=s.site_spec, interactive=s.stage == "review"),
            self.actions: gr.Column(visible=s.stage in ("review", "approved")),
            self.changes: "",
            self.status: self._status(s),
        }
        if s.chat_id and s.stage != "form":   # a refused form's chat_id is thrown away (flows/project.py)
            screen[self.chat_id] = s.chat_id
        return screen

    @staticmethod
    def _status(s: IntakeState) -> str:
        if s.problems:
            return "**Please fix:**\n" + "".join(f"\n- {p}" for p in s.problems)
        if s.stage == "review":
            note = ("The Spec Critic approved it." if s.spec_approved
                    else "The Spec Critic still had fixes after 2 rounds, so check it carefully.")
            return f"### Your plan specification is ready\n{note} Approve it to save it and design the site, or ask for changes."
        if s.stage == "approved":
            return "### Spec approved"
        return ""

    def reset(self) -> dict:
        """A blank intake form, for a new project."""
        return {**self.render(IntakeState(), notify=False),
                self.description: "", self.audience: "", self.look_and_feel: "", self.qualities: [],
                self.api_base_url: "", self.endpoints: ""}

    # ---------------------------------------------------------------- handlers

    def _run(self, action, *args):
        """Runs one intake action in the background, showing each long step as it starts. Returns its intake state."""
        steps: queue.Queue[str] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(action, *args, on_step=steps.put)
            while not (future.done() and steps.empty()):
                try:
                    step = steps.get(timeout=0.5)
                except queue.Empty:
                    continue
                if step in STEP_STATUS:
                    yield {self.status: STEP_STATUS[step]}
        return future.result().intake

    def _begin(self, desc, aud, look, quals, url, eps):
        """Intake form -> intake flow: input guardrail, then the first interview round."""
        yield {self.status: "_Checking your answers..._", self.form: gr.Column(visible=False)}
        form = IntakeForm(description=desc, audience=aud, look_and_feel=look, qualities=quals, api_base_url=url.strip(),
                          endpoints=[e.strip() for e in eps.splitlines() if e.strip()])
        s = yield from self._run(projects_api.new_project, form)
        yield self.render(s)

    def _answer(self, s: IntakeState, *values):
        """Sends this round's answers; the flow asks the next round or writes the spec."""
        picks, typed = values[:MAX_QUESTIONS], values[MAX_QUESTIONS:]
        replies = [(t if p == OTHER else p) or "" for p, t in zip(picks, typed)]
        yield {self.interview: gr.Column(visible=False)}
        s = yield from self._run(projects_api.answer_interview, s.chat_id, replies)
        yield self.render(s)

    def _request_changes(self, s: IntakeState, request: str):
        """HITL #1 edit: the Planning crew rewrites the spec with the user's changes."""
        yield {self.review: gr.Column(visible=False)}
        s = yield from self._run(projects_api.revise_spec, s.chat_id, request)
        yield self.render(s)

    def _approve(self, s: IntakeState, site_spec: str) -> dict:
        """HITL #1 approve: the flow saves the spec and the design job starts."""
        return self.render(projects_api.approve_spec(s.chat_id, site_spec).intake)
