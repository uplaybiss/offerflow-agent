from __future__ import annotations

from typing import Any

from core.database import Database, json_dump, json_load
from core.errors import ConflictError
from core.ids import new_id
from core.time import utc_now


class CandidateRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "candidate_id": str(row["candidate_id"]),
            "owner_username": str(row["owner_username"]),
            "full_name": str(row["full_name"]),
            "email": str(row["email"]),
            "phone": str(row["phone"]),
            "graduation_year": str(row["graduation_year"]),
            "degree": str(row["degree"]),
            "target_roles": json_load(row["target_roles_json"], []),
            "preferred_cities": json_load(row["preferred_cities_json"], []),
            "excluded_companies": json_load(row["excluded_companies_json"], []),
            "preferences": json_load(row["preferences_json"], {}),
            "skills": json_load(row["skills_json"], []),
            "current_resume_text": str(row["current_resume_text"]),
            "current_resume_parsed": json_load(row["current_resume_parsed_json"], {}),
            "current_resume_filename": str(row["current_resume_filename"]),
            "current_resume_sha256": str(row["current_resume_sha256"]),
            "resume_updated_at": str(row["resume_updated_at"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def get_by_owner(self, username: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM candidate_profiles WHERE owner_username = ?",
                (username,),
            ).fetchone()
        return self._row(row) if row else None

    def get_or_create(self, username: str) -> dict[str, Any]:
        existing = self.get_by_owner(username)
        if existing:
            return existing
        now = utc_now()
        candidate_id = new_id("CAN")
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO candidate_profiles (
                        candidate_id, owner_username, created_at, updated_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (candidate_id, username, now, now),
                )
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise
        result = self.get_by_owner(username)
        assert result is not None
        return result

    def update(
        self,
        *,
        username: str,
        expected_version: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        columns = {
            "full_name": values["full_name"],
            "email": values["email"],
            "phone": values["phone"],
            "graduation_year": values["graduation_year"],
            "degree": values["degree"],
            "target_roles_json": json_dump(values["target_roles"]),
            "preferred_cities_json": json_dump(values["preferred_cities"]),
            "excluded_companies_json": json_dump(values["excluded_companies"]),
            "preferences_json": json_dump(values["preferences"]),
            "skills_json": json_dump(values["skills"]),
            "current_resume_text": values["current_resume_text"],
            "current_resume_parsed_json": json_dump(values["current_resume_parsed"]),
            "current_resume_filename": values["current_resume_filename"],
            "current_resume_sha256": values["current_resume_sha256"],
            "resume_updated_at": values["resume_updated_at"],
        }
        assignments = ", ".join(f"{name} = ?" for name in columns)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                f"""
                UPDATE candidate_profiles
                SET {assignments}, version = version + 1, updated_at = ?
                WHERE owner_username = ? AND version = ?
                """,
                (*columns.values(), now, username, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConflictError("候选人档案已变化，请刷新后重试")
        result = self.get_by_owner(username)
        assert result is not None
        return result
