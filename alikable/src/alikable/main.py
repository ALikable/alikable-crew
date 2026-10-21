#!/usr/bin/env python
import sys
import warnings

from dotenv import load_dotenv

from alikable.crew import Alikable
from alikable.flows import change_router
from alikable.flows.intake import run_in_terminal
from alikable.flows.phases import DESIGN_DIR, run_design_phase

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Sample interview summary for training and testing the Planning crew on its own
INPUTS = {
    'interview_summary': 'Task manager UI. Users log in, see their tasks, add and delete them. '
                         'Endpoints: POST /api/auth/login, GET /api/tasks, POST /api/tasks, DELETE /api/tasks/:id.',
    'feedback': 'None',
}


def run():
    """
    Run the whole flow in the terminal, as the UI does on screen (uv run ui):
    intake flow with the sample form -> HITL #1 -> Design crew -> chat with the Change Router.
    """
    load_dotenv()
    state = run_in_terminal()
    if state.stage != "approved":
        return
    print("\nSpec approved. The Design crew is designing your site...")
    _, approved = run_design_phase(state.site_spec)
    print(("The Design Critic approved it." if approved else "The Design Critic still had fixes after 3 rounds.")
          + f" Saved to {DESIGN_DIR.as_posix()}/.")
    change_router.main(state.chat_id)   # same chat_id, so the Chat Agent recalls the intake


def train():
    """
    Train the crew for a given number of iterations.
    """
    try:
        Alikable().planning_crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=INPUTS)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        Alikable().planning_crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    try:
        Alikable().planning_crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=INPUTS)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

def run_with_trigger():
    """
    Run the crew with trigger payload.
    """
    import json

    if len(sys.argv) < 2:
        raise Exception("No trigger payload provided. Please provide JSON payload as argument.")

    try:
        trigger_payload = json.loads(sys.argv[1])
    except json.JSONDecodeError:
        raise Exception("Invalid JSON payload provided as argument")

    inputs = {
        "crewai_trigger_payload": trigger_payload,
        "interview_summary": "",
        "feedback": "None",
    }

    try:
        result = Alikable().planning_crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
