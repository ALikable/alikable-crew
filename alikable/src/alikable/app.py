"""
Gradio UI for the start of the Flow: intake form -> input guardrail -> Planning crew -> HITL #1.

The Discovery Interviewer asks its questions one tab each, as options to pick from,
plus Other for a custom answer. When nothing important is unclear, or after MAX_ROUNDS,
the Planning crew drafts the spec. The user approves it (saved to output/site_spec.json),
edits it by hand, or describes changes for the Planning crew. Run from the project root: uv run ui
"""

import gradio as gr
from dotenv import load_dotenv

from alikable.flows.phases import SITE_SPEC, run_interview, run_planning_phase, save_site_spec
from alikable.guardrails import SECRET_WARNING, check_intake, redact_secrets
from alikable.models import IntakeForm

MAX_QUESTIONS = 4   # question slots on screen, matches the interview task's limit
MAX_ROUNDS = 3      # interview rounds before the Spec Writer starts anyway
OTHER = "Other"
NO_ANSWER = "No answer, choose a sensible default"
QUALITIES = ["Intuitive", "Responsive", "Accessible", "Fast"]


def clean(text: str) -> str:
    """Input guardrail for typed text: removes secrets and tells the user."""
    if (redacted := redact_secrets(text)) != text:
        gr.Warning(SECRET_WARNING)
    return redacted


with gr.Blocks(title="Alikable") as demo:
    state = gr.State({})
    gr.Markdown("# Alikable\nHere are my endpoints, give me the UI: a plain HTML, CSS and JavaScript front end.")

    with gr.Column() as intake:
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

    def plan(s: dict):
        """Planning crew drafts the spec, then HITL #1 shows it for approval."""
        yield {status: "_The Planning crew is writing the plan specification. This takes a few minutes..._",
               intake: gr.Column(visible=False), interview: gr.Column(visible=False), review: gr.Column(visible=False)}
        site_spec, approved = run_planning_phase(s["summary"])
        note = "The Spec Critic approved it." if approved else "The Spec Critic still had fixes after 2 rounds, so check it carefully."
        yield {state: s, status: f"### Your plan specification is ready\n{note} Approve it to save {SITE_SPEC.as_posix()}, or ask for changes.",
               review: gr.Column(visible=True), spec: site_spec, changes: ""}

    def advance(s: dict):
        """Runs one interview round and shows its questions, or plans once nothing is unclear."""
        yield {status: "_The Discovery Interviewer is reading your answers..._",
               intake: gr.Column(visible=False), interview: gr.Column(visible=False)}
        result = run_interview(s["intake"], s["answers"] or "None")
        questions = result.questions[:MAX_QUESTIONS]
        if not questions or s["round"] >= MAX_ROUNDS:
            yield from plan({**s, "summary": result.summary})
            return
        hidden = MAX_QUESTIONS - len(questions)
        shown = [gr.Radio([(f"{o.label} — {o.description}", o.label) for o in q.options]
                          + [(f"{OTHER} — type your own answer", OTHER)], value=None, label=q.question) for q in questions]
        yield {state: {**s, "round": s["round"] + 1, "questions": [q.question for q in questions]},
               status: "", interview: gr.Column(visible=True), question_tabs: gr.Tabs(selected=0),
               **dict(zip(tabs, [gr.Tab(q.header, visible=True) for q in questions] + [gr.Tab(visible=False)] * hidden)),
               **dict(zip(radios, shown + [gr.Radio(value=None)] * hidden)),
               **{o: gr.Textbox(value="", visible=False) for o in others}}

    def begin(desc, aud, look, quals, url, eps):
        """Intake form -> input guardrail -> first interview round."""
        try:
            form, warnings = check_intake(IntakeForm(
                description=desc, audience=aud, look_and_feel=look, qualities=quals, api_base_url=url.strip(),
                endpoints=[e.strip() for e in eps.splitlines() if e.strip()],
            ))
        except ValueError as e:
            yield {status: "**Please fix:**\n" + "".join(f"\n- {line}" for line in str(e).splitlines())}
            return
        for warning in warnings:
            gr.Warning(warning)
        yield from advance({"intake": form.model_dump_json(indent=2), "answers": "", "round": 0})

    def answer(s: dict, *values):
        """Adds this round's answers to the transcript (secrets removed), then runs the next round."""
        picks, typed = values[:MAX_QUESTIONS], values[MAX_QUESTIONS:]
        qa = "\n".join(f"Q: {q}\nA: {(t.strip() if p == OTHER else p) or NO_ANSWER}"
                       for q, p, t in zip(s["questions"], picks, typed))
        yield from advance({**s, "answers": f"{s['answers']}\n{clean(qa)}".strip()})

    def request_changes(s: dict, request: str):
        """HITL #1 edit: the Planning crew rewrites the spec with the user's changes."""
        if not request.strip():
            gr.Warning("Describe what to change first.")
            return
        yield from plan({**s, "summary": f"{s['summary']}\n\nChanges the user asked for after reading the spec:\n{clean(request)}"})

    def approve_spec(site_spec: str):
        """HITL #1 approve: saves the spec as site_spec.json."""
        try:
            save_site_spec(site_spec)
        except ValueError as e:
            return {status: f"**The spec is not valid JSON** ({e}). Fix it above or ask for changes."}
        return {status: f"### Spec approved\nSaved to {SITE_SPEC.as_posix()}.", spec: gr.Code(interactive=False),
                actions: gr.Column(visible=False)}

    outputs = [state, intake, interview, question_tabs, status, review, spec, changes, *tabs, *radios, *others]
    start.click(begin, [description, audience, look_and_feel, qualities, api_base_url, endpoints], outputs)
    submit.click(answer, [state, *radios, *others], outputs)
    revise.click(request_changes, [state, changes], outputs)
    approve.click(approve_spec, spec, [status, spec, actions])
    for radio, other in zip(radios, others):
        radio.change(lambda choice: gr.Textbox(visible=choice == OTHER), radio, other)


def main():
    load_dotenv()
    demo.launch()


if __name__ == "__main__":
    main()
