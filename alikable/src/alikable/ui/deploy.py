"""
The deploy job's files (flows/create_deploy_guide.py): DEPLOY.md to read, and downloads
for the project's site.zip and DEPLOY.md. Each shows only once its file exists.
"""

import gradio as gr

from alikable.projects import Project


class DeployPanel:
    def __init__(self):
        self.heading = gr.Markdown("### Deploy", visible=False)
        with gr.Row():
            self.site_zip = gr.DownloadButton("Download site.zip", visible=False)
            self.guide = gr.DownloadButton("Download DEPLOY.md", visible=False)
        with gr.Accordion("DEPLOY.md", open=False, visible=False) as self.guide_box:
            self.guide_text = gr.Markdown()

    @property
    def outputs(self) -> list:
        return [self.heading, self.site_zip, self.guide, self.guide_box, self.guide_text]

    def render(self, project: Project) -> dict:
        zip_ready, guide_ready = project.release_zip.exists(), project.guide.exists()
        return {self.heading: gr.Markdown(visible=zip_ready or guide_ready),
                self.site_zip: gr.DownloadButton(value=str(project.release_zip) if zip_ready else None,
                                                 visible=zip_ready),
                self.guide: gr.DownloadButton(value=str(project.guide) if guide_ready else None,
                                              visible=guide_ready),
                self.guide_box: gr.Accordion(visible=guide_ready),
                self.guide_text: project.guide.read_text(encoding="utf-8") if guide_ready else ""}
