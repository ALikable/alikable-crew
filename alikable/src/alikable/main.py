#!/usr/bin/env python
import sys
import warnings

from dotenv import load_dotenv

from alikable.crew import Alikable
from alikable.projects import Project

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Training and testing run the Planning crew on its own, in this project folder
DEV_PROJECT = Project("planning-crew-dev")
# Sample interview summary for training and testing the Planning crew on its own
INPUTS = {
    'interview_summary': 'Task manager UI. Users log in, see their tasks, add and delete them. '
                         'Endpoints: POST /api/auth/login, GET /api/tasks, POST /api/tasks, DELETE /api/tasks/:id.',
    'feedback': 'None',
    'chat_id': DEV_PROJECT.chat_id,   # places the spec draft (tasks.yaml)
}


def run():
    """
    Run the Alikable app: the UI with the project picker, intake, and a chat per project.
    crewai run, uv run alikable and uv run ui all start it.
    """
    load_dotenv()
    from alikable.app import main   # imported here so train, test and replay don't load Gradio

    main()


def train():
    """
    Train the crew for a given number of iterations.
    """
    try:
        Alikable(DEV_PROJECT).planning_crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=INPUTS)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        Alikable(DEV_PROJECT).planning_crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    try:
        Alikable(DEV_PROJECT).planning_crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=INPUTS)

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
        "chat_id": DEV_PROJECT.chat_id,
    }

    try:
        result = Alikable(DEV_PROJECT).planning_crew().kickoff(inputs=inputs)
        return result
    except Exception as e:
        raise Exception(f"An error occurred while running the crew with trigger: {e}")
