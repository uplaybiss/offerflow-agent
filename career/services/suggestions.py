from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import hashlib
import os
from typing import Any

from core.errors import NotFoundError
from core.time import configured_timezone, utc_now


SUGGESTION_RULE_VERSION = "task_suggestion_v1"


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(maximum, max(minimum, value))


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=configured_timezone())
    return parsed.astimezone(timezone.utc)


def _suggestion_key(source_type: str, source_id: str) -> str:
    raw = f"{SUGGESTION_RULE_VERSION}|{source_type}|{source_id}"
    return f"sug_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


class SuggestionService:
    def __init__(self, jobs: Any, applications: Any, interviews: Any, tasks: Any) -> None:
        self.jobs = jobs
        self.applications = applications
        self.interviews = interviews
        self.tasks = tasks

    def config(self) -> dict[str, Any]:
        return {
            "version": SUGGESTION_RULE_VERSION,
            "job_deadline_horizon_days": _bounded_int("SUGGESTION_JOB_HORIZON_DAYS", 45, 1, 365),
            "job_deadline_lead_days": _bounded_int("SUGGESTION_JOB_LEAD_DAYS", 3, 0, 30),
            "event_horizon_days": _bounded_int("SUGGESTION_EVENT_HORIZON_DAYS", 30, 1, 180),
            "event_lead_hours": _bounded_int("SUGGESTION_EVENT_LEAD_HOURS", 24, 0, 168),
            "persistence": "preview_until_user_accepts",
        }

    @staticmethod
    def _build(
        *,
        source_type: str,
        source_id: str,
        event_at: str,
        task: dict[str, Any],
        trace_inputs: dict[str, Any],
        rule: str,
    ) -> dict[str, Any]:
        return {
            "suggestion_key": _suggestion_key(source_type, source_id),
            "source": {"type": source_type, "id": source_id, "event_at": event_at},
            "task_preview": task,
            "trace": {
                "rule_version": SUGGESTION_RULE_VERSION,
                "rule": rule,
                "inputs": trace_inputs,
            },
            "persisted": False,
            "requires_confirmation": True,
        }

    def _all(self, candidate_id: str) -> list[dict[str, Any]]:
        config = self.config()
        jobs = self.jobs.list(candidate_id)
        applications = self.applications.list(candidate_id)
        interviews = self.interviews.list(candidate_id)
        app_by_job = {item["job_id"]: item for item in applications}
        app_by_id = {item["application_id"]: item for item in applications}
        now = datetime.now(timezone.utc)
        local_today = datetime.now(configured_timezone()).date()
        suggestions: list[dict[str, Any]] = []

        for job in jobs:
            application = app_by_job.get(job["job_id"])
            if job["effective_status"] != "ACTIVE" or (application and application["status"] != "PLANNED"):
                continue
            try:
                deadline = date.fromisoformat(job["deadline"])
            except (TypeError, ValueError):
                continue
            days_left = (deadline - local_today).days
            if days_left < 0 or days_left > config["job_deadline_horizon_days"]:
                continue
            due_local = datetime.combine(
                deadline - timedelta(days=config["job_deadline_lead_days"]),
                time(hour=18),
                tzinfo=configured_timezone(),
            )
            due_at = _utc_text(due_local)
            suggestions.append(self._build(
                source_type="JOB_DEADLINE",
                source_id=job["job_id"],
                event_at=job["deadline"],
                task={
                    "title": f"准备投递 {job['company_name']} · {job['title']}",
                    "description": f"岗位截止 {job['deadline']}；请核对材料并由你决定是否投递。",
                    "task_type": "APPLICATION",
                    "status": "TODO",
                    "priority": "P1" if days_left <= 7 else "P2",
                    "due_at": due_at,
                    "job_id": job["job_id"],
                    "application_id": application["application_id"] if application else "",
                    "interview_round_id": "",
                },
                trace_inputs={
                    "job_id": job["job_id"], "deadline": job["deadline"],
                    "effective_status": job["effective_status"],
                    "application_status": application["status"] if application else None,
                    "lead_days": config["job_deadline_lead_days"],
                },
                rule="active_job_deadline_requires_user_planning",
            ))

        event_limit = now + timedelta(days=config["event_horizon_days"])
        for interview in interviews:
            scheduled = _parse_utc(interview["scheduled_at"])
            if interview["status"] != "SCHEDULED" or not scheduled or scheduled < now or scheduled > event_limit:
                continue
            application = app_by_id.get(interview["application_id"])
            if not application:
                continue
            job = application.get("job") or {}
            is_assessment = interview["round_type"] == "ASSESSMENT"
            source_type = "ASSESSMENT_TIME" if is_assessment else "INTERVIEW_TIME"
            task_type = "ASSESSMENT" if is_assessment else "INTERVIEW"
            label = "测评" if is_assessment else "面试"
            due_at = _utc_text(scheduled - timedelta(hours=config["event_lead_hours"]))
            suggestions.append(self._build(
                source_type=source_type,
                source_id=interview["round_id"],
                event_at=interview["scheduled_at"],
                task={
                    "title": f"准备{label} {job.get('company_name', '')} · {interview['title']}".strip(),
                    "description": f"{label}时间 {interview['scheduled_at']}；根据已记录轮次生成。",
                    "task_type": task_type,
                    "status": "TODO",
                    "priority": "P1",
                    "due_at": due_at,
                    "job_id": application["job_id"],
                    "application_id": application["application_id"],
                    "interview_round_id": interview["round_id"],
                },
                trace_inputs={
                    "round_id": interview["round_id"], "round_type": interview["round_type"],
                    "scheduled_at": interview["scheduled_at"], "status": interview["status"],
                    "lead_hours": config["event_lead_hours"],
                },
                rule="scheduled_assessment_requires_preparation" if is_assessment else "scheduled_interview_requires_preparation",
            ))

        return sorted(suggestions, key=lambda item: (item["task_preview"]["due_at"], item["suggestion_key"]))

    def list(self, candidate_id: str) -> dict[str, Any]:
        retained = {
            item["suggestion_key"]
            for item in self.tasks.list(candidate_id)
            if item.get("suggestion_key")
        }
        items = [item for item in self._all(candidate_id) if item["suggestion_key"] not in retained]
        return {"config": self.config(), "items": items}

    def accept(self, candidate_id: str, suggestion_key: str) -> dict[str, Any]:
        existing = self.tasks.find_by_suggestion_key(candidate_id, suggestion_key)
        if existing:
            return {"task": existing, "idempotent_replay": True}
        suggestion = next((item for item in self._all(candidate_id) if item["suggestion_key"] == suggestion_key), None)
        if not suggestion:
            raise NotFoundError("建议不存在、已失效或不属于当前候选人")
        task, replayed = self.tasks.create_suggested(
            candidate_id,
            suggestion["task_preview"],
            suggestion_key=suggestion["suggestion_key"],
            suggestion_source=suggestion["source"]["type"],
            suggestion_payload={"source": suggestion["source"], "trace": suggestion["trace"]},
        )
        return {"task": task, "idempotent_replay": replayed}
