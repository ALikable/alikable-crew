"""
Build Checker (the dashed tool box in Documents/Agent_Diagram.png).

Static checks that the built site in output/site/ will load: well-formed HTML,
local links and assets that exist, scripts only from allowlisted CDNs, balanced
CSS, JavaScript that parses (with `node --check`, skipped when node is missing),
valid JSON and no secrets. It does not open a browser, so it cannot catch errors
that only happen while the page runs.
"""

import json
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel

from alikable.models import BuildCheck
from alikable.site_files import SITE_DIR

ALLOWED_CDNS = ("https://cdn.jsdelivr.net/", "https://cdnjs.cloudflare.com/", "https://unpkg.com/")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "source", "track", "wbr"}
# Tags whose end tag HTML lets you leave out, so a missing one is not an error
OPTIONAL_END_TAGS = {"html", "head", "body", "p", "li", "dt", "dd", "option", "optgroup",
                     "thead", "tbody", "tfoot", "tr", "td", "th", "colgroup", "caption"}
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),                                     # OpenAI-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                                          # AWS access keys
    re.compile(r"""(api[_-]?key|secret|token)\s*[:=]\s*['"][A-Za-z0-9_\-]{16,}['"]""", re.I),
]
NODE = shutil.which("node")


class _PageParser(HTMLParser):
    """Collects unclosed or stray tags, linked files and inline scripts of one page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int]] = []
        self.problems: list[str] = []
        self.refs: list[tuple[str, str]] = []           # (tag, url)
        self.inline_scripts: list[tuple[str, str]] = []  # (type, code)
        self.has_doctype = False
        self._script_type: str | None = None

    def handle_decl(self, decl):
        self.has_doctype |= decl.lower().startswith("doctype")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            if a.get("src"):
                self.refs.append(("script", a["src"]))
            else:
                self._script_type = a.get("type") or "text/javascript"
        elif tag == "link" and a.get("href") and "stylesheet" in (a.get("rel") or ""):
            self.refs.append(("stylesheet", a["href"]))
        elif tag in ("img", "source") and a.get("src"):
            self.refs.append((tag, a["src"]))
        elif tag == "a" and a.get("href"):
            self.refs.append(("a", a["href"]))
        if tag not in VOID_TAGS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "script":
            self._script_type = None
        if tag in VOID_TAGS:
            return
        if not any(t == tag for t, _ in self.stack):
            self.problems.append(f"line {self.getpos()[0]}: </{tag}> has no matching <{tag}>")
            return
        while self.stack:
            open_tag, line = self.stack.pop()
            if open_tag == tag:
                break
            if open_tag not in OPTIONAL_END_TAGS:
                self.problems.append(f"line {line}: <{open_tag}> is never closed")

    def handle_data(self, data):
        if self._script_type is not None and data.strip():
            self.inline_scripts.append((self._script_type, data))

    def finish(self) -> None:
        self.close()
        self.problems += [f"line {line}: <{tag}> is never closed"
                          for tag, line in self.stack if tag not in OPTIONAL_END_TAGS]


def _is_local(url: str) -> bool:
    return not re.match(r"^([a-z][a-z0-9+.-]*:|//|#)", url, re.I)


def _check_html(path: Path, rel: str, text: str, errors: list[str], warnings: list[str],
                scripts: list[tuple[str, str, str]]) -> None:
    parser = _PageParser()
    parser.feed(text)
    parser.finish()
    errors += [f"{rel}: {p}" for p in parser.problems]
    if not parser.has_doctype:
        warnings.append(f"{rel}: missing <!DOCTYPE html>")

    for tag, url in parser.refs:
        if _is_local(url):
            target = url.split("#")[0].split("?")[0]
            if target and not (path.parent / target).exists():
                errors.append(f"{rel}: {tag} points to {target}, which does not exist")
        elif tag in ("script", "stylesheet") and url.startswith(("http:", "https:", "//")) \
                and not url.startswith(ALLOWED_CDNS):
            errors.append(f"{rel}: loads {tag} from {url}, which is not an allowlisted CDN")

    for i, (kind, code) in enumerate(parser.inline_scripts, 1):
        if "javascript" in kind or kind == "module":
            scripts.append((f"{rel} (inline script {i})", code, ".mjs" if kind == "module" else ".js"))
        elif "json" in kind:
            try:
                json.loads(code)
            except json.JSONDecodeError as e:
                errors.append(f"{rel} (inline JSON {i}): {e}")


def _check_css(rel: str, text: str, errors: list[str]) -> None:
    if text.count("/*") > text.count("*/"):
        errors.append(f"{rel}: a /* comment is never closed")
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    code = re.sub(r"""(["'])(?:\\.|(?!\1).)*\1""", "", code)
    depth = 0
    for line_no, line in enumerate(code.splitlines(), 1):
        for ch in line:
            depth += {"{": 1, "}": -1}.get(ch, 0)
            if depth < 0:
                errors.append(f"{rel}: line {line_no}: '}}' without a matching '{{'")
                depth = 0
    if depth > 0:
        errors.append(f"{rel}: {depth} '{{' never closed")


def _check_js(scripts: list[tuple[str, str, str]], errors: list[str], warnings: list[str]) -> None:
    if not scripts:
        return
    if not NODE:
        warnings.append("JavaScript was not syntax-checked: node is not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        for i, (label, code, suffix) in enumerate(scripts):
            file = Path(tmp) / f"script{i}{suffix}"
            file.write_text(code, encoding="utf-8")
            run = subprocess.run([NODE, "--check", str(file)], capture_output=True, text=True, timeout=30)
            if run.returncode != 0:
                # node prints the file, the line, a caret and then "SyntaxError: ..."
                message = next((l for l in run.stderr.splitlines() if "Error" in l), run.stderr.strip())
                line = re.search(rf"{re.escape(file.name)}:(\d+)", run.stderr)
                errors.append(f"{label}: " + (f"line {line.group(1)}: " if line else "") + message)


def check_build(site_dir: Path = SITE_DIR) -> BuildCheck:
    errors: list[str] = []
    warnings: list[str] = []
    scripts: list[tuple[str, str, str]] = []   # (label, code, suffix) for node --check

    files = sorted(p for p in site_dir.rglob("*") if p.is_file()) if site_dir.exists() else []
    if not any(p.suffix == ".html" for p in files):
        return BuildCheck(ok=False, errors=[f"{site_dir}/ has no HTML pages"])
    if not (site_dir / "index.html").exists():
        errors.append("index.html is missing, so static hosts will show no home page")

    for path in files:
        rel = path.relative_to(site_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue   # images and other binary files
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                errors.append(f"{rel}: looks like it contains an API key or secret")
                break
        if path.suffix == ".html":
            _check_html(path, rel, text, errors, warnings, scripts)
        elif path.suffix == ".css":
            _check_css(rel, text, errors)
        elif path.suffix in (".js", ".mjs"):
            scripts.append((rel, text, path.suffix))
        elif path.suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as e:
                errors.append(f"{rel}: invalid JSON: {e}")

    _check_js(scripts, errors, warnings)
    return BuildCheck(ok=not errors, errors=errors, warnings=warnings)


class _NoInput(BaseModel):
    pass


class BuildCheckerTool(BaseTool):
    name: str = "Build Checker"
    description: str = (
        "Checks the built site in output/site/ for broken HTML, links or assets that do not "
        "exist, scripts from CDNs that are not allowlisted, unbalanced CSS, JavaScript syntax "
        "errors, invalid JSON and secrets. Takes no input. Returns PASS, or each error with "
        "its file and line."
    )
    args_schema: Type[BaseModel] = _NoInput

    def _run(self) -> str:
        return check_build().as_text()
