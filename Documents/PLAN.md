# PLAN: one app, many projects

What is built, and the next three steps to finish Alikable as one application:

- **A. One folder per project.** Every file a project makes lives in
  `output/projects/<chat_id>/`, so several projects can live in the same install.
- **B. All UI screens** in a `ui/` package behind `app.py`: project picker, intake,
  spec gate, design gate, build progress, chat with jobs and the build gate, deploy.
- **C. `main.py` runs the whole application** by launching that UI.

The UI runs in this project and calls the flows as ordinary Python functions in the
same process. It is not a web API.

## Terms

- **Project**: one website the user builds: one intake form, one spec, one design, one
  build and one deploy guide. A project and its chat share one id, the **`chat_id`**,
  made when the intake form is submitted. The `chat_id` is also the chat's memory scope,
  `/chat/<chat_id>`.
- **Project folder**: `output/projects/<chat_id>/`, everything the project wrote.
- **Gate**: an approval step that waits for the user: HITL #1 (spec), HITL #2 (design),
  HITL #3 (build). See `Documents/Agent_Diagram.png`.

## Decisions

| Question | Decision |
|---|---|
| Where project files live | `output/projects/<chat_id>/`. Memory stays shared in `output/memory/`, one scope per chat (as today) |
| Files already in `output/` | Ignored. New code reads only `output/projects/`. Delete them by hand when no longer needed |
| Reopening a project after a restart | Yes: `session.json` in each project folder, and a project picker as the first screen |
| Users | One local user. The picker lists every project folder; no logins |
| `main.py` | Launches the UI only. The terminal stand-ins (`intake.run_in_terminal`, `change_router.main`) are removed |
| UI code | `app.py` is a thin entry point over a `ui/` package, one module per screen |

## What exists today

| Piece | State |
|---|---|
| Intake flow (`flows/intake.py`, `guardrails.py`) | Built. `IntakeFlow`, one kickoff per user action (`start_intake`, `answer_interview`, `revise_spec`, `approve_spec`), each returning an `IntakeState` whose `stage` (form, interview, review, approved) says what to show: intake form → input guardrail → Discovery Interviewer rounds (multiple choice, max 3) → Planning crew → HITL #1, which saves `output/site_spec.json`. Flows are kept in memory in `intake._flows` |
| Planning crew + review loop (`flows/intake.py`) | Built (`run_interview`, `run_planning_phase`, max 2 rounds, using `run_review_loop` from `flows/phases.py`). Not yet called by the change pipeline: `TODO(planning crew)` in `ChangePipelineFlow.run_planning` |
| Design crew + review loop (`flows/phases.py`) | Built. `run_design_phase(site_spec)`, max 3 rounds; writes `output/design/` |
| Implementation phase (`flows/phases.py`) | Built. `run_implementation_phase(site_spec, design)`: API Integrator → Page Builder return `FileChange`s, Python resets and writes `output/site/`, the Code Reviewer (with the Build Checker) checks the files on disk, max 3 rounds. Not yet called by the change pipeline: `TODO(implementation crew)`. Page Builders are not parallel |
| Polish & Iterate loop (`flows/polish.py`) | Built. QA Tester ‖ Consistency Auditor → Fixer one item at a time, `POLISH_ROUNDS` (default 1) rounds of fixes then a report-only check; writes `output/polish_report.json` |
| Build Checker tool (`tools/build_checker.py`) | Built. Static: HTML, local links, CDN allowlist, CSS braces, `node --check`, JSON, secrets. Always checks `output/site/` |
| Rollback (`site_files.py`) | Built. A fix that adds build errors is undone at once; a change job checkpoints the last approved build in `output/.checkpoint/` and **reject** restores it |
| Deploy Guide crew (`flows/create_deploy_guide.py`) | Built. `run_deploy_guide_phase(host, detail)`: Release Builder (`tools/release_builder.py`) zips `output/site/` to `output/site.zip` and smoke-tests it; the writer makes `output/DEPLOY.md` (also inside the zip) for netlify, vercel, github_pages or s3 at quick/standard/detailed depth; Python checks it, max 2 rounds. Started by approve in the chat |
| Chat + Change Router (`flows/change_router.py`) | Built. `run_chat()`, `chat_status()`, background jobs, `awaiting_approval` (HITL #3). Sessions are kept in memory in `_sessions`. One global `_build_runner` runs change, deploy and rollback jobs one at a time |
| Chat memory (`crew.py`) | Built. One shared `Memory` in `output/memory/`, one scope per chat. Only `chat_crew` saves; the router and check jobs recall read-only. The intake form and interview answers are saved there before planning. Not undone by reject |
| Gradio UI (`app.py`) | Intake screens up to HITL #1, then runs the Design crew and shows "design ready". No design gate, build, chat, jobs or deploy screens |
| `main.py` | `run()` runs intake → HITL #1 → design → chat in the terminal. `train`/`test`/`replay` use the Planning crew alone |

Every path above is fixed under `output/`, so today all chats share one site, one spec
and one checkpoint. Step A changes that.

## The whole application, end to end

```
Project picker ──new──> Intake form ─> Interview rounds ─> Spec gate (HITL #1)
      │                                                       │ approve
      └──open──> (the screen for the project's stage)         v
                                                        Design crew (job)
                                                              v
                                                     Design gate (HITL #2)
                                                              │ approve
                                                              v
                     First build job: implementation -> polish   ┐
                                                              v   │ chat and jobs panel
                                                     Build gate (HITL #3) │ open from here on
                                                       │ approve    │ change / reject
                                                       v            v
                                              Deploy job      Change Router -> change job
                                                       v
                                            DEPLOY.md + site.zip downloads
```

The project's **stage** decides which screen shows when it is opened:
`form → interview → spec_review → designing → design_review → building → build_review
→ deploying → deployed`. After the first build the chat is always available, and a
change from the chat moves the stage back to `building`.

## Step A. One folder per project

### Layout

```
output/
  memory/                      shared Memory, one scope per chat (unchanged)
  projects/<chat_id>/
    session.json               Step B: stage, intake state, chat history, jobs, title, times
    site_spec_draft.json       Spec Writer / Copywriter output_file
    site_spec.json             approved at HITL #1
    spec_review_log.md
    design/                    styles.css, components.html, layouts, design.json, design_notes.md
    design_review_log.md
    site/                      the build
    code_review_log.md
    polish_report.json
    site.zip
    DEPLOY.md
    .checkpoint/               last approved build (site, design, site_spec.json)
```

`output/` is already in `.gitignore`.

### One object owns the paths

Add `src/alikable/projects.py`:

```python
PROJECTS = Path("output/projects")

@dataclass(frozen=True)
class Project:
    chat_id: str

    @property
    def dir(self) -> Path: return PROJECTS / self.chat_id
    site_spec, spec_draft, spec_review_log, design_dir, design_json, design_review_log,
    site_dir, code_review_log, polish_report, release_zip, guide, checkpoint, session  # all under dir

def list_projects() -> list[ProjectSummary]   # for the picker, from each session.json
```

Every module constant below becomes a `Project` property, and the code that used it takes
a `project: Project` (or `chat_id`) argument instead:

| Today | Where | Becomes |
|---|---|---|
| `OUTPUT`, `SITE_DIR`, `CHECKPOINT` | `site_files.py` | `project.dir`, `project.site_dir`, `project.checkpoint`. `site_path`, `read_site`, `apply_changes`, `save_checkpoint`, `restore_checkpoint`, `clear_checkpoint` take the project |
| `SITE_SPEC`, `DESIGN_DIR`, `REVIEW_LOG`, `CODE_REVIEW_LOG` | `flows/phases.py` | project properties. `run_design_phase`, `run_implementation_phase`, `save_design_files`, `reset_site`, `ensure_home_page`, `run_review_loop` (its log path) take the project |
| `SPEC_REVIEW_LOG`, `SITE_SPEC` | `flows/intake.py` | project properties; `IntakeState.chat_id` gives the project |
| `REPORT`, `DESIGN_DIR` | `flows/polish.py` | project properties; add `chat_id` to `PolishState` |
| `GUIDE`, `SITE_DIR` | `flows/create_deploy_guide.py` | project properties; add `chat_id` to `DeployGuideState` |
| `RELEASE_ZIP`, defaults of `package_site` / `build_release` | `tools/release_builder.py` | passed in from the project |
| `DESIGN` | `flows/change_router.py` | `project.design_json`; `PipelineState` gets `chat_id` |
| `output_file: output/...` | `config/tasks.yaml` | `output/projects/{chat_id}/site_spec_draft.json` and `output/projects/{chat_id}/design/design.json`. CrewAI 1.15.28 fills `{...}` in `output_file` from the kickoff inputs (`Task.interpolate_inputs_and_add_conversation_history`), so the planning and design kickoffs must pass `chat_id` |

### Tools need the project too

`BuildCheckerTool` and `ReleaseBuilderTool` take no input and always check
`output/site/`. Agents call them, so the folder can't come from the agent.

- Give both tools a `site_dir: Path` field (and `zip_path` for the Release Builder) and
  build them with the project's folder.
- `@agent` methods take no arguments, so add `bind_project(crew, project)` in `crew.py`.
  It runs after a crew is built and sets the folder on every project-aware tool of its
  agents. Every place that builds the Code Reviewer, QA Tester or Deploy Guide Writer
  crew calls it. Check first whether `@CrewBase` allows `Alikable(chat_id)`. If it does,
  that is simpler.
- Don't use a `ContextVar` for this. Jobs run in worker threads, and CrewAI may run
  tools in other threads, which don't inherit it.

### Jobs per project

- Replace the global `_build_runner` with one single-worker runner per `ChatSession`.
  Jobs of one project still run one at a time, and different projects can run at once.
  `_check_runner` can stay shared.
- The per-phase `__main__` test runners (`phases.py`, `polish.py`,
  `create_deploy_guide.py`) take a `chat_id` argument.

### Done when

- Two projects started one after the other each have their own spec, design, site,
  checkpoint and deploy files, and rejecting in one doesn't touch the other.
- `grep -rn '"output/\|Path("output' src/` finds only `projects.py` and `crew.py`
  (`MEMORY_DIR`).

## Step B. All UI screens

### B1. One session per project (backend, before the screens)

Today the intake keeps its flows in `intake._flows` and the chat keeps its sessions in
`change_router._sessions`. Join them into one `ProjectSession` per `chat_id`, in a new
`flows/project.py`, that owns:

- `stage` (the list under "The whole application")
- the `IntakeFlow` (until the spec is approved) and the `ChatSession` (from then on)
- the gates: `awaiting: Literal["spec", "design", "build"] | None`, which replaces
  `awaiting_approval: bool` in `ChatSession` and `ChatResponse`
- saving to and loading from `session.json`

Functions the UI calls. Each returns a `ProjectView`: the stage, the intake state, the
chat reply, jobs and awaiting gate, and the file paths to preview:

```python
new_project(form) / answer_interview(chat_id, replies) / revise_spec(chat_id, request) / approve_spec(chat_id, spec)
approve_design(chat_id, styles_css=None) / revise_design(chat_id, request)
approve_build(chat_id, host, detail) / reject_build(chat_id)
run_chat(message, chat_id) / status(chat_id) / open_project(chat_id) / list_projects()
```

What each gate does:

- **Spec approved (HITL #1)** starts a **design job**. Approval doesn't wait for it, and
  the stage becomes `designing`. When the job finishes, the stage becomes
  `design_review`.
- **Design revised** runs the design phase again with the request added to the spec,
  the same way `ChangePipelineFlow.run_design` does ("Requested change: ...").
- **Design approved (HITL #2)** starts the **first build job**: `ChangePipelineFlow` with
  `route="implementation"`, which runs implementation → polish and sets `awaiting="build"`.
  - Fill in `TODO(implementation crew)` in `ChangePipelineFlow.run_implementation` first.
    `run_implementation_phase` is already built.
  - Remove the stand-in in `PolishFlow.load_build` that copies the design layouts.
  - The first build needs no checkpoint, because there is no approved build to go back
    to. Reject before the first approval reruns the build instead.
- **Build approved (HITL #3)** calls a direct `approve(chat_id, host, detail)` in
  `change_router.py`. It reuses the body of `ChatFlow.start_deploy`, with the same
  "only when awaiting" check, so no LLM call is spent on the Chat Agent picking
  `approve`. **Reject** works the same way, with `reject(chat_id)` reusing
  `start_rollback`. Saying "approve" or "undo that" in the chat keeps working.
- Fill in `TODO(planning crew)` too. Routing a change to planning reruns
  `run_planning_phase` with the current spec plus the change as the summary, then
  reloads the spec.

Persistence (`session.json`):

- Save after every user action and every job update: stage, `IntakeState`, chat
  history, jobs, awaiting, title (the first line of the intake description), and
  created and updated times.
- On load, jobs that were `queued` or `running` become **`interrupted`**. Add that
  status to `Job`. They can't continue, so the UI offers **Retry**, which starts the
  same job again.
- The `IntakeFlow` comes back by building a new flow and passing the saved state on the
  next kickoff. Drop the state's `id` from those inputs so CrewAI doesn't treat the
  kickoff as a restore. The Flow `@persist` decorator would also work, but it keeps
  state in a separate SQLite file. `session.json` keeps everything about a project in
  its folder.

### B2. The `ui/` package

```
src/alikable/app.py          builds gr.Blocks from the modules below, launch settings, main()
src/alikable/ui/
  __init__.py                show(view) -> the visible screen and its contents for a ProjectView
  projects.py                picker: table of projects (title, stage, updated) + New project
  intake.py                  today's app.py screens: form, interview tabs, spec gate (HITL #1)
  design.py                  design gate (HITL #2)
  build.py                   jobs panel, job details, build gate banner (HITL #3), site preview
  chat.py                    chat panel
  deploy.py                  host/detail pickers, DEPLOY.md view, downloads
  preview.py                 static file serving for previews (see below)
```

Each module makes its components inside the shared `gr.Blocks` and registers its
handlers. One `show(view)` in `ui/__init__.py` decides which screen is visible from
`view.stage`, so the screens can't disagree about the stage.

| Screen | Shown at stage | Contents |
|---|---|---|
| Project picker | first screen | `gr.Dataframe` of `list_projects()`; Open, New project. The current `chat_id` is kept in `gr.BrowserState`, so a page reload reopens it |
| Intake | `form`, `interview` | As today (move from `app.py`) |
| Spec gate (HITL #1) | `spec_review` | As today: spec in `gr.Code`, Approve, describe changes |
| Design progress | `designing` | Status line from the design job's `step` |
| Design gate (HITL #2) | `design_review` | Iframe preview of `components.html` and each page layout (page dropdown), `styles.css` in a `gr.Code` editor, Approve, describe changes. A hand edit is saved to `design/styles.css` **and** to `styles_css` in `design/design.json`, because the builders read `design.json` |
| Build (first build and changes) | `building`, `build_review`, `deploying`, `deployed` | Left: chat. Right: jobs panel and job details. Banner at `awaiting="build"` with the polish summary (fixes, build check, open bugs and suggestions from `polish_report.json`) and Approve / Reject. Site preview tab |
| Deploy | at the banner, then `deployed` | Host (`gr.Dropdown`: Netlify, Vercel, GitHub Pages, S3) and detail (`gr.Radio`: quick, standard, detailed) next to Approve; afterwards `DEPLOY.md` in `gr.Markdown` and `gr.DownloadButton`s for `site.zip` and `DEPLOY.md` |

Chat and jobs panel details:

- Chat: `gr.Chatbot` (messages format), message box and Send. The Send handler calls
  `run_chat` and updates the jobs panel and banner from the same response. Send is
  disabled while a call runs (`ChatSession.turn_lock` already queues overlapping
  calls).
- Jobs: newest first, with status, title, step and id, and a color for queued,
  running, done, failed and interrupted. Selecting a job shows its result or error,
  and Retry if it was interrupted.
- `gr.Timer(2)` calls `status(chat_id)` and refreshes the jobs panel, banner and stage.
  It does nothing until a project is open.
- Finished jobs are not posted into the chat. The Chat Agent already reports them in
  its next reply (`jobs_for_chat()`).

Layout of the build screen:

```
+--------------------------------------------+-------------------------------+
| Chat                                       | Jobs                          |
|  user: make the header dark                | [running] Change from the     |
|  alikable: Sending this to the design      |   design crew (design crew)   |
|            crew...                         | [done]    First build         |
| +----------------------------------------+ +-------------------------------+
| | Build ready. Polish: 3 fixed, build    | | Job details: result / error   |
| | check passed. Host [Netlify v]         | |                               |
| | Detail (o) standard  [Approve][Reject] | | [Site preview] tab            |
| +----------------------------------------+ +-------------------------------+
| [ message box                    ] [Send]  |                               |
+--------------------------------------------+-------------------------------+
```

### Previews need the project folders served

A `gr.HTML` iframe needs a URL, and a page's relative links (`styles.css`, `js/app.js`)
must resolve next to it. Gradio's `allowed_paths` serves single files under
`/gradio_api/file=...`. Whether relative links resolve there is uncertain, so the
plan doesn't rely on it:

- `ui/preview.py` makes a FastAPI app, mounts
  `StaticFiles(directory="output/projects")` at `/preview`, and mounts the Gradio app
  on it with `gr.mount_gradio_app`. `app.main()` runs it with uvicorn.
- Iframe sources are then `/preview/<chat_id>/site/index.html` and
  `/preview/<chat_id>/design/components.html`.
- Add a cache-busting query (`?v=<updated_at>`) so a new build reloads.
- **Limit:** pages that call the user's real API from the preview may be blocked by CORS
  unless that API allows the app's origin. Mock data always works. Say so in the preview.

### Done when

- From the picker, a new project goes through every screen to the downloads, and an
  old project opens on the right screen after an app restart.
- A design hand edit shows up in the first build.

## Step C. `main.py` runs the application

- `main.run()` loads `.env` and launches the UI (`alikable.app.main`), so `crewai run`,
  `uv run alikable` and `uv run ui` all start the same app. Point the `alikable`,
  `run_crew` and `ui` scripts in `pyproject.toml` at it.
- Remove the terminal stand-ins: `run_in_terminal` and `SAMPLE_FORM` in
  `flows/intake.py`, `main()` in `flows/change_router.py`, and the terminal pipeline in
  `main.py`.
- Keep `train`, `test`, `replay` and `run_with_trigger` on the Planning crew with
  `INPUTS`. They are CrewAI developer commands, not part of the app.
- `load_dotenv()` runs once at app start.

## Order and dependencies

1. **Step A**, folders, paths, tool binding and per-project runners. Everything else
   writes files, so this goes first. Test it with the per-phase `__main__` runners.
2. **Step B1**, `ProjectSession`, gates, the two TODOs, direct approve/reject, and
   `session.json`. Test it with crews faked.
3. **Step B2**, the `ui/` package. Move the intake screens first with no behavior
   change, then add the design gate, build, chat, deploy, picker and previews.
4. **Step C**, `main.py` and `pyproject.toml`, then remove the stand-ins.

## Later (not in these steps)

1. **QA Tester in a real browser**: the QA Tester reads the code instead of using the
   site. It needs MCP Playwright to click through pages and read console errors. The
   Build Checker is static only.
2. **Parallel Page Builders**: one per page, as in the diagram.
3. **Background checks get no file access.** They only see the spec and design text.
   Give reviewers read-only access to the project folder.
4. **Several users / hosting on Hugging Face Spaces**: projects per browser, logins, and
   persistent storage, because Space storage is lost on restart.
5. **Crews build every agent and task (low priority).** Each `@crew` call builds all 15
   agents and 15 tasks to return the few it uses (about 0.4s per crew build). Removing
   `@crew` would fix it, at the cost of the automatic crew name and kickoff hooks.
6. **Streaming chat replies**: split `chat_task` into a structured decision task and a
   streamed reply task, run the reply with `Crew(stream=True)`, and make Send a
   generator that yields partial replies.
7. **Old `output/` files**: delete by hand; nothing reads them after Step A.

## Testing

- Move the scratch tests into `tests/`, with crews faked:
  - `test_intake.py`: refused form, removed secrets, max 3 rounds, memory saved once,
    empty change request, invalid JSON on approve, approve twice
  - `test_change_router.py`: routing for each route, job statuses, one change job at a
    time per project, approve only when awaiting, clarify replies
  - `test_projects.py`: two projects never share files; reject restores only its own
    project; `session.json` round trip; running jobs load as interrupted
- UI: drive each screen with `gradio_client` and fake crews (as was done for the
  intake screens), then one real run from the picker to the downloads.
