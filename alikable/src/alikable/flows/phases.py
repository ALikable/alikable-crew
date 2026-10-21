"""
Phases that run a crew more than once.

Design (max 3 rounds): the crew runs its tasks once, and the review loop runs it
again with the critic's changes as {feedback} until the critic says APPROVED. At the
end, each part of the design is saved as its own file. Planning uses the same review
loop from the intake flow (flows/intake.py).
Implementation (max 3 rounds): the builders write output/site/, then the Code
Reviewer checks the files on disk.
"""

import json
from collections.abc import Callable
from pathlib import Path

from crewai import Crew
from crewai.crews.crew_output import CrewOutput

import shutil

from alikable.crew import Alikable
from alikable.models import DesignSystem, FileChange, SiteBuild
from alikable.site_files import SITE_DIR, apply_changes, read_site

REVIEW_LOG = Path("output/design_review_log.md")
DESIGN_DIR = Path("output/design")
CODE_REVIEW_LOG = Path("output/code_review_log.md")
SITE_SPEC = Path("output/site_spec.json")   # the approved spec every later crew reads

def is_approved(review: str) -> bool:
    """True if the critic's answer starts with APPROVED (ignores ** and # around it)."""
    cleaned = review.strip().strip("*#`'\" ").upper()
    return cleaned.startswith("APPROVED")


def save_design_files(design: DesignSystem | None) -> None:
    """Save each part of the design as its own file in output/design/."""
    if design is None:
        print("The design was not structured; no design files saved.")
        return

    DESIGN_DIR.mkdir(parents=True, exist_ok=True)
    (DESIGN_DIR / "styles.css").write_text(design.styles_css, encoding="utf-8")

    # Wrap the component snippets in a page that links styles.css, so it previews styled
    components_page = (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>Components</title>\n<link rel=\"stylesheet\" href=\"styles.css\">\n"
        "</head>\n<body>\n" + design.components_html + "\n</body>\n</html>\n"
    )
    (DESIGN_DIR / "components.html").write_text(components_page, encoding="utf-8")

    (DESIGN_DIR / "design_notes.md").write_text(
        f"# Design notes\n\nTemplate used: {design.template_used}\n\n{design.notes}", encoding="utf-8"
    )
    for page in design.layouts:
        file_name = Path(page.file).name          # keep only the name, e.g. "index.html"
        (DESIGN_DIR / file_name).write_text(page.html, encoding="utf-8")

    print(f"Design files saved to: {DESIGN_DIR}/  (open index.html in a browser)")


def run_review_loop(name: str, make_crew: Callable[[], Crew], inputs: dict,
                    max_rounds: int, log_path: Path) -> tuple[CrewOutput, bool]:
    """Runs a writer/critic crew (critic last) until APPROVED. Returns (last result, approved)."""
    feedback = "None"   # first round: no feedback yet
    log = f"# {name} review log\n"

    for round_no in range(1, max_rounds + 1):
        print(f"\n===== {name.upper()} ROUND {round_no} of {max_rounds} =====\n")

        result = make_crew().kickoff(inputs={**inputs, "feedback": feedback})
        review = result.tasks_output[-1].raw             # critic's answer

        # Show and record what the critic said this round
        print(f"\n----- CRITIC, ROUND {round_no} -----\n{review}\n")
        log += f"\n## Round {round_no}\n\n{review}\n"

        if is_approved(review):
            print(f"{name} APPROVED in round {round_no}.")
            break

        feedback = review   # critic's changes go into the next round
    else:
        print(f"Not approved after {max_rounds} rounds; using the last {name.lower()}.")

    log_path.write_text(log, encoding="utf-8")
    return result, is_approved(review)


def run_design_phase(site_spec: str, max_rounds: int = 3) -> tuple[str, bool]:
    """Returns (design, approved)."""
    result, approved = run_review_loop(
        "Design", lambda: Alikable().design_crew(), {"site_spec": site_spec},
        max_rounds, REVIEW_LOG,
    )
    save_design_files(result.tasks_output[0].pydantic)  # the designer's output as a DesignSystem
    return result.tasks_output[0].raw, approved          # designer's output (as JSON text)

def collect_files(result: CrewOutput) -> list[FileChange]:
    """All files from the builders' answers (API Integrator, then Page Builder)."""
    files: list[FileChange] = []
    for task_output in result.tasks_output:
        if isinstance(task_output.pydantic, SiteBuild):
            files += task_output.pydantic.files
            print(f"{task_output.agent} returned: {[f.path for f in task_output.pydantic.files]}")
        else:
            print(f"WARNING: {task_output.agent} did not return files in the SiteBuild shape.")
    # styles.css always comes from the design, so a builder can't overwrite it
    return [f for f in files if f.path.strip("/") != "styles.css"]

def reset_site() -> None:
    """Empty output/site/ and put the design's styles.css back, so no old files are left."""
    shutil.rmtree(SITE_DIR, ignore_errors=True)
    SITE_DIR.mkdir(parents=True)
    shutil.copy2(DESIGN_DIR / "styles.css", SITE_DIR / "styles.css")
    # Safety rule: the hidden attribute always wins, even over display: flex
    with open(SITE_DIR / "styles.css", "a", encoding="utf-8") as css:
        css.write("\n[hidden] { display: none !important; }\n")

def ensure_home_page(site_spec: str) -> None:
    """If there is no index.html, add one that sends visitors to the first page."""
    if (SITE_DIR / "index.html").exists():
        return
    pages = json.loads(site_spec).get("pages", [])
    names = list(pages)                       # dict → its keys ("login", ...); list → its items
    first_page = names[0] if names else None
    if isinstance(first_page, dict):          # your example format: {"file": "index.html", ...}
        first_page = first_page.get("file") or first_page.get("name")
    if first_page and not str(first_page).endswith(".html"):
        first_page = f"{first_page}.html"     # "login" → "login.html"
    if not first_page or not (SITE_DIR / first_page).exists():
        built = sorted(p.name for p in SITE_DIR.glob("*.html"))   # fall back to a page that was built
        first_page = built[0] if built else None
    if first_page:
        (SITE_DIR / "index.html").write_text(
            f'<meta http-equiv="refresh" content="0; url={first_page}">'
            f'<a href="{first_page}">Continue</a>',
            encoding="utf-8",
        )

def run_implementation_phase(site_spec: str, design: str, max_rounds: int = 3) -> bool:
    """Builds the site into output/site/ and loops on the Code Reviewer. Returns approved."""
    feedback = "None"          # round 1: no feedback yet
    previous_build = "None"    # round 1: nothing built yet
    log = "# Code review log\n"

    for round_no in range(1, max_rounds + 1):
        print(f"\n===== IMPLEMENTATION ROUND {round_no} of {max_rounds} =====\n")

        # 1. The builders write the code, starting from last round's files if there are any
        build = Alikable().implementation_crew().kickoff(
            inputs={"site_spec": site_spec, "design": design, "feedback": feedback,
                    "previous_build": previous_build}
        )

        # 2. Python empties output/site/ and saves the new files
        files = collect_files(build)
        reset_site()
        apply_changes(files)
        ensure_home_page(site_spec)
        print(f"Saved {len(files)} files to {SITE_DIR}/")

        # 3. The reviewer checks the real files on disk
        review = Alikable().code_review_crew().kickoff(
            inputs={"site_spec": site_spec, "site_files": read_site()}
        ).raw

        print(f"\n----- CODE REVIEWER, ROUND {round_no} -----\n{review}\n")
        log += f"\n## Round {round_no}\n\n{review}\n"

        if is_approved(review):
            print(f"Site APPROVED in round {round_no}.")
            CODE_REVIEW_LOG.write_text(log, encoding="utf-8")
            return True

        feedback = review                 # reviewer's fixes go into the next round
        previous_build = read_site()      # and the builders start from this round's files

    print(f"Not approved after {max_rounds} rounds; keeping the last build.")
    CODE_REVIEW_LOG.write_text(log, encoding="utf-8")
    return False
    
if __name__ == "__main__":
    # Test runs with the sample spec until the Planning crew provides the real one.
    #   uv run python -m alikable.flows.phases                 -> design phase
    #   uv run python -m alikable.flows.phases implementation  -> implementation phase
    import sys
    from dotenv import load_dotenv

    load_dotenv()
    spec = SITE_SPEC.read_text(encoding="utf-8")   # the spec approved in John's UI

    if len(sys.argv) > 1 and sys.argv[1] == "implementation":
        design = Path("output/design/design.json").read_text(encoding="utf-8")
        approved = run_implementation_phase(spec, design)
        print(f"\nApproved: {approved}. Site saved to {SITE_DIR}/")
        print(f"Review log saved to: {CODE_REVIEW_LOG}")
    else:
        design, approved = run_design_phase(spec)
        print(f"\nApproved: {approved}. Design saved to output/design/")
        print(f"Review log saved to: {REVIEW_LOG}")