# PLAN: Gradio UI on top of the Change Router

How the Gradio UI uses `src/alikable/flows/change_router.py`, and what is still unbuilt
around it. The UI runs in this project and calls the chat as ordinary Python functions
in the same process. It is not a web API.

## What exists today

| Piece | State |
|---|---|
| `flows/change_router.py` | Built. `run_chat()`, `chat_status()`, background jobs, approval state |
| Chat Agent, Change Router (`crew.py`, YAML) | Built |
| Design crew + review loop (`phases.py`) | Built |
| Intake flow (first build) | Not built |
| Planning, Implementation, Polish, Deploy Guide crews | Defined in `crew.py`, not built. `TODO(<crew>)` placeholders in the change pipeline |
| Gradio UI | Not built (this plan) |

## The contract the UI builds on

```python
from alikable.flows.change_router import run_chat, chat_status

response = run_chat(message, session_id)   # one call per user message; session_id=None starts a chat
response = chat_status(session_id)         # refresh without sending a message
```

Both return a `ChatResponse`:

| Field | UI use |
|---|---|
| `session_id` | Keep in `gr.State`; pass back on every call |
| `reply` | Append to the chat as the assistant message (empty from `chat_status`) |
| `awaiting_approval` | Show the approval banner and the Approve button (HITL #3) |
| `jobs: list[Job]` | Jobs panel: `kind`, `title`, `status`, `step`, `result`, `error`, `updated_at` |

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

- `uv add gradio`; add `ui = "alikable.ui.app:main"` to `[project.scripts]`.
- New `src/alikable/ui/app.py` with a `gr.Blocks` app:
  - `gr.Chatbot` (messages format), `gr.Textbox` + Send button, `gr.State` for `session_id`.
  - Send handler: call `run_chat(text, session_id)`, append the user and assistant
    messages, store `response.session_id`, and update the jobs panel and banner from
    the same response.
  - Disable the Send button while a call is running. `ChatSession.turn_lock` already
    queues overlapping calls, but the UI should not encourage them.
- `load_dotenv()` once at app start (`main()` in `change_router.py` does this only for
  the terminal).

```python
def send(text, history, session_id):
    response = run_chat(text, session_id)
    history += [{"role": "user", "content": text},
                {"role": "assistant", "content": response.reply}]
    return "", history, response.session_id, jobs_table(response), banner(response)
```

### Step 2. Jobs panel and polling

- `gr.Dataframe` (or a `gr.HTML` list) of jobs: status, title, step, job id. Show
  newest first, with a status color for queued, running, done and failed.
- `gr.Timer(2)` whose tick calls `chat_status(session_id)` and refreshes the jobs panel
  and the approval banner. Skip the tick while `session_id` is `None`.
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
  def approve(session_id: str) -> ChatResponse:
      """Start the deploy job without asking the Chat Agent."""
  ```

  It should reuse the body of `ChatFlow.start_deploy`, with the same "only when
  awaiting approval" guard.
- Describing a change in the chat while the banner is up already works: a new change
  clears `awaiting_approval`.

### Step 4. Intake flow and HITL #1 / #2 in the UI

The first build happens before the chat, so the UI needs a first screen and two more
approval gates.

- Intake form screen (`gr.Column` of fields with the predetermined questions), shown
  until a site spec exists, then replaced by the chat.
- Input guardrail on submit: front-end only (HTML/CSS/JS), no secrets.
- **Discovery interview through the UI.** `interview_task` has `human_input: true`,
  which reads from the terminal and blocks inside the crew. In the UI this would hang
  the job. Options:
  1. Run the interview as chat turns: the Discovery Interviewer asks one question per
     `run_chat` call until it has enough, then the planning job starts. (Recommended:
     reuses the chat panel.)
  2. Collect all follow-up answers in the intake form and drop `human_input`.
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

1. **Intake flow** (Step 4): intake form → input guardrail → planning → HITL #1 →
   design → HITL #2 → implementation → polish → HITL #3 → deploy, as a Flow that reuses
   the change pipeline's crew steps and ends in a `ChatSession`.
2. **Planning crew** (Steps 4 and changes): the interview cannot use `human_input` under
   the UI (see Step 4). Fix `crew.py:21`: `knowledge_source=` should be
   `knowledge_sources=`, so the interviewer currently gets no design-practices
   knowledge. Then replace `TODO(planning crew)` in `ChangePipelineFlow.run_planning`.
3. **Implementation crew**: no task writes files yet, and there are no tools (MCP
   Filesystem, Build Checker) and no parallel Page Builders. Replace
   `TODO(implementation crew)`.
4. **Polish crew**: needs MCP Playwright for the QA Tester. Replace `TODO(polish crew)`.
5. **Deploy Guide crew**: needs the Release Builder tool (package + smoke test) to
   produce `site.zip`. Replace `TODO(deploy guide crew)` in `ChatFlow.start_deploy`.
6. **`approve(session_id)`** in `change_router.py` (Step 3).
7. **Background checks get no file access.** They only see the spec and design text.
   Once tools exist, give reviewers read-only access to `output/`.
8. **One project per run.** Sessions are separate, but all of them read and write the
   same `output/` folder. That's fine for a single local user. Running several projects
   would need a folder per session.
9. **Persistence.** Sessions and jobs are in memory and are lost when the app restarts.
   If that matters, save `ChatSession` state (history, jobs, awaiting) to
   `output/session.json`, or use the Flow `@persist` decorator.
10. **Streaming (deferred).** Later: split `chat_task` into a structured decision task and
    a streamed reply task, run the reply with `Crew(stream=True)`, and make the Send
    handler a generator that yields partial replies to the `gr.Chatbot`.

## Testing

- Unit-test `change_router.py` with the crews faked: routing for each route, job status
  changes, one-at-a-time change jobs, approve only when awaiting, and clarify replies.
  The scratch test from building the router covers these and can move to
  `tests/test_change_router.py`.
- UI: start the app, send a change, and watch the job go queued → running (with its
  step) → done. Check that the banner appears and that Approve starts a deploy job.
