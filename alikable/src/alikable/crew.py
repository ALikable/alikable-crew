import os
import threading

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource
from crewai.memory import Memory, MemoryScope, MemorySlice
from alikable.models import AuditReport, ChatReply, DesignSystem, FixResult, Interview, QAReport, RouteDecision, SiteBuild
from alikable.projects import Project
from alikable.tools.build_checker import BuildCheckerTool
from alikable.tools.release_builder import ReleaseBuilderTool
from crewai.mcp import MCPServerStdio
from crewai.mcp.filters import create_static_tool_filter
# ------------------------------------------------------------------ Memory
# Only the chat side remembers. Every other crew works from its inputs alone, so
# reviews and rework stay independent. One Memory backs every chat; each chat is
# the scope /chat/<chat_id>. output/memory is not checkpointed, so rejecting a
# build keeps what the user said.

MEMORY_DIR = "output/memory"
_memory: Memory | None = None
_memory_lock = threading.Lock()


def shared_memory() -> Memory:
    """The one Memory for this process, made on first use (after load_dotenv)."""
    global _memory
    with _memory_lock:
        if _memory is None:
            _memory = Memory(storage=MEMORY_DIR, llm=os.getenv("MEMORY_MODEL", "gpt-5.4-mini"))
        return _memory


def chat_memory(chat_id: str) -> MemoryScope:
    """Read and write one chat's memories."""
    return MemoryScope(root_path=f"/chat/{chat_id}", memory=shared_memory())


def chat_memory_read_only(chat_id: str) -> MemorySlice:
    """Recall one chat's memories without saving anything."""
    return MemorySlice(scopes=[f"/chat/{chat_id}"], read_only=True, memory=shared_memory())


@CrewBase
class Alikable():
    """Alikable crews, one per phase of Documents/Agent_Diagram.png, for one project.

    The project gives the tools their folder: agents call the Build Checker and the
    Release Builder without input, so the folder can't come from the agent. Kickoffs
    whose tasks have an output_file must also pass the project's chat_id as an input
    (tasks.yaml)."""

    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(self, project: Project):
        self.project = project

    # ------------------------------------------------------------------ Agents

    @agent
    def discovery_interviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["discovery_interviewer"],
            knowledge_sources=[
                TextFileKnowledgeSource(file_paths=["design_practices.txt"])
            ],
            verbose=True,
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
            knowledge_sources=[TextFileKnowledgeSource(file_paths=["design_practices.txt"])],
            verbose=True
        )

    @agent
    def design_system_designer(self) -> Agent:
        return Agent(
            config=self.agents_config['design_system_designer'], # type: ignore[index]
            knowledge_sources=[TextFileKnowledgeSource(file_paths=["design_templates.txt"])],
            llm="openai/gpt-5.6-luna",
            verbose=True
        )

    @agent
    def design_critic(self) -> Agent:
        return Agent(
            config=self.agents_config['design_critic'], # type: ignore[index]
            knowledge_sources=[TextFileKnowledgeSource(file_paths=["design_templates.txt"])],
            llm="openai/gpt-5.6-luna",
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
            llm="openai/gpt-5.6-luna",
            verbose=True
        )
    
    @agent
    def code_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config['code_reviewer'], # type: ignore[index]
            tools=[BuildCheckerTool(site_dir=self.project.site_dir)],
            mcps=[MCPServerStdio(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem",
                      str(self.project.site_dir.resolve())],
                tool_filter=create_static_tool_filter(
                    allowed_tool_names=["list_directory", "read_text_file"]
                ),
            )],
            llm="openai/gpt-5.6-luna",
            verbose=True
        )

    @agent
    def qa_tester(self) -> Agent:
        return Agent(
            config=self.agents_config['qa_tester'], # type: ignore[index]
            tools=[BuildCheckerTool(site_dir=self.project.site_dir)],
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
            tools=[ReleaseBuilderTool(site_dir=self.project.site_dir, zip_path=self.project.release_zip)],
            verbose=True
        )

    @agent
    def change_router(self) -> Agent:
        return Agent(
            config=self.agents_config['change_router'], # type: ignore[index]
            verbose=True
        )

    @agent
    def chat_agent(self) -> Agent:
        return Agent(
            config=self.agents_config['chat_agent'], # type: ignore[index]
            verbose=True
        )

    # ------------------------------------------------------------------- Tasks

    @task
    def interview_task(self) -> Task:
        return Task(
            config=self.tasks_config['interview_task'], # type: ignore[index]
            output_pydantic=Interview,
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
            output_pydantic=DesignSystem,
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
            output_pydantic=SiteBuild,
        )

    @task
    def page_build_task(self) -> Task:
        return Task(
            config=self.tasks_config['page_build_task'], # type: ignore[index]
            output_pydantic=SiteBuild,
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
            output_pydantic=QAReport,
        )

    @task
    def consistency_audit_task(self) -> Task:
        return Task(
            config=self.tasks_config['consistency_audit_task'], # type: ignore[index]
            output_pydantic=AuditReport,
        )

    @task
    def fix_task(self) -> Task:
        return Task(
            config=self.tasks_config['fix_task'], # type: ignore[index]
            output_pydantic=FixResult,
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
            output_pydantic=RouteDecision,
        )

    @task
    def chat_task(self) -> Task:
        return Task(
            config=self.tasks_config['chat_task'], # type: ignore[index]
            output_pydantic=ChatReply,
        )

    # ------------------------------------------------------------------ Crews
    # Every crew is sequential. Only the chat crews take a chat_id and use memory.

    @crew
    def interview_crew(self) -> Crew:
        """Runs one round of the Discovery Interviewer"""
        return Crew(
            agents=[self.discovery_interviewer()],
            tasks=[self.interview_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def planning_crew(self) -> Crew:
        """Writes site_spec.json from the interview summary"""
        return Crew(
            agents=[self.spec_writer(), self.copywriter(), self.spec_critic()],
            tasks=[self.spec_writing_task(), self.copywriting_task(), self.spec_review_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def design_crew(self) -> Crew:
        """Designs the components, stylesheet and page layouts"""
        return Crew(
            agents=[self.design_system_designer(), self.design_critic()],
            tasks=[self.design_task(), self.design_review_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def implementation_crew(self) -> Crew:
        """Builds the API module and the pages (the Code Reviewer runs after they are saved)"""
        return Crew(
            agents=[self.api_integrator(), self.page_builder()],
            tasks=[self.api_integration_task(), self.page_build_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def code_review_crew(self) -> Crew:
        """Reviews the project's built site"""
        return Crew(
            agents=[self.code_reviewer()],
            tasks=[self.code_review_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def qa_crew(self) -> Crew:
        """Finds bugs in the built site"""
        return Crew(
            agents=[self.qa_tester()],
            tasks=[self.qa_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def audit_crew(self) -> Crew:
        """Finds where the built site drifts from the spec and design"""
        return Crew(
            agents=[self.consistency_auditor()],
            tasks=[self.consistency_audit_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def fix_crew(self) -> Crew:
        """Fixes one bug, inconsistency or small user change"""
        return Crew(
            agents=[self.fixer()],
            tasks=[self.fix_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def deploy_crew(self) -> Crew:
        """Writes DEPLOY.md for the packaged site"""
        return Crew(
            agents=[self.deploy_guide_writer()],
            tasks=[self.deploy_guide_task()],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def change_router_crew(self, chat_id: str) -> Crew:
        """Decides which crew handles a change request. Recalls the chat's memories, saves none."""
        return Crew(
            agents=[self.change_router()],
            tasks=[self.route_change_task()],
            process=Process.sequential,
            memory=chat_memory_read_only(chat_id),
            verbose=True,
        )

    @crew
    def chat_crew(self, chat_id: str) -> Crew:
        """Answers one chat message and decides what to do with it. Remembers the chat."""
        return Crew(
            agents=[self.chat_agent()],
            tasks=[self.chat_task()],
            process=Process.sequential,
            memory=chat_memory(chat_id),
            verbose=True,
        )
