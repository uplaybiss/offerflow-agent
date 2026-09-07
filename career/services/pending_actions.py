from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
from typing import Any

from career.models import (
    ApplicationStatus,
    InterviewType,
    PendingActionStatus,
    TaskPriority,
    TaskType,
)
from career.repositories.pending_actions import PendingActionRepository
from career.services.memory import validate_chat_id
from core.database import json_dump
from core.errors import PermissionError, ValidationError
from core.time import normalize_utc_datetime


class PendingActionService:
    def __init__(self, repository: PendingActionRepository) -> None:
        self.repository = repository

    @staticmethod
    def _expiry(seconds: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")

    def propose_application_transition(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        chat_id: str,
        application_id: str,
        target_status: str,
        expected_version: Any,
        next_action: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        application_id = str(application_id or "").strip()
        target_status = str(target_status or "").upper()
        if not application_id:
            raise ValidationError("application_id 不能为空")
        if target_status not in {item.value for item in ApplicationStatus}:
            raise ValidationError("目标投递状态无效")
        try:
            expected = int(expected_version)
        except (TypeError, ValueError):
            raise ValidationError("expected_version 必须是整数") from None
        if expected < 1:
            raise ValidationError("expected_version 必须大于 0")
        payload = {
            "application_id": application_id,
            "target_status": target_status,
            "expected_version": expected,
            "next_action": str(next_action or "")[:500],
            "notes": str(notes or "")[:10_000],
        }
        request_hash = hashlib.sha256(
            json_dump({"action_type": "APPLICATION_TRANSITION", "payload": payload}).encode("utf-8")
        ).hexdigest()
        try:
            ttl = max(60, min(int(os.getenv("PENDING_ACTION_TTL_SECONDS", "900")), 86_400))
        except ValueError:
            ttl = 900
        action, replayed = self.repository.create_application_transition(
            candidate_id=candidate_id,
            actor_username=actor_username,
            chat_id=validate_chat_id(chat_id),
            payload=payload,
            request_hash=request_hash,
            expires_at=self._expiry(ttl),
        )
        return {"action": action, "idempotent_replay": replayed}

    def confirm_application_transition(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        action_id: str,
        confirmation_grant: str,
    ) -> dict[str, Any]:
        if not confirmation_grant:
            raise PermissionError("确认授权只能由服务端确认请求生成")
        action, application, replayed = self.repository.confirm_and_execute(
            candidate_id=candidate_id,
            actor_username=actor_username,
            action_id=str(action_id or ""),
            raw_grant=confirmation_grant,
            grant_expires_at=self._expiry(60),
        )
        return {"action": action, "application": application, "idempotent_replay": replayed}

    def propose_interview_progression(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        chat_id: str,
        application_id: str,
        current_round_id: str,
        current_round_result: str,
        next_round_type: str,
        next_round_title: str,
        next_round_scheduled_at: str,
        task_title: str,
        task_due_at: str,
        expected_application_version: Any,
        expected_interview_version: Any,
    ) -> dict[str, Any]:
        application_id = str(application_id or "").strip()
        current_round_id = str(current_round_id or "").strip()
        next_round_title = str(next_round_title or "").strip()
        task_title = str(task_title or "").strip()
        if not application_id or not current_round_id:
            raise ValidationError("application_id 和 current_round_id 不能为空")
        if not next_round_title or not task_title:
            raise ValidationError("下一轮面试标题和准备任务标题不能为空")
        normalized_type = str(next_round_type or "").upper()
        if normalized_type not in {item.value for item in InterviewType}:
            raise ValidationError("next_round_type 无效")
        try:
            expected_application = int(expected_application_version)
            expected_interview = int(expected_interview_version)
        except (TypeError, ValueError):
            raise ValidationError("Application 和 Interview version 必须是整数") from None
        if expected_application < 1 or expected_interview < 1:
            raise ValidationError("Application 和 Interview version 必须大于 0")
        if not str(next_round_scheduled_at or "").strip() or not str(task_due_at or "").strip():
            raise ValidationError("下一轮时间和准备任务截止时间必须明确，歧义时间应先澄清")
        try:
            scheduled_at = normalize_utc_datetime(str(next_round_scheduled_at))
            due_at = normalize_utc_datetime(str(task_due_at))
        except ValueError:
            raise ValidationError("下一轮时间和任务截止时间必须是合法 ISO 时间") from None
        if due_at > scheduled_at:
            raise ValidationError("准备任务截止时间不能晚于下一轮面试时间")
        payload = {
            "application_id": application_id,
            "current_round_id": current_round_id,
            "current_round_result": str(current_round_result or "")[:2_000],
            "next_round_type": normalized_type,
            "next_round_title": next_round_title[:200],
            "next_round_scheduled_at": scheduled_at,
            "task_title": task_title[:200],
            "task_due_at": due_at,
            "expected_application_version": expected_application,
            "expected_interview_version": expected_interview,
        }
        request_hash = hashlib.sha256(
            json_dump({"action_type": "INTERVIEW_PROGRESSION", "payload": payload}).encode("utf-8")
        ).hexdigest()
        try:
            ttl = max(60, min(int(os.getenv("PENDING_ACTION_TTL_SECONDS", "900")), 86_400))
        except ValueError:
            ttl = 900
        action, replayed = self.repository.create_interview_progression(
            candidate_id=candidate_id,
            actor_username=actor_username,
            chat_id=validate_chat_id(chat_id),
            payload=payload,
            request_hash=request_hash,
            expires_at=self._expiry(ttl),
        )
        return {"action": action, "idempotent_replay": replayed}

    def confirm_pending_action(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        action_id: str,
        confirmation_grant: str,
    ) -> dict[str, Any]:
        return self.confirm_application_transition(
            candidate_id=candidate_id,
            actor_username=actor_username,
            action_id=action_id,
            confirmation_grant=confirmation_grant,
        )

    def propose_task_create(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        chat_id: str,
        title: str,
        task_type: str,
        due_at: str,
        priority: str = "P2",
        description: str = "",
        job_id: str = "",
        application_id: str = "",
        interview_round_id: str = "",
    ) -> dict[str, Any]:
        normalized_title = str(title or "").strip()
        normalized_type = str(task_type or "GENERAL").upper()
        normalized_priority = str(priority or "P2").upper()
        if not normalized_title:
            raise ValidationError("待办标题不能为空")
        if normalized_type not in {item.value for item in TaskType}:
            raise ValidationError("待办类型无效")
        if normalized_priority not in {item.value for item in TaskPriority}:
            raise ValidationError("待办优先级无效")
        if not str(due_at or "").strip():
            raise ValidationError("待办截止时间必须明确；使用默认时刻时也要在确认卡中展示")
        try:
            normalized_due_at = normalize_utc_datetime(str(due_at))
        except ValueError:
            raise ValidationError("待办截止时间必须是合法 ISO 时间") from None
        payload = {
            "title": normalized_title[:200],
            "task_type": normalized_type,
            "due_at": normalized_due_at,
            "priority": normalized_priority,
            "description": str(description or "")[:10_000],
            "job_id": str(job_id or "").strip(),
            "application_id": str(application_id or "").strip(),
            "interview_round_id": str(interview_round_id or "").strip(),
        }
        request_hash = hashlib.sha256(
            json_dump({"action_type": "TASK_CREATE", "payload": payload}).encode("utf-8")
        ).hexdigest()
        try:
            ttl = max(60, min(int(os.getenv("PENDING_ACTION_TTL_SECONDS", "900")), 86_400))
        except ValueError:
            ttl = 900
        action, replayed = self.repository.create_task(
            candidate_id=candidate_id,
            actor_username=actor_username,
            chat_id=validate_chat_id(chat_id),
            payload=payload,
            request_hash=request_hash,
            expires_at=self._expiry(ttl),
        )
        return {"action": action, "idempotent_replay": replayed}

    def confirm_from_frontend(self, *, candidate_id: str, actor_username: str, action_id: str) -> dict[str, Any]:
        return self.confirm_pending_action(
            candidate_id=candidate_id,
            actor_username=actor_username,
            action_id=action_id,
            confirmation_grant=secrets.token_urlsafe(32),
        )

    def list(self, candidate_id: str, status: str = "") -> list[dict[str, Any]]:
        normalized = str(status or "").upper()
        if normalized and normalized not in {item.value for item in PendingActionStatus}:
            raise ValidationError("待确认动作状态无效")
        return self.repository.list(candidate_id=candidate_id, status=normalized)

    def get(self, candidate_id: str, action_id: str) -> dict[str, Any]:
        return self.repository.get(candidate_id=candidate_id, action_id=action_id)

    def cancel(self, *, candidate_id: str, actor_username: str, action_id: str) -> dict[str, Any]:
        return self.repository.cancel(
            candidate_id=candidate_id,
            actor_username=actor_username,
            action_id=action_id,
        )
