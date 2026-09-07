from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    password_salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    candidate_id TEXT PRIMARY KEY,
    owner_username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    graduation_year TEXT NOT NULL DEFAULT '',
    degree TEXT NOT NULL DEFAULT '',
    target_roles_json TEXT NOT NULL DEFAULT '[]',
    preferred_cities_json TEXT NOT NULL DEFAULT '[]',
    excluded_companies_json TEXT NOT NULL DEFAULT '[]',
    preferences_json TEXT NOT NULL DEFAULT '{}',
    skills_json TEXT NOT NULL DEFAULT '[]',
    current_resume_text TEXT NOT NULL DEFAULT '',
    current_resume_parsed_json TEXT NOT NULL DEFAULT '{}',
    current_resume_filename TEXT NOT NULL DEFAULT '',
    current_resume_sha256 TEXT NOT NULL DEFAULT '',
    resume_updated_at TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(owner_username) REFERENCES users(username) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    employment_type TEXT NOT NULL DEFAULT '',
    recruitment_cycle TEXT NOT NULL DEFAULT '',
    graduation_year TEXT NOT NULL DEFAULT '',
    deadline TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'EXPIRED', 'CLOSED', 'ARCHIVED')),
    description_text TEXT NOT NULL DEFAULT '',
    required_skills_json TEXT NOT NULL DEFAULT '[]',
    preferred_skills_json TEXT NOT NULL DEFAULT '[]',
    is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
    favorited_at TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK (source_type IN ('MANUAL', 'JD_PASTE', 'COMPANY_CAREER')),
    source_name TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    external_job_id TEXT NOT NULL DEFAULT '',
    company_career_url TEXT NOT NULL DEFAULT '',
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    content_sha256 TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_id, content_sha256),
    UNIQUE(candidate_id, job_id),
    FOREIGN KEY(candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_external_identity
    ON jobs(candidate_id, source_type, external_job_id)
    WHERE external_job_id <> '';
CREATE INDEX IF NOT EXISTS idx_jobs_candidate_status
    ON jobs(candidate_id, status, is_favorite, deadline, updated_at DESC);

CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('PLANNED', 'APPLIED', 'ASSESSMENT', 'INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN')),
    next_action TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    applied_at TEXT NOT NULL DEFAULT '',
    offer_at TEXT NOT NULL DEFAULT '',
    rejected_at TEXT NOT NULL DEFAULT '',
    withdrawn_at TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_id, job_id),
    FOREIGN KEY(candidate_id, job_id) REFERENCES jobs(candidate_id, job_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_applications_candidate_status
    ON applications(candidate_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS application_events (
    event_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL,
    from_status TEXT NOT NULL DEFAULT '',
    to_status TEXT NOT NULL,
    actor_username TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    command_id TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    resulting_version INTEGER NOT NULL CHECK (resulting_version >= 1),
    created_at TEXT NOT NULL,
    UNIQUE(application_id, sequence),
    UNIQUE(application_id, command_id),
    FOREIGN KEY(application_id) REFERENCES applications(application_id) ON DELETE CASCADE,
    FOREIGN KEY(actor_username) REFERENCES users(username) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_application_events_timeline
    ON application_events(application_id, sequence);

CREATE TABLE IF NOT EXISTS interview_rounds (
    round_id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL,
    round_no INTEGER NOT NULL CHECK (round_no >= 1),
    round_type TEXT NOT NULL DEFAULT 'OTHER'
        CHECK (round_type IN ('ASSESSMENT', 'TECHNICAL', 'HR', 'MANAGER', 'OTHER')),
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PLANNED'
        CHECK (status IN ('PLANNED', 'SCHEDULED', 'COMPLETED', 'CANCELLED')),
    scheduled_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(application_id, round_no),
    FOREIGN KEY(application_id) REFERENCES applications(application_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_interviews_schedule
    ON interview_rounds(application_id, status, scheduled_at);

CREATE TABLE IF NOT EXISTS job_search_tasks (
    task_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    job_id TEXT,
    application_id TEXT,
    interview_round_id TEXT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    task_type TEXT NOT NULL DEFAULT 'GENERAL'
        CHECK (task_type IN ('GENERAL', 'APPLICATION', 'ASSESSMENT', 'INTERVIEW', 'MATERIAL', 'FOLLOW_UP')),
    status TEXT NOT NULL DEFAULT 'TODO'
        CHECK (status IN ('TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED')),
    priority TEXT NOT NULL DEFAULT 'P2'
        CHECK (priority IN ('P1', 'P2', 'P3')),
    due_at TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'MANUAL'
        CHECK (origin IN ('MANUAL', 'SUGGESTED')),
    suggestion_key TEXT NOT NULL DEFAULT '',
    suggestion_source TEXT NOT NULL DEFAULT '',
    suggestion_payload_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE SET NULL,
    FOREIGN KEY(application_id) REFERENCES applications(application_id) ON DELETE SET NULL,
    FOREIGN KEY(interview_round_id) REFERENCES interview_rounds(round_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_candidate_due
    ON job_search_tasks(candidate_id, status, due_at, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_memories (
    memory_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    current_job_id TEXT,
    current_application_id TEXT,
    current_interview_id TEXT,
    current_task_id TEXT,
    last_user_goal TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_id, chat_id),
    FOREIGN KEY(candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
    FOREIGN KEY(current_job_id) REFERENCES jobs(job_id) ON DELETE SET NULL,
    FOREIGN KEY(current_application_id) REFERENCES applications(application_id) ON DELETE SET NULL,
    FOREIGN KEY(current_interview_id) REFERENCES interview_rounds(round_id) ON DELETE SET NULL,
    FOREIGN KEY(current_task_id) REFERENCES job_search_tasks(task_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_candidate_updated
    ON agent_memories(candidate_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS pending_actions (
    action_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    actor_username TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    action_type TEXT NOT NULL
        CHECK (action_type IN ('APPLICATION_TRANSITION', 'INTERVIEW_PROGRESSION')),
    payload_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    expected_version INTEGER NOT NULL CHECK (expected_version >= 1),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'EXECUTED', 'EXPIRED', 'CANCELLED', 'FAILED')),
    expires_at TEXT NOT NULL,
    confirmation_grant_hash TEXT NOT NULL DEFAULT '',
    grant_expires_at TEXT NOT NULL DEFAULT '',
    confirmed_at TEXT NOT NULL DEFAULT '',
    executed_at TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    failure_code TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(candidate_id, actor_username, chat_id, request_hash),
    FOREIGN KEY(candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
    FOREIGN KEY(actor_username) REFERENCES users(username) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_pending_actions_candidate_status
    ON pending_actions(candidate_id, status, expires_at, updated_at DESC);
"""


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


class Database:
    def __init__(self, path: str) -> None:
        self.path = str(Path(path).resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=10,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)
            self._migrate_phase3(connection)
            self._migrate_final_hardening(connection)

    @staticmethod
    def _migrate_phase3(connection: sqlite3.Connection) -> None:
        """Add Phase 3 task provenance columns to an existing Phase 1/2 database."""
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(job_search_tasks)").fetchall()
        }
        additions = {
            "origin": "TEXT NOT NULL DEFAULT 'MANUAL' CHECK (origin IN ('MANUAL', 'SUGGESTED'))",
            "suggestion_key": "TEXT NOT NULL DEFAULT ''",
            "suggestion_source": "TEXT NOT NULL DEFAULT ''",
            "suggestion_payload_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE job_search_tasks ADD COLUMN {name} {declaration}")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_suggestion_key
            ON job_search_tasks(candidate_id, suggestion_key)
            WHERE suggestion_key <> ''
            """
        )

    @staticmethod
    def _migrate_final_hardening(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'pending_actions'"
        ).fetchone()
        if not row or "INTERVIEW_PROGRESSION" in str(row["sql"]):
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("ALTER TABLE pending_actions RENAME TO pending_actions_phase4")
            connection.execute(
                """
                CREATE TABLE pending_actions (
                    action_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    actor_username TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    action_type TEXT NOT NULL
                        CHECK (action_type IN ('APPLICATION_TRANSITION', 'INTERVIEW_PROGRESSION')),
                    payload_json TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    expected_version INTEGER NOT NULL CHECK (expected_version >= 1),
                    status TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK (status IN ('PENDING', 'EXECUTED', 'EXPIRED', 'CANCELLED', 'FAILED')),
                    expires_at TEXT NOT NULL,
                    confirmation_grant_hash TEXT NOT NULL DEFAULT '',
                    grant_expires_at TEXT NOT NULL DEFAULT '',
                    confirmed_at TEXT NOT NULL DEFAULT '',
                    executed_at TEXT NOT NULL DEFAULT '',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    failure_code TEXT NOT NULL DEFAULT '',
                    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(candidate_id, actor_username, chat_id, request_hash),
                    FOREIGN KEY(candidate_id) REFERENCES candidate_profiles(candidate_id) ON DELETE CASCADE,
                    FOREIGN KEY(actor_username) REFERENCES users(username) ON DELETE RESTRICT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO pending_actions (
                    action_id, candidate_id, actor_username, chat_id, action_type,
                    payload_json, request_hash, expected_version, status, expires_at,
                    confirmation_grant_hash, grant_expires_at, confirmed_at, executed_at,
                    result_json, failure_code, version, created_at, updated_at
                )
                SELECT action_id, candidate_id, actor_username, chat_id, action_type,
                       payload_json, request_hash, expected_version, status, expires_at,
                       confirmation_grant_hash, grant_expires_at, confirmed_at, executed_at,
                       result_json, failure_code, version, created_at, updated_at
                FROM pending_actions_phase4
                """
            )
            connection.execute("DROP TABLE pending_actions_phase4")
            connection.execute(
                """
                CREATE INDEX idx_pending_actions_candidate_status
                ON pending_actions(candidate_id, status, expires_at, updated_at DESC)
                """
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def table_names(self) -> list[str]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [str(row["name"]) for row in rows]


def database_path() -> str:
    configured = os.getenv("OFFERFLOW_DB_PATH", "runtime/offerflow.db")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return str(path)
