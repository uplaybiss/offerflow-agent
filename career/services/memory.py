from __future__ import annotations

import re
from typing import Any

from career.repositories.memory import AgentMemoryRepository
from core.errors import ValidationError


CHAT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")


def validate_chat_id(value: Any) -> str:
    chat_id = str(value or "").strip()
    if not CHAT_ID_PATTERN.fullmatch(chat_id):
        raise ValidationError("chat_id 需为 8-100 位字母、数字或 ._:-")
    return chat_id


def safe_goal_summary(message: str, *, candidate_name: str = "") -> str:
    text = " ".join(str(message or "").split())
    text = EMAIL_PATTERN.sub("[EMAIL]", text)
    text = PHONE_PATTERN.sub("[PHONE]", text)
    if candidate_name:
        text = text.replace(candidate_name, "[NAME]")
    # AgentMemory intentionally stores a controlled intent label rather than a
    # chat excerpt. This prevents resume/JD free text from becoming long-lived
    # memory while retaining enough context to resume the workflow.
    labels = []
    for keywords, label in (
        (("投递", "申请", "状态", "offer", "拒绝"), "投递进度管理"),
        (("面试", "测评", "一面", "二面"), "面试安排管理"),
        (("待办", "截止", "提醒", "任务"), "求职待办管理"),
        (("技能", "匹配", "缺口", "学习"), "岗位匹配与技能缺口"),
        (("岗位", "职位", "公司", "jd", "收藏"), "岗位检索与比较"),
    ):
        if any(keyword in text.casefold() for keyword in keywords):
            labels.append(label)
    return "、".join(dict.fromkeys(labels)) or "一般求职咨询"


class AgentMemoryService:
    def __init__(self, repository: AgentMemoryRepository) -> None:
        self.repository = repository

    def get(self, candidate_id: str, chat_id: str) -> dict[str, Any] | None:
        return self.repository.get(candidate_id=candidate_id, chat_id=validate_chat_id(chat_id))

    def remember(
        self,
        candidate_id: str,
        chat_id: str,
        *,
        message: str,
        candidate_name: str = "",
        current_job_id: str = "",
        current_application_id: str = "",
        current_interview_id: str = "",
        current_task_id: str = "",
    ) -> dict[str, Any]:
        return self.repository.upsert(
            candidate_id=candidate_id,
            chat_id=validate_chat_id(chat_id),
            values={
                "current_job_id": str(current_job_id or ""),
                "current_application_id": str(current_application_id or ""),
                "current_interview_id": str(current_interview_id or ""),
                "current_task_id": str(current_task_id or ""),
                "last_user_goal": safe_goal_summary(message, candidate_name=candidate_name),
            },
        )
