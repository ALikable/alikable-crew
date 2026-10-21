"""
Project picker: the first screen. One row per project folder (projects.list_projects),
most recently updated first. Selecting a row opens that project (app.py).
"""

import gradio as gr

from alikable.projects import list_projects

HEADERS = ["Project", "Progress", "Updated", "Id"]
ID_COLUMN = HEADERS.index("Id")


class ProjectsScreen:
    def __init__(self):
        with gr.Row():
            gr.Markdown("## Your projects\nSelect a project to open it, or start a new one.")
            self.new = gr.Button("New project", variant="primary", scale=0)
        self.table = gr.Dataframe(headers=HEADERS, interactive=False, wrap=True)
        self.empty = gr.Markdown("_No projects yet._", visible=False)

    @property
    def outputs(self) -> list:
        return [self.table, self.empty]

    def render(self) -> dict:
        rows = [[p.title, p.progress, p.updated_at.astimezone().strftime("%Y-%m-%d %H:%M"), p.chat_id]
                for p in list_projects()]
        return {self.table: gr.Dataframe(value={"data": rows, "headers": HEADERS}, visible=bool(rows)),
                self.empty: gr.Markdown(visible=not rows)}

    @staticmethod
    def selected_id(evt: gr.SelectData) -> str:
        """The chat_id of the row the user selected."""
        return str(evt.row_value[ID_COLUMN])
