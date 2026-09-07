from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class SourceType(str, Enum):
    MANUAL = "MANUAL"
    JD_PASTE = "JD_PASTE"
    COMPANY_CAREER = "COMPANY_CAREER"


class ApplicationStatus(str, Enum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


APPLICATION_TRANSITIONS: dict[str, set[str]] = {
    ApplicationStatus.PLANNED.value: {
        ApplicationStatus.APPLIED.value,
        ApplicationStatus.WITHDRAWN.value,
    },
    ApplicationStatus.APPLIED.value: {
        ApplicationStatus.ASSESSMENT.value,
        ApplicationStatus.INTERVIEW.value,
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.WITHDRAWN.value,
    },
    ApplicationStatus.ASSESSMENT.value: {
        ApplicationStatus.INTERVIEW.value,
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.WITHDRAWN.value,
    },
    ApplicationStatus.INTERVIEW.value: {
        ApplicationStatus.OFFER.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.WITHDRAWN.value,
    },
    ApplicationStatus.OFFER.value: {ApplicationStatus.WITHDRAWN.value},
    ApplicationStatus.REJECTED.value: set(),
    ApplicationStatus.WITHDRAWN.value: set(),
}


class InterviewStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InterviewType(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    TECHNICAL = "TECHNICAL"
    HR = "HR"
    MANAGER = "MANAGER"
    OTHER = "OTHER"


class TaskStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskType(str, Enum):
    GENERAL = "GENERAL"
    APPLICATION = "APPLICATION"
    ASSESSMENT = "ASSESSMENT"
    INTERVIEW = "INTERVIEW"
    MATERIAL = "MATERIAL"
    FOLLOW_UP = "FOLLOW_UP"


class TaskPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class PendingActionStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class PendingActionType(str, Enum):
    APPLICATION_TRANSITION = "APPLICATION_TRANSITION"
    INTERVIEW_PROGRESSION = "INTERVIEW_PROGRESSION"
    TASK_CREATE = "TASK_CREATE"
