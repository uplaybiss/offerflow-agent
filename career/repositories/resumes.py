from __future__ import annotations

from typing import Any

from core.database import Database, json_dump, json_load
from core.errors import ConflictError, NotFoundError
from core.ids import new_id
from core.time import utc_now


class ResumeVersionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        result = {
            "resume_version_id": str(row["resume_version_id"]),
            "candidate_id": str(row["candidate_id"]),
            "source_job_id": str(row["source_job_id"] or ""),
            "title": str(row["title"]),
            "base_resume_hash": str(row["base_resume_hash"]),
            "content_text": str(row["content_text"]),
            "structured": json_load(row["structured_json"], {}),
            "created_from": str(row["created_from"]),
            "archived": bool(row["archived"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        keys = row.keys()
        if "job_company_name" in keys:
            result["job"] = {
                "company_name": str(row["job_company_name"] or ""),
                "title": str(row["job_title"] or ""),
            }
        return result

    @staticmethod
    def _validate_job(connection: Any, candidate_id: str, source_job_id: str) -> None:
        if not source_job_id:
            return
        row = connection.execute(
            "SELECT 1 FROM jobs WHERE candidate_id = ? AND job_id = ?",
            (candidate_id, source_job_id),
        ).fetchone()
        if not row:
            raise NotFoundError("关联岗位不存在")

    def create(self, *, candidate_id: str, values: dict[str, Any]) -> dict[str, Any]:
        version_id = new_id("RSV")
        now = utc_now()
        with self.database.transaction() as connection:
            self._validate_job(connection, candidate_id, values["source_job_id"])
            connection.execute(
                """
                INSERT INTO resume_versions (
                    resume_version_id, candidate_id, source_job_id, title,
                    base_resume_hash, content_text, structured_json, created_from,
                    archived, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
                """,
                (
                    version_id, candidate_id, values["source_job_id"] or None,
                    values["title"], values["base_resume_hash"], values["content_text"],
                    json_dump(values["structured"]), values["created_from"], now, now,
                ),
            )
        return self.get(candidate_id=candidate_id, resume_version_id=version_id)

    def get(self, *, candidate_id: str, resume_version_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT rv.*, j.company_name AS job_company_name, j.title AS job_title
                FROM resume_versions rv
                LEFT JOIN jobs j ON j.job_id = rv.source_job_id
                WHERE rv.candidate_id = ? AND rv.resume_version_id = ?
                """,
                (candidate_id, resume_version_id),
            ).fetchone()
        if not row:
            raise NotFoundError("简历版本不存在")
        return self._row(row)

    def list(self, *, candidate_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT rv.*, j.company_name AS job_company_name, j.title AS job_title
                FROM resume_versions rv
                LEFT JOIN jobs j ON j.job_id = rv.source_job_id
                WHERE rv.candidate_id = ? AND (? = 1 OR rv.archived = 0)
                ORDER BY rv.updated_at DESC, rv.resume_version_id DESC
                """,
                (candidate_id, int(include_archived)),
            ).fetchall()
        return [self._row(row) for row in rows]

    def update(
        self,
        *,
        candidate_id: str,
        resume_version_id: str,
        expected_version: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            self._validate_job(connection, candidate_id, values["source_job_id"])
            cursor = connection.execute(
                """
                UPDATE resume_versions
                SET source_job_id = ?, title = ?, content_text = ?, structured_json = ?,
                    archived = ?, version = version + 1, updated_at = ?
                WHERE candidate_id = ? AND resume_version_id = ? AND version = ?
                """,
                (
                    values["source_job_id"] or None, values["title"], values["content_text"],
                    json_dump(values["structured"]), int(values["archived"]), utc_now(),
                    candidate_id, resume_version_id, expected_version,
                ),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM resume_versions WHERE candidate_id = ? AND resume_version_id = ?",
                    (candidate_id, resume_version_id),
                ).fetchone()
                if not exists:
                    raise NotFoundError("简历版本不存在")
                raise ConflictError("简历版本已变化，请刷新后重试")
        return self.get(candidate_id=candidate_id, resume_version_id=resume_version_id)

