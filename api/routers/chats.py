from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from api.dependencies import candidate_for, current_user, services
from api.schemas import ChatThreadCreateBody, ChatThreadUpdateBody, body_dict


router = APIRouter(prefix="/api/chat-threads", tags=["chat-history"])


@router.get("")
def list_threads(
    request: Request,
    include_archived: bool = Query(False),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).chats.list(candidate["candidate_id"], include_archived)}


@router.post("", status_code=201)
def create_thread(
    body: ChatThreadCreateBody,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"thread": services(request).chats.create(candidate["candidate_id"], body_dict(body))}


@router.get("/{chat_id}")
def get_thread(chat_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    service = services(request).chats
    return {
        "thread": service.get(candidate["candidate_id"], chat_id),
        "messages": service.messages(candidate["candidate_id"], chat_id),
    }


@router.patch("/{chat_id}")
def update_thread(
    chat_id: str,
    body: ChatThreadUpdateBody,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"thread": services(request).chats.update(candidate["candidate_id"], chat_id, body_dict(body))}


@router.delete("/{chat_id}", status_code=204)
def delete_thread(chat_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> Response:
    candidate = candidate_for(request, user)
    services(request).chats.delete(candidate["candidate_id"], chat_id)
    return Response(status_code=204)

