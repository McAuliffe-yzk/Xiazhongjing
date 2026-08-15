"""SQLite-backed local settings and Skill registry."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from config import DATA_DIR


DB_PATH = DATA_DIR / "xiangzhongjing.db"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def initialize() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skills (
                name TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                phase TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL CHECK (source IN ('builtin', 'custom')),
                core INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                dir_path TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.commit()


def get_setting(key: str, default: str | None = None) -> str | None:
    initialize()
    with _connect() as connection:
        row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def set_setting(key: str, value: str) -> None:
    initialize()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, _now()),
        )
        connection.commit()


def get_all_settings() -> dict[str, str]:
    initialize()
    with _connect() as connection:
        rows = connection.execute("SELECT key, value FROM app_settings").fetchall()
    return {str(row["key"]): str(row["value"]) for row in rows}


def upsert_skill_registry(row: dict[str, Any]) -> None:
    initialize()
    fields = (
        "name",
        "display_name",
        "phase",
        "description",
        "source",
        "core",
        "enabled",
        "dir_path",
        "sort_order",
    )
    values = [row[field] for field in fields]
    now = _now()
    with _connect() as connection:
        connection.execute(
            f"""
            INSERT INTO skills ({', '.join(fields)}, created_at, updated_at)
            VALUES ({', '.join('?' for _ in fields)}, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                display_name = excluded.display_name,
                phase = excluded.phase,
                description = excluded.description,
                source = excluded.source,
                core = excluded.core,
                enabled = excluded.enabled,
                dir_path = excluded.dir_path,
                sort_order = excluded.sort_order,
                updated_at = excluded.updated_at
            """,
            (*values, now, now),
        )
        connection.commit()


def get_skill_registry(name: str) -> dict[str, Any] | None:
    initialize()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
    return dict(row) if row else None


def list_skills_registry() -> list[dict[str, Any]]:
    initialize()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM skills ORDER BY sort_order ASC, name ASC"
        ).fetchall()
    return [dict(row) for row in rows]


def set_skill_enabled(name: str, enabled: int) -> None:
    initialize()
    with _connect() as connection:
        connection.execute(
            "UPDATE skills SET enabled = ?, updated_at = ? WHERE name = ?",
            (1 if enabled else 0, _now(), name),
        )
        connection.commit()


def delete_skill_registry(name: str) -> None:
    initialize()
    with _connect() as connection:
        connection.execute("DELETE FROM skills WHERE name = ?", (name,))
        connection.commit()
