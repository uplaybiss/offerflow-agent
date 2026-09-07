from __future__ import annotations

from typing import Any

from fastapi import Request

from core.container import Services
from core.errors import AuthenticationError, PermissionError


def services(request: Request) -> Services:
    return request.app.state.services


def current_user(request: Request) -> dict[str, Any]:
    username = request.session.get("username")
    if not username:
        raise AuthenticationError("请先登录")
    user = services(request).auth.get_user(str(username))
    if not user["active"]:
        request.session.clear()
        raise AuthenticationError("账号已停用")
    return user


def admin_user(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if user["role"] != "admin":
        raise PermissionError("需要管理员权限")
    return user


def candidate_for(request: Request, user: dict[str, Any]) -> dict[str, Any]:
    return services(request).candidate.get(user["username"])
