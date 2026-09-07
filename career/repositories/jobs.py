from __future__ import annotations

from typing import Any

from core.database import Database, json_dump, json_load
from core.errors import ConflictError, NotFoundError
from core.ids import new_id
from core.time import utc_now


class JobRepository:
    _UPDATE_FIELDS = {
        "company_name",
        "title",
        "location",
        "employment_type",
        "recruitment_cycle",
        "graduation_year",
        "deadline",
        "status",
        "description_text",
        "required_skills_json",
        "preferred_skills_json",
        "is_favorite",
        "favorited_at",
        "source_type",
        "source_name",
        "source_url",
        "external_job_id",
        "company_career_url",
        "source_metadata_json",
        "content_sha256",
        "last_seen_at",
    }

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def row(row: Any) -> dict[str, Any]:
        return {
            "job_id": str(row["job_id"]),
            "candidate_id": str(row["candidate_id"]),
            "company_name": str(row["company_name"]),
            "title": str(row["title"]),
            "location": str(row["location"]),
            "employment_type": str(row["employment_type"]),
            "recruitment_cycle": str(row["recruitment_cycle"]),
            "graduation_year": str(row["graduation_year"]),
            "deadline": str(row["deadline"]),
            "status": str(row["status"]),
            "description_text": str(row["description_text"]),
            "required_skills": json_load(row["required_skills_json"], []),
            "preferred_skills": json_load(row["preferred_skills_json"], []),
            "is_favorite": bool(row["is_favorite"]),
            "favorited_at": str(row["favorited_at"]),
            "source_type": str(row["source_type"]),
            "source_name": str(row["source_name"]),
            "source_url": str(row["source_url"]),
            "external_job_id": str(row["external_job_id"]),
            "company_career_url": str(row["company_career_url"]),
            "source_metadata": json_load(row["source_metadata_json"], {}),
            "content_sha256": str(row["content_sha256"]),
            "first_seen_at": str(row["first_seen_at"]),
            "last_seen_at": str(row["last_seen_at"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def create(self, *, candidate_id: str, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        job_id = new_id("JOB")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        job_id, candidate_id, company_name, title, location,
                        employment_type, recruitment_cycle, graduation_year,
                        deadline, status, description_text,
                        required_skills_json, preferred_skills_json,
                        is_favorite, favorited_at, source_type, source_name,
                        source_url, external_job_id, company_career_url,
                        source_metadata_json, content_sha256, first_seen_at,
                        last_seen_at, created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        job_id,
                        candidate_id,
                        values["company_name"],
                        values["title"],
                        values["location"],
                        values["employment_type"],
                        values["recruitment_cycle"],
                        values["graduation_year"],
                        values["deadline"],
                        values["status"],
                        values["description_text"],
                        json_dump(values["required_skills"]),
                        json_dump(values["preferred_skills"]),
                        1 if values["is_favorite"] else 0,
                        now if values["is_favorite"] else "",
                        values["source_type"],
                        values["source_name"],
                        values["source_url"],
                        values["external_job_id"],
                        values["company_career_url"],
                        json_dump(values["source_metadata"]),
                        values["content_sha256"],
                        now,
                        now,
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ConflictError("该岗位已存在，请更新原记录") from exc
            raise
        return self.get(candidate_id=candidate_id, job_id=job_id)

    def get(self, *, candidate_id: str, job_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE candidate_id = ? AND job_id = ?",
                (candidate_id, job_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("岗位不存在")
        return self.row(row)

    def list(
        self,
        *,
        candidate_id: str,
        search: str = "",
        status: str = "",
        as_of_date: str = "",
        favorite_only: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses = ["candidate_id = ?"]
        params: list[Any] = [candidate_id]
        if search:
            clauses.append("(company_name LIKE ? OR title LIKE ? OR location LIKE ? OR description_text LIKE ?)")
            pattern = f"%{search}%"
            params.extend([pattern, pattern, pattern, pattern])
        if status == "EXPIRED":
            clauses.append("(status = 'EXPIRED' OR (status = 'ACTIVE' AND deadline <> '' AND deadline < ?))")
            params.append(as_of_date)
        elif status == "ACTIVE":
            clauses.append("(status = 'ACTIVE' AND (deadline = '' OR deadline >= ?))")
            params.append(as_of_date)
        elif status:
            clauses.append("status = ?")
            params.append(status)
        if favorite_only:
            clauses.append("is_favorite = 1")
        params.append(max(1, min(limit, 500)))
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY is_favorite DESC, updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self.row(row) for row in rows]

    def update(
        self,
        *,
        candidate_id: str,
        job_id: str,
        expected_version: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        unknown = set(changes) - self._UPDATE_FIELDS
        if unknown:
            raise ValueError(f"unsupported job fields: {sorted(unknown)}")
        if not changes:
            return self.get(candidate_id=candidate_id, job_id=job_id)
        now = utc_now()
        assignments = [f"{name} = ?" for name in changes]
        values = list(changes.values())
        assignments.extend(["version = version + 1", "updated_at = ?"])
        values.extend([now, candidate_id, job_id, expected_version])
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    f"UPDATE jobs SET {', '.join(assignments)} WHERE candidate_id = ? AND job_id = ? AND version = ?",
                    values,
                )
                if cursor.rowcount != 1:
                    exists = connection.execute(
                        "SELECT 1 FROM jobs WHERE candidate_id = ? AND job_id = ?",
                        (candidate_id, job_id),
                    ).fetchone()
                    if not exists:
                        raise NotFoundError("岗位不存在")
                    raise ConflictError("岗位已变化，请刷新后重试")
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ConflictError("更新后与已有岗位重复") from exc
            raise
        return self.get(candidate_id=candidate_id, job_id=job_id)
