from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any

from core.database import Database
from core.errors import ConflictError, NotFoundError, ValidationError
from core.time import utc_now


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
PASSWORD_ITERATIONS = 310_000


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return salt.hex(), digest.hex()


class AuthService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def bootstrap_local_users(self) -> None:
        with self.database.connection() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        if count:
            return
        self.create_user("admin", "admin", role="admin")
        self.create_user("demo", "demo", role="user")

    def create_user(self, username: str, password: str, *, role: str = "user") -> dict[str, Any]:
        username = str(username or "").strip()
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValidationError("用户名需为 3-32 位字母、数字、点、下划线或连字符")
        if len(password) < 4 or len(password) > 128:
            raise ValidationError("密码长度需为 4-128 位")
        if role not in {"admin", "user"}:
            raise ValidationError("角色无效")
        salt, password_hash = _hash_password(password)
        now = utc_now()
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO users (
                        username, password_salt, password_hash, role, active,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 1, ?, ?)
                    """,
                    (username, salt, password_hash, role, now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ConflictError("用户名已存在") from exc
            raise
        return self.get_user(username)

    def verify(self, username: str, password: str) -> dict[str, Any] | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None or not bool(row["active"]):
            return None
        _, supplied = _hash_password(password, str(row["password_salt"]))
        if not hmac.compare_digest(supplied, str(row["password_hash"])):
            return None
        return self._public(row)

    def get_user(self, username: str) -> dict[str, Any]:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            raise NotFoundError("用户不存在")
        return self._public(row)

    def list_users(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY username").fetchall()
        return [self._public(row) for row in rows]

    @staticmethod
    def _public(row: Any) -> dict[str, Any]:
        return {
            "username": str(row["username"]),
            "role": str(row["role"]),
            "active": bool(row["active"]),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }
