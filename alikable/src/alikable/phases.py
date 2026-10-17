"""
Phases that run a crew more than once.

Interview: one Discovery Interviewer round per batch of user answers.
Planning (max 2 rounds) and Design (max 3 rounds): the crew runs its tasks once,
and the review loop runs it again with the critic's changes as {feedback} until
the critic says APPROVED. At the end, each part of the design is saved as its own file.
"""

from collections.abc import Callable
from pathlib import Path

from crewai import Crew
from crewai.crews.crew_output import CrewOutput

from alikable.crew import Alikable
from alikable.models import DesignSystem, Interview

REVIEW_LOG = Path("output/design_review_log.md")
SPEC_REVIEW_LOG = Path("output/spec_review_log.md")
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


def run_interview(intake_form: str, answers: str) -> Interview:
    """One interview round: the questions to ask next (none when done) and the summary so far."""
    result = Alikable().interview_crew().kickoff(
        inputs={"intake_form": intake_form, "answers": answers}
    )
    return result.pydantic or Interview(questions=[], summary=result.raw)   # unstructured: treat as done


def run_planning_phase(interview_summary: str, max_rounds: int = 2) -> tuple[str, bool]:
    """Returns (site_spec, approved)."""
    result, approved = run_review_loop(
        "Spec", lambda: Alikable().planning_crew(), {"interview_summary": interview_summary},
        max_rounds, SPEC_REVIEW_LOG,
    )
    return result.tasks_output[1].raw, approved       # Copywriter's output is the complete spec


def run_design_phase(site_spec: str, max_rounds: int = 3) -> tuple[str, bool]:
    """Returns (design, approved)."""
    result, approved = run_review_loop(
        "Design", lambda: Alikable().design_crew(), {"site_spec": site_spec},
        max_rounds, REVIEW_LOG,
    )
    save_design_files(result.tasks_output[0].pydantic)  # the designer's output as a DesignSystem
    return result.tasks_output[0].raw, approved          # designer's output (as JSON text)


if __name__ == "__main__":
    # Test run with the sample spec until the Planning crew provides the real one.
    from dotenv import load_dotenv

    load_dotenv()
    spec = Path("examples/site_spec_task_manager.json").read_text(encoding="utf-8")
    design, approved = run_design_phase(spec)
    print(f"\nApproved: {approved}. Design saved to output/design/")
    print(f"Review log saved to: {REVIEW_LOG}")
