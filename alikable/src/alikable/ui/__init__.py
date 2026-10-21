"""
The screens of the Alikable UI, one module each (Step B2 in Documents/PLAN.md).

  navigation.py  which screen a project opens on, and showing exactly one screen
  projects.py    project picker: every project folder, plus New project
  intake.py      intake form, interview rounds and the spec gate (HITL #1), then the design
  chat.py        the project's chat with the Chat Agent
  build.py       jobs panel, job details and the build approval notice (HITL #3)
  deploy.py      downloads for site.zip and DEPLOY.md

Each screen makes its components inside the shared gr.Blocks and has a render method
that returns the updates for one project. app.py places the screens and wires them
together; no screen knows about another.
"""
