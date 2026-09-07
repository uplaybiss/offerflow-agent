from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from career.models import (
    ApplicationStatus,
    InterviewStatus,
    InterviewType,
    JobStatus,
    SourceType,
    TaskPriority,
    TaskStatus,
    TaskType,
)


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CandidateUpdateBody(StrictBody):
    candidate_id: str | None = None
    owner_username: str | None = None
    version: int = Field(ge=1)
    full_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    graduation_year: str | None = Field(default=None, max_length=20)
    degree: str | None = Field(default=None, max_length=100)
    target_roles: list[str] | None = Field(default=None, max_length=100)
    preferred_cities: list[str] | None = Field(default=None, max_length=100)
    excluded_companies: list[str] | None = Field(default=None, max_length=100)
    preferences: dict[str, Any] | None = None
    skills: list[str] | None = Field(default=None, max_length=500)
    current_resume_text: str | None = Field(default=None, max_length=500_000)
    current_resume_parsed: dict[str, Any] | None = None
    current_resume_filename: str | None = Field(default=None, max_length=255)
    current_resume_sha256: str | None = None
    resume_updated_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class JobCreateBody(StrictBody):
    company_name: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    employment_type: str = Field(default="", max_length=100)
    recruitment_cycle: str = Field(default="", max_length=100)
    graduation_year: str = Field(default="", max_length=20)
    deadline: str = Field(default="", max_length=10)
    status: JobStatus = JobStatus.ACTIVE
    description_text: str = Field(default="", max_length=500_000)
    required_skills: list[str] = Field(default_factory=list, max_length=500)
    preferred_skills: list[str] = Field(default_factory=list, max_length=500)
    is_favorite: bool = False
    source_type: SourceType = SourceType.MANUAL
    source_name: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2_000)
    external_job_id: str = Field(default="", max_length=200)
    company_career_url: str = Field(default="", max_length=2_000)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class JobUpdateBody(StrictBody):
    version: int = Field(ge=1)
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    employment_type: str | None = Field(default=None, max_length=100)
    recruitment_cycle: str | None = Field(default=None, max_length=100)
    graduation_year: str | None = Field(default=None, max_length=20)
    deadline: str | None = Field(default=None, max_length=10)
    status: JobStatus | None = None
    description_text: str | None = Field(default=None, max_length=500_000)
    required_skills: list[str] | None = Field(default=None, max_length=500)
    preferred_skills: list[str] | None = Field(default=None, max_length=500)
    is_favorite: bool | None = None
    source_type: SourceType | None = None
    source_name: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2_000)
    external_job_id: str | None = Field(default=None, max_length=200)
    company_career_url: str | None = Field(default=None, max_length=2_000)
    source_metadata: dict[str, Any] | None = None


class ApplicationCreateBody(StrictBody):
    job_id: str = Field(min_length=1, max_length=100)
    status: ApplicationStatus = ApplicationStatus.PLANNED
    command_id: str = Field(min_length=8, max_length=100)
    next_action: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=10_000)


class ApplicationTransitionBody(StrictBody):
    status: ApplicationStatus
    version: int = Field(ge=1)
    command_id: str = Field(min_length=8, max_length=100)
    next_action: str = Field(default="", max_length=500)
    notes: str = Field(default="", max_length=10_000)


class InterviewCreateBody(StrictBody):
    round_no: int | None = Field(default=None, ge=1)
    round_type: InterviewType = InterviewType.OTHER
    title: str = Field(min_length=1, max_length=200)
    status: InterviewStatus = InterviewStatus.PLANNED
    scheduled_at: str = Field(default="", max_length=50)
    notes: str = Field(default="", max_length=10_000)
    result: str = Field(default="", max_length=2_000)


class InterviewUpdateBody(StrictBody):
    round_id: str | None = None
    application_id: str | None = None
    version: int = Field(ge=1)
    round_no: int | None = Field(default=None, ge=1)
    round_type: InterviewType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: InterviewStatus | None = None
    scheduled_at: str | None = Field(default=None, max_length=50)
    notes: str | None = Field(default=None, max_length=10_000)
    result: str | None = Field(default=None, max_length=2_000)
    completed_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TaskCreateBody(StrictBody):
    job_id: str = Field(default="", max_length=100)
    application_id: str = Field(default="", max_length=100)
    interview_round_id: str = Field(default="", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    task_type: TaskType = TaskType.GENERAL
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.P2
    due_at: str = Field(default="", max_length=50)


class TaskUpdateBody(StrictBody):
    task_id: str | None = None
    candidate_id: str | None = None
    version: int = Field(ge=1)
    job_id: str | None = Field(default=None, max_length=100)
    application_id: str | None = Field(default=None, max_length=100)
    interview_round_id: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    task_type: TaskType | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: str | None = Field(default=None, max_length=50)
    origin: Literal["MANUAL", "SUGGESTED"] | None = None
    suggestion_key: str | None = None
    suggestion_source: str | None = None
    suggestion_payload: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TextPreviewBody(StrictBody):
    text: str = Field(min_length=1, max_length=500_000)


class CompareJobsBody(StrictBody):
    job_ids: list[str]


class HistoryMessage(StrictBody):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class AgentChatBody(StrictBody):
    chat_id: str = Field(min_length=8, max_length=100)
    message: str = Field(min_length=1, max_length=20_000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=30)
    current_job_id: str = Field(default="", max_length=100)
    current_application_id: str = Field(default="", max_length=100)
    current_interview_id: str = Field(default="", max_length=100)
    current_task_id: str = Field(default="", max_length=100)


def body_dict(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(mode="json", exclude_none=True)
