from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource


@CrewBase
class Alikable():
    """Alikable crews, one per phase of Documents/Agent_Diagram.png"""

    agents: list[BaseAgent]
    tasks: list[Task]

    # ------------------------------------------------------------------ Agents

    @agent
    def discovery_interviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['discovery_interviewer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def spec_writer(self) -> Agent:
        return Agent(
            config=self.agents_config['spec_writer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def copywriter(self) -> Agent:
        return Agent(
            config=self.agents_config['copywriter'], # type: ignore[index]
            verbose=True
        )

    @agent
    def spec_critic(self) -> Agent:
        return Agent(
            config=self.agents_config['spec_critic'], # type: ignore[index]
            verbose=True
        )

    @agent
    def design_system_designer(self) -> Agent:
        return Agent(
            config=self.agents_config['design_system_designer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def design_critic(self) -> Agent:
        return Agent(
            config=self.agents_config['design_critic'], # type: ignore[index]
            verbose=True
        )

    @agent
    def api_integrator(self) -> Agent:
        return Agent(
            config=self.agents_config['api_integrator'], # type: ignore[index]
            verbose=True
        )

    @agent
    def page_builder(self) -> Agent:
        return Agent(
            config=self.agents_config['page_builder'], # type: ignore[index]
            verbose=True
        )

    @agent
    def code_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['code_reviewer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def qa_tester(self) -> Agent:
        return Agent(
            config=self.agents_config['qa_tester'], # type: ignore[index]
            verbose=True
        )

    @agent
    def consistency_auditor(self) -> Agent:
        return Agent(
            config=self.agents_config['consistency_auditor'], # type: ignore[index]
            verbose=True
        )

    @agent
    def fixer(self) -> Agent:
        return Agent(
            config=self.agents_config['fixer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def deploy_guide_writer(self) -> Agent:
        return Agent(
            config=self.agents_config['deploy_guide_writer'], # type: ignore[index]
            verbose=True
        )

    @agent
    def change_router(self) -> Agent:
        return Agent(
            config=self.agents_config['change_router'], # type: ignore[index]
            verbose=True
        )

    # ------------------------------------------------------------------- Tasks

    @task
    def interview_task(self) -> Task:
        return Task(
            config=self.tasks_config['interview_task'], # type: ignore[index]
        )

    @task
    def spec_writing_task(self) -> Task:
        return Task(
            config=self.tasks_config['spec_writing_task'], # type: ignore[index]
        )

    @task
    def copywriting_task(self) -> Task:
        return Task(
            config=self.tasks_config['copywriting_task'], # type: ignore[index]
        )

    @task
    def spec_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['spec_review_task'], # type: ignore[index]
        )

    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task'], # type: ignore[index]
        )

    @task
    def design_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_review_task'], # type: ignore[index]
        )

    @task
    def api_integration_task(self) -> Task:
        return Task(
            config=self.tasks_config['api_integration_task'], # type: ignore[index]
        )

    @task
    def page_build_task(self) -> Task:
        return Task(
            config=self.tasks_config['page_build_task'], # type: ignore[index]
        )

    @task
    def code_review_task(self) -> Task:
        return Task(
            config=self.tasks_config['code_review_task'], # type: ignore[index]
        )

    @task
    def qa_task(self) -> Task:
        return Task(
            config=self.tasks_config['qa_task'], # type: ignore[index]
        )

    @task
    def consistency_audit_task(self) -> Task:
        return Task(
            config=self.tasks_config['consistency_audit_task'], # type: ignore[index]
        )

    @task
    def fix_task(self) -> Task:
        return Task(
            config=self.tasks_config['fix_task'], # type: ignore[index]
        )

    @task
    def deploy_guide_task(self) -> Task:
        return Task(
            config=self.tasks_config['deploy_guide_task'], # type: ignore[index]
        )

    @task
    def route_change_task(self) -> Task:
        return Task(
            config=self.tasks_config['route_change_task'], # type: ignore[index]
        )

    # ------------------------------------------------------------------ Crews

    def _crew(self, *tasks: Task) -> Crew:
        """Builds a sequential crew from the given tasks and the agents that own them."""
        return Crew(
            agents=[t.agent for t in tasks],
            tasks=list(tasks),
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def planning_crew(self) -> Crew:
        """Interviews the user and writes site_spec.json"""
        return self._crew(self.interview_task(), self.spec_writing_task(),
                          self.copywriting_task(), self.spec_review_task())

    @crew
    def design_crew(self) -> Crew:
        """Designs the components, stylesheet and page layouts"""
        return self._crew(self.design_task(), self.design_review_task())

    @crew
    def implementation_crew(self) -> Crew:
        """Builds the API module and the pages, then reviews them"""
        return self._crew(self.api_integration_task(), self.page_build_task(),
                          self.code_review_task())

    @crew
    def polish_crew(self) -> Crew:
        """Finds and fixes bugs and inconsistencies, and applies small changes"""
        return self._crew(self.qa_task(), self.consistency_audit_task(), self.fix_task())

    @crew
    def deploy_crew(self) -> Crew:
        """Writes DEPLOY.md for the packaged site"""
        return self._crew(self.deploy_guide_task())

    @crew
    def change_router_crew(self) -> Crew:
        """Decides which crew handles a change request"""
        return self._crew(self.route_change_task())
