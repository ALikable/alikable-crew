"""
The screens of the Alikable UI, one module each (Step B2 in Documents/PLAN.md).

  navigation.py  which screen a project's stage shows, and showing exactly one screen
  projects.py    project picker: every project folder, plus New project
  intake.py      intake form, interview rounds and the spec gate (HITL #1)
  design.py      design progress and the design gate (HITL #2)
  chat.py        the project's chat with the Chat Agent
  build.py       the build gate (HITL #3) and the jobs panel, with job details and Retry
  deploy.py      DEPLOY.md and the downloads for site.zip and DEPLOY.md
  preview.py     a page picker and a link that opens a design or build page in a new tab

Each screen makes its components inside the shared gr.Blocks and has a render method
that returns the updates for one project. Every action goes through flows/project.py
and gets a ProjectView back. app.py places the screens and wires them together; no
screen knows about another.
"""

import gradio as gr

from alikable.models import ProjectView


def warn(view: ProjectView) -> ProjectView:
    """Shows why the action was refused, if it was."""
    for problem in view.problems:
        gr.Warning(problem)
    return view
