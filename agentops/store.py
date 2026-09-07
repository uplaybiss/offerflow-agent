from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from core.errors import ConflictError, NotFoundError
from core.ids import new_id
from core.time import utc_now


AGENTOPS_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_config_versions (
    version_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'VALIDATED', 'RELEASED')),
    settings_json TEXT NOT NULL,
    settings_sha256 TEXT NOT NULL,
    validation_json TEXT NOT NULL DEFAULT '{}',
    revision INTEGER NOT NULL DEFAULT 1,
    created_by_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    validated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS agent_release_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    stable_version_id TEXT NOT NULL DEFAULT '',
    canary_version_id TEXT NOT NULL DEFAULT '',
    canary_percent REAL NOT NULL DEFAULT 0,
    generation INTEGER NOT NULL DEFAULT 0,
    updated_by_ref TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_release_audit (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    generation INTEGER NOT NULL,
    version_id TEXT NOT NULL DEFAULT '',
    actor_ref TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_release_audit_created
    ON agent_release_audit(created_at DESC);

CREATE TABLE IF NOT EXISTS agentops_commands (
    command_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any, default: Any) -> Any:
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class AgentOpsStore:
    def __init__(self, path: str) -> None:
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(AGENTOPS_SCHEMA)
            connection.execute(
                """
                INSERT OR IGNORE INTO agent_release_state (
                    singleton_id, updated_at
                ) VALUES (1, ?)
                """,
                (utc_now(),),
            )

    def migrate_enabled_tools(self, enabled_tools: list[str]) -> int:
        """Add the pre-whitelist semantic (all tools enabled) to legacy immutable configs."""
        migrated = 0
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT version_id, settings_json FROM agent_config_versions"
            ).fetchall()
            generation = int(connection.execute(
                "SELECT generation FROM agent_release_state WHERE singleton_id = 1"
            ).fetchone()[0])
            now = utc_now()
            for row in rows:
                settings = _load(row["settings_json"], {})
                if not isinstance(settings, dict) or "enabled_tools" in settings:
                    continue
                settings["enabled_tools"] = list(enabled_tools)
                serialized = _dump(settings)
                digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                connection.execute(
                    "UPDATE agent_config_versions SET settings_json = ?, settings_sha256 = ? WHERE version_id = ?",
                    (serialized, digest, str(row["version_id"])),
                )
                connection.execute(
                    """
                    INSERT INTO agent_release_audit (
                        event_id, event_type, generation, version_id, actor_ref,
                        detail_json, created_at
                    ) VALUES (?, 'CONFIG_SCHEMA_MIGRATED', ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id("AUD"), generation, str(row["version_id"]),
                        "system-migration", _dump({"added": "enabled_tools", "semantic": "all-existing-tools"}), now,
                    ),
                )
                migrated += 1
        return migrated

    @staticmethod
    def _configuration(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "version_id": str(row["version_id"]),
            "label": str(row["label"]),
            "status": str(row["status"]),
            "settings": _load(row["settings_json"], {}),
            "settings_sha256": str(row["settings_sha256"]),
            "validation": _load(row["validation_json"], {}),
            "revision": int(row["revision"]),
            "created_by_ref": str(row["created_by_ref"]),
            "created_at": str(row["created_at"]),
            "validated_at": str(row["validated_at"]),
        }

    @staticmethod
    def _release(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "stable_version_id": str(row["stable_version_id"]),
            "canary_version_id": str(row["canary_version_id"]),
            "canary_percent": float(row["canary_percent"]),
            "generation": int(row["generation"]),
            "updated_by_ref": str(row["updated_by_ref"]),
            "updated_at": str(row["updated_at"]),
        }

    def bootstrap(self, *, settings: dict[str, Any], settings_sha256: str, actor_ref: str) -> dict[str, Any]:
        with self.transaction() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM agent_config_versions").fetchone()[0])
            if count == 0:
                now = utc_now()
                version_id = new_id("CFG")
                validation = {"valid": True, "errors": [], "source": "environment-bootstrap"}
                connection.execute(
                    """
                    INSERT INTO agent_config_versions (
                        version_id, label, status, settings_json, settings_sha256,
                        validation_json, revision, created_by_ref, created_at, validated_at
                    ) VALUES (?, 'environment-baseline', 'RELEASED', ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (version_id, _dump(settings), settings_sha256, _dump(validation), actor_ref, now, now),
                )
                connection.execute(
                    """
                    UPDATE agent_release_state
                    SET stable_version_id = ?, canary_version_id = '', canary_percent = 0,
                        generation = 1, updated_by_ref = ?, updated_at = ?
                    WHERE singleton_id = 1
                    """,
                    (version_id, actor_ref, now),
                )
                connection.execute(
                    """
                    INSERT INTO agent_release_audit (
                        event_id, event_type, generation, version_id, actor_ref,
                        detail_json, created_at
                    ) VALUES (?, 'BASELINE_BOOTSTRAPPED', 1, ?, ?, '{}', ?)
                    """,
                    (new_id("AUD"), version_id, actor_ref, now),
                )
        return self.release_state()

    def create_configuration(
        self,
        *,
        label: str,
        settings: dict[str, Any],
        settings_sha256: str,
        actor_ref: str,
    ) -> dict[str, Any]:
        version_id = new_id("CFG")
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_config_versions (
                    version_id, label, status, settings_json, settings_sha256,
                    validation_json, revision, created_by_ref, created_at
                ) VALUES (?, ?, 'DRAFT', ?, ?, '{}', 1, ?, ?)
                """,
                (version_id, label, _dump(settings), settings_sha256, actor_ref, now),
            )
        return self.get_configuration(version_id)

    def get_configuration(self, version_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_config_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("运行配置不存在")
        return self._configuration(row)

    def list_configurations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_config_versions ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [self._configuration(row) for row in rows]

    def validate_configuration(
        self,
        *,
        version_id: str,
        expected_revision: int,
        validation: dict[str, Any],
        actor_ref: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_config_versions
                SET status = 'VALIDATED', validation_json = ?, revision = revision + 1,
                    validated_at = ?
                WHERE version_id = ? AND status = 'DRAFT' AND revision = ?
                """,
                (_dump(validation), now, version_id, expected_revision),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT status, revision FROM agent_config_versions WHERE version_id = ?",
                    (version_id,),
                ).fetchone()
                if row is None:
                    raise NotFoundError("运行配置不存在")
                raise ConflictError("配置已变化或不再是可校验草稿，请刷新后重试")
            generation = int(connection.execute(
                "SELECT generation FROM agent_release_state WHERE singleton_id = 1"
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO agent_release_audit (
                    event_id, event_type, generation, version_id, actor_ref,
                    detail_json, created_at
                ) VALUES (?, 'CONFIG_VALIDATED', ?, ?, ?, ?, ?)
                """,
                (new_id("AUD"), generation, version_id, actor_ref, _dump(validation), now),
            )
        return self.get_configuration(version_id)

    def release_state(self) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_release_state WHERE singleton_id = 1"
            ).fetchone()
        assert row is not None
        return self._release(row)

    def mutate_release(
        self,
        *,
        command_id: str,
        scope: str,
        payload_hash: str,
        expected_generation: int,
        stable_version_id: str,
        canary_version_id: str,
        canary_percent: float,
        version_id: str,
        actor_ref: str,
        event_type: str,
        detail: dict[str, Any],
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            prior = connection.execute(
                "SELECT scope, payload_hash, result_json FROM agentops_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if prior is not None:
                if str(prior["scope"]) != scope or str(prior["payload_hash"]) != payload_hash:
                    raise ConflictError("command_id 已用于不同的 AgentOps 操作")
                result = _load(prior["result_json"], {})
                result["idempotent_replay"] = True
                return result

            state_row = connection.execute(
                "SELECT * FROM agent_release_state WHERE singleton_id = 1"
            ).fetchone()
            assert state_row is not None
            if int(state_row["generation"]) != expected_generation:
                raise ConflictError("发布代次已变化，请刷新后重试")
            version_row = connection.execute(
                "SELECT * FROM agent_config_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
            if version_row is None:
                raise NotFoundError("运行配置不存在")
            if str(version_row["status"]) not in {"VALIDATED", "RELEASED"}:
                raise ConflictError("配置必须先通过校验才能发布")

            now = utc_now()
            generation = expected_generation + 1
            cursor = connection.execute(
                """
                UPDATE agent_release_state
                SET stable_version_id = ?, canary_version_id = ?, canary_percent = ?,
                    generation = ?, updated_by_ref = ?, updated_at = ?
                WHERE singleton_id = 1 AND generation = ?
                """,
                (
                    stable_version_id, canary_version_id, float(canary_percent), generation,
                    actor_ref, now, expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError("发布代次已变化，请刷新后重试")
            connection.execute(
                "UPDATE agent_config_versions SET status = 'RELEASED' WHERE version_id = ?",
                (version_id,),
            )
            connection.execute(
                """
                INSERT INTO agent_release_audit (
                    event_id, event_type, generation, version_id, actor_ref,
                    detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_id("AUD"), event_type, generation, version_id, actor_ref, _dump(detail), now),
            )
            state = {
                "stable_version_id": stable_version_id,
                "canary_version_id": canary_version_id,
                "canary_percent": float(canary_percent),
                "generation": generation,
                "updated_by_ref": actor_ref,
                "updated_at": now,
            }
            result = {"release": state, "idempotent_replay": False}
            connection.execute(
                """
                INSERT INTO agentops_commands (
                    command_id, scope, payload_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (command_id, scope, payload_hash, _dump(result), now),
            )
            return result

    def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_release_audit ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [
            {
                "event_id": str(row["event_id"]),
                "event_type": str(row["event_type"]),
                "generation": int(row["generation"]),
                "version_id": str(row["version_id"]),
                "actor_ref": str(row["actor_ref"]),
                "detail": _load(row["detail_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def table_names(self) -> list[str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [str(row["name"]) for row in rows]
