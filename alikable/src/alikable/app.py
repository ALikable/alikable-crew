"""
Gradio UI for the start of the Flow: intake form -> input guardrail -> Planning crew.

The Discovery Interviewer asks its questions as options to pick from, plus Other
for a custom answer. When nothing important is unclear, or after MAX_ROUNDS, the
Planning crew writes site_spec.json. Run from the project root: uv run ui

Submitting the form starts a chat: its chat_id is the chat's memory scope (crew.py).
Before planning, the form and the interview answers are saved to that memory, so the
Chat Agent knows what the user asked for. The interview and planning crews have no
memory of their own.
"""

import uuid

import gradio as gr
from dotenv import load_dotenv

from alikable.crew import chat_memory
from alikable.flows.phases import run_interview, run_planning_phase
from alikable.guardrails import SECRET_WARNING, check_intake, redact_secrets
from alikable.models import IntakeForm

MAX_QUESTIONS = 4   # question slots on screen, matches the interview task's limit
MAX_ROUNDS = 3      # interview rounds before the Spec Writer starts anyway
OTHER = "Other"
NO_ANSWER = "No answer, choose a sensible default"
QUALITIES = ["Intuitive", "Responsive", "Accessible", "Fast"]

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
        gr.Markdown("### The Discovery Interviewer has a few questions\nPick an answer, or Other to type your own. Skip any you want the agents to decide.")
        slots = [(gr.Radio(visible=False), gr.Textbox(label="Your answer", visible=False)) for _ in range(MAX_QUESTIONS)]
        submit = gr.Button("Submit answers", variant="primary")

    status = gr.Markdown()
    spec = gr.Code(language="json", label="site_spec.json", visible=False)
    radios, others = [r for r, _ in slots], [o for _, o in slots]

    def advance(s: dict):
        """Runs one interview round and shows its questions, or writes the spec once nothing is unclear."""
        yield {status: "_The Discovery Interviewer is reading your answers..._",
               intake: gr.Column(visible=False), interview: gr.Column(visible=False)}
        result = run_interview(s["intake"], s["answers"] or "None")
        questions = result.questions[:MAX_QUESTIONS]
        if questions and s["round"] < MAX_ROUNDS:
            shown = [gr.Radio(q.options + [OTHER], value=None, label=q.question, visible=True) for q in questions]
            yield {state: {**s, "round": s["round"] + 1, "questions": [q.question for q in questions]},
                   status: "", interview: gr.Column(visible=True),
                   **dict(zip(radios, shown + [gr.Radio(value=None, visible=False)] * (MAX_QUESTIONS - len(shown)))),
                   **{o: gr.Textbox(value="", visible=False) for o in others}}
            return
        yield {status: "_The Planning crew is writing site_spec.json. This takes a few minutes..._"}
        # Both are already free of secrets: the input guardrail and redact_secrets ran on them
        chat_memory(s["chat_id"]).remember(
            f"Intake form:\n{s['intake']}\n\nInterview answers:\n{s['answers'] or 'None'}",
            source="intake",
        )
        site_spec, approved = run_planning_phase(result.summary)
        note = "The Spec Critic approved it." if approved else "The Spec Critic still had fixes after 2 rounds, so check it carefully."
        yield {status: f"### site_spec.json is ready\n{note} Saved to output/site_spec.json.", spec: gr.Code(site_spec, visible=True)}

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
        yield from advance({"chat_id": uuid.uuid4().hex, "intake": form.model_dump_json(indent=2),
                            "answers": "", "round": 0})

    def answer(s: dict, *values):
        """Adds this round's answers to the transcript (secrets removed), then runs the next round."""
        picks, typed = values[:MAX_QUESTIONS], values[MAX_QUESTIONS:]
        qa = "\n".join(f"Q: {q}\nA: {(t.strip() if p == OTHER else p) or NO_ANSWER}"
                       for q, p, t in zip(s["questions"], picks, typed))
        if (clean := redact_secrets(qa)) != qa:
            gr.Warning(SECRET_WARNING)
        yield from advance({**s, "answers": f"{s['answers']}\n{clean}".strip()})

    outputs = [state, intake, interview, status, spec, *radios, *others]
    start.click(begin, [description, audience, look_and_feel, qualities, api_base_url, endpoints], outputs)
    submit.click(answer, [state, *radios, *others], outputs)
    for radio, other in slots:
        radio.change(lambda choice: gr.Textbox(visible=choice == OTHER), radio, other)


def main():
    load_dotenv()
    demo.launch()


if __name__ == "__main__":
    main()
