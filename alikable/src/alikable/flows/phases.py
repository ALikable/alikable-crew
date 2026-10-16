"""
Design phase with its review loop (max 3 rounds).

The crew runs its tasks once. This loop runs it again with the
critic's changes as {feedback} until the critic says APPROVED.
At the end, each part of the design is saved as its own file.
"""

from pathlib import Path

from alikable.crew import Alikable
from alikable.models import DesignSystem                 

REVIEW_LOG = Path("output/design_review_log.md")
DESIGN_DIR = Path("output/design")                       


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

def run_design_phase(site_spec: str, max_rounds: int = 3) -> tuple[str, bool]:
    """Returns (design, approved)."""
    feedback = "None"   # first round: no feedback yet
    design = ""
    structured = None                                     
    log = "# Design review log\n"

    for round_no in range(1, max_rounds + 1):
        print(f"\n===== DESIGN ROUND {round_no} of {max_rounds} =====\n")

        result = Alikable().design_crew().kickoff(
            inputs={"site_spec": site_spec, "feedback": feedback}
        )
        design = result.tasks_output[0].raw              # designer's output (as JSON text)
        structured = result.tasks_output[0].pydantic     # NEW: the same output as a DesignSystem object
        review = result.tasks_output[1].raw              # critic's answer

        # Show and record what the critic said this round
        print(f"\n----- CRITIC, ROUND {round_no} -----\n{review}\n")
        log += f"\n## Round {round_no}\n\n{review}\n"

        if is_approved(review):
            print(f"Design APPROVED in round {round_no}.")
            REVIEW_LOG.write_text(log, encoding="utf-8")
            save_design_files(structured)                 
            return design, True

        feedback = review   # critic's changes go into the next round

    print(f"Not approved after {max_rounds} rounds; using the last design.")
    REVIEW_LOG.write_text(log, encoding="utf-8")
    save_design_files(structured)                         
    return design, False


if __name__ == "__main__":
    # Test run with the sample spec until the Planning crew provides the real one.
    from dotenv import load_dotenv

    load_dotenv()
    spec = Path("examples/site_spec_task_manager.json").read_text(encoding="utf-8")
    design, approved = run_design_phase(spec)
    print(f"\nApproved: {approved}. Design saved to output/design/")
    print(f"Review log saved to: {REVIEW_LOG}")