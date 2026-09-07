from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from career.state_machine import validate_application_transition
from core.database import Database, json_dump, json_load
from core.errors import ConflictError, NotFoundError, PermissionError, ValidationError
from core.ids import new_id
from core.time import utc_now


def _is_past(value: str) -> bool:
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    return parsed.astimezone(timezone.utc) < datetime.now(timezone.utc)


class PendingActionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        stored_status = str(row["status"])
        effective_status = "EXPIRED" if stored_status == "PENDING" and _is_past(str(row["expires_at"])) else stored_status
        return {
            "action_id": str(row["action_id"]),
            "candidate_id": str(row["candidate_id"]),
            "actor_username": str(row["actor_username"]),
            "chat_id": str(row["chat_id"]),
            "action_type": str(row["action_type"]),
            "payload": json_load(row["payload_json"], {}),
            "request_hash": str(row["request_hash"]),
            "expected_version": int(row["expected_version"]),
            "status": effective_status,
            "expires_at": str(row["expires_at"]),
            "confirmed_at": str(row["confirmed_at"]),
            "executed_at": str(row["executed_at"]),
            "result": json_load(row["result_json"], {}),
            "failure_code": str(row["failure_code"]),
            "version": int(row["version"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "requires_confirmation": effective_status == "PENDING",
        }

    def get(self, *, candidate_id: str, action_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM pending_actions WHERE candidate_id = ? AND action_id = ?",
                (candidate_id, action_id),
            ).fetchone()
        if not row:
            raise NotFoundError("待确认动作不存在")
        return self._row(row)

    def list(self, *, candidate_id: str, status: str = "") -> list[dict[str, Any]]:
        params: list[Any] = [candidate_id]
        where = "candidate_id = ?"
        if status:
            where += " AND status = ?"
            params.append(status)
        with self.database.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM pending_actions WHERE {where} ORDER BY updated_at DESC LIMIT 100",
                params,
            ).fetchall()
        return [self._row(row) for row in rows]

    def create_application_transition(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        chat_id: str,
        payload: dict[str, Any],
        request_hash: str,
        expires_at: str,
    ) -> tuple[dict[str, Any], bool]:
        now = utc_now()
        with self.database.transaction() as connection:
            current = connection.execute(
                "SELECT status, version FROM applications WHERE candidate_id = ? AND application_id = ?",
                (candidate_id, payload["application_id"]),
            ).fetchone()
            if not current:
                raise NotFoundError("投递记录不存在")
            if int(current["version"]) != int(payload["expected_version"]):
                raise ConflictError("投递记录已变化，请刷新后重新提议")
            validate_application_transition(str(current["status"]), str(payload["target_status"]))

            existing = connection.execute(
                """
                SELECT * FROM pending_actions
                WHERE candidate_id = ? AND actor_username = ? AND chat_id = ? AND request_hash = ?
                """,
                (candidate_id, actor_username, chat_id, request_hash),
            ).fetchone()
            if existing:
                status = str(existing["status"])
                if status in {"PENDING", "EXECUTED"} and (status == "EXECUTED" or not _is_past(str(existing["expires_at"]))):
                    return self._row(existing), True
                connection.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'PENDING', expires_at = ?, confirmation_grant_hash = '',
                        grant_expires_at = '', confirmed_at = '', executed_at = '',
                        result_json = '{}', failure_code = '', version = version + 1,
                        updated_at = ?
                    WHERE action_id = ?
                    """,
                    (expires_at, now, str(existing["action_id"])),
                )
                action_id = str(existing["action_id"])
            else:
                action_id = new_id("ACT")
                connection.execute(
                    """
                    INSERT INTO pending_actions (
                        action_id, candidate_id, actor_username, chat_id, action_type,
                        payload_json, request_hash, expected_version, status,
                        expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'APPLICATION_TRANSITION', ?, ?, ?, 'PENDING', ?, ?, ?)
                    """,
                    (
                        action_id,
                        candidate_id,
                        actor_username,
                        chat_id,
                        json_dump(payload),
                        request_hash,
                        int(payload["expected_version"]),
                        expires_at,
                        now,
                        now,
                    ),
                )
        return self.get(candidate_id=candidate_id, action_id=action_id), False

    def confirm_and_execute(
        self,
        *,
        candidate_id: str,
        actor_username: str,
        action_id: str,
        raw_grant: str,
        grant_expires_at: str,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        now = utc_now()
        replayed = False
        application_id = ""
        with self.database.transaction() as connection:
            action = connection.execute(
                "SELECT * FROM pending_actions WHERE candidate_id = ? AND action_id = ?",
                (candidate_id, action_id),
            ).fetchone()
            if not action:
                raise NotFoundError("待确认动作不存在")
            if str(action["actor_username"]) != actor_username:
                raise PermissionError("确认人必须与提议动作的账号一致")
            payload = json_load(action["payload_json"], {})
            application_id = str(payload.get("application_id") or "")
            if str(action["status"]) == "EXECUTED":
                replayed = True
            else:
                if str(action["status"]) != "PENDING":
                    raise ConflictError("该动作当前不可确认")
                if _is_past(str(action["expires_at"])):
                    raise ConflictError("待确认动作已过期，请重新提议")
                canonical_hash = hashlib.sha256(
                    json_dump({"action_type": str(action["action_type"]), "payload": payload}).encode("utf-8")
                ).hexdigest()
                if canonical_hash != str(action["request_hash"]):
                    raise ConflictError("待确认动作请求哈希不一致")
                if not raw_grant:
                    raise PermissionError("缺少服务端确认授权")
                grant_hash = hashlib.sha256(
                    f"{raw_grant}|{action_id}|{actor_username}|{canonical_hash}".encode("utf-8")
                ).hexdigest()

                current = connection.execute(
                    "SELECT * FROM applications WHERE candidate_id = ? AND application_id = ?",
                    (candidate_id, application_id),
                ).fetchone()
                if not current:
                    raise NotFoundError("投递记录不存在")
                expected_version = int(action["expected_version"])
                if int(current["version"]) != expected_version:
                    raise ConflictError("投递记录已变化，原确认卡已失效")
                current_status = str(current["status"])
                target_status = str(payload["target_status"])
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
                    SET status = ?, next_action = ?, notes = ?, applied_at = ?,
                        offer_at = ?, rejected_at = ?, withdrawn_at = ?,
                        version = version + 1, updated_at = ?
                    WHERE candidate_id = ? AND application_id = ? AND version = ?
                    """,
                    (
                        target_status,
                        str(payload.get("next_action") or ""),
                        str(payload.get("notes") or ""),
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
                    ) VALUES (?, ?, ?, 'AGENT_STATUS_CHANGED', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("EVT"),
                        application_id,
                        sequence,
                        current_status,
                        target_status,
                        actor_username,
                        f"Agent 确认执行：{current_status} → {target_status}",
                        json_dump({
                            "action_id": action_id,
                            "next_action": str(payload.get("next_action") or ""),
                            "notes": str(payload.get("notes") or ""),
                        }),
                        f"agent:{action_id}",
                        canonical_hash,
                        resulting_version,
                        now,
                    ),
                )
                result = {
                    "application_id": application_id,
                    "from_status": current_status,
                    "to_status": target_status,
                    "resulting_version": resulting_version,
                }
                connection.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'EXECUTED', confirmation_grant_hash = ?,
                        grant_expires_at = ?, confirmed_at = ?, executed_at = ?,
                        result_json = ?, version = version + 1, updated_at = ?
                    WHERE action_id = ? AND status = 'PENDING'
                    """,
                    (grant_hash, grant_expires_at, now, now, json_dump(result), now, action_id),
                )

        action_result = self.get(candidate_id=candidate_id, action_id=action_id)
        with self.database.connection() as connection:
            application = connection.execute(
                "SELECT * FROM applications WHERE candidate_id = ? AND application_id = ?",
                (candidate_id, application_id),
            ).fetchone()
        if not application:
            raise NotFoundError("投递记录不存在")
        return action_result, {key: application[key] for key in application.keys()}, replayed

    def cancel(self, *, candidate_id: str, actor_username: str, action_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE pending_actions
                SET status = 'CANCELLED', version = version + 1, updated_at = ?
                WHERE candidate_id = ? AND actor_username = ? AND action_id = ? AND status = 'PENDING'
                """,
                (now, candidate_id, actor_username, action_id),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT status FROM pending_actions WHERE candidate_id = ? AND action_id = ?",
                    (candidate_id, action_id),
                ).fetchone()
                if not row:
                    raise NotFoundError("待确认动作不存在")
                raise ConflictError("该动作当前不可取消")
        return self.get(candidate_id=candidate_id, action_id=action_id)
