"""
Polish & Iterate phase (the Polish & Iterate crew in Documents/Agent_Diagram.png).

Each round the QA Tester and the Consistency Auditor check the site in output/site/
at the same time, then the Fixer handles their findings one at a time, highest
severity first. A small user change routed straight to polish is fixed first. After
every fix the Build Checker runs again, and a fix that adds build errors is rolled
back. The loop stops when a check finds nothing or after max_rounds rounds of fixes.
A last check always follows the last fixes and only reports, so the PolishReport
says what is still open.

Approving or rejecting the result is not done here. The change job that runs this
waits for approval in the chat (HITL #3), and rejecting restores the checkpoint
taken before the change (see site_files.py).
"""

import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from crewai.flow.flow import Flow, listen, or_, router, start
from pydantic import PrivateAttr

from alikable.crew import Alikable
from alikable.models import (AuditReport, BugReport, FixRecord, FixResult, PolishReport, PolishState, QAReport,
                             Suggestion)
from alikable.site_files import SITE_DIR, apply_changes, read_site, restore
from alikable.tools.build_checker import check_build

REPORT = Path("output/polish_report.json")
DESIGN_DIR = Path("output/design")
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _describe(item: BugReport | Suggestion) -> tuple[str, str]:
    """A one-line label for the report, and the full problem for the Fixer."""
    if isinstance(item, BugReport):
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(item.steps, 1))
        return (f"{item.severity} bug on {item.page}: {item.actual}",
                f"Bug on {item.page} ({item.severity})\nSteps:\n{steps}\n"
                f"What happens: {item.actual}\nWhat should happen: {item.expected}")
    return (f"{item.severity} inconsistency on {item.page}: {item.current}",
            f"Inconsistency on {item.page} ({item.severity})\nRule it breaks: {item.rule}\n"
            f"Now: {item.current}\nChange to make: {item.proposed}")


class PolishFlow(Flow[PolishState]):
    """Check, fix, re-check, up to max_rounds rounds of fixes."""

    _on_step: Callable[[str], None] | None = PrivateAttr(default=None)   # set by the change job

    def _step(self, step: str) -> None:
        print(f"\n===== POLISH: {step} =====\n")
        if self._on_step:
            self._on_step(step)

    @start()
    def load_build(self):
        # TODO(implementation crew): it will write output/site/. Until then, polish the
        # design's page layouts so this phase can be run and tested.
        if not any(SITE_DIR.glob("*.html")) and DESIGN_DIR.exists():
            SITE_DIR.mkdir(parents=True, exist_ok=True)
            for file in DESIGN_DIR.iterdir():
                if file.suffix in (".html", ".css") and file.name != "components.html":
                    shutil.copy2(file, SITE_DIR / file.name)

    @listen(or_(load_build, "recheck"))
    def check(self):
        final = self.state.round >= self.state.max_rounds
        self._step("polish final check" if final else f"polish round {self.state.round + 1}: checking")
        crews = Alikable()
        files = read_site()
        with ThreadPoolExecutor(max_workers=2) as pool:   # QA and the audit do not depend on each other
            qa = pool.submit(crews.qa_crew().kickoff, inputs={
                "site_spec": self.state.site_spec, "site_files": files,
            })
            audit = pool.submit(crews.audit_crew().kickoff, inputs={
                "site_spec": self.state.site_spec, "design": self.state.design or "None", "site_files": files,
            })
            qa_report, audit_report = qa.result().pydantic, audit.result().pydantic

        # An unstructured answer counts as nothing found, so it cannot loop forever
        self.state.bugs = qa_report.bugs if isinstance(qa_report, QAReport) else []
        self.state.suggestions = audit_report.suggestions if isinstance(audit_report, AuditReport) else []

    @router(check)
    def decide(self) -> Literal["fix", "done"]:
        if self.state.round >= self.state.max_rounds:
            return "done"
        if self.state.bugs or self.state.suggestions or self.state.change_request:
            return "fix"
        return "done"

    @router("fix")
    def fix_issues(self) -> Literal["recheck"]:
        self.state.round += 1
        found = sorted([*self.state.bugs, *self.state.suggestions], key=lambda i: SEVERITY_ORDER[i.severity])
        items = [_describe(i) for i in found]
        if self.state.max_fixes_per_round:
            items = items[: self.state.max_fixes_per_round]
        if self.state.change_request:
            items.insert(0, (f"User change: {self.state.change_request}",
                             f"Change the user asked for: {self.state.change_request}"))
            self.state.change_request = ""

        for n, (label, problem) in enumerate(items, 1):
            self._step(f"polish round {self.state.round}: fixing {n} of {len(items)}")
            self.state.report.fixes.append(self._fix(label, problem))
        return "recheck"

    def _fix(self, label: str, problem: str) -> FixRecord:
        """Ask the Fixer for one fix, write it, and roll it back if it breaks the build."""
        errors_before = set(check_build().errors)
        try:
            result = Alikable().fix_crew().kickoff(inputs={
                "issue": problem, "site_spec": self.state.site_spec, "site_files": read_site(),
            }).pydantic
        except Exception as e:   # one failed fix should not stop the others
            return FixRecord(issue=label, status="failed", note=f"The Fixer failed: {e}")
        if not isinstance(result, FixResult):
            return FixRecord(issue=label, status="failed", note="The Fixer's answer was not structured; nothing changed.")
        if result.status == "skipped" or not result.files:
            return FixRecord(issue=label, status="skipped", note=result.note)

        changed = [c.path for c in result.files]
        try:
            backup = apply_changes(result.files)
        except ValueError as e:
            return FixRecord(issue=label, status="failed", files=changed, note=f"Not written: {e}")

        new_errors = [e for e in check_build().errors if e not in errors_before]
        if new_errors:
            restore(backup)
            return FixRecord(issue=label, status="reverted", files=changed,
                             note=f"{result.note} Rolled back, it broke the build: " + "; ".join(new_errors))
        return FixRecord(issue=label, status="fixed", files=changed, note=result.note)

    @listen("done")
    def finish(self) -> PolishReport:
        build = check_build()
        report = self.state.report
        report.rounds = self.state.round
        report.build_ok, report.build_errors = build.ok, build.errors
        report.open_bugs, report.open_suggestions = self.state.bugs, self.state.suggestions
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report


def run_polish_phase(site_spec: str, design: str = "", change_request: str = "", max_rounds: int = 1,
                     on_step: Callable[[str], None] | None = None) -> PolishReport:
    """Polish output/site/ and return what was fixed and what is still open."""
    flow = PolishFlow()
    flow._on_step = on_step
    flow.kickoff(inputs={"site_spec": site_spec, "design": design,
                         "change_request": change_request, "max_rounds": max_rounds})
    return flow.state.report


if __name__ == "__main__":
    # Test run on output/site/ (or the design layouts) with the sample spec.
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    spec = Path("examples/site_spec_task_manager.json").read_text(encoding="utf-8")
    design = Path("output/design/design.json")
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    report = run_polish_phase(spec, design.read_text(encoding="utf-8") if design.exists() else "",
                              max_rounds=rounds)
    print(f"\n{report.summary()}\nReport saved to: {REPORT}")
