"""
Downloads for the deploy job's files: the project's site.zip and DEPLOY.md
(flows/create_deploy_guide.py). Each button shows only once its file exists.
"""

import gradio as gr

from alikable.projects import Project


class DeployPanel:
    def __init__(self):
        self.heading = gr.Markdown("### Deploy", visible=False)
        with gr.Row():
            self.site_zip = gr.DownloadButton("Download site.zip", visible=False)
            self.guide = gr.DownloadButton("Download DEPLOY.md", visible=False)

    @property
    def outputs(self) -> list:
        return [self.heading, self.site_zip, self.guide]

    def render(self, project: Project) -> dict:
        zip_ready, guide_ready = project.release_zip.exists(), project.guide.exists()
        return {self.heading: gr.Markdown(visible=zip_ready or guide_ready),
                self.site_zip: gr.DownloadButton(value=str(project.release_zip) if zip_ready else None,
                                                 visible=zip_ready),
                self.guide: gr.DownloadButton(value=str(project.guide) if guide_ready else None,
                                              visible=guide_ready)}

    @staticmethod
    def signature(project: Project) -> str:
        """Changes whenever a new package or guide is written."""
        return "|".join(str(p.stat().st_mtime) if p.exists() else "-" for p in (project.release_zip, project.guide))
