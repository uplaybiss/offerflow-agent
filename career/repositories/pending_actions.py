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
        effective_status = (
            "EXPIRED"
            if stored_status == "PENDING" and _is_past(str(row["expires_at"]))
            else stored_status
        )
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

    @staticmethod
    def _reuse_or_insert(
        connection: Any,
        *,
        candidate_id: str,
        actor_username: str,
        chat_id: str,
        action_type: str,
        payload: dict[str, Any],
        request_hash: str,
        expected_version: int,
        expires_at: str,
        now: str,
    ) -> tuple[str, bool]:
        existing = connection.execute(
            """
            SELECT * FROM pending_actions
            WHERE candidate_id = ? AND actor_username = ? AND chat_id = ? AND request_hash = ?
            """,
            (candidate_id, actor_username, chat_id, request_hash),
        ).fetchone()
        if existing:
            status = str(existing["status"])
            if status in {"PENDING", "EXECUTED"} and (
                status == "EXECUTED" or not _is_past(str(existing["expires_at"]))
            ):
                return str(existing["action_id"]), True
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
            return str(existing["action_id"]), False

        action_id = new_id("ACT")
        connection.execute(
            """
            INSERT INTO pending_actions (
                action_id, candidate_id, actor_username, chat_id, action_type,
                payload_json, request_hash, expected_version, status,
                expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?)
            """,
            (
                action_id, candidate_id, actor_username, chat_id, action_type,
                json_dump(payload), request_hash, expected_version, expires_at, now, now,
            ),
        )
        return action_id, False

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
            action_id, replayed = self._reuse_or_insert(
                connection,
                candidate_id=candidate_id,
                actor_username=actor_username,
                chat_id=chat_id,
                action_type="APPLICATION_TRANSITION",
                payload=payload,
                request_hash=request_hash,
                expected_version=int(payload["expected_version"]),
                expires_at=expires_at,
                now=now,
            )
        return self.get(candidate_id=candidate_id, action_id=action_id), replayed

    def create_interview_progression(
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
            application = connection.execute(
                "SELECT status, version FROM applications WHERE candidate_id = ? AND application_id = ?",
                (candidate_id, payload["application_id"]),
            ).fetchone()
            if not application:
                raise NotFoundError("投递记录不存在")
            if str(application["status"]) != "INTERVIEW":
                raise ConflictError("组合面试推进只允许用于 INTERVIEW 状态投递")
            if int(application["version"]) != int(payload["expected_application_version"]):
                raise ConflictError("投递记录已变化，请刷新后重新提议")
            current_round = connection.execute(
                """
                SELECT version, status FROM interview_rounds
                WHERE round_id = ? AND application_id = ?
                """,
                (payload["current_round_id"], payload["application_id"]),
            ).fetchone()
            if not current_round:
                raise NotFoundError("当前面试轮次不存在或不属于该投递")
            if int(current_round["version"]) != int(payload["expected_interview_version"]):
                raise ConflictError("当前面试轮次已变化，请刷新后重新提议")
            if str(current_round["status"]) not in {"PLANNED", "SCHEDULED"}:
                raise ConflictError("当前面试轮次已经完成或取消")
            action_id, replayed = self._reuse_or_insert(
                connection,
                candidate_id=candidate_id,
                actor_username=actor_username,
                chat_id=chat_id,
                action_type="INTERVIEW_PROGRESSION",
                payload=payload,
                request_hash=request_hash,
                expected_version=int(payload["expected_application_version"]),
                expires_at=expires_at,
                now=now,
            )
        return self.get(candidate_id=candidate_id, action_id=action_id), replayed

    def create_task(
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
            self._validate_task_links(connection, candidate_id, payload)
            action_id, replayed = self._reuse_or_insert(
                connection,
                candidate_id=candidate_id,
                actor_username=actor_username,
                chat_id=chat_id,
                action_type="TASK_CREATE",
                payload=payload,
                request_hash=request_hash,
                expected_version=1,
                expires_at=expires_at,
                now=now,
            )
        return self.get(candidate_id=candidate_id, action_id=action_id), replayed

    @staticmethod
    def _validate_task_links(connection: Any, candidate_id: str, payload: dict[str, Any]) -> None:
        job_id = str(payload.get("job_id") or "")
        application_id = str(payload.get("application_id") or "")
        interview_id = str(payload.get("interview_round_id") or "")
        if job_id:
            job = connection.execute(
                "SELECT 1 FROM jobs WHERE candidate_id = ? AND job_id = ?",
                (candidate_id, job_id),
            ).fetchone()
            if not job:
                raise NotFoundError("关联岗位不存在")
        application = None
        if application_id:
            application = connection.execute(
                "SELECT job_id FROM applications WHERE candidate_id = ? AND application_id = ?",
                (candidate_id, application_id),
            ).fetchone()
            if not application:
                raise NotFoundError("关联投递不存在")
            if job_id and str(application["job_id"]) != job_id:
                raise ValidationError("岗位与投递不属于同一业务链")
        interview = None
        if interview_id:
            interview = connection.execute(
                """
                SELECT r.application_id, a.job_id FROM interview_rounds r
                JOIN applications a ON a.application_id = r.application_id
                WHERE a.candidate_id = ? AND r.round_id = ?
                """,
                (candidate_id, interview_id),
            ).fetchone()
            if not interview:
                raise NotFoundError("关联面试不存在")
            if application_id and str(interview["application_id"]) != application_id:
                raise ValidationError("投递与面试不属于同一业务链")
            if job_id and str(interview["job_id"]) != job_id:
                raise ValidationError("岗位与面试不属于同一业务链")

    @staticmethod
    def _execute_application_transition(
        connection: Any,
        *,
        action_id: str,
        candidate_id: str,
        actor_username: str,
        payload: dict[str, Any],
        expected_version: int,
        canonical_hash: str,
        now: str,
    ) -> dict[str, Any]:
        application_id = str(payload["application_id"])
        current = connection.execute(
            "SELECT * FROM applications WHERE candidate_id = ? AND application_id = ?",
            (candidate_id, application_id),
        ).fetchone()
        if not current:
            raise NotFoundError("投递记录不存在")
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
                target_status, str(payload.get("next_action") or ""),
                str(payload.get("notes") or ""), timestamps["applied_at"],
                timestamps["offer_at"], timestamps["rejected_at"],
                timestamps["withdrawn_at"], now, candidate_id, application_id,
                expected_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ConflictError("投递记录并发更新失败")
        sequence = int(connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM application_events WHERE application_id = ?",
            (application_id,),
        ).fetchone()[0])
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
                new_id("EVT"), application_id, sequence, current_status, target_status,
                actor_username, f"Agent 确认执行：{current_status} → {target_status}",
                json_dump({
                    "action_id": action_id,
                    "next_action": str(payload.get("next_action") or ""),
                    "notes": str(payload.get("notes") or ""),
                }),
                f"agent:{action_id}", canonical_hash, resulting_version, now,
            ),
        )
        return {
            "action_type": "APPLICATION_TRANSITION",
            "application_id": application_id,
            "from_status": current_status,
            "to_status": target_status,
            "resulting_version": resulting_version,
        }

    @staticmethod
    def _execute_interview_progression(
        connection: Any,
        *,
        action_id: str,
        candidate_id: str,
        actor_username: str,
        payload: dict[str, Any],
        canonical_hash: str,
        now: str,
    ) -> dict[str, Any]:
        application_id = str(payload["application_id"])
        expected_application = int(payload["expected_application_version"])
        current = connection.execute(
            "SELECT * FROM applications WHERE candidate_id = ? AND application_id = ?",
            (candidate_id, application_id),
        ).fetchone()
        if not current:
            raise NotFoundError("投递记录不存在")
        if str(current["status"]) != "INTERVIEW":
            raise ConflictError("投递已不在 INTERVIEW 状态，原确认卡失效")
        if int(current["version"]) != expected_application:
            raise ConflictError("投递记录已变化，原确认卡已失效")

        current_round = connection.execute(
            """
            SELECT * FROM interview_rounds
            WHERE round_id = ? AND application_id = ?
            """,
            (payload["current_round_id"], application_id),
        ).fetchone()
        if not current_round:
            raise NotFoundError("当前面试轮次不存在或不属于该投递")
        expected_interview = int(payload["expected_interview_version"])
        if int(current_round["version"]) != expected_interview:
            raise ConflictError("当前面试轮次已变化，原确认卡已失效")
        if str(current_round["status"]) not in {"PLANNED", "SCHEDULED"}:
            raise ConflictError("当前面试轮次已经完成或取消")
        updated = connection.execute(
            """
            UPDATE interview_rounds
            SET status = 'COMPLETED', completed_at = ?, result = ?,
                version = version + 1, updated_at = ?
            WHERE round_id = ? AND application_id = ? AND version = ?
            """,
            (
                now, payload["current_round_result"], now,
                payload["current_round_id"], application_id, expected_interview,
            ),
        )
        if updated.rowcount != 1:
            raise ConflictError("当前面试轮次并发更新失败")

        next_round_id = new_id("INT")
        next_round_no = int(connection.execute(
            "SELECT COALESCE(MAX(round_no), 0) + 1 FROM interview_rounds WHERE application_id = ?",
            (application_id,),
        ).fetchone()[0])
        connection.execute(
            """
            INSERT INTO interview_rounds (
                round_id, application_id, round_no, round_type, title,
                status, scheduled_at, completed_at, notes, result,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'SCHEDULED', ?, '', '', '', ?, ?)
            """,
            (
                next_round_id, application_id, next_round_no,
                payload["next_round_type"], payload["next_round_title"],
                payload["next_round_scheduled_at"], now, now,
            ),
        )

        task_id = new_id("TSK")
        connection.execute(
            """
            INSERT INTO job_search_tasks (
                task_id, candidate_id, job_id, application_id,
                interview_round_id, title, description, task_type,
                status, priority, due_at, origin, suggestion_key,
                suggestion_source, suggestion_payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, '', 'INTERVIEW', 'TODO', 'P1', ?,
                      'MANUAL', '', '', '{}', ?, ?)
            """,
            (
                task_id, candidate_id, str(current["job_id"]), application_id,
                next_round_id, payload["task_title"], payload["task_due_at"], now, now,
            ),
        )

        resulting_version = expected_application + 1
        changed = connection.execute(
            """
            UPDATE applications
            SET status = 'INTERVIEW', next_action = ?, version = version + 1, updated_at = ?
            WHERE candidate_id = ? AND application_id = ? AND status = 'INTERVIEW' AND version = ?
            """,
            (
                f"准备{payload['next_round_title']}", now, candidate_id,
                application_id, expected_application,
            ),
        )
        if changed.rowcount != 1:
            raise ConflictError("投递记录并发更新失败")

        sequence = int(connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM application_events WHERE application_id = ?",
            (application_id,),
        ).fetchone()[0])
        connection.execute(
            """
            INSERT INTO application_events (
                event_id, application_id, sequence, event_type,
                from_status, to_status, actor_username, message,
                payload_json, command_id, request_hash,
                resulting_version, created_at
            ) VALUES (?, ?, ?, 'INTERVIEW_PROGRESSED', 'INTERVIEW', 'INTERVIEW', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("EVT"), application_id, sequence, actor_username,
                "Agent 确认完成当前面试并安排下一轮",
                json_dump({
                    "action_id": action_id,
                    "completed_round_id": str(payload["current_round_id"]),
                    "next_round_id": next_round_id,
                    "task_id": task_id,
                }),
                f"agent:{action_id}", canonical_hash, resulting_version, now,
            ),
        )
        return {
            "action_type": "INTERVIEW_PROGRESSION",
            "application_id": application_id,
            "from_status": "INTERVIEW",
            "to_status": "INTERVIEW",
            "resulting_version": resulting_version,
            "completed_round_id": str(payload["current_round_id"]),
            "completed_round_version": expected_interview + 1,
            "next_round_id": next_round_id,
            "task_id": task_id,
        }

    @classmethod
    def _execute_task_create(
        cls,
        connection: Any,
        *,
        action_id: str,
        candidate_id: str,
        payload: dict[str, Any],
        now: str,
    ) -> dict[str, Any]:
        cls._validate_task_links(connection, candidate_id, payload)
        task_id = new_id("TSK")
        connection.execute(
            """
            INSERT INTO job_search_tasks (
                task_id, candidate_id, job_id, application_id, interview_round_id,
                title, description, task_type, status, priority, due_at, origin,
                suggestion_key, suggestion_source, suggestion_payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'TODO', ?, ?, 'MANUAL', '', '', '{}', ?, ?)
            """,
            (
                task_id, candidate_id, payload.get("job_id") or None,
                payload.get("application_id") or None,
                payload.get("interview_round_id") or None,
                payload["title"], payload.get("description", ""),
                payload["task_type"], payload["priority"], payload["due_at"], now, now,
            ),
        )
        return {
            "action_type": "TASK_CREATE",
            "task_id": task_id,
            "title": payload["title"],
            "task_type": payload["task_type"],
            "priority": payload["priority"],
            "due_at": payload["due_at"],
        }

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
        business_id = ""
        action_type = ""
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
            action_type = str(action["action_type"])
            business_id = str(payload.get("application_id") or "")
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

                if action_type == "APPLICATION_TRANSITION":
                    result = self._execute_application_transition(
                        connection,
                        action_id=action_id,
                        candidate_id=candidate_id,
                        actor_username=actor_username,
                        payload=payload,
                        expected_version=int(action["expected_version"]),
                        canonical_hash=canonical_hash,
                        now=now,
                    )
                elif action_type == "INTERVIEW_PROGRESSION":
                    result = self._execute_interview_progression(
                        connection,
                        action_id=action_id,
                        candidate_id=candidate_id,
                        actor_username=actor_username,
                        payload=payload,
                        canonical_hash=canonical_hash,
                        now=now,
                    )
                elif action_type == "TASK_CREATE":
                    result = self._execute_task_create(
                        connection,
                        action_id=action_id,
                        candidate_id=candidate_id,
                        payload=payload,
                        now=now,
                    )
                    business_id = str(result["task_id"])
                else:
                    raise ValidationError("待确认动作类型无效")
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
            if action_type == "TASK_CREATE":
                business = connection.execute(
                    "SELECT * FROM job_search_tasks WHERE candidate_id = ? AND task_id = ?",
                    (candidate_id, action_result["result"].get("task_id") or business_id),
                ).fetchone()
            else:
                business = connection.execute(
                    "SELECT * FROM applications WHERE candidate_id = ? AND application_id = ?",
                    (candidate_id, business_id),
                ).fetchone()
        if not business:
            raise NotFoundError("确认动作对应的业务对象不存在")
        return action_result, {key: business[key] for key in business.keys()}, replayed

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
