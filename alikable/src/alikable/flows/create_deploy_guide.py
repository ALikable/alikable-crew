"""
Deploy Guide phase (the Deploy Guide crew in Documents/Agent_Diagram.png).

Runs after the user approves the build (HITL #3):
  1. collect the approved spec, js/config.js and the polish report
  2. the Release Builder packages the project's site/ as its site.zip and smoke-tests it
  3. the Deploy Guide Writer writes DEPLOY.md for the host and detail the user picked
  4. Python checks the guide: the required headings, no secrets, and only files that
     are in the package. A guide that fails goes back to the writer, max 2 rounds.
  5. DEPLOY.md is saved in the project folder and added to site.zip next to index.html

The site was approved, so this phase never edits it. Build or smoke-test failures
go into the guide's Known problems section, and the user fixes them with a change
in the chat. Nothing is deployed: the user deploys site.zip by following DEPLOY.md.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal, get_args

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import PrivateAttr

from alikable.crew import Alikable
from alikable.models import HOST_NAMES, DeployGuideResult, DeployGuideState, GuideDetail, PolishReport
from alikable.projects import Project
from alikable.tools.build_checker import SECRET_PATTERNS
from alikable.tools.release_builder import add_to_release, build_release

DEPLOY_NOTES = Path("knowledge/deploy_guides.txt")

DETAIL_RULES: dict[str, str] = {
    "quick": "Short enough to read in two minutes: one or two lines per section, at most 8 numbered "
             "deploy steps, no explanations of why, and at most 3 troubleshooting bullets.",
    "standard": "Numbered steps, each followed by one short sentence on what the user should see when "
                "it worked, and the troubleshooting from the deploy notes that applies to this site.",
    "detailed": "For someone deploying for the first time: explain why each step matters and what they "
                "should see after it, how to add a custom domain, how to open the browser console, and "
                "every troubleshooting item from the deploy notes.",
}
# Files the guide may name besides the ones in the package
GUIDE_FILES = {"DEPLOY.md", "site.zip"}
FILE_REF = re.compile(r"`\.?/?([\w-][\w./-]*\.(?:html|css|js|mjs|json|md|zip|png|jpe?g|svg|gif|webp|ico|txt))`")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def deploy_notes(host: str, uses_api: bool) -> str:
    """The sections of knowledge/deploy_guides.txt that apply to this host and site."""
    sections = re.split(r"^\[Deploy guides \| (.+?)\]\s*$", _read(DEPLOY_NOTES), flags=re.M)
    wanted = ("Before deploying", HOST_NAMES[host], "Troubleshooting", "What DEPLOY.md must contain") \
        + (("Connecting the deployed site",) if uses_api else ())
    return "\n\n".join(f"[{title}]\n{body.strip()}" for title, body in zip(sections[1::2], sections[2::2])
                       if title.startswith(wanted))


def required_headings(host: str, uses_api: bool, release_ok: bool) -> list[str]:
    return ["What you are deploying",
            *([] if release_ok else ["Known problems"]),
            "Before you deploy",
            f"Deploy to {HOST_NAMES[host]}",
            *(["Connect your API"] if uses_api else []),
            "Update the site later",
            "Troubleshooting"]


def strip_fence(text: str) -> str:
    """Remove a ``` fence around the whole document."""
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.removesuffix("```").rstrip()
    return text


def validate_guide(guide: str, headings: list[str], package_files: list[str]) -> list[str]:
    """What is wrong with the guide; empty when it passes."""
    problems = []
    found = {line.lstrip("#").strip().lower() for line in guide.splitlines() if line.startswith("## ")}
    problems += [f'Missing the heading "## {h}".' for h in headings if h.lower() not in found]

    if any(p.search(guide) for p in SECRET_PATTERNS):
        problems.append("Contains what looks like an API key, token or secret. Remove it.")

    allowed = set(package_files) | GUIDE_FILES
    names = {Path(f).name for f in allowed}
    unknown = sorted({ref for ref in FILE_REF.findall(guide)
                      if ref not in allowed and ref not in names and not any(ref.endswith("/" + f) for f in allowed)})
    if unknown:
        problems.append("Names files that are not in the package: " + ", ".join(unknown)
                        + ". Use only the files listed in the release report.")
    return problems


class DeployGuideFlow(Flow[DeployGuideState]):
    """Package, smoke-test, write the guide, check it, save both."""

    _on_step: Callable[[str], None] | None = PrivateAttr(default=None)   # set by the deploy job

    @property
    def project(self) -> Project:
        return Project(self.state.chat_id)

    def _step(self, step: str) -> None:
        print(f"\n===== DEPLOY: {step} =====\n")
        if self._on_step:
            self._on_step(step)

    @start()
    def collect_inputs(self):
        self._step("collecting the spec, config and polish report")
        project = self.project
        self.state.site_spec = _read(project.site_spec) or "None"
        self.state.config_js = _read(project.site_dir / "js" / "config.js")
        self.state.uses_api = bool(re.search(r"""API_BASE_URL\s*=\s*['"][^'"]+['"]""", self.state.config_js)) \
            or '"endpoints"' in self.state.site_spec
        if project.polish_report.exists():
            self.state.polish_summary = PolishReport.model_validate_json(_read(project.polish_report)).summary()

    @listen(collect_inputs)
    def package(self):
        self._step("release builder: packaging and smoke test")
        self.state.release = build_release(self.project.site_dir, self.project.release_zip)

    @listen(or_(package, "rewrite"))
    def write_guide(self):
        self.state.round += 1
        self._step(f"deploy guide writer: round {self.state.round} of {self.state.max_rounds}")
        release = self.state.release
        headings = required_headings(self.state.host, self.state.uses_api, release.ok)
        feedback = "None"
        if self.state.problems:
            feedback = "\n".join(f"{i}. {p}" for i, p in enumerate(self.state.problems, 1)) \
                + f"\n\nYour previous guide:\n{self.state.guide}"

        result = Alikable(self.project).deploy_crew().kickoff(inputs={
            "host_name": HOST_NAMES[self.state.host],
            "headings": "; ".join(headings),
            "detail": self.state.detail,
            "detail_rule": DETAIL_RULES[self.state.detail],
            "deploy_notes": deploy_notes(self.state.host, self.state.uses_api),
            "release_report": release.as_text(),
            "config_js": self.state.config_js or "None (the site has no js/config.js)",
            "polish_summary": self.state.polish_summary or "None",
            "site_spec": self.state.site_spec,
            "feedback": feedback,
        })
        self.state.guide = strip_fence(result.raw)
        self.state.problems = validate_guide(self.state.guide, headings, release.files)

    @router(write_guide)
    def review(self) -> Literal["rewrite", "done"]:
        if self.state.problems and self.state.round < self.state.max_rounds:
            return "rewrite"
        return "done"

    @listen("done")
    def save(self) -> DeployGuideResult:
        self._step("saving DEPLOY.md and site.zip")
        guide = self.project.guide
        guide.parent.mkdir(parents=True, exist_ok=True)
        guide.write_text(self.state.guide + "\n", encoding="utf-8")
        add_to_release(guide.name, self.state.guide + "\n", self.project.release_zip)
        return self.result()

    def result(self) -> DeployGuideResult:
        return DeployGuideResult(
            zip_path=self.project.release_zip.as_posix(), guide_path=self.project.guide.as_posix(), guide=self.state.guide,
            host=self.state.host, detail=self.state.detail,
            release_ok=self.state.release.ok, guide_problems=self.state.problems,
        )


def run_deploy_guide_phase(project: Project, host: str = "netlify", detail: str = "standard",
                           on_step: Callable[[str], None] | None = None) -> DeployGuideResult:
    """Package the project's site/ as its site.zip and write its DEPLOY.md (also inside the zip).

    host: netlify, vercel, github_pages or s3. detail: quick, standard or detailed.
    Raises FileNotFoundError if the project's site/ has no pages.
    """
    if host not in HOST_NAMES:
        raise ValueError(f"Unknown host {host!r}; use one of {', '.join(HOST_NAMES)}")
    if detail not in get_args(GuideDetail):
        raise ValueError(f"Unknown detail {detail!r}; use one of {', '.join(get_args(GuideDetail))}")
    flow = DeployGuideFlow()
    flow._on_step = on_step
    flow.kickoff(inputs={"chat_id": project.chat_id, "host": host, "detail": detail})
    return flow.result()


if __name__ == "__main__":
    # Test run on a project's site/:
    #   uv run python -m alikable.flows.create_deploy_guide <chat_id> [host] [detail]
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    result = run_deploy_guide_phase(Project(sys.argv[1]), *sys.argv[2:4])
    print(f"\n{result.summary()}")
