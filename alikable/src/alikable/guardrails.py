"""
Input guardrail: checks the user's input before any agent sees it.

Alikable builds plain HTML, CSS and JavaScript front ends for the user's
existing backend, so other stacks and backend work are rejected, endpoints must
be a method and a path, and secrets are removed so they never reach an LLM.
"""

import re

from alikable.models import IntakeForm

MAX_CHARS = 5000
SECRET_WARNING = "A secret (token, key or password) was removed. The agents never need secrets, so please don't paste them."

OFF_SCOPE = re.compile(
    r"\b(react(?!\s+to\b)|vue|angular|svelte|next\.js|nuxt|typescript|php|django|flask|rails|node\.js)\b", re.I
)
BACKEND_WORK = re.compile(
    r"\b(?:build|create|write|develop|set up)\s+(?:a\s+|an\s+|the\s+|my\s+)?(?:new\s+)?(?:backend|back-end|server|database)\b", re.I
)
ENDPOINT = re.compile(r"^(GET|POST|PUT|PATCH|DELETE)\s+/\S*$", re.I)
URL = re.compile(r"^https?://\S+$")

# Each pattern keeps group 1 (e.g. "Bearer ") and replaces the secret after it.
SECRETS = [
    re.compile(r"(bearer\s+)[\w.~+/=-]{8,}", re.I),
    re.compile(
        r"(\b(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)\s*[:=]\s*)"
        r"(?!(?:string|number|boolean|integer)\b|[{<\[])[^\s&\"',}]+",
        re.I,
    ),
    re.compile(r"(://[^\s:/@\"]+:)[^\s@/\"]+(?=@)"),  # user:password@host
    re.compile(
        r"()\b(?:eyJ[\w-]+\.[\w-]+\.[\w-]+|sk-[\w-]{16,}|gh[pousr]_\w{20,}|github_pat_\w{20,}|AKIA[0-9A-Z]{16}|AIza[\w-]{35}|xox[abprs]-[\w-]{10,})"
    ),
]


def redact_secrets(text: str) -> str:
    """Replaces tokens, keys and passwords in the text with [REDACTED]."""
    for pattern in SECRETS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def check_intake(form: IntakeForm) -> tuple[IntakeForm, list[str]]:
    """Returns the form with secrets removed and the warnings to show.
    Raises ValueError with one problem per line when the form can't go to the agents."""
    text = " ".join([form.description, form.audience, form.look_and_feel])
    errors = []
    if not form.description.strip():
        errors.append("Describe what the app should do.")
    if len(text + form.api_base_url + "".join(form.endpoints)) > MAX_CHARS:
        errors.append(f"Keep your answers under {MAX_CHARS} characters in total.")
    if stacks := sorted({s.lower() for s in OFF_SCOPE.findall(text)}):
        errors.append(f"Alikable builds plain HTML, CSS and JavaScript only. Please remove: {', '.join(stacks)}.")
    if BACKEND_WORK.search(text):
        errors.append("Alikable builds only the front end for your existing backend. Please remove the backend work.")
    if form.api_base_url and not URL.match(form.api_base_url):
        errors.append("The API base URL must start with http:// or https://.")
    errors += [f"Endpoint '{e}' must be a method and a path, e.g. GET /api/tasks." for e in form.endpoints if not ENDPOINT.match(e)]
    if errors:
        raise ValueError("\n".join(errors))

    clean = form.model_copy(update={
        name: [redact_secrets(v) for v in value] if isinstance(value, list) else redact_secrets(value)
        for name, value in form.model_dump().items()
    })
    return clean, [SECRET_WARNING] if clean != form else []
