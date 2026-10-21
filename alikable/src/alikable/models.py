"""
Shapes (Pydantic models) for structured task outputs, flow state and the UI,
grouped by crew to match Documents/Agent_Diagram.png.
"""

from __future__ import annotations   # lets a model use one defined further down

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ Intake form

class IntakeForm(BaseModel):
    """The intake form answers. The input guardrail checks them before any agent runs."""

    description: str
    audience: str = ""
    look_and_feel: str = ""
    qualities: list[str] = []
    api_base_url: str = ""  # empty when there is no backend yet
    endpoints: list[str] = []  # "METHOD /path", one per item


class Option(BaseModel):
    """One answer the user can pick."""

    label: str = Field(description="The answer in 1 to 5 words; add (Recommended) to the one you recommend")
    description: str = Field(description="One line on what picking it means or its trade-off")

# ---------------------------------------------------------------- Planning crew
# The Discovery Interviewer's rounds. The Spec Writer writes site_spec.json as raw JSON.

class Question(BaseModel):
    """One follow-up question from the Discovery Interviewer."""

    header: str = Field(description="A 1 to 3 word label for the question, e.g. Premium price")
    question: str = Field(description="A short, specific question")
    options: list[Option] = Field(
        description="2 to 4 likely answers, the recommended one first; the user can also type their own"
    )


class Interview(BaseModel):
    """One round of the Discovery Interviewer."""

    questions: list[Question] = Field(
        description="This round's questions, at most 4; empty when nothing important is unclear"
    )
    summary: str = Field(
        description="The requirements so far under the headings purpose, audience, pages, look and feel, qualities, API details, open questions"
    )


# ------------------------------------------------------------------ Design crew

class PageLayout(BaseModel):
    """One page of the site, as an HTML skeleton."""

    file: str = Field(description="The page's file name from the site spec, e.g. index.html")
    html: str = Field(
        description=(
            "Complete HTML skeleton of this page: <!DOCTYPE html>, head with "
            '<link rel="stylesheet" href="styles.css">, and the full layout built from '
            "the component classes. Use realistic placeholder content, no JavaScript. "
            "Use only classes from styles_css and never style attributes; hide "
            "elements with the hidden attribute."
        )
    )
        

class DesignSystem(BaseModel):
    """Everything the Design System Designer produces."""

    template_used: str = Field(description="Which preexisting template was the starting point, and why")
    styles_css: str = Field(
        description="The complete stylesheet: design tokens in :root, then every component's styles, with a comment explaining each decision"
    )
    components_html: str = Field(
        description="An HTML snippet for every component (button variants, inputs, cards, alerts, ...), each with a short comment saying what it is for"
    )
    layouts: list[PageLayout] = Field(description="One layout for every page in the site spec")
    notes: str = Field(description="Design decisions, accessibility notes and anything the Page Builder must know, in Markdown")


# ---------------------------------------------------------- Implementation crew

# Not built yet. Its build goes to output/site/ as FileChange objects (see Site files).


# -------------------------------------------------------- Polish & Iterate crew

POLISH_ROUNDS = 1    # rounds of fixes in the polish phase of a change job

Severity = Literal["high", "medium", "low"]


class BugReport(BaseModel):
    """One bug the QA Tester found."""

    page: str = Field(description="The file the bug is on, as named in the site files, e.g. index.html")
    steps: list[str] = Field(description="Steps to reproduce the bug")
    actual: str = Field(description="What happens")
    expected: str = Field(description="What should happen")
    severity: Severity = Field(description="high: broken or a build error. medium: works badly. low: cosmetic")


class QAReport(BaseModel):
    bugs: list[BugReport] = Field(default_factory=list, description="Every bug found; empty if there are none")


class Suggestion(BaseModel):
    """One inconsistency the Consistency Auditor found."""

    page: str = Field(description="The file the problem is on, as named in the site files, e.g. styles.css")
    rule: str = Field(description="The rule from the site spec or the design that it breaks")
    current: str = Field(description="What the site does now")
    proposed: str = Field(description="The exact change that would fix it")
    severity: Severity = Field(description="high: contradicts the spec. medium: visible drift. low: minor")


class AuditReport(BaseModel):
    suggestions: list[Suggestion] = Field(
        default_factory=list, description="Every inconsistency found; empty if there are none"
    )


class FixResult(BaseModel):
    """What the Fixer returns for one bug or suggestion."""

    status: Literal["fixed", "skipped"] = Field(
        description="fixed: files changed. skipped: already fixed, not a real problem, or not fixable in HTML, CSS and JavaScript"
    )
    files: list[FileChange] = Field(default_factory=list, description="For fixed: every file you changed")
    note: str = Field(description="One line: what you changed, or why you skipped it")


class FixRecord(BaseModel):
    """What happened to one bug or suggestion, after the build check."""

    issue: str
    status: Literal["fixed", "skipped", "reverted", "failed"]   # reverted: the fix broke the build and was undone
    files: list[str] = []
    note: str = ""


class PolishReport(BaseModel):
    """The result of the polish phase, shown at HITL #3."""

    rounds: int = 0                         # rounds of fixes that ran
    fixes: list[FixRecord] = []
    build_ok: bool = False
    build_errors: list[str] = []
    open_bugs: list[BugReport] = []         # still found by the last check
    open_suggestions: list[Suggestion] = []

    def summary(self) -> str:
        counts = {s: sum(f.status == s for f in self.fixes) for s in ("fixed", "skipped", "reverted", "failed")}
        done = ", ".join(f"{n} {s}" for s, n in counts.items() if n) or "nothing to fix"
        build = "Build check passed." if self.build_ok else f"Build check failed with {len(self.build_errors)} error(s)."
        still_open = len(self.open_bugs) + len(self.open_suggestions)
        return (f"Polish: {self.rounds} round(s), {done}. {build}"
                + (f" {still_open} issue(s) still open." if still_open else " No open issues."))


class PolishState(BaseModel):
    site_spec: str = ""
    design: str = ""
    change_request: str = ""     # a small user change routed straight to polish; fixed first, once
    max_rounds: int = 1          # rounds of fixes; a report-only check always follows the last one
    max_fixes_per_round: int = 0  # 0: no limit; otherwise the lowest-severity items wait for the next round
    round: int = 0
    bugs: list[BugReport] = []
    suggestions: list[Suggestion] = []
    report: PolishReport = PolishReport()


# ------------------------------------------------------------ Deploy Guide crew

# The Release Builder packages output/site/ and smoke-tests the package; the Deploy
# Guide Writer writes DEPLOY.md as Markdown (flows/create_deploy_guide.py).

DeployHost = Literal["netlify", "vercel", "github_pages", "s3"]
GuideDetail = Literal["quick", "standard", "detailed"]   # how long and how explained DEPLOY.md is

HOST_NAMES: dict[str, str] = {
    "netlify": "Netlify", "vercel": "Vercel", "github_pages": "GitHub Pages", "s3": "AWS S3 static website hosting",
}


class SmokeCheck(BaseModel):
    """One request the Release Builder made to the unzipped package."""

    path: str                  # as requested, e.g. index.html or js/api.js
    status: int | None = None  # HTTP status; None when the request did not get an answer
    ok: bool
    note: str = ""             # e.g. "linked from index.html"


class ReleaseReport(BaseModel):
    """The packaged site and how its smoke test went."""

    zip_path: str = ""
    files: list[str] = []      # paths inside the zip
    size_bytes: int = 0
    build: BuildCheck
    smoke: list[SmokeCheck] = []

    @property
    def failures(self) -> list[SmokeCheck]:
        return [c for c in self.smoke if not c.ok]

    @property
    def ok(self) -> bool:
        return self.build.ok and not self.failures

    def as_text(self) -> str:
        lines = [f"Package: {self.zip_path} ({len(self.files)} files, {self.size_bytes / 1024:.1f} KB)",
                 "Files: " + ", ".join(self.files),
                 "Build check: " + self.build.as_text(),
                 f"Smoke test: {len(self.smoke) - len(self.failures)} of {len(self.smoke)} requests OK, "
                 "served from a subfolder as GitHub Pages does"]
        lines += [f"FAILED {c.path}: " + (f"HTTP {c.status}" if c.status else "no answer")
                  + (f" ({c.note})" if c.note else "") for c in self.failures]
        return "\n".join(lines)


class DeployGuideState(BaseModel):
    host: DeployHost = "netlify"
    detail: GuideDetail = "standard"
    max_rounds: int = 2          # times the Deploy Guide Writer may write the guide
    round: int = 0
    site_spec: str = ""
    config_js: str = ""          # js/config.js, where the API base URL is set
    uses_api: bool = False
    polish_summary: str = ""
    release: ReleaseReport | None = None
    guide: str = ""
    problems: list[str] = []     # what the last guide failed in validation; empty when it passed


class DeployGuideResult(BaseModel):
    """What the deploy job returns and the UI offers for download."""

    zip_path: str
    guide_path: str
    guide: str
    host: DeployHost
    detail: GuideDetail
    release_ok: bool
    guide_problems: list[str] = []   # still there after the last round

    def summary(self) -> str:
        release = "Package passed the build check and smoke test." if self.release_ok \
            else "Package has problems; see Known problems in the guide."
        guide = "Guide passed validation." if not self.guide_problems \
            else f"Guide still has {len(self.guide_problems)} problem(s): " + "; ".join(self.guide_problems)
        return (f"Wrote {self.guide_path} ({self.detail} guide for {HOST_NAMES[self.host]}) "
                f"and {self.zip_path}. {release} {guide}")


# ----------------------------------------------------------- Change Router crew
# The Chat Agent and the Change Router, the state of the chat and change flows,
# and what the UI gets back (flows/change_router.py).

class ChatReply(BaseModel):
    """What the Chat Agent decides to do with one user message."""

    action: Literal["reply", "change", "check", "approve", "reject"] = Field(
        description=(
            "reply: answer a question or chat about the project. "
            "change: the user wants the site changed. "
            "check: run reviewers in the background to investigate something without changing files. "
            "approve: the build is waiting for approval and the user approves it. "
            "reject: the build is waiting for approval and the user wants it undone, back to the last approved build."
        )
    )
    message: str = Field(description="The reply to show the user, in Markdown")
    change_request: str = Field(
        default="", description="For change: the change restated clearly and completely for the Change Router"
    )
    check_agents: list[
        Literal["qa_tester", "consistency_auditor", "code_reviewer", "spec_critic", "design_critic"]
    ] = Field(default_factory=list, description="For check: the reviewers to run in the background")
    check_question: str = Field(default="", description="For check: what the reviewers should find out")
    deploy_host: DeployHost = Field(
        default="netlify", description="For approve: the static host the user wants to deploy on; netlify if they did not say"
    )
    deploy_detail: GuideDetail = Field(
        default="standard", description="For approve: how detailed the user wants the deploy guide; standard if they did not say"
    )


class RouteDecision(BaseModel):
    """Which crew the Change Router sends a change to."""

    crew: Literal["planning", "design", "implementation", "polish", "clarify"] = Field(
        description=(
            "planning: new pages or features. design: style or layout changes. "
            "implementation: behavior or code changes that keep the spec and design. "
            "polish: small fixes. clarify: the request is too vague to route."
        )
    )
    request: str = Field(description="The request restated clearly for that crew, or the clarifying question")


class ChatState(BaseModel):
    message: str = ""                # the user's latest message
    reply: str = ""                  # what to show the user for this message
    history: list[str] = []
    action: str = ""                 # the Chat Agent's choice: reply, change, check or approve
    change_request: str = ""         # the change, restated for the Change Router, then for its crew
    route: str = ""                  # crew the change starts at
    check_agents: list[str] = []     # reviewers to run in the background
    check_question: str = ""
    deploy_host: str = "netlify"     # for approve: where the user deploys, and how detailed a guide
    deploy_detail: str = "standard"


class PipelineState(BaseModel):
    route: str = ""             # crew the change starts at
    change_request: str = ""
    site_spec: str = ""
    design: str = ""
    polish_rounds: int = POLISH_ROUNDS
    notes: list[str] = []       # one line per crew, becomes the job result


class Job(BaseModel):
    """One background job, as the UI shows it."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    kind: Literal["check", "change", "deploy", "rollback"]
    title: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    step: str = ""      # what is running right now, e.g. "design crew"
    result: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatResponse(BaseModel):
    """Everything the UI needs after a message or a status refresh."""

    chat_id: str        # made at the intake form; also the chat's memory scope
    reply: str = ""
    awaiting_approval: bool = False
    jobs: list[Job] = []


# ------------------------------------------------------------------- Site files

class FileChange(BaseModel):
    path: str = Field(description="The file's path in the site files, e.g. index.html or js/app.js")
    content: str = Field(description="The complete new contents of the file, not a diff")


# ------------------------------------------------------------------------ Tools

class SiteBuild(BaseModel):
    """What an Implementation crew agent built: files for output/site/."""

    files: list[FileChange] = Field(
        description="Every file you wrote: its path in the site (e.g. index.html or js/api.js) "
                    "and its complete contents"
    )
    notes: str = Field(description="One short paragraph: what you built and what the next agent must know")



class BuildCheck(BaseModel):
    ok: bool
    errors: list[str] = []      # "path: problem"; any error means the site is broken
    warnings: list[str] = []

    def as_text(self) -> str:
        if self.ok and not self.warnings:
            return "PASS: no build errors."
        lines = ["PASS" if self.ok else f"FAIL: {len(self.errors)} build error(s)"]
        lines += [f"ERROR {e}" for e in self.errors] + [f"WARNING {w}" for w in self.warnings]
        return "\n".join(lines)


FixResult.model_rebuild()   # its FileChange is defined in Site files, below it
ReleaseReport.model_rebuild()   # its BuildCheck is defined in Tools, below it
DeployGuideState.model_rebuild()
