"""
Gradio UI for the start of the Flow: intake form -> input guardrail -> Planning crew -> HITL #1 -> Design crew.

The intake flow (flows/intake.py) does the work up to HITL #1; this file only draws its
screens. The Discovery Interviewer asks its questions one tab each, as options to pick
from, plus Other for a custom answer. Then the user approves the spec (saved to
output/site_spec.json), edits it by hand, or describes changes for the Planning crew.
Approving starts the Design crew on output/site_spec.json, which saves the design to
output/design/. Run from the project root: uv run ui
"""

import queue
from concurrent.futures import ThreadPoolExecutor

import gradio as gr
from dotenv import load_dotenv

from alikable.flows import intake
from alikable.flows.intake import MAX_QUESTIONS
from alikable.flows.phases import DESIGN_DIR, SITE_SPEC, run_design_phase
from alikable.models import IntakeForm, IntakeState

OTHER = "Other"
QUALITIES = ["Intuitive", "Responsive", "Accessible", "Fast"]
STEP_STATUS = {   # the intake flow's steps that take long enough to show
    "discovery interviewer": "_The Discovery Interviewer is reading your answers..._",
    "planning crew": "_The Planning crew is writing the plan specification. This takes a few minutes..._",
}


with gr.Blocks(title="Alikable") as demo:
    state = gr.State(IntakeState())
    gr.Markdown("# Alikable\nHere are my endpoints, give me the UI: a plain HTML, CSS and JavaScript front end.")

    with gr.Column() as intake_form:
        description = gr.Textbox(label="What should the app do?", lines=3,
                                 placeholder="Users log in, see their tasks, add and delete them.")
        audience = gr.Textbox(label="Who will use it?")
        look_and_feel = gr.Textbox(label="How should it look?", placeholder="Clean, light theme, blue accent")
        qualities = gr.CheckboxGroup(QUALITIES, label="What matters most?")
        api_base_url = gr.Textbox(label="API base URL", info="Leave empty if there is no backend yet; the pages will use mock data.")
        endpoints = gr.Textbox(label="Endpoints", lines=4, info="One per line: method and path. Never paste tokens or passwords.",
                               placeholder="POST /api/auth/login\nGET /api/tasks")
        start = gr.Button("Start", variant="primary")

    with gr.Column(visible=False) as interview:
        gr.Markdown("### The Discovery Interviewer has a few questions\nAnswer each tab: pick an option, or Other to type your own. Leave any blank to let the agents decide.")
        with gr.Tabs() as question_tabs:
            slots = []
            for i in range(MAX_QUESTIONS):
                with gr.Tab(f"Question {i + 1}", id=i, visible=False) as tab:
                    slots.append((tab, gr.Radio(), gr.Textbox(label="Your answer", visible=False)))
        submit = gr.Button("Submit answers", variant="primary")

    status = gr.Markdown()
    with gr.Column(visible=False) as review:
        spec = gr.Code(language="json", label="Plan specification (you can edit it before approving)", interactive=True)
        with gr.Column() as actions:
            changes = gr.Textbox(label="Or describe what to change", lines=2,
                                 info="The Planning crew rewrites the spec with these changes; hand edits above are not kept.")
            with gr.Row():
                approve = gr.Button("Approve spec", variant="primary")
                revise = gr.Button("Request changes")
    tabs, radios, others = (list(c) for c in zip(*slots))

    def run(action, *args):
        """Runs one intake action in the background, showing each long step as it starts. Returns the new state."""
        steps: queue.Queue[str] = queue.Queue()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(action, *args, on_step=steps.put)
            while not (future.done() and steps.empty()):
                try:
                    step = steps.get(timeout=0.5)
                except queue.Empty:
                    continue
                if step in STEP_STATUS:
                    yield {status: STEP_STATUS[step]}
        return future.result()

    def show(s: IntakeState) -> dict:
        """The screen for the flow's stage, with its warnings and problems."""
        for warning in s.warnings:
            gr.Warning(warning)
        screen = {state: s, intake_form: gr.Column(visible=s.stage == "form"),
                  interview: gr.Column(visible=s.stage == "interview"),
                  review: gr.Column(visible=s.stage in ("review", "approved"))}
        if s.problems:
            return {**screen, status: "**Please fix:**\n" + "".join(f"\n- {p}" for p in s.problems)}
        if s.stage == "interview":
            hidden = MAX_QUESTIONS - len(s.questions)
            shown = [gr.Radio([(f"{o.label} — {o.description}", o.label) for o in q.options]
                              + [(f"{OTHER} — type your own answer", OTHER)], value=None, label=q.question)
                     for q in s.questions]
            return {**screen, status: "", question_tabs: gr.Tabs(selected=0),
                    **dict(zip(tabs, [gr.Tab(q.header, visible=True) for q in s.questions] + [gr.Tab(visible=False)] * hidden)),
                    **dict(zip(radios, shown + [gr.Radio(value=None)] * hidden)),
                    **{o: gr.Textbox(value="", visible=False) for o in others}}
        if s.stage == "review":
            note = "The Spec Critic approved it." if s.spec_approved else "The Spec Critic still had fixes after 2 rounds, so check it carefully."
            return {**screen, status: f"### Your plan specification is ready\n{note} Approve it to save {SITE_SPEC.as_posix()}, or ask for changes.",
                    spec: s.site_spec, changes: ""}
        return screen

    def begin(desc, aud, look, quals, url, eps):
        """Intake form -> intake flow: input guardrail, then the first interview round."""
        yield {status: "_Checking your answers..._", intake_form: gr.Column(visible=False)}
        form = IntakeForm(description=desc, audience=aud, look_and_feel=look, qualities=quals, api_base_url=url.strip(),
                          endpoints=[e.strip() for e in eps.splitlines() if e.strip()])
        s = yield from run(intake.start_intake, form)
        yield show(s)

    def answer(s: IntakeState, *values):
        """Sends this round's answers; the flow asks the next round or writes the spec."""
        picks, typed = values[:MAX_QUESTIONS], values[MAX_QUESTIONS:]
        replies = [(t if p == OTHER else p) or "" for p, t in zip(picks, typed)]
        yield {interview: gr.Column(visible=False)}
        s = yield from run(intake.answer_interview, s.chat_id, replies)
        yield show(s)

    def request_changes(s: IntakeState, request: str):
        """HITL #1 edit: the Planning crew rewrites the spec with the user's changes."""
        yield {review: gr.Column(visible=False)}
        s = yield from run(intake.revise_spec, s.chat_id, request)
        yield show(s)

    def approve_spec(s: IntakeState, site_spec: str):
        """HITL #1 approve: the flow saves the spec, then the Design crew designs the site from it."""
        s = intake.approve_spec(s.chat_id, site_spec)
        if s.problems:
            yield show(s)
            return
        yield {state: s, status: f"### Spec approved\nSaved to {SITE_SPEC.as_posix()}.\n\n_The Design crew is designing "
                                 "your site. This takes a few minutes..._",
               spec: gr.Code(interactive=False), actions: gr.Column(visible=False)}
        try:
            _, approved = run_design_phase(SITE_SPEC.read_text(encoding="utf-8"))
        except Exception as e:
            yield {status: f"**The design failed** ({e}). Approve again to retry.",
                   spec: gr.Code(interactive=True), actions: gr.Column(visible=True)}
            return
        note = "The Design Critic approved it." if approved else "The Design Critic still had fixes after 3 rounds, so check it carefully."
        yield {status: f"### Your design is ready\n{note} Saved to {DESIGN_DIR.as_posix()}/."}

    outputs = [state, intake_form, interview, question_tabs, status, review, spec, changes, actions,
               *tabs, *radios, *others]
    start.click(begin, [description, audience, look_and_feel, qualities, api_base_url, endpoints], outputs)
    submit.click(answer, [state, *radios, *others], outputs)
    revise.click(request_changes, [state, changes], outputs)
    approve.click(approve_spec, [state, spec], outputs)
    for radio, other in zip(radios, others):
        radio.change(lambda choice: gr.Textbox(visible=choice == OTHER), radio, other)


def main():
    load_dotenv()
    demo.launch()


if __name__ == "__main__":
    main()
