"""
Which screen a project shows, from its stage (flows/project.py), and showing exactly one.
"""

from typing import Literal

import gradio as gr

from alikable.models import ProjectView, Stage

Screen = Literal["projects", "intake", "design", "build"]
SCREENS: dict[Stage, Screen] = {
    "form": "intake", "interview": "intake", "spec_review": "intake",
    "designing": "design", "design_review": "design",
    "building": "build", "build_review": "build", "deploying": "build", "deployed": "build",
}
CANT_OPEN = "That project stopped before its spec was approved and can't continue. Start a new project."


def screen_for(view: ProjectView | None) -> Screen:
    """The one rule for which screen a project shows: the picker when there is no project."""
    return SCREENS[view.stage] if view else "projects"


class Screens:
    """The top-level columns, of which exactly one is visible."""

    def __init__(self, **columns: gr.Column):
        self.columns = columns

    @property
    def outputs(self) -> list[gr.Column]:
        return list(self.columns.values())

    def show(self, screen: Screen) -> dict:
        return {column: gr.Column(visible=name == screen) for name, column in self.columns.items()}
