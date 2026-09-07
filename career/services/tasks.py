from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from typing import Any

from career.models import TaskPriority, TaskStatus, TaskType
from career.repositories.tasks import TaskRepository
from core.errors import ValidationError
from core.time import normalize_utc_datetime, timezone_name, utc_now


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self.repository = repository

    @staticmethod
    def _values(payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        current = current or {}
        value = lambda name, default="": payload.get(name, current.get(name, default))
        title = str(value("title") or "").strip()
        if not title:
            raise ValidationError("待办标题不能为空")
        task_type = str(value("task_type", "GENERAL") or "GENERAL").upper()
        status = str(value("status", "TODO") or "TODO").upper()
        priority = str(value("priority", "P2") or "P2").upper()
        if task_type not in {item.value for item in TaskType}:
            raise ValidationError("task_type 无效")
        if status not in {item.value for item in TaskStatus}:
            raise ValidationError("status 无效")
        if priority not in {item.value for item in TaskPriority}:
            raise ValidationError("priority 无效")
        try:
            due_at = normalize_utc_datetime(str(value("due_at") or ""))
        except ValueError:
            raise ValidationError("due_at 必须是合法 ISO 时间") from None
        return {
            "job_id": str(value("job_id") or ""),
            "application_id": str(value("application_id") or ""),
            "interview_round_id": str(value("interview_round_id") or ""),
            "title": title[:200],
            "description": str(value("description") or "")[:10_000],
            "task_type": task_type,
            "status": status,
            "priority": priority,
            "due_at": due_at,
        }

    def create(self, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        values = self._values(payload)
        values.update({"origin": "MANUAL", "suggestion_key": "", "suggestion_source": "", "suggestion_payload": {}})
        return self.repository.create(candidate_id=candidate_id, values=values)

    def create_suggested(
        self,
        candidate_id: str,
        payload: dict[str, Any],
        *,
        suggestion_key: str,
        suggestion_source: str,
        suggestion_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        values = self._values(payload)
        values.update({
            "origin": "SUGGESTED",
            "suggestion_key": suggestion_key,
            "suggestion_source": suggestion_source,
            "suggestion_payload": suggestion_payload,
        })
        return self.repository.create_suggested(candidate_id=candidate_id, values=values)

    def find_by_suggestion_key(self, candidate_id: str, suggestion_key: str) -> dict[str, Any] | None:
        return self.repository.find_by_suggestion_key(candidate_id=candidate_id, suggestion_key=suggestion_key)

    def update(self, candidate_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.repository.get(candidate_id=candidate_id, task_id=task_id)
        try:
            expected_version = int(payload.get("version"))
        except (TypeError, ValueError):
            raise ValidationError("version 必须是整数") from None
        return self.repository.update(
            candidate_id=candidate_id,
            task_id=task_id,
            expected_version=expected_version,
            values=self._values(payload, current),
        )

    def list(self, candidate_id: str, status: str = "") -> list[dict[str, Any]]:
        if status and str(status).upper() not in {item.value for item in TaskStatus}:
            raise ValidationError("status 无效")
        return self.repository.list(candidate_id=candidate_id, status=str(status or "").upper())


class WorkbenchService:
    def __init__(self, jobs: Any, applications: Any, interviews: Any, tasks: TaskService) -> None:
        self.jobs = jobs
        self.applications = applications
        self.interviews = interviews
        self.tasks = tasks

    def overview(self, candidate_id: str) -> dict[str, Any]:
        jobs = self.jobs.list(candidate_id)
        applications = self.applications.list(candidate_id)
        interviews = self.interviews.list(candidate_id, upcoming_only=True)
        tasks = self.tasks.list(candidate_id)
        now = utc_now()
        try:
            interview_horizon_days = max(1, min(int(os.getenv("WORKBENCH_INTERVIEW_HORIZON_DAYS", "30")), 365))
        except ValueError:
            interview_horizon_days = 30
        interview_limit = (
            datetime.now(timezone.utc) + timedelta(days=interview_horizon_days)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        open_tasks = [item for item in tasks if item["status"] in {"TODO", "IN_PROGRESS"}]
        overdue_tasks = [item for item in open_tasks if item["due_at"] and item["due_at"] < now]
        recent_interviews = [
            item for item in interviews
            if item["status"] == "SCHEDULED"
            and item["scheduled_at"]
            and now <= item["scheduled_at"] <= interview_limit
        ][:8]
        application_counts = Counter(item["status"] for item in applications)
        funnel_stages = ("PLANNED", "APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER")
        total = len(applications)
        return {
            "timezone": timezone_name(),
            "counts": {
                "jobs": len(jobs),
                "favorites": sum(1 for item in jobs if item["is_favorite"]),
                "applications": len(applications),
                "open_tasks": len(open_tasks),
                "overdue_tasks": len(overdue_tasks),
                "upcoming_interviews": len(recent_interviews),
            },
            "application_statuses": dict(application_counts),
            "application_funnel": [
                {
                    "stage": stage,
                    "count": application_counts.get(stage, 0),
                    "share": round(application_counts.get(stage, 0) / total, 4) if total else 0,
                }
                for stage in funnel_stages
            ],
            "outcomes": {
                "REJECTED": application_counts.get("REJECTED", 0),
                "WITHDRAWN": application_counts.get("WITHDRAWN", 0),
            },
            "upcoming_interviews": recent_interviews,
            "recent_interviews": recent_interviews,
            "overdue_tasks": overdue_tasks[:12],
            "tasks": tasks[:12],
            "favorite_jobs": [item for item in jobs if item["is_favorite"]][:8],
        }
