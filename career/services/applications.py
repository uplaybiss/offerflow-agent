from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from career.models import ApplicationStatus, InterviewStatus, InterviewType
from career.repositories.applications import ApplicationRepository, InterviewRepository
from career.state_machine import validate_initial_application_status
from core.errors import ValidationError
from core.time import normalize_utc_datetime


COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


def _request_hash(operation: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"operation": operation, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _command(value: Any) -> str:
    command_id = str(value or "").strip()
    if not COMMAND_PATTERN.fullmatch(command_id):
        raise ValidationError("command_id 需为 8-100 位字母、数字或 ._:-")
    return command_id


class ApplicationService:
    def __init__(self, repository: ApplicationRepository) -> None:
        self.repository = repository

    def create(self, candidate_id: str, actor_username: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = validate_initial_application_status(str(payload.get("status", "PLANNED")))
        command_id = _command(payload.get("command_id"))
        operation = {
            "job_id": str(payload.get("job_id") or ""),
            "status": status,
            "next_action": str(payload.get("next_action") or "")[:500],
            "notes": str(payload.get("notes") or "")[:10_000],
        }
        if not operation["job_id"]:
            raise ValidationError("job_id 不能为空")
        item, replayed = self.repository.create(
            candidate_id=candidate_id,
            actor_username=actor_username,
            command_id=command_id,
            request_hash=_request_hash("create_application", operation),
            **operation,
        )
        return {"application": item, "idempotent_replay": replayed}

    def transition(self, candidate_id: str, application_id: str, actor_username: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("status") or "").upper()
        if not status:
            raise ValidationError("status 不能为空")
        try:
            expected_version = int(payload.get("version"))
        except (TypeError, ValueError):
            raise ValidationError("version 必须是整数") from None
        command_id = _command(payload.get("command_id"))
        operation = {
            "target_status": status,
            "next_action": str(payload.get("next_action") or "")[:500],
            "notes": str(payload.get("notes") or "")[:10_000],
            "expected_version": expected_version,
        }
        item, replayed = self.repository.transition(
            candidate_id=candidate_id,
            application_id=application_id,
            actor_username=actor_username,
            command_id=command_id,
            request_hash=_request_hash("transition_application", operation),
            **operation,
        )
        return {"application": item, "idempotent_replay": replayed}

    def get(self, candidate_id: str, application_id: str) -> dict[str, Any]:
        return self.repository.get(candidate_id=candidate_id, application_id=application_id)

    def list(self, candidate_id: str, status: str = "") -> list[dict[str, Any]]:
        normalized = str(status or "").upper()
        if normalized and normalized not in {item.value for item in ApplicationStatus}:
            raise ValidationError("投递状态无效")
        return self.repository.list(candidate_id=candidate_id, status=normalized)


class InterviewService:
    def __init__(self, repository: InterviewRepository) -> None:
        self.repository = repository

    @staticmethod
    def _values(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        current = current or {}
        value = lambda name, default="": payload.get(name, current.get(name, default))
        round_type = str(value("round_type", "OTHER") or "OTHER").upper()
        status = str(value("status", "PLANNED") or "PLANNED").upper()
        if round_type not in {item.value for item in InterviewType}:
            raise ValidationError("round_type 无效")
        if status not in {item.value for item in InterviewStatus}:
            raise ValidationError("status 无效")
        title = str(value("title") or "").strip()
        if not title:
            raise ValidationError("面试标题不能为空")
        try:
            scheduled_at = normalize_utc_datetime(str(value("scheduled_at") or ""))
        except ValueError:
            raise ValidationError("scheduled_at 必须是合法 ISO 时间") from None
        values = {
            "round_type": round_type,
            "title": title[:200],
            "status": status,
            "scheduled_at": scheduled_at,
            "notes": str(value("notes") or "")[:10_000],
            "result": str(value("result") or "")[:2_000],
        }
        if "round_no" in payload and payload["round_no"] not in (None, ""):
            try:
                values["round_no"] = int(payload["round_no"])
            except (TypeError, ValueError):
                raise ValidationError("round_no 必须是整数") from None
            if values["round_no"] < 1:
                raise ValidationError("round_no 必须大于 0")
        return values

    def create(self, candidate_id: str, application_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.repository.create(candidate_id=candidate_id, application_id=application_id, values=self._values(payload))

    def update(self, candidate_id: str, round_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.repository.get(candidate_id=candidate_id, round_id=round_id)
        try:
            expected_version = int(payload.get("version"))
        except (TypeError, ValueError):
            raise ValidationError("version 必须是整数") from None
        return self.repository.update(
            candidate_id=candidate_id,
            round_id=round_id,
            expected_version=expected_version,
            values=self._values(payload, current),
        )

    def list(self, candidate_id: str, application_id: str = "", upcoming_only: bool = False) -> list[dict[str, Any]]:
        return self.repository.list(candidate_id=candidate_id, application_id=application_id, upcoming_only=upcoming_only)
