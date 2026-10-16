"""
Shapes (Pydantic models) for structured task outputs.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Designing and Developing
class PageLayout(BaseModel):
    """One page of the site, as an HTML skeleton."""

    file: str = Field(description="The page's file name from the site spec, e.g. index.html")
    html: str = Field(
        description=(
            "Complete HTML skeleton of this page: <!DOCTYPE html>, head with "
            '<link rel="stylesheet" href="styles.css">, and the full layout built from '
            "the component classes. Use realistic placeholder content, no JavaScript."
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

# Chat and change routing
class ChatReply(BaseModel):
    """What the Chat Agent decides to do with one user message."""

    action: Literal["reply", "change", "check", "approve"] = Field(
        description=(
            "reply: answer a question or chat about the project. "
            "change: the user wants the site changed. "
            "check: run reviewers in the background to investigate something without changing files. "
            "approve: the build is waiting for approval and the user approves it."
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
