from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import os
import secrets
from typing import Any

from career.models import ApplicationStatus, PendingActionStatus
from career.repositories.pending_actions import PendingActionRepository
from career.services.memory import validate_chat_id
from core.database import json_dump
from core.errors import PermissionError, ValidationError


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

    def confirm_from_frontend(self, *, candidate_id: str, actor_username: str, action_id: str) -> dict[str, Any]:
        return self.confirm_application_transition(
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
