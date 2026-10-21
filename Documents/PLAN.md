# PLAN: Gradio UI on top of the Change Router

How the Gradio UI uses `src/alikable/flows/change_router.py`, and what is still unbuilt
around it. The UI runs in this project and calls the chat as ordinary Python functions
in the same process. It is not a web API.

## What exists today

| Piece | State |
|---|---|
| `flows/change_router.py` | Built. `run_chat()`, `chat_status()`, background jobs, approval state |
| Chat Agent, Change Router (`crew.py`, YAML) | Built |
| Design crew + review loop (`flows/phases.py`) | Built |
| Polish & Iterate loop (`flows/polish.py`) | Built. QA Tester ‖ Consistency Auditor → Fixer one item at a time, `POLISH_ROUNDS` (default 1) rounds of fixes then a report-only check; writes `output/polish_report.json` |
| Build Checker tool (`tools/build_checker.py`) | Built. Static: HTML, local links, CDN allowlist, CSS braces, `node --check`, JSON, secrets |
| Rollback (`site_files.py`) | Built. A fix that adds build errors is undone at once; a change job checkpoints the last approved build and **reject** restores it |
| Intake flow (`flows/intake.py`, `guardrails.py`) | Built. `IntakeFlow`, one kickoff per user action (`start_intake`, `answer_interview`, `revise_spec`, `approve_spec`), each returning an `IntakeState` whose `stage` (form, interview, review, approved) says what to show: intake form → input guardrail → Discovery Interviewer rounds (multiple choice, max 3) → Planning crew → HITL #1, which saves `output/site_spec.json`. `run_in_terminal()` is the terminal version |
| Planning crew + review loop (`flows/intake.py`) | Built (`run_interview`, `run_planning_phase`, max 2 rounds, using `run_review_loop` from `flows/phases.py`). Not yet called by the change pipeline: `TODO(planning crew)` in `ChangePipelineFlow.run_planning` |
| `main.py` (`crewai run`) | Runs the whole flow in the terminal: intake flow with a sample form → HITL #1 → Design crew → the Change Router chat with the intake's `chat_id`. `train`/`test`/`replay` still use the Planning crew alone |
| Implementation crew | Defined in `crew.py`, not built. `TODO(<crew>)` placeholder in the change pipeline |
| Deploy Guide crew (`flows/create_deploy_guide.py`) | Built. `run_deploy_guide_phase(host, detail)`: Release Builder (`tools/release_builder.py`) zips `output/site/` to `output/site.zip` and smoke-tests it on localhost; the writer makes `output/DEPLOY.md` (also inside the zip) for one host (netlify, vercel, github_pages, s3) at quick/standard/detailed depth; Python checks headings, secrets and file names, max 2 rounds. Started by approve in the chat |
| Chat memory (`crew.py`) | Built. One shared `Memory` in `output/memory/` (LLM: `MEMORY_MODEL`, default `gpt-5.4-mini`), one scope per chat, `/chat/<chat_id>`. Only `chat_crew` saves; `change_router_crew` and check jobs recall read-only; every other crew has no memory. The intake form and interview answers are saved there before planning. Not undone by reject |
| Gradio UI | Intake screen built (`src/alikable/app.py`): draws the intake flow's screens up to HITL #1, then runs the Design crew. Chat, jobs and approval panels not built (this plan) |

## The contract the UI builds on

```python
from alikable.flows.change_router import run_chat, chat_status

response = run_chat(message, chat_id)   # one call per user message; chat_id comes from the intake form
response = chat_status(chat_id)         # refresh without sending a message
```

Both return a `ChatResponse`:

| Field | UI use |
|---|---|
| `chat_id` | Made by the intake form, kept in `gr.State`; pass on every call. It is also the chat's memory scope, `/chat/<chat_id>` |
| `reply` | Append to the chat as the assistant message (empty from `chat_status`) |
| `awaiting_approval` | Show the approval banner with Approve and Reject buttons (HITL #3) |
| `jobs: list[Job]` | Jobs panel: `kind` (check, change, deploy, rollback), `title`, `status`, `step`, `result`, `error`, `updated_at` |

`run_chat` returns after the Chat Agent answers (seconds). Crews run as background jobs,
so the UI never waits on them. It polls `chat_status` to show their progress.

## Layout

```
+--------------------------------------------+-------------------------------+
| Chat                                       | Jobs                          |
|                                            | [running] Change from the     |
|  user: make the header dark                |   design crew: ... (design    |
|  alikable: Sending this to the design      |   crew)            job 5803e6 |
|            crew...                         | [queued]  Change from the     |
|                                            |   polish crew: ... job 0c94ac |
|                                            | [done]    QA Tester check     |
|                                            |                               |
| +----------------------------------------+ +-------------------------------+
| | Build ready. [Approve] or describe a   | | Job details (selected job):   |
| | change.                                | |   result / error              |
| +----------------------------------------+ +-------------------------------+
| [ message box                    ] [Send]  |                               |
+--------------------------------------------+-------------------------------+
```

## Implementation steps

### Step 1. Chat panel (works with today's code)

- Gradio and the `ui` script (`alikable.app:main`) already exist. Add the chat to the
  existing `gr.Blocks` in `src/alikable/app.py`, shown once the intake screen is done (Step 4):
  - `gr.Chatbot` (messages format), `gr.Textbox` + Send button, `gr.State` for `chat_id`.
  - Send handler: call `run_chat(text, chat_id)`, append the user and assistant
    messages, and update the jobs panel and banner from
    the same response.
  - Disable the Send button while a call is running. `ChatSession.turn_lock` already
    queues overlapping calls, but the UI should not encourage them.
- `load_dotenv()` once at app start (`main()` in `change_router.py` does this only for
  the terminal).

```python
def send(text, history, chat_id):
    response = run_chat(text, chat_id)
    history += [{"role": "user", "content": text},
                {"role": "assistant", "content": response.reply}]
    return "", history, jobs_table(response), banner(response)
```

### Step 2. Jobs panel and polling

- `gr.Dataframe` (or a `gr.HTML` list) of jobs: status, title, step, job id. Show
  newest first, with a status color for queued, running, done and failed.
- `gr.Timer(2)` whose tick calls `chat_status(chat_id)` and refreshes the jobs panel
  and the approval banner. Skip the tick until the intake form has made a `chat_id`.
- Selecting a job shows its `result` or `error` in a details box.
- When a job finishes, show it in the jobs panel but do not post into the chat. The
  Chat Agent already reports finished results in its next reply (`jobs_for_chat()`),
  so posting them again would duplicate them.

### Step 3. Approval controls (HITL #3)

- Banner (`gr.Markdown`, visible only when `awaiting_approval`): "Build ready. Approve
  or describe a change."
- Approve button. Today it would have to send the text "approve" through `run_chat`,
  which spends an LLM call and relies on the Chat Agent picking `approve`. Add a direct
  call in `change_router.py` instead:

  ```python
  def approve(chat_id: str) -> ChatResponse:
      """Start the deploy job without asking the Chat Agent."""
  ```

  It should reuse the body of `ChatFlow.start_deploy`, with the same "only when
  awaiting approval" guard.
- Reject button: same idea, a direct `reject(chat_id)` that reuses
  `ChatFlow.start_rollback`. Saying "undo that" in the chat already works through the
  Chat Agent's `reject` action. Rejecting undoes every change since the last approval,
  not only the latest one.
- Show `output/polish_report.json` with the banner: fixes (fixed, skipped, reverted,
  failed), the build check, and the bugs and suggestions still open.
- Describing a change in the chat while the banner is up already works: a new change
  clears `awaiting_approval` and builds on top of the unapproved build.

### Step 4. Intake flow and HITL #1 / #2 in the UI

The first build happens before the chat, so the UI needs a first screen and two more
approval gates.

- **Done** (`flows/intake.py`, drawn by `app.py`): the intake form, the input guardrail
  (`guardrails.py`: front end only, endpoints as method + path, secrets removed), the
  Discovery interview as rounds of multiple-choice questions on screen (`human_input` was
  dropped), the Planning crew, and the spec gate (HITL #1). After approval `app.py` runs
  the Design crew.
- Still to do: the design gate, then replace the intake screen with the chat.
- Generalize the approval state so one banner serves all three gates:
  `awaiting_approval: bool` → `awaiting: Literal["spec", "design", "build"] | None`.
  - Spec gate (HITL #1): show `site_spec.json`; Approve or describe edits → planning.
  - Design gate (HITL #2): show `output/design/components.html` and the page layouts in a
    `gr.HTML` iframe preview, plus `styles.css` in a `gr.Code` editor; Approve or edit →
    design. Hand edits are saved back to `output/design/`.
  - Build gate (HITL #3): as in Step 3.
- After the intake flow finishes, it hands over to the same `ChatSession`, so the job
  history and gates stay in one place.

### Step 5. Show the built site

- Preview the built pages in a `gr.HTML` iframe (or serve `output/` with Gradio's
  `allowed_paths`).
- After the deploy job, offer `site.zip` and `DEPLOY.md` with `gr.DownloadButton`.

## Unfinished backend tasks

In rough order; the UI steps above note which ones they depend on.

1. **Intake flow** (Step 4): intake form → input guardrail → planning → HITL #1 is built
   (`flows/intake.py`). Still to do: design → HITL #2 → implementation → polish →
   HITL #3 → deploy, reusing the change pipeline's crew steps and ending in a
   `ChatSession`. Today `main.py` and `app.py` run only the design after HITL #1.
2. **Planning crew in the change pipeline**: the crew and `run_planning_phase()`
   (`flows/intake.py`) are built (and the `knowledge_sources` typo is fixed). Replace `TODO(planning crew)` in
   `ChangePipelineFlow.run_planning` with a call to it. It takes an interview summary,
   not a change request, so pass the current spec plus the change as the summary,
   then reload `site_spec` from `SITE_SPEC`.
3. **Implementation crew**: no task writes files yet, and there are no parallel Page
   Builders. Replace `TODO(implementation crew)`.
   - **Assumption (agreed for now): the build lands in `output/site/`** as plain HTML,
     CSS and JS files, with `index.html` at the top. The polish loop, the Build Checker
     and the checkpoint all read from there (`site_files.SITE_DIR`).
   - Return files as `FileChange` objects and write them with
     `site_files.apply_changes()`, as the Fixer does, rather than giving agents a
     file-write tool. That keeps writes inside `output/site/` and undoable.
   - Give the Code Reviewer the `BuildCheckerTool` too.
   - Then remove the stand-in in `PolishFlow.load_build`, which copies the design
     layouts into `output/site/` when it has no pages.
4. **Polish crew**: built, but the QA Tester reads the code instead of using the site:
   it needs MCP Playwright to click through pages and read console errors. The Build
   Checker is static only, so runtime errors are not caught yet.
5. **Deploy Guide crew**: built. The UI still needs a host picker and a detail picker
   (today the Chat Agent reads them from the approve message, default netlify/standard),
   a `gr.Markdown` view of `DEPLOY.md`, and download buttons (Step 5).
6. **`approve(chat_id)`** in `change_router.py` (Step 3).
7. **Background checks get no file access.** They only see the spec and design text.
   Once tools exist, give reviewers read-only access to `output/`.
8. **One project per run.** Sessions are separate, but all of them read and write the
   same `output/` folder. That's fine for a single local user. Running several projects
   would need a folder per session.
9. **Persistence.** Sessions and jobs are in memory and are lost when the app restarts.
   If that matters, save `ChatSession` state (history, jobs, awaiting) to
   `output/session.json`, or use the Flow `@persist` decorator. Memory already survives
   restarts (`output/memory/`), but `chat_id` lives in `gr.State`, so a page reload starts a
   new chat and the old chat's memories are never read again. Resuming needs both the
   session saved and the `chat_id` kept (e.g. `gr.BrowserState`).
10. **Crews build every agent and task (low priority).** Each `@crew` call builds all 15
    agents and 15 tasks to return the few it uses (about 0.4s per crew build). Knowledge is not
    embedded then (only at kickoff, for the crew's own agents), so it costs no LLM or embedding
    calls. Removing `@crew` would fix it, at the cost of the automatic crew name and kickoff hooks.
11. **Streaming (deferred).** Later: split `chat_task` into a structured decision task and
    a streamed reply task, run the reply with `Crew(stream=True)`, and make the Send
    handler a generator that yields partial replies to the `gr.Chatbot`.

## Testing

- Unit-test `change_router.py` with the crews faked: routing for each route, job status
  changes, one-at-a-time change jobs, approve only when awaiting, and clarify replies.
  The scratch test from building the router covers these and can move to
  `tests/test_change_router.py`.
- UI: start the app, send a change, and watch the job go queued → running (with its
  step) → done. Check that the banner appears and that Approve starts a deploy job.
