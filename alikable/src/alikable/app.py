"""
The Alikable UI: places the screens of the ui/ package in one gr.Blocks and wires them
together. Each screen draws itself (ui/*.py); this file decides which one shows.

  Project picker --New project--> Intake (form, interview, spec gate, design)
        │                                   │ design written
        └--select a project--> Chat ------- ┘  (chat, jobs, approval notice, downloads)

Which screen a project opens on comes from one rule, ui/navigation.screen_for. The open
project's chat_id is kept in the browser, so reloading the page reopens it. While the
chat shows, a timer refreshes the jobs panel and downloads every 2 seconds, and only
redraws them when something changed.

Run from the project root: uv run ui (main.run loads .env first)
"""

import gradio as gr

from alikable.flows import change_router, intake as intake_flow
from alikable.projects import PROJECTS, Project
from alikable.ui.build import BuildPanel
from alikable.ui.chat import CSS, ChatScreen
from alikable.ui.deploy import DeployPanel
from alikable.ui.intake import IntakeScreen
from alikable.ui.navigation import Screen, Screens, screen_for
from alikable.ui.projects import ProjectsScreen

REFRESH_SECONDS = 2


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Alikable") as demo:
        chat_id = gr.BrowserState("", storage_key="alikable_chat_id")
        seen = gr.State("")   # what the panels last drew, so the timer skips unchanged updates
        with gr.Row(equal_height=True):
            gr.Markdown("# Alikable\nHere are my endpoints, give me the UI: a plain HTML, CSS and JavaScript front end.")
            all_projects = gr.Button("← All projects", size="sm", variant="secondary", scale=0, min_width=0,
                                     visible=False)

        with gr.Column() as projects_column:
            projects = ProjectsScreen()
        with gr.Column(visible=False) as intake_column:
            intake = IntakeScreen(chat_id)
        with gr.Column(visible=False) as chat_column:
            with gr.Row():
                with gr.Column(scale=3):
                    chat = ChatScreen(chat_id)
                with gr.Column(scale=2):
                    build = BuildPanel(chat_id)
                    deploy = DeployPanel()
        timer = gr.Timer(REFRESH_SECONDS, active=False)
        screens = Screens(projects=projects_column, intake=intake_column, chat=chat_column)
        everything = [chat_id, seen, timer, all_projects, *screens.outputs, *projects.outputs, *intake.outputs,
                      *chat.outputs, *build.outputs, *deploy.outputs]
        panel_outputs = [seen, *build.outputs, *deploy.outputs]

        def panels(cid: str) -> dict:
            """The jobs panel and downloads, and what they show."""
            project, response = Project(cid), change_router.chat_status(cid)
            return {**build.render(project, response), **deploy.render(project),
                    seen: build.signature(response) + "|" + deploy.signature(project)}

        def show(screen: Screen) -> dict:
            """One screen visible; the back button and the refresh timer only where they apply."""
            return {**screens.show(screen), all_projects: gr.Button(visible=screen != "projects"),
                    timer: gr.Timer(active=screen == "chat")}

        def open_project(cid: str) -> dict:
            """Shows the screen the project is at; the picker if there is none."""
            destination = screen_for(cid)
            if destination.notice:
                gr.Warning(destination.notice)
            view = show(destination.screen)
            if destination.screen == "projects":
                return {**view, **projects.render(), chat_id: ""}
            if destination.screen == "intake":
                return {**view, **intake.render(intake_flow.current_state(cid), notify=False), chat_id: cid}
            return {**view, **chat.render(Project(cid)), **panels(cid), chat_id: cid}

        def open_designed(cid: str) -> dict:
            """After the spec gate: opens the chat once the design is written, otherwise stays put."""
            return open_project(cid) if cid and Project(cid).design_json.exists() else unchanged(everything)

        def new_project() -> dict:
            return {**show("intake"), **intake.reset(), chat_id: ""}

        def open_selected(evt: gr.SelectData) -> dict:
            return open_project(projects.selected_id(evt))

        def refresh(cid: str, last: str) -> dict:
            """Timer tick: redraws the panels only when something changed."""
            if not cid:
                return unchanged(panel_outputs)
            update = panels(cid)
            return unchanged(panel_outputs) if update[seen] == last else update

        demo.load(open_project, chat_id, everything)
        all_projects.click(lambda: open_project(""), None, everything)
        projects.new.click(new_project, None, everything)
        projects.table.select(open_selected, None, everything)
        intake.approved.then(open_designed, chat_id, everything)
        chat.sent.then(panels, chat_id, panel_outputs)
        timer.tick(refresh, [chat_id, seen], panel_outputs, show_progress="hidden")
    return demo


def unchanged(components: list) -> dict:
    """An update that leaves every component as it is (Gradio needs a value per output)."""
    return {component: gr.skip() for component in components}


def main():
    """Launch the UI. main.run loads .env before calling this."""
    build_app().queue(default_concurrency_limit=None).launch(allowed_paths=[str(PROJECTS.resolve())], css=CSS)


if __name__ == "__main__":
    main()
