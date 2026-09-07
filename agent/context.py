from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class AgentRequestContext:
    services: Any
    candidate: dict[str, Any]
    actor_username: str
    chat_id: str
    trace: Any
    current_job_id: str = ""
    current_application_id: str = ""
    current_interview_id: str = ""
    current_task_id: str = ""
    sandbox: bool = False
    confirmation_grant: str = ""
    proposed_actions: list[dict[str, Any]] = field(default_factory=list)


_CURRENT: ContextVar[AgentRequestContext | None] = ContextVar("offerflow_agent_context", default=None)


def current_agent_context() -> AgentRequestContext:
    context = _CURRENT.get()
    if context is None:
        raise RuntimeError("Career Agent 工具只能在服务端请求上下文中执行")
    return context


@contextmanager
def bind_agent_context(context: AgentRequestContext) -> Iterator[AgentRequestContext]:
    token = _CURRENT.set(context)
    try:
        yield context
    finally:
        _CURRENT.reset(token)
