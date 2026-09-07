from __future__ import annotations

from typing import Any

from core.database import Database, json_dump, json_load
from core.errors import ConflictError, NotFoundError, ValidationError
from core.ids import new_id
from core.time import utc_now


class TaskRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "task_id": str(row["task_id"]),
            "candidate_id": str(row["candidate_id"]),
            "job_id": str(row["job_id"] or ""),
            "application_id": str(row["application_id"] or ""),
            "interview_round_id": str(row["interview_round_id"] or ""),
            "title": str(row["title"]),
            "description": str(row["description"]),
            "task_type": str(row["task_type"]),
            "status": str(row["status"]),
            "priority": str(row["priority"]),
            "due_at": str(row["due_at"]),
            "origin": str(row["origin"]),
            "suggestion_key": str(row["suggestion_key"]),
            "suggestion_source": str(row["suggestion_source"]),
            "suggestion_payload": json_load(row["suggestion_payload_json"], {}),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _validate_links(self, connection: Any, candidate_id: str, values: dict[str, Any]) -> None:
        job_id = values.get("job_id")
        application_id = values.get("application_id")
        round_id = values.get("interview_round_id")

        if job_id:
            job = connection.execute(
                "SELECT job_id FROM jobs WHERE candidate_id = ? AND job_id = ?",
                (candidate_id, job_id),
            ).fetchone()
            if not job:
                raise NotFoundError("关联的岗位不存在")

        application = None
        if application_id:
            application = connection.execute(
                "SELECT application_id, job_id FROM applications WHERE candidate_id = ? AND application_id = ?",
                (candidate_id, application_id),
            ).fetchone()
            if not application:
                raise NotFoundError("关联的投递不存在")

        interview = None
        if round_id:
            interview = connection.execute(
                """
                SELECT r.round_id, r.application_id, a.job_id
                FROM interview_rounds r
                JOIN applications a ON a.application_id = r.application_id
                WHERE a.candidate_id = ? AND r.round_id = ?
                """,
                (candidate_id, round_id),
            ).fetchone()
            if not interview:
                raise NotFoundError("关联的面试轮次不存在")

        if job_id and application and str(application["job_id"]) != job_id:
            raise ValidationError("job_id 与 application_id 不属于同一业务链")
        if application_id and interview and str(interview["application_id"]) != application_id:
            raise ValidationError("application_id 与 interview_round_id 不属于同一业务链")
        if job_id and interview and str(interview["job_id"]) != job_id:
            raise ValidationError("job_id 与 interview_round_id 不属于同一业务链")

    def create(self, *, candidate_id: str, values: dict[str, Any]) -> dict[str, Any]:
        task_id = new_id("TSK")
        now = utc_now()
        with self.database.transaction() as connection:
            self._validate_links(connection, candidate_id, values)
            connection.execute(
                """
                INSERT INTO job_search_tasks (
                    task_id, candidate_id, job_id, application_id,
                    interview_round_id, title, description, task_type,
                    status, priority, due_at, origin, suggestion_key,
                    suggestion_source, suggestion_payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    candidate_id,
                    values.get("job_id") or None,
                    values.get("application_id") or None,
                    values.get("interview_round_id") or None,
                    values["title"],
                    values["description"],
                    values["task_type"],
                    values["status"],
                    values["priority"],
                    values["due_at"],
                    values.get("origin", "MANUAL"),
                    values.get("suggestion_key", ""),
                    values.get("suggestion_source", ""),
                    json_dump(values.get("suggestion_payload", {})),
                    now,
                    now,
                ),
            )
        return self.get(candidate_id=candidate_id, task_id=task_id)

    def find_by_suggestion_key(self, *, candidate_id: str, suggestion_key: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM job_search_tasks WHERE candidate_id = ? AND suggestion_key = ?",
                (candidate_id, suggestion_key),
            ).fetchone()
        return self._row(row) if row else None

    def create_suggested(self, *, candidate_id: str, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        existing = self.find_by_suggestion_key(
            candidate_id=candidate_id, suggestion_key=values["suggestion_key"]
        )
        if existing:
            return existing, True
        try:
            return self.create(candidate_id=candidate_id, values=values), False
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise
            existing = self.find_by_suggestion_key(
                candidate_id=candidate_id, suggestion_key=values["suggestion_key"]
            )
            if existing:
                return existing, True
            raise

    def get(self, *, candidate_id: str, task_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM job_search_tasks WHERE candidate_id = ? AND task_id = ?",
                (candidate_id, task_id),
            ).fetchone()
        if not row:
            raise NotFoundError("待办不存在")
        return self._row(row)

    def list(self, *, candidate_id: str, status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = [candidate_id]
        where = "candidate_id = ?"
        if status:
            where += " AND status = ?"
            params.append(status)
        params.append(max(1, min(limit, 500)))
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM job_search_tasks WHERE {where}
                ORDER BY CASE status WHEN 'TODO' THEN 0 WHEN 'IN_PROGRESS' THEN 1 ELSE 2 END,
                         CASE WHEN due_at = '' THEN 1 ELSE 0 END, due_at, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def update(
        self,
        *,
        candidate_id: str,
        task_id: str,
        expected_version: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            self._validate_links(connection, candidate_id, values)
            cursor = connection.execute(
                """
                UPDATE job_search_tasks
                SET job_id = ?, application_id = ?, interview_round_id = ?,
                    title = ?, description = ?, task_type = ?, status = ?,
                    priority = ?, due_at = ?, version = version + 1, updated_at = ?
                WHERE candidate_id = ? AND task_id = ? AND version = ?
                """,
                (
                    values.get("job_id") or None,
                    values.get("application_id") or None,
                    values.get("interview_round_id") or None,
                    values["title"],
                    values["description"],
                    values["task_type"],
                    values["status"],
                    values["priority"],
                    values["due_at"],
                    now,
                    candidate_id,
                    task_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM job_search_tasks WHERE candidate_id = ? AND task_id = ?",
                    (candidate_id, task_id),
                ).fetchone()
                if not exists:
                    raise NotFoundError("待办不存在")
                raise ConflictError("待办已变化，请刷新后重试")
        return self.get(candidate_id=candidate_id, task_id=task_id)
