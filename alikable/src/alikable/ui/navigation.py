"""
Which screen a project opens on, from what it has written and what is still in memory.

There is no session.json yet (Step B1 in Documents/PLAN.md), so an intake that did not
reach the approved spec is lost when the app restarts: its flow lived only in memory.
"""

from typing import Literal, NamedTuple

import gradio as gr

from alikable.flows import intake
from alikable.projects import CHAT_ID, Project

Screen = Literal["projects", "intake", "chat"]


class Destination(NamedTuple):
    screen: Screen
    notice: str = ""   # why the project could not be opened, if it could not


def screen_for(chat_id: str | None) -> Destination:
    """The one rule for where a project opens."""
    if not chat_id or not CHAT_ID.fullmatch(chat_id):
        return Destination("projects")
    project = Project(chat_id)
    if project.design_json.exists():
        return Destination("chat")
    if intake.current_state(chat_id) is not None:   # interview, spec gate or designing, this run
        return Destination("intake")
    if project.site_spec.exists():                  # spec approved, design never finished
        return Destination("chat")
    if project.dir.exists():
        return Destination("projects", f"“{project.title}” stopped before its spec was approved, and the app has "
                                       "restarted since, so its intake can't continue. Start a new project.")
    return Destination("projects")


class Screens:
    """The top-level columns, of which exactly one is visible."""

    def __init__(self, **columns: gr.Column):
        self.columns = columns

    @property
    def outputs(self) -> list[gr.Column]:
        return list(self.columns.values())

    def show(self, screen: Screen) -> dict:
        return {column: gr.Column(visible=name == screen) for name, column in self.columns.items()}
