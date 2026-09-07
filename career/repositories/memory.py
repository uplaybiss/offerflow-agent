from __future__ import annotations

from typing import Any

from core.database import Database
from core.errors import NotFoundError, ValidationError
from core.ids import new_id
from core.time import utc_now


class AgentMemoryRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "memory_id": str(row["memory_id"]),
            "candidate_id": str(row["candidate_id"]),
            "chat_id": str(row["chat_id"]),
            "current_job_id": str(row["current_job_id"] or ""),
            "current_application_id": str(row["current_application_id"] or ""),
            "current_interview_id": str(row["current_interview_id"] or ""),
            "current_task_id": str(row["current_task_id"] or ""),
            "last_user_goal": str(row["last_user_goal"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _validate_refs(connection: Any, candidate_id: str, values: dict[str, str]) -> None:
        job_id = values.get("current_job_id") or ""
        application_id = values.get("current_application_id") or ""
        interview_id = values.get("current_interview_id") or ""
        task_id = values.get("current_task_id") or ""

        if job_id:
            row = connection.execute(
                "SELECT 1 FROM jobs WHERE candidate_id = ? AND job_id = ?",
                (candidate_id, job_id),
            ).fetchone()
            if not row:
                raise NotFoundError("AgentMemory 关联岗位不存在")

        application = None
        if application_id:
            application = connection.execute(
                "SELECT job_id FROM applications WHERE candidate_id = ? AND application_id = ?",
                (candidate_id, application_id),
            ).fetchone()
            if not application:
                raise NotFoundError("AgentMemory 关联投递不存在")
            if job_id and str(application["job_id"]) != job_id:
                raise ValidationError("AgentMemory 的岗位与投递不属于同一业务链")

        interview = None
        if interview_id:
            interview = connection.execute(
                """
                SELECT r.application_id, a.job_id
                FROM interview_rounds r
                JOIN applications a ON a.application_id = r.application_id
                WHERE a.candidate_id = ? AND r.round_id = ?
                """,
                (candidate_id, interview_id),
            ).fetchone()
            if not interview:
                raise NotFoundError("AgentMemory 关联面试不存在")
            if application_id and str(interview["application_id"]) != application_id:
                raise ValidationError("AgentMemory 的投递与面试不属于同一业务链")
            if job_id and str(interview["job_id"]) != job_id:
                raise ValidationError("AgentMemory 的岗位与面试不属于同一业务链")

        if task_id:
            task = connection.execute(
                """
                SELECT job_id, application_id, interview_round_id
                FROM job_search_tasks
                WHERE candidate_id = ? AND task_id = ?
                """,
                (candidate_id, task_id),
            ).fetchone()
            if not task:
                raise NotFoundError("AgentMemory 关联待办不存在")
            comparisons = (
                (job_id, str(task["job_id"] or ""), "岗位"),
                (application_id, str(task["application_id"] or ""), "投递"),
                (interview_id, str(task["interview_round_id"] or ""), "面试"),
            )
            for selected, linked, label in comparisons:
                if selected and linked and selected != linked:
                    raise ValidationError(f"AgentMemory 的{label}与待办不属于同一业务链")

    def get(self, *, candidate_id: str, chat_id: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_memories WHERE candidate_id = ? AND chat_id = ?",
                (candidate_id, chat_id),
            ).fetchone()
        return self._row(row) if row else None

    def upsert(self, *, candidate_id: str, chat_id: str, values: dict[str, str]) -> dict[str, Any]:
        now = utc_now()
        memory_id = new_id("MEM")
        with self.database.transaction() as connection:
            self._validate_refs(connection, candidate_id, values)
            connection.execute(
                """
                INSERT INTO agent_memories (
                    memory_id, candidate_id, chat_id, current_job_id,
                    current_application_id, current_interview_id, current_task_id,
                    last_user_goal, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id, chat_id) DO UPDATE SET
                    current_job_id = excluded.current_job_id,
                    current_application_id = excluded.current_application_id,
                    current_interview_id = excluded.current_interview_id,
                    current_task_id = excluded.current_task_id,
                    last_user_goal = excluded.last_user_goal,
                    version = agent_memories.version + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    memory_id,
                    candidate_id,
                    chat_id,
                    values.get("current_job_id") or None,
                    values.get("current_application_id") or None,
                    values.get("current_interview_id") or None,
                    values.get("current_task_id") or None,
                    values.get("last_user_goal", ""),
                    now,
                    now,
                ),
            )
        result = self.get(candidate_id=candidate_id, chat_id=chat_id)
        assert result is not None
        return result
