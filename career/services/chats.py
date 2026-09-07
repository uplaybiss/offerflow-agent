from __future__ import annotations

from typing import Any

from career.repositories.chats import ChatRepository
from career.services.memory import validate_chat_id
from core.errors import ValidationError
from core.ids import new_id


class ChatService:
    def __init__(self, repository: ChatRepository) -> None:
        self.repository = repository

    def create(self, candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        requested = str(payload.get("chat_id") or "").strip()
        chat_id = validate_chat_id(requested) if requested else new_id("CHAT")
        title = str(payload.get("title") or "新对话").strip()[:100] or "新对话"
        return self.repository.create(candidate_id=candidate_id, chat_id=chat_id, title=title)

    def ensure(self, candidate_id: str, chat_id: str) -> dict[str, Any]:
        return self.repository.create(
            candidate_id=candidate_id,
            chat_id=validate_chat_id(chat_id),
            title="新对话",
        )

    def get(self, candidate_id: str, chat_id: str) -> dict[str, Any]:
        return self.repository.get(candidate_id=candidate_id, chat_id=validate_chat_id(chat_id))

    def list(self, candidate_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        return self.repository.list(candidate_id=candidate_id, include_archived=include_archived)

    def update(self, candidate_id: str, chat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        title: str | None = None
        if "title" in payload:
            title = str(payload.get("title") or "").strip()
            if not title:
                raise ValidationError("对话标题不能为空")
            title = title[:100]
        archived = bool(payload["archived"]) if "archived" in payload else None
        return self.repository.update(
            candidate_id=candidate_id,
            chat_id=validate_chat_id(chat_id),
            title=title,
            archived=archived,
        )

    def delete(self, candidate_id: str, chat_id: str) -> None:
        self.repository.delete(candidate_id=candidate_id, chat_id=validate_chat_id(chat_id))

    def append(self, candidate_id: str, chat_id: str, role: str, content: str) -> dict[str, Any]:
        normalized_role = str(role or "").upper()
        if normalized_role not in {"USER", "ASSISTANT"}:
            raise ValidationError("对话消息角色无效")
        text = str(content or "").strip()
        limit = 20_000 if normalized_role == "USER" else 50_000
        if not text or len(text) > limit:
            raise ValidationError("对话消息为空或过长")
        return self.repository.append_message(
            candidate_id=candidate_id,
            chat_id=validate_chat_id(chat_id),
            role=normalized_role,
            content=text,
        )

    def messages(self, candidate_id: str, chat_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        return self.repository.messages(
            candidate_id=candidate_id,
            chat_id=validate_chat_id(chat_id),
            limit=limit,
        )

    def runner_history(self, candidate_id: str, chat_id: str, limit: int) -> list[dict[str, str]]:
        items = self.messages(candidate_id, chat_id, limit=max(1, min(limit, 20)))
        return [
            {"role": "user" if item["role"] == "USER" else "assistant", "content": item["content"]}
            for item in items
        ]

