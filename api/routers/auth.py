from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import admin_user, current_user, services
from core.errors import AuthenticationError


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class CreateUserBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    password: str
    role: str = "user"


@router.post("/login")
def login(body: LoginBody, request: Request) -> dict[str, Any]:
    user = services(request).auth.verify(body.username.strip(), body.password)
    if not user:
        raise AuthenticationError("用户名或密码错误")
    request.session.clear()
    request.session["username"] = user["username"]
    return {"user": user}


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)


@router.get("/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"user": user}


@router.get("/users")
def list_users(request: Request, _: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"items": services(request).auth.list_users()}


@router.post("/users", status_code=201)
def create_user(body: CreateUserBody, request: Request, _: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"user": services(request).auth.create_user(body.username, body.password, role=body.role)}
