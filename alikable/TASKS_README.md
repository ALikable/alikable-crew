# Alikable tasks: summary of changes

Source of truth: `Documents/Agent_Diagram.png` / `agent-flow.html` (newer than `ALikable.pdf`, which
describes the earlier 4-crew / 7-agent design). `agents.yaml` already followed the diagram; the tasks
and crews did not exist yet.

## Files

| File | Change |
|------|--------|
| `src/alikable/config/tasks.yaml` | **Replaced.** The template `research_task` / `reporting_task` pointed at agents that no longer exist. Now 14 tasks, one per agent, grouped by crew. |
| `src/alikable/crew.py` | **Replaced.** It referenced the removed `researcher` / `reporting_analyst` agents and would have raised `KeyError`. Now one `@agent` and one `@task` per YAML entry, plus one crew per phase. |
| `src/alikable/main.py` | **Edited.** The four duplicated `topic` / `current_year` dicts became one `INPUTS`; entry points use `planning_crew()`. |
| `TASKS_README.md` | **Created.** This file. |

`agents.yaml`, `custom_tool.py`, `pyproject.toml` and the template `README.md` are untouched.

## Design

- **Crews** (`crew.py`): `interview_crew`, `planning_crew`, `design_crew`, `implementation_crew`,
  `qa_crew`, `audit_crew`, `fix_crew` (Polish & Iterate, one crew per task so `flows/polish.py` can
  run QA and the audit in parallel and the Fixer once per issue), `deploy_crew`,
  `change_router_crew`, `chat_crew`. A single `_crew()` helper builds them, so each is one line.
- **Data inside a crew** moves with `context` in YAML. **Data between crews** moves as inputs
  (`site_spec`, `design`, `change_request`), because the Flow owns `site_spec.json`.
- **Output guardrails** from the diagram (valid CSS and layouts, no secrets in code, deploy steps
  tested) are string `guardrail`s in YAML, so they need no Python.
- **Files written**: `output/site_spec.json`, `output/design/` (by `phases.save_design_files`),
  `output/site/` (the build; agents return `FileChange`s and `site_files.py` writes them),
  `output/polish_report.json`, `output/DEPLOY.md`.
- **Interview**: `interview_crew` runs one `interview_task` round per batch of answers. It returns an
  `Interview` (questions with options, plus a summary), and the Gradio UI shows each question as
  options plus Other. `human_input` was removed because it reads from the console.
- **UI** (`app.py`, `uv run ui`): intake form -> input guardrail (`guardrails.py`) -> interview
  (max 3 rounds) -> `planning_crew` (Spec Writer, Copywriter, Spec Critic, max 2 rounds via
  `flows/phases.run_review_loop`, shared with the Design phase).
- **Router output** is a `RouteDecision` (planning, design, implementation, polish or clarify, plus the
  restated request). The chat and change pipeline are in `flows/change_router.py`; see `PLAN.md`.
- Verified against the CrewAI 1.15.28 source (the locked version): YAML keys are real `Task` fields,
  and `agent` / `context` resolve from YAML. A static check confirmed every agent and task is wired,
  every `context` points to an earlier task in the same crew, and every placeholder has an input.

## Not done (out of scope for tasks.yaml, needed next)

- **The Flow**: HITL #1 and #2, parallel Page Builders, and the hand-over from the intake UI to the
  chat. The chat, Change Router, polish loop and HITL #3 are built; `PLAN.md` tracks the rest.
  `crewai run` runs the Planning crew on the sample summary in `main.py`; `uv run ui` runs intake,
  guardrail and the Planning phase.
- **Tools**: Release Builder, MCP Filesystem / Playwright / GitHub, research team, memory. Tasks that
  mention a browser or packaging assume those tools once wired. The Build Checker
  (`tools/build_checker.py`) is built and used by the QA Tester and the polish loop.
- **Tool guardrails** beyond the Build Checker. `QAReport` and the other polish models are in `models.py`.
- **Not run end to end**: CrewAI is not installed here (Python 3.14 is outside `>=3.10,<3.14`), so no
  LLM run was done. Try `crewai run` after `crewai install`.
