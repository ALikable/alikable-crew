"""
Release Builder (the dashed tool box in the Deploy Guide crew of Documents/Agent_Diagram.png).

Packages the built site in output/site/ as output/site.zip, with index.html at the
top of the zip, then smoke-tests the package: it unzips it into a temporary folder,
serves it on localhost from a subfolder (as GitHub Pages does, so links that start
with / break here too) and requests the home page, every page and every local file
a page links to. It runs the Build Checker on the site as well.

It never deploys anything. The flow adds DEPLOY.md to the zip once the guide is written.
"""

import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type
from urllib.parse import urljoin, urlparse

from crewai.tools import BaseTool
from pydantic import BaseModel

from alikable.models import ReleaseReport, SmokeCheck
from alikable.site_files import OUTPUT, SITE_DIR
from alikable.tools.build_checker import _is_local, _PageParser, check_build

RELEASE_ZIP = OUTPUT / "site.zip"
SUBFOLDER = "site"   # the package is served at http://127.0.0.1:<port>/site/


def _site_files(site_dir: Path) -> list[Path]:
    """Every file to ship, skipping hidden files such as .DS_Store."""
    return sorted(p for p in site_dir.rglob("*")
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(site_dir).parts))


def package_site(site_dir: Path = SITE_DIR, zip_path: Path = RELEASE_ZIP) -> list[str]:
    """Zip the site with its files at the top of the zip. Returns the paths inside it."""
    files = _site_files(site_dir)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(site_dir).as_posix())
    return [p.relative_to(site_dir).as_posix() for p in files]


def add_to_release(name: str, text: str, zip_path: Path = RELEASE_ZIP) -> None:
    """Add one text file (e.g. DEPLOY.md) to the top of the zip, replacing one already there."""
    with zipfile.ZipFile(zip_path) as zf:
        entries = [(info, zf.read(info)) for info in zf.infolist() if info.filename != name]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in entries:
            zf.writestr(info, data)
        zf.writestr(name, text)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def _get(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return None


def smoke_test(zip_path: Path = RELEASE_ZIP) -> list[SmokeCheck]:
    """Serve the unzipped package from a subfolder on localhost and request every page and linked file."""
    checks: list[SmokeCheck] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / SUBFOLDER
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(root)

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=tmp))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}/{SUBFOLDER}/"
        try:
            status = _get(base)   # what a static host shows at the site's URL
            has_index = (root / "index.html").exists()   # without it the server lists the folder instead
            checks.append(SmokeCheck(path="/", status=status, ok=status == 200 and has_index,
                                     note="home page" if has_index else "home page: index.html is missing"))

            seen: set[str] = set()
            for page in sorted(root.rglob("*.html")):
                rel = page.relative_to(root).as_posix()
                status = _get(base + rel)
                checks.append(SmokeCheck(path=rel, status=status, ok=status == 200, note="page"))

                parser = _PageParser()
                parser.feed(page.read_text(encoding="utf-8"))
                parser.finish()
                for tag, url in parser.refs:
                    if not _is_local(url):
                        continue
                    target = urljoin(base + rel, url.split("#")[0])
                    if not urlparse(url).path or target in seen:
                        continue
                    seen.add(target)
                    status = _get(target)
                    shown = target.removeprefix(base) if target.startswith(base) else urlparse(target).path
                    checks.append(SmokeCheck(path=shown, status=status, ok=status == 200,
                                             note=f"{tag} linked from {rel} as {url}"))
        finally:
            server.shutdown()
            server.server_close()
    return checks


def build_release(site_dir: Path = SITE_DIR, zip_path: Path = RELEASE_ZIP) -> ReleaseReport:
    """Check, package and smoke-test the site. Raises FileNotFoundError if there is no site."""
    if not site_dir.exists() or not any(site_dir.glob("*.html")):
        raise FileNotFoundError(f"{site_dir}/ has no HTML pages to package")
    build = check_build(site_dir)
    files = package_site(site_dir, zip_path)
    return ReleaseReport(zip_path=zip_path.as_posix(), files=files, size_bytes=zip_path.stat().st_size,
                         build=build, smoke=smoke_test(zip_path))


class _NoInput(BaseModel):
    pass


class ReleaseBuilderTool(BaseTool):
    name: str = "Release Builder"
    description: str = (
        "Packages the built site in output/site/ as output/site.zip and smoke-tests the package "
        "on localhost, served from a subfolder as GitHub Pages does: the home page, every page "
        "and every local file the pages link to. Also runs the Build Checker. Takes no input. "
        "Returns the files in the package, the build check and every failed request."
    )
    args_schema: Type[BaseModel] = _NoInput

    def _run(self) -> str:
        try:
            return build_release().as_text()
        except FileNotFoundError as e:
            return f"FAIL: {e}"
