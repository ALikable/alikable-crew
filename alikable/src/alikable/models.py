"""
Shapes (Pydantic models) for structured task outputs.
"""

from pydantic import BaseModel, Field


class IntakeForm(BaseModel):
    """The intake form answers. The input guardrail checks them before any agent runs."""

    description: str
    audience: str = ""
    look_and_feel: str = ""
    qualities: list[str] = []
    api_base_url: str = ""  # empty when there is no backend yet
    endpoints: list[str] = []  # "METHOD /path", one per item


class Question(BaseModel):
    """One follow-up question from the Discovery Interviewer."""

    question: str = Field(description="A short, specific question")
    options: list[str] = Field(
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