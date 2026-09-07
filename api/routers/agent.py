from __future__ import annotations

import json
from typing import Any, Iterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from api.dependencies import candidate_for, current_user, services
from api.schemas import AgentChatBody, body_dict


router = APIRouter(prefix="/api", tags=["career-agent"])


@router.get("/agent/capabilities")
def capabilities(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return services(request).agent.capabilities()


@router.get("/agent/memory/{chat_id}")
def get_memory(chat_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"memory": services(request).memory.get(candidate["candidate_id"], chat_id)}


@router.get("/pending-actions")
def list_pending_actions(request: Request, status: str = "", user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).pending_actions.list(candidate["candidate_id"], status)}


@router.post("/pending-actions/{action_id}/confirm")
def confirm_pending_action(action_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).agent.confirm_action(candidate=candidate, actor_username=user["username"], action_id=action_id)


@router.post("/pending-actions/{action_id}/cancel")
def cancel_pending_action(action_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"action": services(request).pending_actions.cancel(
        candidate_id=candidate["candidate_id"], actor_username=user["username"], action_id=action_id,
    )}


def _chunks(text: str, size: int = 80) -> Iterator[str]:
    for offset in range(0, len(text), size):
        yield text[offset:offset + size]


@router.post("/agent/chat/stream")
def chat_stream(body: AgentChatBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> StreamingResponse:
    candidate = candidate_for(request, user)
    result = services(request).agent.run(
        candidate=candidate,
        actor_username=user["username"],
        payload=body_dict(body),
    )

    def generate() -> Iterator[str]:
        yield json.dumps({"type": "meta", "chat_id": result["chat_id"], "trace_id": result["trace"]["trace_id"]}, ensure_ascii=False) + "\n"
        for text in _chunks(result["answer"]):
            yield json.dumps({"type": "delta", "text": text}, ensure_ascii=False) + "\n"
        for action in result["pending_actions"]:
            yield json.dumps({"type": "pending_action", "action": action}, ensure_ascii=False) + "\n"
        yield json.dumps({
            "type": "complete", "answer": result["answer"], "memory": result["memory"],
            "trace": result["trace"], "runtime": result["runtime"],
            "disclaimer": result["disclaimer"],
        }, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
