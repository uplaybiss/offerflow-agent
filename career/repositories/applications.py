from __future__ import annotations

from typing import Any

from career.state_machine import validate_application_transition
from core.database import Database, json_dump, json_load
from core.errors import ConflictError, NotFoundError
from core.ids import new_id
from core.time import utc_now


class ApplicationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        result = {
            "application_id": str(row["application_id"]),
            "candidate_id": str(row["candidate_id"]),
            "job_id": str(row["job_id"]),
            "status": str(row["status"]),
            "next_action": str(row["next_action"]),
            "notes": str(row["notes"]),
            "applied_at": str(row["applied_at"]),
            "offer_at": str(row["offer_at"]),
            "rejected_at": str(row["rejected_at"]),
            "withdrawn_at": str(row["withdrawn_at"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
        if "company_name" in row.keys():
            result["job"] = {
                "company_name": str(row["company_name"]),
                "title": str(row["job_title"]),
                "location": str(row["job_location"]),
                "deadline": str(row["job_deadline"]),
                "status": str(row["job_status"]),
                "is_favorite": bool(row["job_favorite"]),
            }
        return result

    @staticmethod
    def _event(row: Any) -> dict[str, Any]:
        return {
            "event_id": str(row["event_id"]),
            "sequence": int(row["sequence"]),
            "event_type": str(row["event_type"]),
            "from_status": str(row["from_status"]),
            "to_status": str(row["to_status"]),
            "actor_username": str(row["actor_username"]),
            "message": str(row["message"]),
            "payload": json_load(row["payload_json"], {}),
            "command_id": str(row["command_id"]),
            "resulting_version": int(row["resulting_version"]),
            "created_at": str(row["created_at"]),
        }

    def _joined_query(self) -> str:
        return """
            SELECT a.*, j.company_name, j.title AS job_title,
                   j.location AS job_location, j.deadline AS job_deadline,
                   j.status AS job_status, j.is_favorite AS job_favorite
            FROM applications a
            JOIN jobs j ON j.job_id = a.job_id AND j.candidate_id = a.candidate_id
        """

    def create(
        self,
        *,
        candidate_id: str,
        job_id: str,
        status: str,
        next_action: str,
        notes: str,
        actor_username: str,
        command_id: str,
        request_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        application_id = new_id("APP")
        replayed = False
        with self.database.transaction() as connection:
            job = connection.execute(
                "SELECT 1 FROM jobs WHERE candidate_id = ? AND job_id = ?",
                (candidate_id, job_id),
            ).fetchone()
            if not job:
                raise NotFoundError("岗位不存在")
            existing = connection.execute(
                "SELECT application_id FROM applications WHERE candidate_id = ? AND job_id = ?",
                (candidate_id, job_id),
            ).fetchone()
            if existing:
                application_id = str(existing["application_id"])
                event = connection.execute(
                    "SELECT request_hash FROM application_events WHERE application_id = ? AND command_id = ?",
                    (application_id, command_id),
                ).fetchone()
                if event and str(event["request_hash"]) == request_hash:
                    replayed = True
                elif event:
                    raise ConflictError("相同 command_id 不能用于不同请求")
                else:
                    raise ConflictError("该岗位已经建立投递记录")
            else:
                applied_at = now if status != "PLANNED" else ""
                offer_at = now if status == "OFFER" else ""
                rejected_at = now if status == "REJECTED" else ""
                withdrawn_at = now if status == "WITHDRAWN" else ""
                connection.execute(
                    """
                    INSERT INTO applications (
                        application_id, candidate_id, job_id, status,
                        next_action, notes, applied_at, offer_at,
                        rejected_at, withdrawn_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        application_id,
                        candidate_id,
                        job_id,
                        status,
                        next_action,
                        notes,
                        applied_at,
                        offer_at,
                        rejected_at,
                        withdrawn_at,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO application_events (
                        event_id, application_id, sequence, event_type,
                        from_status, to_status, actor_username, message,
                        payload_json, command_id, request_hash,
                        resulting_version, created_at
                    ) VALUES (?, ?, 1, 'APPLICATION_CREATED', '', ?, ?, ?, '{}', ?, ?, 1, ?)
                    """,
                    (
                        new_id("EVT"),
                        application_id,
                        status,
                        actor_username,
                        "建立投递记录",
                        command_id,
                        request_hash,
                        now,
                    ),
                )
        return self.get(candidate_id=candidate_id, application_id=application_id), replayed

    def transition(
        self,
        *,
        candidate_id: str,
        application_id: str,
        target_status: str,
        next_action: str,
        notes: str,
        expected_version: int,
        actor_username: str,
        command_id: str,
        request_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        replayed = False
        with self.database.transaction() as connection:
            existing_event = connection.execute(
                "SELECT request_hash FROM application_events WHERE application_id = ? AND command_id = ?",
                (application_id, command_id),
            ).fetchone()
            if existing_event:
                if str(existing_event["request_hash"]) != request_hash:
                    raise ConflictError("相同 command_id 不能用于不同请求")
                replayed = True
            else:
                current = connection.execute(
                    "SELECT * FROM applications WHERE candidate_id = ? AND application_id = ?",
                    (candidate_id, application_id),
                ).fetchone()
                if not current:
                    raise NotFoundError("投递记录不存在")
                if int(current["version"]) != expected_version:
                    raise ConflictError("投递记录已变化，请刷新后重试")
                current_status = str(current["status"])
                validate_application_transition(current_status, target_status)
                resulting_version = expected_version + 1
                timestamps = {
                    "applied_at": str(current["applied_at"]),
                    "offer_at": str(current["offer_at"]),
                    "rejected_at": str(current["rejected_at"]),
                    "withdrawn_at": str(current["withdrawn_at"]),
                }
                if target_status == "APPLIED" and not timestamps["applied_at"]:
                    timestamps["applied_at"] = now
                if target_status == "OFFER":
                    timestamps["offer_at"] = now
                if target_status == "REJECTED":
                    timestamps["rejected_at"] = now
                if target_status == "WITHDRAWN":
                    timestamps["withdrawn_at"] = now
                cursor = connection.execute(
                    """
                    UPDATE applications
                    SET status = ?, next_action = ?, notes = ?,
                        applied_at = ?, offer_at = ?, rejected_at = ?,
                        withdrawn_at = ?, version = version + 1, updated_at = ?
                    WHERE candidate_id = ? AND application_id = ? AND version = ?
                    """,
                    (
                        target_status,
                        next_action,
                        notes,
                        timestamps["applied_at"],
                        timestamps["offer_at"],
                        timestamps["rejected_at"],
                        timestamps["withdrawn_at"],
                        now,
                        candidate_id,
                        application_id,
                        expected_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConflictError("投递记录并发更新失败")
                sequence = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM application_events WHERE application_id = ?",
                        (application_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO application_events (
                        event_id, application_id, sequence, event_type,
                        from_status, to_status, actor_username, message,
                        payload_json, command_id, request_hash,
                        resulting_version, created_at
                    ) VALUES (?, ?, ?, 'STATUS_CHANGED', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("EVT"),
                        application_id,
                        sequence,
                        current_status,
                        target_status,
                        actor_username,
                        f"{current_status} → {target_status}",
                        json_dump({"next_action": next_action, "notes": notes}),
                        command_id,
                        request_hash,
                        resulting_version,
                        now,
                    ),
                )
        return self.get(candidate_id=candidate_id, application_id=application_id), replayed

    def get(self, *, candidate_id: str, application_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                self._joined_query() + " WHERE a.candidate_id = ? AND a.application_id = ?",
                (candidate_id, application_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("投递记录不存在")
            events = connection.execute(
                "SELECT * FROM application_events WHERE application_id = ? ORDER BY sequence",
                (application_id,),
            ).fetchall()
        result = self._row(row)
        result["events"] = [self._event(item) for item in events]
        return result

    def list(self, *, candidate_id: str, status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = [candidate_id]
        where = " WHERE a.candidate_id = ?"
        if status:
            where += " AND a.status = ?"
            params.append(status)
        params.append(max(1, min(limit, 500)))
        with self.database.connection() as connection:
            rows = connection.execute(
                self._joined_query() + where + " ORDER BY a.updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row(row) for row in rows]


class InterviewRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "round_id": str(row["round_id"]),
            "application_id": str(row["application_id"]),
            "round_no": int(row["round_no"]),
            "round_type": str(row["round_type"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "scheduled_at": str(row["scheduled_at"]),
            "completed_at": str(row["completed_at"]),
            "notes": str(row["notes"]),
            "result": str(row["result"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def create(self, *, candidate_id: str, application_id: str, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        round_id = new_id("INT")
        try:
            with self.database.transaction() as connection:
                application = connection.execute(
                    "SELECT 1 FROM applications WHERE candidate_id = ? AND application_id = ?",
                    (candidate_id, application_id),
                ).fetchone()
                if not application:
                    raise NotFoundError("投递记录不存在")
                round_no = values.get("round_no") or int(
                    connection.execute(
                        "SELECT COALESCE(MAX(round_no), 0) + 1 FROM interview_rounds WHERE application_id = ?",
                        (application_id,),
                    ).fetchone()[0]
                )
                connection.execute(
                    """
                    INSERT INTO interview_rounds (
                        round_id, application_id, round_no, round_type, title,
                        status, scheduled_at, completed_at, notes, result,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        round_id,
                        application_id,
                        round_no,
                        values["round_type"],
                        values["title"],
                        values["status"],
                        values["scheduled_at"],
                        now if values["status"] == "COMPLETED" else "",
                        values["notes"],
                        values["result"],
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ConflictError("该轮次编号已存在") from exc
            raise
        return self.get(candidate_id=candidate_id, round_id=round_id)

    def get(self, *, candidate_id: str, round_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT r.* FROM interview_rounds r
                JOIN applications a ON a.application_id = r.application_id
                WHERE a.candidate_id = ? AND r.round_id = ?
                """,
                (candidate_id, round_id),
            ).fetchone()
        if not row:
            raise NotFoundError("面试轮次不存在")
        return self._row(row)

    def list(self, *, candidate_id: str, application_id: str = "", upcoming_only: bool = False) -> list[dict[str, Any]]:
        clauses = ["a.candidate_id = ?"]
        params: list[Any] = [candidate_id]
        if application_id:
            clauses.append("r.application_id = ?")
            params.append(application_id)
        if upcoming_only:
            clauses.append("r.status IN ('PLANNED', 'SCHEDULED')")
        with self.database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT r.* FROM interview_rounds r
                JOIN applications a ON a.application_id = r.application_id
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE WHEN r.scheduled_at = '' THEN 1 ELSE 0 END,
                         r.scheduled_at, r.round_no
                """,
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def update(
        self,
        *,
        candidate_id: str,
        round_id: str,
        expected_version: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        current = self.get(candidate_id=candidate_id, round_id=round_id)
        completed_at = current["completed_at"]
        if values["status"] == "COMPLETED" and not completed_at:
            completed_at = now
        elif values["status"] != "COMPLETED":
            completed_at = ""
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE interview_rounds
                SET round_type = ?, title = ?, status = ?, scheduled_at = ?,
                    completed_at = ?, notes = ?, result = ?,
                    version = version + 1, updated_at = ?
                WHERE round_id = ? AND version = ?
                  AND application_id IN (
                    SELECT application_id FROM applications WHERE candidate_id = ?
                  )
                """,
                (
                    values["round_type"],
                    values["title"],
                    values["status"],
                    values["scheduled_at"],
                    completed_at,
                    values["notes"],
                    values["result"],
                    now,
                    round_id,
                    expected_version,
                    candidate_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("面试轮次已变化，请刷新后重试")
        return self.get(candidate_id=candidate_id, round_id=round_id)
