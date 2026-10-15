from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource


@CrewBase
class Alikable():
    """Alikable crew"""

    agents: list[BaseAgent]
    tasks: list[Task]



    @agent
    def discovery_interviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["discovery_interviewer"],
            knowledge_source=[
                TextFileKnowledgeSource(file_paths=["design_practices.txt"])
            ],
            verbose=True,
        )


    @task
    def research_task(self) -> Task:
        return Task(
            config=self.tasks_config['research_task'], # type: ignore[index]
        )

    @task
    def reporting_task(self) -> Task:
        return Task(
            config=self.tasks_config['reporting_task'], # type: ignore[index]
            output_file='report.md'
        )

    @crew
    def crew(self) -> Crew:
        """Creates the Alikable crew"""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
