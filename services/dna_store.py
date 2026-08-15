"""SQLite store for optional external blogger DNA reagents."""

from __future__ import annotations

import json
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
            CREATE TABLE IF NOT EXISTS style_dna_reagents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                source_text TEXT NOT NULL DEFAULT '',
                source_kind TEXT NOT NULL DEFAULT 'paste',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        connection.commit()


def _row_full(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    try:
        item["tags"] = json.loads(str(item.pop("tags_json", "[]")))
    except json.JSONDecodeError:
        item["tags"] = []
    return item


def create_dna_reagent(
    name: str,
    notes: str,
    content: str,
    tags: list[str],
    source_text: str,
    source_kind: str,
) -> dict[str, Any]:
    initialize()
    now = _now()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO style_dna_reagents
                (name, notes, content, tags_json, source_text, source_kind, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                notes,
                content,
                json.dumps(tags or [], ensure_ascii=False),
                source_text,
                source_kind,
                now,
                now,
            ),
        )
        connection.commit()
        reagent_id = int(cursor.lastrowid)
    reagent = get_dna_reagent(reagent_id)
    if reagent is None:
        raise ValueError("DNA 试剂创建失败")
    return reagent


def list_dna_reagents() -> list[dict[str, Any]]:
    initialize()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, name, notes, tags_json, source_kind, created_at, updated_at
            FROM style_dna_reagents
            ORDER BY id ASC
            """
        ).fetchall()
    return [_row_full(row) for row in rows]


def get_dna_reagent(reagent_id: int) -> dict[str, Any] | None:
    initialize()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM style_dna_reagents WHERE id = ?",
            (reagent_id,),
        ).fetchone()
    return _row_full(row) if row else None


def get_dna_reagents_by_ids(ids: list[int]) -> list[dict[str, Any]]:
    initialize()
    ordered: list[int] = []
    seen: set[int] = set()
    for value in ids:
        try:
            reagent_id = int(value)
        except (TypeError, ValueError):
            continue
        if reagent_id not in seen:
            seen.add(reagent_id)
            ordered.append(reagent_id)
    if not ordered:
        return []
    placeholders = ",".join("?" for _ in ordered)
    with _connect() as connection:
        rows = {
            int(row["id"]): row
            for row in connection.execute(
                f"SELECT * FROM style_dna_reagents WHERE id IN ({placeholders})",
                ordered,
            ).fetchall()
        }
    return [_row_full(rows[reagent_id]) for reagent_id in ordered if reagent_id in rows]


def update_dna_reagent(
    reagent_id: int,
    *,
    name: str,
    notes: str,
    content: str,
    tags: list[str],
) -> dict[str, Any] | None:
    initialize()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE style_dna_reagents
            SET name = ?, notes = ?, content = ?, tags_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                notes,
                content,
                json.dumps(tags or [], ensure_ascii=False),
                _now(),
                reagent_id,
            ),
        )
        connection.commit()
    if cursor.rowcount == 0:
        return None
    return get_dna_reagent(reagent_id)


def delete_dna_reagent(reagent_id: int) -> None:
    initialize()
    with _connect() as connection:
        connection.execute("DELETE FROM style_dna_reagents WHERE id = ?", (reagent_id,))
        connection.commit()
