from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runner import AgentRunner
from agent.service import CareerAgentService
from agentops.service import AgentOpsService, agentops_database_path
from agentops.store import AgentOpsStore
from career.repositories.applications import ApplicationRepository, InterviewRepository
from career.repositories.candidate import CandidateRepository
from career.repositories.chats import ChatRepository
from career.repositories.jobs import JobRepository
from career.repositories.memory import AgentMemoryRepository
from career.repositories.pending_actions import PendingActionRepository
from career.repositories.resumes import ResumeVersionRepository
from career.repositories.tasks import TaskRepository
from career.services.applications import ApplicationService, InterviewService
from career.services.candidate import CandidateService
from career.services.chats import ChatService
from career.services.jobs import JobService
from career.services.memory import AgentMemoryService
from career.services.pending_actions import PendingActionService
from career.services.resumes import ResumeWorkspaceService
from career.services.skill_gaps import SkillGapService
from career.services.suggestions import SuggestionService
from career.services.tasks import TaskService, WorkbenchService
from core.database import Database
from core.security import AuthService
from matching.dictionary import SkillDictionary
from matching.service import MatchingService
from parsing.llm import DashScopeLlmClient, LlmClient
from parsing.service import ParsingService
from quality.store import QualityStore, quality_database_path
from quality.eval import FixedEvalService
from quality.contract_eval import AgentContractEvalService
from quality.management import QualityManagementService


@dataclass
class Services:
    database: Database
    auth: AuthService
    candidate: CandidateService
    jobs: JobService
    applications: ApplicationService
    interviews: InterviewService
    tasks: TaskService
    workbench: WorkbenchService
    parsing: ParsingService
    matching: MatchingService
    suggestions: SuggestionService
    chats: ChatService
    resumes: ResumeWorkspaceService
    memory: AgentMemoryService
    pending_actions: PendingActionService
    skill_gaps: SkillGapService
    quality: QualityStore
    evaluation: FixedEvalService
    contract_evaluation: AgentContractEvalService
    agentops: AgentOpsService
    quality_management: QualityManagementService
    agent: Any


def build_services(
    database: Database,
    *,
    llm_client: LlmClient | None = None,
    quality_path: str | None = None,
    agentops_path: str | None = None,
    agent_runner: AgentRunner | None = None,
) -> Services:
    auth = AuthService(database)
    candidate = CandidateService(CandidateRepository(database))
    jobs = JobService(JobRepository(database))
    applications = ApplicationService(ApplicationRepository(database))
    interviews = InterviewService(InterviewRepository(database))
    tasks = TaskService(TaskRepository(database))
    memory = AgentMemoryService(AgentMemoryRepository(database))
    chats = ChatService(ChatRepository(database))
    pending_actions = PendingActionService(PendingActionRepository(database))
    llm = llm_client or DashScopeLlmClient()
    parsing = ParsingService(llm)
    matching = MatchingService(jobs, SkillDictionary(), llm)
    resumes = ResumeWorkspaceService(ResumeVersionRepository(database), jobs, matching, llm)
    skill_gaps = SkillGapService(jobs, matching)
    suggestions = SuggestionService(jobs, applications, interviews, tasks)
    quality = QualityStore(quality_path or quality_database_path())
    quality.initialize()
    agentops = AgentOpsService(AgentOpsStore(agentops_path or agentops_database_path()))
    evaluation = FixedEvalService(quality)
    contract_evaluation = AgentContractEvalService(quality)
    quality_management = QualityManagementService(quality, evaluation, contract_evaluation, agentops)
    container = Services(
        database=database,
        auth=auth,
        candidate=candidate,
        jobs=jobs,
        applications=applications,
        interviews=interviews,
        tasks=tasks,
        workbench=WorkbenchService(jobs, applications, interviews, tasks),
        parsing=parsing,
        matching=matching,
        suggestions=suggestions,
        chats=chats,
        resumes=resumes,
        memory=memory,
        pending_actions=pending_actions,
        skill_gaps=skill_gaps,
        quality=quality,
        evaluation=evaluation,
        contract_evaluation=contract_evaluation,
        agentops=agentops,
        quality_management=quality_management,
        agent=None,
    )
    container.agent = CareerAgentService(container, quality, agentops, runner=agent_runner)
    return container
