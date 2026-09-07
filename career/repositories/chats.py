from __future__ import annotations

from typing import Any

from core.database import Database
from core.errors import ConflictError, NotFoundError, ValidationError
from core.ids import new_id
from core.time import utc_now


class ChatRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _thread(row: Any) -> dict[str, Any]:
        return {
            "chat_id": str(row["chat_id"]),
            "candidate_id": str(row["candidate_id"]),
            "title": str(row["title"]),
            "archived": bool(row["archived"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    @staticmethod
    def _message(row: Any) -> dict[str, Any]:
        return {
            "message_id": str(row["message_id"]),
            "chat_id": str(row["chat_id"]),
            "role": str(row["role"]),
            "content": str(row["content"]),
            "created_at": str(row["created_at"]),
        }

    def create(self, *, candidate_id: str, chat_id: str, title: str = "新对话") -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM chat_threads WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if existing:
                if str(existing["candidate_id"]) != candidate_id:
                    raise ConflictError("对话 ID 已被其他候选人使用")
                return self._thread(existing)
            connection.execute(
                """
                INSERT INTO chat_threads (
                    chat_id, candidate_id, title, archived, created_at, updated_at
                ) VALUES (?, ?, ?, 0, ?, ?)
                """,
                (chat_id, candidate_id, title, now, now),
            )
        return self.get(candidate_id=candidate_id, chat_id=chat_id)

    def get(self, *, candidate_id: str, chat_id: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM chat_threads WHERE candidate_id = ? AND chat_id = ?",
                (candidate_id, chat_id),
            ).fetchone()
        if not row:
            raise NotFoundError("对话不存在")
        return self._thread(row)

    def list(self, *, candidate_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM chat_threads
                WHERE candidate_id = ? AND (? = 1 OR archived = 0)
                ORDER BY updated_at DESC, chat_id DESC
                LIMIT 200
                """,
                (candidate_id, int(include_archived)),
            ).fetchall()
        return [self._thread(row) for row in rows]

    def update(
        self,
        *,
        candidate_id: str,
        chat_id: str,
        title: str | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        current = self.get(candidate_id=candidate_id, chat_id=chat_id)
        next_title = current["title"] if title is None else title
        next_archived = current["archived"] if archived is None else archived
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE chat_threads SET title = ?, archived = ?, updated_at = ?
                WHERE candidate_id = ? AND chat_id = ?
                """,
                (next_title, int(next_archived), utc_now(), candidate_id, chat_id),
            )
        return self.get(candidate_id=candidate_id, chat_id=chat_id)

    def delete(self, *, candidate_id: str, chat_id: str) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM chat_threads WHERE candidate_id = ? AND chat_id = ?",
                (candidate_id, chat_id),
            )
            if cursor.rowcount != 1:
                raise NotFoundError("对话不存在")
            connection.execute(
                "DELETE FROM agent_memories WHERE candidate_id = ? AND chat_id = ?",
                (candidate_id, chat_id),
            )

    def append_message(
        self, *, candidate_id: str, chat_id: str, role: str, content: str
    ) -> dict[str, Any]:
        now = utc_now()
        message_id = new_id("MSG")
        with self.database.transaction() as connection:
            thread = connection.execute(
                "SELECT title FROM chat_threads WHERE candidate_id = ? AND chat_id = ?",
                (candidate_id, chat_id),
            ).fetchone()
            if not thread:
                raise NotFoundError("对话不存在")
            connection.execute(
                """
                INSERT INTO chat_messages (message_id, chat_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (message_id, chat_id, role, content, now),
            )
            title = str(thread["title"])
            if role == "USER" and title == "新对话":
                compact = " ".join(content.split())
                title = compact[:36] + ("…" if len(compact) > 36 else "")
            connection.execute(
                "UPDATE chat_threads SET title = ?, archived = 0, updated_at = ? WHERE chat_id = ?",
                (title or "新对话", now, chat_id),
            )
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM chat_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
        assert row is not None
        return self._message(row)

    def messages(self, *, candidate_id: str, chat_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        self.get(candidate_id=candidate_id, chat_id=chat_id)
        safe_limit = max(1, min(int(limit), 2000))
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM chat_messages WHERE chat_id = ?
                    ORDER BY created_at DESC, message_id DESC LIMIT ?
                ) ORDER BY created_at, message_id
                """,
                (chat_id, safe_limit),
            ).fetchall()
        return [self._message(row) for row in rows]

