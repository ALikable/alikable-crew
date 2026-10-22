"""
The Alikable UI: places the screens of the ui/ package in one gr.Blocks and wires them
together. Each screen draws itself (ui/*.py); this file decides which one shows.

  Project picker --New project--> Intake --spec approved--> Design --design approved--> Build
        └--select a project--> the screen for its stage (ui/navigation.screen_for)

The build screen has the chat, the build gate and the deploy files on the left, and
the jobs and the site's pages, to open in a new tab, on the right.

The open project's chat_id is kept in the browser, so reloading the page reopens it.
While the design or build screen shows, a timer polls the project every 2 seconds and
redraws the live panels only when something changed; if the project moved to another
screen (by an action in another tab), it opens that screen.

Run from the project root: uv run ui (main.run loads .env first)
"""

import os

import gradio as gr

from alikable.flows import project as projects_api
from alikable.models import ProjectView
from alikable.projects import PROJECTS, Project
from alikable.ui import preview
from alikable.ui.build import BuildGate, JobsPanel
from alikable.ui.chat import CSS, ChatScreen
from alikable.ui.deploy import DeployPanel
from alikable.ui.design import DesignScreen
from alikable.ui.intake import IntakeScreen
from alikable.ui.navigation import CANT_OPEN, Screen, Screens, screen_for
from alikable.ui.projects import ProjectsScreen

REFRESH_SECONDS = 2
LIVE_SCREENS = ("design", "build")   # screens whose panels change while jobs run


def build_app() -> gr.Blocks:
    with gr.Blocks(title="Alikable") as demo:
        chat_id = gr.BrowserState("", storage_key="alikable_chat_id")
        seen = gr.State("")   # what the live panels last drew, so the timer skips unchanged updates
        with gr.Row():
            gr.Markdown("# Alikable\nHere are my endpoints, give me the UI: a plain HTML, CSS and JavaScript front end.")
            all_projects = gr.Button("← All projects", size="sm", variant="secondary", scale=0, min_width=160,
                                     visible=False)

        with gr.Column() as projects_column:
            projects = ProjectsScreen()
        with gr.Column(visible=False) as intake_column:
            intake = IntakeScreen(chat_id)
        with gr.Column(visible=False) as design_column:
            design = DesignScreen(chat_id)
        with gr.Column(visible=False) as build_column:
            with gr.Row():
                with gr.Column(scale=3):
                    chat = ChatScreen(chat_id)
                    gate = BuildGate(chat_id)
                    deploy = DeployPanel()
                with gr.Column(scale=2):
                    with gr.Tabs():
                        with gr.Tab("Jobs"):
                            jobs = JobsPanel(chat_id)
                        with gr.Tab("Site preview"):
                            site = preview.OpenInBrowser(chat_id, lambda p: p.site_dir, first="index.html", note=True)
        timer = gr.Timer(REFRESH_SECONDS, active=False)
        screens = Screens(projects=projects_column, intake=intake_column, design=design_column, build=build_column)
        live_outputs = [seen, *design.outputs, *gate.outputs, *jobs.outputs, *deploy.outputs, *site.outputs]
        everything = [chat_id, timer, all_projects, *screens.outputs, *projects.outputs, *intake.outputs,
                      *chat.outputs, *live_outputs]

        def live(view: ProjectView) -> dict:
            """The panels that change while jobs run, and what they show."""
            project = Project(view.chat_id)
            return {**design.render(view), **gate.render(view), **jobs.render(view), **deploy.render(project),
                    **site.render(project), seen: signature(view)}

        def show(screen: Screen) -> dict:
            """One screen visible; the back button and the refresh timer only where they apply."""
            return {**screens.show(screen), all_projects: gr.Button(visible=screen != "projects"),
                    timer: gr.Timer(active=screen in LIVE_SCREENS)}

        def open_project(cid: str) -> dict:
            """Shows the screen for the project's stage; the picker if there is no project."""
            view = projects_api.open_project(cid) if cid else None
            if view is None:
                if cid:
                    gr.Warning(CANT_OPEN)
                return {**show("projects"), **projects.render(), chat_id: "", seen: ""}
            screen = screen_for(view)
            if screen == "intake":
                return {**show(screen), **intake.render(view.intake, notify=False), chat_id: cid, seen: ""}
            return {**show(screen), **chat.render(view), **live(view), chat_id: cid}

        def follow(cid: str, current: Screen) -> dict:
            """After an action: opens the project's screen if the action moved it to another one."""
            view = projects_api.open_project(cid) if cid else None
            return open_project(cid) if view and screen_for(view) != current else unchanged(everything)

        def new_project() -> dict:
            return {**show("intake"), **intake.reset(), chat_id: "", seen: ""}

        def open_selected(evt: gr.SelectData) -> dict:
            return open_project(projects.selected_id(evt))

        def redraw(cid: str) -> dict:
            return live(projects_api.status(cid)) if cid else unchanged(live_outputs)

        def refresh(cid: str, last: str) -> dict:
            """Timer tick: redraws the live panels only when something changed."""
            view = projects_api.open_project(cid) if cid else None
            if view is None or signature(view) == last:
                return unchanged(everything)
            if screen_for(view) != last.split("|")[0]:
                return open_project(cid)
            return {**unchanged(everything), **live(view)}

        demo.load(open_project, chat_id, everything)
        all_projects.click(lambda: open_project(""), None, everything)
        projects.new.click(new_project, None, everything)
        projects.table.select(open_selected, None, everything)
        intake.approved.then(lambda cid: follow(cid, "intake"), chat_id, everything)
        design.approved.then(lambda cid: follow(cid, "design"), chat_id, everything)
        for acted in [chat.sent, *gate.acted, *jobs.acted]:
            acted.then(redraw, chat_id, live_outputs)
        timer.tick(refresh, [chat_id, seen], everything, show_progress="hidden")
    return demo


def signature(view: ProjectView) -> str:
    """Changes whenever the live panels would draw something different. Starts with the screen."""
    jobs = ",".join(f"{j.id}:{j.status}:{j.step}" for j in view.jobs)
    return f"{screen_for(view)}|{view.stage}|{view.awaiting}|{jobs}"


def unchanged(components: list) -> dict:
    """An update that leaves every component as it is (Gradio needs a value per output)."""
    return {component: gr.skip() for component in components}


def main():
    """
    Launch the UI. main.run loads .env before calling this.

    ALIKABLE_HOST and ALIKABLE_PORT set where it listens (127.0.0.1:7860 by default; on a
    server, keep 127.0.0.1 behind the reverse proxy). With ALIKABLE_USER and ALIKABLE_PASSWORD
    set, every page and served file asks for that login first.
    """
    user, password = os.getenv("ALIKABLE_USER"), os.getenv("ALIKABLE_PASSWORD")
    build_app().queue(default_concurrency_limit=None).launch(
        server_name=os.getenv("ALIKABLE_HOST", "127.0.0.1"),
        server_port=int(os.getenv("ALIKABLE_PORT", "7860")),
        auth=(user, password) if user and password else None,
        allowed_paths=[str(PROJECTS.resolve())],
        css=CSS,
    )


if __name__ == "__main__":
    main()
