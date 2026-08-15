"""匣中镜的 SQLite 持久化、Skill 版本与运行记录。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from config import BASE_DIR, DATA_DIR


LEGACY_DB_PATH = BASE_DIR / "xiangzhongjing.db"
DB_PATH = DATA_DIR / "xiangzhongjing.db"
BASELINE_STYLE_VERSION = "v2.2"
CREATION_QUALITY_TARGET_PROJECTS = 5

LEGACY_LIBRARY_BOOKS: dict[str, dict[str, str]] = {
    "jianlai": {"title": "《剑来》", "author": "烽火戏诸侯"},
    "musk": {"title": "《埃隆·马斯克传》", "author": "沃尔特·艾萨克森"},
    "daode": {"title": "《道德经》", "author": "老子"},
}

LEGACY_BOOK_PERSONAS: tuple[dict[str, Any], ...] = (
    {
        "id": "musk-action",
        "name": "马斯克",
        "book_ids": ["musk"],
        "description": "行动、风险、创业决策和极限执行。",
        "voice": "直接、行动导向，愿意讨论风险与代价。",
        "boundaries": "不虚构本人经历；没有书库依据时明确以思想推演作答。",
    },
    {
        "id": "chen-ping-an",
        "name": "陈平安",
        "book_ids": ["jianlai"],
        "description": "道路、长期主义、心气和选择。",
        "voice": "朴素、克制，先问本心，再谈怎么走路。",
        "boundaries": "不冒充小说原文；没有逐字依据时不输出引号式引用。",
    },
    {
        "id": "qi-jing-chun",
        "name": "齐静春",
        "book_ids": ["jianlai"],
        "description": "读书人的担当、温厚判断和对世事的体谅。",
        "voice": "温厚、清醒，兼顾道理、处境与担当。",
        "boundaries": "不冒充小说原文；没有逐字依据时不输出引号式引用。",
    },
    {
        "id": "laozi-daodejing",
        "name": "老子",
        "book_ids": ["daode"],
        "description": "取舍、顺势、自知、知止和克制。",
        "voice": "简洁、留白，以反问和辨析帮助用户看清取舍。",
        "boundaries": "只把已收录原句作为引文，其余内容明确属于当代阐释。",
    },
)


class StateConflictError(RuntimeError):
    def __init__(self, current_revision: int):
        super().__init__("工作区状态版本已更新")
        self.current_revision = current_revision


def _migrate_legacy_database() -> None:
    # An explicitly selected data directory is an isolation boundary for tests,
    # containers, community installs, and restored private copies.
    if os.getenv("XIANGZHONGJING_DATA_DIR", "").strip():
        return
    if DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_DB_PATH, DB_PATH)


_migrate_legacy_database()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _version_key(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", str(version))
    return tuple(int(number) for number in numbers) or (0,)


def _normalize_skill_version(skill_content: str, version: str) -> str:
    """Keep model-authored self-version references aligned with the stored version."""
    heading_pattern = r"(?m)^#\s*匣中镜创作撰写 Skill\s+(v[\d.]+)\s*$"
    heading = re.search(heading_pattern, skill_content)
    generated_version = heading.group(1) if heading else ""
    normalized = re.sub(
        heading_pattern,
        f"# 匣中镜创作撰写 Skill {version}",
        skill_content,
        count=1,
    )
    if generated_version and generated_version != version:
        normalized = re.sub(
            rf"(?<![\w.]){re.escape(generated_version)}(?![\d.])",
            version,
            normalized,
        )
    return normalized


def _has_reviewable_ab(evaluation: dict[str, Any]) -> bool:
    comparison = evaluation.get("ab_test")
    return bool(
        evaluation.get("ab_test_completed")
        and isinstance(comparison, dict)
        and comparison.get("passed") is True
        and str(comparison.get("current_copy") or "").strip()
        and str(comparison.get("candidate_copy") or "").strip()
    )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


_SCHEMA_MIGRATIONS: tuple[tuple[int, str, str], ...] = (
    (
        1,
        "personal_memory_engine_v1",
        """
        CREATE TABLE IF NOT EXISTS creator_memory_chunks (
            id TEXT PRIMARY KEY,
            source_document_id INTEGER NOT NULL,
            source_filename TEXT NOT NULL DEFAULT '',
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            char_start INTEGER NOT NULL DEFAULT 0,
            char_end INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_document_id, chunk_index),
            FOREIGN KEY(source_document_id) REFERENCES reference_documents(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS creator_memories (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL DEFAULT 'reflection',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            source_document_id INTEGER,
            source_filename TEXT NOT NULL DEFAULT '',
            source_session_id TEXT NOT NULL DEFAULT '',
            source_message_id TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.7,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'forgotten', 'archived')),
            occurred_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(source_document_id) REFERENCES reference_documents(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS dialogue_feedback (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            verdict TEXT NOT NULL
                CHECK (verdict IN ('like_self', 'unlike_self', 'remember', 'forget')),
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(message_id) REFERENCES dialogue_messages(id) ON DELETE CASCADE,
            FOREIGN KEY(session_id) REFERENCES dialogue_sessions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dialogue_memory_checkpoints (
            session_id TEXT PRIMARY KEY,
            summarized_message_count INTEGER NOT NULL DEFAULT 0,
            last_message_id TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES dialogue_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_creator_memory_chunks_document
        ON creator_memory_chunks(source_document_id, chunk_index);

        CREATE INDEX IF NOT EXISTS idx_creator_memories_status
        ON creator_memories(status, memory_type, updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_creator_memories_session
        ON creator_memories(source_session_id, source_message_id);

        CREATE INDEX IF NOT EXISTS idx_dialogue_feedback_session
        ON dialogue_feedback(session_id, updated_at DESC);
        """,
    ),
    (
        2,
        "creator_onboarding_library_v2",
        """
        CREATE TABLE IF NOT EXISTS library_books (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL DEFAULT 'user_import',
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived', 'error')),
            parse_count INTEGER NOT NULL DEFAULT 0,
            quotable_count INTEGER NOT NULL DEFAULT 0,
            note_count INTEGER NOT NULL DEFAULT 0,
            source_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS book_personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            book_ids_json TEXT NOT NULL DEFAULT '[]',
            description TEXT NOT NULL DEFAULT '',
            voice TEXT NOT NULL DEFAULT '',
            boundaries TEXT NOT NULL DEFAULT '',
            builtin INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'archived')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        ALTER TABLE book_citations ADD COLUMN book_id TEXT NOT NULL DEFAULT '';

        CREATE INDEX IF NOT EXISTS idx_library_books_status
        ON library_books(status, updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_book_personas_status
        ON book_personas(status, updated_at DESC);

        CREATE INDEX IF NOT EXISTS idx_book_citations_book_id
        ON book_citations(project_id, book_id, quality_status, material_type, id DESC);
        """,
    ),
)


def _legacy_book_id(title: str) -> str:
    normalized = re.sub(r"[《》\s]", "", str(title or "")).lower()
    for book_id, book in LEGACY_LIBRARY_BOOKS.items():
        expected = re.sub(r"[《》\s]", "", book["title"]).lower()
        if normalized and (normalized in expected or expected in normalized):
            return book_id
    return ""


def _slug_id(value: str, prefix: str) -> str:
    ascii_slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    if ascii_slug:
        return f"{prefix}-{ascii_slug[:48]}"
    digest = hashlib.sha1(str(value or uuid.uuid4().hex).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _refresh_library_book_counts(
    connection: sqlite3.Connection, book_id: str, *, now: str | None = None
) -> None:
    counts = connection.execute(
        """
        SELECT
            COUNT(*) AS parse_count,
            COUNT(DISTINCT source_title) AS source_count,
            SUM(CASE WHEN material_type = 'direct_quote' AND quality_status = 'valid' THEN 1 ELSE 0 END) AS quotable_count,
            SUM(CASE WHEN material_type IN ('reading_note', 'context_excerpt') AND quality_status != 'quarantined' THEN 1 ELSE 0 END) AS note_count
        FROM book_citations
        WHERE project_id = '' AND book_id = ?
        """,
        (book_id,),
    ).fetchone()
    connection.execute(
        """
        UPDATE library_books
        SET parse_count = ?, quotable_count = ?, note_count = ?, source_count = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            int(counts["parse_count"] or 0),
            int(counts["quotable_count"] or 0),
            int(counts["note_count"] or 0),
            int(counts["source_count"] or 0),
            now or _now(),
            book_id,
        ),
    )


def _backfill_library_catalog(connection: sqlite3.Connection) -> None:
    """Promote existing citation-only books without seeding blank installations."""
    rows = connection.execute(
        "SELECT book, COUNT(*) AS count FROM book_citations WHERE project_id = '' GROUP BY book"
    ).fetchall()
    now = _now()
    available_ids: set[str] = set()
    for row in rows:
        title = str(row["book"] or "").strip()
        if not title:
            continue
        book_id = _legacy_book_id(title) or _slug_id(title, "book")
        legacy = LEGACY_LIBRARY_BOOKS.get(book_id, {})
        connection.execute(
            """
            INSERT INTO library_books (
                id, title, author, description, source_type, status,
                parse_count, created_at, updated_at
            ) VALUES (?, ?, ?, '', ?, 'active', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                parse_count = MAX(library_books.parse_count, excluded.parse_count),
                updated_at = excluded.updated_at
            """,
            (
                book_id,
                legacy.get("title") or title,
                legacy.get("author") or "",
                "legacy" if book_id in LEGACY_LIBRARY_BOOKS else "citation_migration",
                int(row["count"] or 0),
                now,
                now,
            ),
        )
        connection.execute(
            "UPDATE book_citations SET book_id = ? WHERE project_id = '' AND book = ? AND book_id = ''",
            (book_id, title),
        )
        available_ids.add(book_id)

    for persona in LEGACY_BOOK_PERSONAS:
        if not set(persona["book_ids"]).issubset(available_ids):
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO book_personas (
                id, name, book_ids_json, description, voice, boundaries,
                builtin, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 'active', ?, ?)
            """,
            (
                persona["id"],
                persona["name"],
                json.dumps(persona["book_ids"], ensure_ascii=False),
                persona["description"],
                persona["voice"],
                persona["boundaries"],
                now,
                now,
            ),
        )

    for book_id in available_ids:
        _refresh_library_book_counts(connection, book_id, now=now)


def _apply_schema_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            applied_at TEXT NOT NULL
        )
        """
    )
    applied = {
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version, name, sql in _SCHEMA_MIGRATIONS:
        if version in applied:
            continue
        connection.executescript(sql)
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, name, _now()),
        )


def initialize_store() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS reference_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                content_hash TEXT NOT NULL UNIQUE,
                text_content TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS style_skill_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK (status IN ('candidate', 'published', 'archived')),
                source_document_id INTEGER,
                skill_content TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                published_at TEXT,
                FOREIGN KEY(source_document_id) REFERENCES reference_documents(id)
            );

            CREATE TABLE IF NOT EXISTS skill_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                skill_name TEXT NOT NULL,
                skill_version TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                input_summary TEXT NOT NULL,
                output_summary TEXT NOT NULL DEFAULT '',
                error_code TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                finished_at TEXT,
                latency_ms INTEGER
            );

            CREATE TABLE IF NOT EXISTS book_citations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL DEFAULT '',
                book TEXT NOT NULL,
                quote TEXT NOT NULL,
                attribution TEXT NOT NULL,
                source_title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                evidence_text TEXT NOT NULL,
                material_type TEXT NOT NULL DEFAULT 'direct_quote',
                quality_status TEXT NOT NULL DEFAULT 'pending_review',
                quality_reason TEXT NOT NULL DEFAULT '',
                source_locator TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS generation_jobs (
                generation_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                current_stage TEXT NOT NULL DEFAULT '',
                failed_stage TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error_json TEXT NOT NULL DEFAULT '{}',
                attempt INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS style_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL DEFAULT '',
                style_version TEXT NOT NULL,
                decision TEXT NOT NULL,
                feedback TEXT NOT NULL DEFAULT '',
                copy_snapshot TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS dialogue_sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL CHECK (mode IN ('mirror', 'book')),
                persona_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                source_scope_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT,
                pinned_at TEXT,
                deleted_at TEXT,
                last_message_at TEXT,
                last_message_preview TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS dialogue_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                citations_json TEXT NOT NULL DEFAULT '[]',
                extractable_json TEXT NOT NULL DEFAULT '[]',
                skill_trace_json TEXT NOT NULL DEFAULT '[]',
                turn_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'completed',
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES dialogue_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS dialogue_memories (
                session_id TEXT PRIMARY KEY,
                summary_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES dialogue_sessions(id)
            );

            CREATE TABLE IF NOT EXISTS persona_assets (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                asset_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS creation_quality_meta (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                tracking_started_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS creation_quality_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                diary_entry_id TEXT NOT NULL UNIQUE,
                project_id TEXT NOT NULL,
                project_title TEXT NOT NULL DEFAULT '',
                generation_id TEXT NOT NULL DEFAULT '',
                style_version TEXT NOT NULL DEFAULT '',
                generation_attempts INTEGER NOT NULL DEFAULT 0,
                regeneration_count INTEGER NOT NULL DEFAULT 0,
                successful_generations INTEGER NOT NULL DEFAULT 0,
                failed_generations INTEGER NOT NULL DEFAULT 0,
                first_generation_at TEXT,
                last_generation_at TEXT,
                published_at TEXT NOT NULL,
                creation_duration_seconds INTEGER,
                generation_elapsed_seconds INTEGER NOT NULL DEFAULT 0,
                generated_chars INTEGER NOT NULL DEFAULT 0,
                published_chars INTEGER NOT NULL DEFAULT 0,
                edit_similarity REAL,
                edit_distance_ratio REAL,
                adoption_status TEXT NOT NULL,
                generated_copy TEXT NOT NULL DEFAULT '',
                published_copy TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_creation_quality_project
            ON creation_quality_outcomes(project_id, created_at DESC);
            """
        )
        _apply_schema_migrations(connection)
        _backfill_library_catalog(connection)
        connection.execute(
            """
            INSERT OR IGNORE INTO creation_quality_meta (id, tracking_started_at)
            VALUES (1, ?)
            """,
            (_now(),),
        )
        app_state_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(app_state)").fetchall()
        }
        if "revision" not in app_state_columns:
            connection.execute(
                "ALTER TABLE app_state ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
            )
        session_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(dialogue_sessions)").fetchall()
        }
        for column, definition in {
            "pinned_at": "TEXT",
            "deleted_at": "TEXT",
            "last_message_at": "TEXT",
            "last_message_preview": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in session_columns:
                connection.execute(
                    f"ALTER TABLE dialogue_sessions ADD COLUMN {column} {definition}"
                )
        message_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(dialogue_messages)").fetchall()
        }
        for column, definition in {
            "turn_id": "TEXT NOT NULL DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'completed'",
        }.items():
            if column not in message_columns:
                connection.execute(
                    f"ALTER TABLE dialogue_messages ADD COLUMN {column} {definition}"
                )
        citation_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(book_citations)").fetchall()
        }
        for column, definition in {
            "material_type": "TEXT NOT NULL DEFAULT 'direct_quote'",
            "quality_status": "TEXT NOT NULL DEFAULT 'pending_review'",
            "quality_reason": "TEXT NOT NULL DEFAULT ''",
            "source_locator": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in citation_columns:
                connection.execute(
                    f"ALTER TABLE book_citations ADD COLUMN {column} {definition}"
                )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_book_citations_quality
            ON book_citations(project_id, book, quality_status, material_type, id DESC)
            """
        )
        connection.commit()
    from config import reload_settings
    from services import dna_store, settings_store
    from services.skill_runtime import sync_skill_registry

    settings_store.DB_PATH = DB_PATH
    dna_store.DB_PATH = DB_PATH
    settings_store.initialize()
    dna_store.initialize()
    sync_skill_registry()
    reload_settings()


def load_state() -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT state_json, revision FROM app_state WHERE id = 1"
        ).fetchone()
    if not row:
        return {"_revision": 0}
    try:
        state = json.loads(row["state_json"])
    except json.JSONDecodeError:
        state = {}
    if not isinstance(state, dict):
        state = {}
    state["_revision"] = int(row["revision"] or 0)
    return state


def _copy_signature(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _normalized_edit_distance(source: str, target: str) -> float:
    """Return the exact character-level Levenshtein distance as a 0-1 ratio."""
    if source == target:
        return 0.0
    if not source or not target:
        return 1.0
    if len(source) < len(target):
        source, target = target, source
    previous = list(range(len(target) + 1))
    for source_index, source_character in enumerate(source, start=1):
        current = [source_index]
        for target_index, target_character in enumerate(target, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[target_index] + 1,
                    previous[target_index - 1]
                    + (source_character != target_character),
                )
            )
        previous = current
    return previous[-1] / max(len(source), len(target))


def _state_diary_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries = state.get("diaryEntries")
    if not isinstance(entries, list):
        return []
    return [item for item in entries if isinstance(item, dict)]


def _record_publication_outcome(
    connection: sqlite3.Connection,
    entry: dict[str, Any],
) -> None:
    diary_entry_id = str(entry.get("id") or "").strip()
    project_id = str(entry.get("project_id") or "").strip()
    published_copy = str(entry.get("copy") or "").strip()
    if not diary_entry_id or not project_id or not published_copy:
        return
    if connection.execute(
        "SELECT id FROM creation_quality_outcomes WHERE diary_entry_id = ?",
        (diary_entry_id,),
    ).fetchone():
        return
    if connection.execute(
        "SELECT id FROM creation_quality_outcomes WHERE project_id = ?",
        (project_id,),
    ).fetchone():
        return
    tracked_projects = connection.execute(
        "SELECT COUNT(DISTINCT project_id) AS count FROM creation_quality_outcomes"
    ).fetchone()
    if int(tracked_projects["count"] if tracked_projects else 0) >= CREATION_QUALITY_TARGET_PROJECTS:
        return

    tracking_row = connection.execute(
        "SELECT tracking_started_at FROM creation_quality_meta WHERE id = 1"
    ).fetchone()
    tracking_started_at = str(tracking_row["tracking_started_at"] if tracking_row else _now())
    previous = connection.execute(
        """
        SELECT created_at FROM creation_quality_outcomes
        WHERE project_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (project_id,),
    ).fetchone()
    session_started_at = max(
        tracking_started_at,
        str(previous["created_at"]) if previous else tracking_started_at,
    )
    jobs = connection.execute(
        """
        SELECT generation_id, status, result_json, created_at, updated_at
        FROM generation_jobs
        WHERE project_id = ? AND created_at >= ?
        ORDER BY created_at ASC
        """,
        (project_id, session_started_at),
    ).fetchall()
    generation_attempts = len(jobs)
    successful = [row for row in jobs if row["status"] == "succeeded"]
    failed = [row for row in jobs if row["status"] == "failed"]
    latest_success = successful[-1] if successful else None
    generated_copy = ""
    style_version = ""
    generation_id = ""
    if latest_success:
        generation_id = str(latest_success["generation_id"] or "")
        try:
            result = json.loads(latest_success["result_json"] or "{}")
        except json.JSONDecodeError:
            result = {}
        generated_copy = str(result.get("copy") or "").strip()
        style_version = str(result.get("style_version") or "").strip()

    generated_signature = _copy_signature(generated_copy)
    published_signature = _copy_signature(published_copy)
    similarity: float | None = None
    distance: float | None = None
    if generated_signature:
        distance = _normalized_edit_distance(generated_signature, published_signature)
        similarity = 1.0 - distance
        if distance <= 0.03:
            adoption_status = "direct"
        elif distance <= 0.2:
            adoption_status = "light_edit"
        else:
            adoption_status = "major_edit"
    else:
        adoption_status = "no_ai_baseline"

    now = _now()
    published_at = str(entry.get("published_at") or now)
    first_generation_at = str(jobs[0]["created_at"]) if jobs else None
    last_generation_at = str(jobs[-1]["updated_at"]) if jobs else None
    duration_seconds: int | None = None
    if first_generation_at:
        duration_row = connection.execute(
            "SELECT MAX(0, CAST((julianday(?) - julianday(?)) * 86400 AS INTEGER)) AS seconds",
            (published_at, first_generation_at),
        ).fetchone()
        duration_seconds = int(duration_row["seconds"]) if duration_row and duration_row["seconds"] is not None else None
    generation_elapsed_row = connection.execute(
        """
        SELECT COALESCE(SUM(MAX(0, (julianday(updated_at) - julianday(created_at)) * 86400)), 0) AS seconds
        FROM generation_jobs
        WHERE project_id = ? AND created_at >= ?
        """,
        (project_id, session_started_at),
    ).fetchone()
    generation_elapsed_seconds = int(round(float(generation_elapsed_row["seconds"] or 0)))
    connection.execute(
        """
        INSERT INTO creation_quality_outcomes (
            diary_entry_id, project_id, project_title, generation_id,
            style_version, generation_attempts, regeneration_count,
            successful_generations, failed_generations, first_generation_at,
            last_generation_at, published_at, creation_duration_seconds,
            generation_elapsed_seconds, generated_chars, published_chars,
            edit_similarity, edit_distance_ratio, adoption_status,
            generated_copy, published_copy, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            diary_entry_id,
            project_id,
            str(entry.get("project_title") or ""),
            generation_id,
            style_version,
            generation_attempts,
            max(0, generation_attempts - 1),
            len(successful),
            len(failed),
            first_generation_at,
            last_generation_at,
            published_at,
            duration_seconds,
            generation_elapsed_seconds,
            len(generated_signature),
            len(published_signature),
            similarity,
            distance,
            adoption_status,
            generated_copy,
            published_copy,
            now,
        ),
    )


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    initialize_store()
    now = _now()
    expected_revision_value = state.get("_revision")
    expected_revision = (
        int(expected_revision_value)
        if isinstance(expected_revision_value, (int, float))
        else None
    )
    stored_state = {key: value for key, value in state.items() if key != "_revision"}
    payload = json.dumps(stored_state, ensure_ascii=False)
    with _connect() as connection:
        previous_row = connection.execute(
            "SELECT state_json, revision FROM app_state WHERE id = 1"
        ).fetchone()
        current_revision = int(previous_row["revision"] or 0) if previous_row else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise StateConflictError(current_revision)
        try:
            previous_state = json.loads(previous_row["state_json"]) if previous_row else {}
        except json.JSONDecodeError:
            previous_state = {}
        previous_diary_ids = {
            str(item.get("id") or "")
            for item in _state_diary_entries(previous_state)
        }
        new_diary_entries = [
            item
            for item in _state_diary_entries(state)
            if str(item.get("id") or "") not in previous_diary_ids
        ]
        next_revision = current_revision + 1
        if previous_row:
            cursor = connection.execute(
                """
                UPDATE app_state
                SET state_json = ?, updated_at = ?, revision = ?
                WHERE id = 1 AND revision = ?
                """,
                (payload, now, next_revision, current_revision),
            )
            if cursor.rowcount != 1:
                latest = connection.execute(
                    "SELECT revision FROM app_state WHERE id = 1"
                ).fetchone()
                raise StateConflictError(int(latest["revision"] if latest else 0))
        else:
            connection.execute(
                """
                INSERT INTO app_state (id, state_json, updated_at, revision)
                VALUES (1, ?, ?, ?)
                """,
                (payload, now, next_revision),
            )
        for entry in new_diary_entries:
            _record_publication_outcome(connection, entry)
        connection.commit()
    return {"saved": True, "updated_at": now, "revision": next_revision}


def creation_quality_summary(limit: int = 5) -> dict[str, Any]:
    initialize_store()
    limit = max(1, min(int(limit), 20))
    with _connect() as connection:
        tracking_row = connection.execute(
            "SELECT tracking_started_at FROM creation_quality_meta WHERE id = 1"
        ).fetchone()
        tracking_started_at = str(tracking_row["tracking_started_at"] if tracking_row else _now())
        rows = connection.execute(
            """
            SELECT id, diary_entry_id, project_id, project_title, generation_id,
                   style_version, generation_attempts, regeneration_count,
                   successful_generations, failed_generations, first_generation_at,
                   last_generation_at, published_at, creation_duration_seconds,
                   generation_elapsed_seconds, generated_chars, published_chars,
                   edit_similarity, edit_distance_ratio, adoption_status, created_at
            FROM creation_quality_outcomes
            WHERE created_at >= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (tracking_started_at, limit),
        ).fetchall()
        totals = connection.execute(
            """
            SELECT COUNT(*) AS samples,
                   COALESCE(AVG(regeneration_count), 0) AS avg_regenerations,
                   COALESCE(AVG(creation_duration_seconds), 0) AS avg_creation_seconds,
                   COALESCE(AVG(generation_elapsed_seconds), 0) AS avg_generation_seconds,
                   COALESCE(AVG(edit_distance_ratio), 0) AS avg_edit_distance
            FROM creation_quality_outcomes
            WHERE created_at >= ?
            """,
            (tracking_started_at,),
        ).fetchone()
        status_rows = connection.execute(
            """
            SELECT adoption_status, COUNT(*) AS count
            FROM creation_quality_outcomes
            WHERE created_at >= ?
            GROUP BY adoption_status
            """,
            (tracking_started_at,),
        ).fetchall()
        generation_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count, COUNT(DISTINCT project_id) AS projects
            FROM generation_jobs
            WHERE created_at >= ?
            GROUP BY status
            """,
            (tracking_started_at,),
        ).fetchall()
    generation_status = {str(row["status"]): int(row["count"]) for row in generation_rows}
    tracked_projects = max((int(row["projects"]) for row in generation_rows), default=0)
    return {
        "tracking_started_at": tracking_started_at,
        "target_samples": CREATION_QUALITY_TARGET_PROJECTS,
        "sample_count": int(totals["samples"] or 0),
        "tracked_projects": tracked_projects,
        "generation_status": generation_status,
        "averages": {
            "regenerations": round(float(totals["avg_regenerations"] or 0), 2),
            "creation_seconds": round(float(totals["avg_creation_seconds"] or 0), 1),
            "generation_seconds": round(float(totals["avg_generation_seconds"] or 0), 1),
            "edit_distance_ratio": round(float(totals["avg_edit_distance"] or 0), 4),
        },
        "adoption_counts": {
            str(row["adoption_status"]): int(row["count"])
            for row in status_rows
        },
        "outcomes": [dict(row) for row in rows],
    }


def create_generation_job(payload: dict[str, Any]) -> dict[str, Any]:
    initialize_store()
    generation_id = uuid.uuid4().hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO generation_jobs (
                generation_id, project_id, status, payload_json, created_at, updated_at
            ) VALUES (?, ?, 'pending', ?, ?, ?)
            """,
            (
                generation_id,
                str(payload.get("project_id") or ""),
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
    return {"generation_id": generation_id, "status": "pending", "created_at": now}


def get_generation_job(generation_id: str) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM generation_jobs WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    for key in ("payload_json", "checkpoint_json", "result_json", "error_json"):
        target = key.removesuffix("_json")
        try:
            item[target] = json.loads(item.pop(key) or "{}")
        except json.JSONDecodeError:
            item[target] = {}
            item.pop(key, None)
    return item


def update_generation_job(
    generation_id: str,
    *,
    status: str | None = None,
    current_stage: str | None = None,
    failed_stage: str | None = None,
    payload: dict[str, Any] | None = None,
    checkpoint: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    increment_attempt: bool = False,
) -> dict[str, Any]:
    initialize_store()
    assignments = ["updated_at = ?"]
    values: list[Any] = [_now()]
    for column, value in (
        ("status", status),
        ("current_stage", current_stage),
        ("failed_stage", failed_stage),
    ):
        if value is not None:
            assignments.append(f"{column} = ?")
            values.append(value)
    for column, value in (
        ("payload_json", payload),
        ("checkpoint_json", checkpoint),
        ("result_json", result),
        ("error_json", error),
    ):
        if value is not None:
            assignments.append(f"{column} = ?")
            values.append(json.dumps(value, ensure_ascii=False))
    if increment_attempt:
        assignments.append("attempt = attempt + 1")
    values.append(generation_id)
    with _connect() as connection:
        connection.execute(
            f"UPDATE generation_jobs SET {', '.join(assignments)} WHERE generation_id = ?",
            values,
        )
        connection.commit()
    job = get_generation_job(generation_id)
    if not job:
        raise ValueError("生成任务不存在")
    return job


def save_style_feedback(
    project_id: str,
    style_version: str,
    decision: str,
    feedback: str,
    copy_snapshot: str,
) -> dict[str, Any]:
    initialize_store()
    now = _now()
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO style_feedback (
                project_id, style_version, decision, feedback, copy_snapshot, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_id, style_version, decision, feedback, copy_snapshot, now),
        )
        connection.commit()
    return {"id": int(cursor.lastrowid), "saved": True, "created_at": now}


def recent_style_feedback(limit: int = 30) -> list[dict[str, Any]]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, project_id, style_version, decision, feedback,
                   copy_snapshot, created_at
            FROM style_feedback ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [dict(row) for row in rows]


def start_skill_run(
    run_id: str,
    skill_name: str,
    skill_version: str,
    model: str,
    input_summary: str,
) -> None:
    initialize_store()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO skill_runs (
                run_id, skill_name, skill_version, model, status,
                input_summary, started_at
            ) VALUES (?, ?, ?, ?, 'running', ?, ?)
            """,
            (run_id, skill_name, skill_version, model, input_summary[:1200], _now()),
        )
        connection.commit()


def finish_skill_run(
    run_id: str,
    status: str,
    latency_ms: int,
    output_summary: str = "",
    error_code: str = "",
    error_message: str = "",
) -> None:
    initialize_store()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE skill_runs
            SET status = ?, output_summary = ?, error_code = ?,
                error_message = ?, finished_at = ?, latency_ms = ?
            WHERE run_id = ?
            """,
            (
                status,
                output_summary[:1200],
                error_code,
                error_message[:1200],
                _now(),
                latency_ms,
                run_id,
            ),
        )
        connection.commit()


def recent_skill_runs(limit: int = 30) -> list[dict[str, Any]]:
    initialize_store()
    safe_limit = max(1, min(limit, 100))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT run_id, skill_name, skill_version, model, status,
                   error_code, error_message, started_at, finished_at, latency_ms
            FROM skill_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def create_dialogue_session(
    project_id: str,
    mode: str,
    persona_id: str,
    title: str = "",
    source_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_store()
    if mode not in {"mirror", "book"}:
        raise ValueError("会话模式必须为 mirror 或 book")
    session_id = uuid.uuid4().hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO dialogue_sessions (
                id, project_id, mode, persona_id, title,
                source_scope_json, created_at, updated_at,
                last_message_at, last_message_preview
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                project_id,
                mode,
                persona_id,
                title or ("镜中人对话" if mode == "mirror" else "书中人对话"),
                json.dumps(source_scope or {}, ensure_ascii=False),
                now,
                now,
                None,
                "",
            ),
        )
        connection.commit()
    session = get_dialogue_session(session_id)
    if not session:
        raise ValueError("对话会话创建失败")
    return session


def list_dialogue_sessions(
    project_id: str = "",
    include_archived: bool = False,
    limit: int = 50,
    *,
    query: str = "",
    mode: str = "",
    persona_id: str = "",
    include_deleted: bool = False,
    global_only: bool = False,
) -> list[dict[str, Any]]:
    initialize_store()
    clauses = []
    values: list[Any] = []
    if project_id:
        clauses.append("project_id = ?")
        values.append(project_id)
    elif global_only:
        clauses.append("project_id = ''")
    if not include_archived:
        clauses.append("archived_at IS NULL")
    if include_deleted:
        clauses.append("deleted_at IS NOT NULL")
    else:
        clauses.append("deleted_at IS NULL")
    if query.strip():
        clauses.append("(title LIKE ? OR last_message_preview LIKE ?)")
        needle = f"%{query.strip()}%"
        values.extend([needle, needle])
    if mode in {"mirror", "book"}:
        clauses.append("mode = ?")
        values.append(mode)
    if persona_id:
        clauses.append("persona_id = ?")
        values.append(persona_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(limit, 500)))
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, project_id, mode, persona_id, title, source_scope_json,
                   created_at, updated_at, archived_at, pinned_at, deleted_at,
                   last_message_at, last_message_preview,
                   (SELECT COUNT(*) FROM dialogue_messages dm WHERE dm.session_id = dialogue_sessions.id) AS message_count
            FROM dialogue_sessions
            {where}
            ORDER BY pinned_at IS NULL ASC, updated_at DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
    sessions: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["source_scope"] = _json_load(item.pop("source_scope_json"), {})
        sessions.append(item)
    return sessions


def get_dialogue_session(session_id: str) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, project_id, mode, persona_id, title, source_scope_json,
                   created_at, updated_at, archived_at, pinned_at, deleted_at,
                   last_message_at, last_message_preview,
                   (SELECT COUNT(*) FROM dialogue_messages dm WHERE dm.session_id = dialogue_sessions.id) AS message_count
            FROM dialogue_sessions WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["source_scope"] = _json_load(item.pop("source_scope_json"), {})
    return item


def update_dialogue_session(
    session_id: str,
    *,
    title: str | None = None,
    source_scope: dict[str, Any] | None = None,
    archived: bool | None = None,
    pinned: bool | None = None,
    deleted: bool | None = None,
) -> dict[str, Any]:
    initialize_store()
    assignments = ["updated_at = ?"]
    values: list[Any] = [_now()]
    if title is not None:
        assignments.append("title = ?")
        values.append(title)
    if source_scope is not None:
        assignments.append("source_scope_json = ?")
        values.append(json.dumps(source_scope, ensure_ascii=False))
    if archived is not None:
        assignments.append("archived_at = ?")
        values.append(_now() if archived else None)
    if pinned is not None:
        assignments.append("pinned_at = ?")
        values.append(_now() if pinned else None)
    if deleted is not None:
        assignments.append("deleted_at = ?")
        values.append(_now() if deleted else None)
    values.append(session_id)
    with _connect() as connection:
        connection.execute(
            f"UPDATE dialogue_sessions SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        connection.commit()
    session = get_dialogue_session(session_id)
    if not session:
        raise ValueError("对话会话不存在")
    return session


def add_dialogue_message(
    session_id: str,
    role: str,
    content: str,
    *,
    payload: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    extractable: list[dict[str, Any]] | None = None,
    skill_trace: list[dict[str, Any]] | None = None,
    turn_id: str = "",
    status: str = "completed",
) -> dict[str, Any]:
    initialize_store()
    if role not in {"user", "assistant", "system"}:
        raise ValueError("消息角色必须为 user、assistant 或 system")
    message_id = uuid.uuid4().hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO dialogue_messages (
                id, session_id, role, content, payload_json, citations_json,
                extractable_json, skill_trace_json, turn_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                role,
                content,
                json.dumps(payload or {}, ensure_ascii=False),
                json.dumps(citations or [], ensure_ascii=False),
                json.dumps(extractable or [], ensure_ascii=False),
                json.dumps(skill_trace or [], ensure_ascii=False),
                turn_id,
                status if status in {"pending", "completed", "failed"} else "completed",
                now,
            ),
        )
        connection.execute(
            """UPDATE dialogue_sessions
               SET updated_at = ?, last_message_at = ?, last_message_preview = ?
               WHERE id = ?""",
            (now, now, content.replace("\n", " ").strip()[:140], session_id),
        )
        connection.commit()
    return {
        "id": message_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "payload": payload or {},
        "citations": citations or [],
        "extractable": extractable or [],
        "skill_trace": skill_trace or [],
        "turn_id": turn_id,
        "status": status if status in {"pending", "completed", "failed"} else "completed",
        "created_at": now,
    }


def get_dialogue_message(message_id: str) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            """SELECT id, session_id, role, content, payload_json, citations_json,
                      extractable_json, skill_trace_json, turn_id, status, created_at
               FROM dialogue_messages WHERE id = ?""",
            (message_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["payload"] = _json_load(item.pop("payload_json"), {})
    item["citations"] = _json_load(item.pop("citations_json"), [])
    item["extractable"] = _json_load(item.pop("extractable_json"), [])
    item["skill_trace"] = _json_load(item.pop("skill_trace_json"), [])
    with _connect() as connection:
        feedback = connection.execute(
            """
            SELECT verdict, note, updated_at
            FROM dialogue_feedback
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
    item["feedback"] = dict(feedback) if feedback else {}
    return item


def update_dialogue_message(
    message_id: str,
    *,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initialize_store()
    assignments: list[str] = []
    values: list[Any] = []
    if status is not None:
        if status not in {"pending", "completed", "failed"}:
            raise ValueError("消息状态无效")
        assignments.append("status = ?")
        values.append(status)
    if payload is not None:
        assignments.append("payload_json = ?")
        values.append(json.dumps(payload, ensure_ascii=False))
    if not assignments:
        message = get_dialogue_message(message_id)
        if not message:
            raise ValueError("对话消息不存在")
        return message
    values.append(message_id)
    with _connect() as connection:
        connection.execute(
            f"UPDATE dialogue_messages SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        connection.commit()
    message = get_dialogue_message(message_id)
    if not message:
        raise ValueError("对话消息不存在")
    return message


def _message_cursor(item: dict[str, Any]) -> str:
    return f"{item.get('created_at') or ''}|{item.get('id') or ''}"


def list_dialogue_messages_page(
    session_id: str,
    limit: int = 30,
    before: str = "",
) -> dict[str, Any]:
    initialize_store()
    safe_limit = max(1, min(limit, 80))
    before_time = ""
    before_id = ""
    if before and "|" in before:
        before_time, before_id = before.split("|", 1)
    clauses = ["session_id = ?"]
    values: list[Any] = [session_id]
    if before_time and before_id:
        clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
        values.extend([before_time, before_time, before_id])
    values.append(safe_limit + 1)
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, session_id, role, content, payload_json, citations_json,
                   extractable_json, skill_trace_json, turn_id, status, created_at
            FROM dialogue_messages
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
    has_more = len(rows) > safe_limit
    rows = rows[:safe_limit]
    messages: list[dict[str, Any]] = []
    feedback_by_message: dict[str, dict[str, Any]] = {}
    message_ids = [str(row["id"]) for row in rows]
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        with _connect() as feedback_connection:
            feedback_rows = feedback_connection.execute(
                f"""
                SELECT message_id, verdict, note, updated_at
                FROM dialogue_feedback
                WHERE message_id IN ({placeholders})
                """,
                message_ids,
            ).fetchall()
        feedback_by_message = {
            str(row["message_id"]): {
                "verdict": row["verdict"],
                "note": row["note"],
                "updated_at": row["updated_at"],
            }
            for row in feedback_rows
        }
    for row in reversed(rows):
        item = dict(row)
        item["payload"] = _json_load(item.pop("payload_json"), {})
        item["citations"] = _json_load(item.pop("citations_json"), [])
        item["extractable"] = _json_load(item.pop("extractable_json"), [])
        item["skill_trace"] = _json_load(item.pop("skill_trace_json"), [])
        item["feedback"] = feedback_by_message.get(str(item["id"]), {})
        messages.append(item)
    return {
        "messages": messages,
        "has_more": has_more,
        "next_before": _message_cursor(messages[0]) if has_more and messages else "",
    }


def list_dialogue_messages(session_id: str, limit: int = 30) -> list[dict[str, Any]]:
    return list_dialogue_messages_page(session_id, limit=limit)["messages"]


def clear_dialogue_messages(session_id: str) -> dict[str, Any]:
    initialize_store()
    now = _now()
    with _connect() as connection:
        connection.execute("DELETE FROM dialogue_messages WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM dialogue_memories WHERE session_id = ?", (session_id,))
        connection.execute(
            """UPDATE dialogue_sessions
               SET updated_at = ?, last_message_at = NULL, last_message_preview = ''
               WHERE id = ?""",
            (now, session_id),
        )
        connection.commit()
    session = get_dialogue_session(session_id)
    if not session:
        raise ValueError("对话会话不存在")
    return session


def delete_dialogue_session(session_id: str, *, permanent: bool = False) -> dict[str, Any] | None:
    initialize_store()
    session = get_dialogue_session(session_id)
    if not session:
        return None
    if not permanent:
        return update_dialogue_session(session_id, deleted=True, pinned=False)
    with _connect() as connection:
        connection.execute("DELETE FROM dialogue_messages WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM dialogue_memories WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM dialogue_sessions WHERE id = ?", (session_id,))
        connection.commit()
    return session


def get_dialogue_memory(session_id: str) -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT summary_json, updated_at FROM dialogue_memories WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return {}
    summary = _json_load(row["summary_json"], {})
    if isinstance(summary, dict):
        summary["updated_at"] = row["updated_at"]
        return summary
    return {}


def save_dialogue_memory(session_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    initialize_store()
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO dialogue_memories (session_id, summary_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                summary_json = excluded.summary_json,
                updated_at = excluded.updated_at
            """,
            (session_id, json.dumps(summary, ensure_ascii=False), now),
        )
        connection.commit()
    return {"session_id": session_id, "summary": summary, "updated_at": now}


def create_persona_asset(
    asset_type: str,
    content: str,
    *,
    title: str = "",
    project_id: str = "",
    source: str = "",
    confidence: float = 0,
) -> dict[str, Any]:
    initialize_store()
    asset_id = uuid.uuid4().hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO persona_assets (
                id, project_id, asset_type, title, content, source,
                confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                project_id,
                asset_type,
                title,
                content,
                source,
                float(confidence or 0),
                now,
                now,
            ),
        )
        connection.commit()
    return {
        "id": asset_id,
        "project_id": project_id,
        "asset_type": asset_type,
        "title": title,
        "content": content,
        "source": source,
        "confidence": float(confidence or 0),
        "created_at": now,
        "updated_at": now,
    }


def list_persona_assets(
    project_id: str = "",
    asset_type: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    initialize_store()
    clauses = []
    values: list[Any] = []
    if project_id:
        clauses.append("(project_id = ? OR project_id = '')")
        values.append(project_id)
    if asset_type:
        clauses.append("asset_type = ?")
        values.append(asset_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(limit, 100)))
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, project_id, asset_type, title, content, source,
                   confidence, created_at, updated_at
            FROM persona_assets
            {where}
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def get_persona_asset(asset_id: str) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, project_id, asset_type, title, content, source,
                   confidence, created_at, updated_at
            FROM persona_assets
            WHERE id = ?
            """,
            (asset_id,),
        ).fetchone()
    return dict(row) if row else None


def update_persona_asset_type(asset_id: str, asset_type: str) -> dict[str, Any] | None:
    initialize_store()
    now = _now()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE persona_assets
            SET asset_type = ?, updated_at = ?
            WHERE id = ?
            """,
            (asset_type, now, asset_id),
        )
        connection.commit()
    if cursor.rowcount == 0:
        return None
    return get_persona_asset(asset_id)


def list_reference_documents(limit: int = 20) -> list[dict[str, Any]]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, filename, text_content, analysis_json, created_at
            FROM reference_documents
            ORDER BY id ASC
            LIMIT ?
            """,
            (max(1, min(limit, 50)),),
        ).fetchall()
    documents: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["analysis"] = json.loads(item.pop("analysis_json") or "{}")
        except json.JSONDecodeError:
            item["analysis"] = {}
            item.pop("analysis_json", None)
        documents.append(item)
    return documents


def save_reference_document(
    filename: str,
    text: str,
    analysis: dict[str, Any],
) -> tuple[int, bool]:
    initialize_store()
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    now = _now()
    with _connect() as connection:
        existing = connection.execute(
            "SELECT id FROM reference_documents WHERE content_hash = ?",
            (content_hash,),
        ).fetchone()
        if existing:
            return int(existing["id"]), False
        cursor = connection.execute(
            """
            INSERT INTO reference_documents (
                filename, content_hash, text_content, analysis_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                filename,
                content_hash,
                text,
                json.dumps(analysis, ensure_ascii=False),
                now,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid), True


def reference_document_count() -> int:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM reference_documents"
        ).fetchone()
    return int(row["count"]) if row else 0


def create_style_candidate(
    source_document_id: int,
    skill_content: str,
    evidence: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT version FROM style_skill_versions"
        ).fetchall()
        latest = max((_version_key(row["version"]) for row in rows), default=(2, 0))
        major = max(2, latest[0])
        minor = (latest[1] if len(latest) > 1 and latest[0] == major else 0) + 1
        version = f"v{major}.{minor}"
        skill_content = _normalize_skill_version(skill_content, version)
        cursor = connection.execute(
            """
            INSERT INTO style_skill_versions (
                version, status, source_document_id, skill_content,
                evidence_json, evaluation_json, created_at
            ) VALUES (?, 'candidate', ?, ?, ?, ?, ?)
            """,
            (
                version,
                source_document_id,
                skill_content,
                json.dumps(evidence, ensure_ascii=False),
                json.dumps(evaluation, ensure_ascii=False),
                _now(),
            ),
        )
        connection.commit()
    return {
        "id": int(cursor.lastrowid),
        "version": version,
        "status": "candidate",
    }


def update_style_candidate(
    version_id: int,
    skill_content: str,
    evidence: dict[str, Any],
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT id, version, status FROM style_skill_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        if not row or row["status"] != "candidate":
            raise ValueError("待修订候选 Skill 不存在")
        version = str(row["version"])
        normalized = _normalize_skill_version(skill_content, version)
        connection.execute(
            """
            UPDATE style_skill_versions
            SET skill_content = ?, evidence_json = ?, evaluation_json = ?
            WHERE id = ?
            """,
            (
                normalized,
                json.dumps(evidence, ensure_ascii=False),
                json.dumps(evaluation, ensure_ascii=False),
                version_id,
            ),
        )
        connection.commit()
    return {"id": version_id, "version": version, "status": "candidate"}


def mark_style_comparison_completed(
    version_id: int,
    comparison: dict[str, Any],
) -> dict[str, Any]:
    item = get_style_version(version_id)
    if not item or item.get("status") != "candidate":
        raise ValueError("待对照候选 Skill 不存在")
    evaluation = item.get("evaluation") if isinstance(item.get("evaluation"), dict) else {}
    evaluation.update(
        {
            "ab_test_completed": True,
            "ab_test_passed": comparison.get("passed") is True,
            "ab_test_completed_at": _now(),
            "ab_test": comparison,
        }
    )
    with _connect() as connection:
        connection.execute(
            "UPDATE style_skill_versions SET evaluation_json = ? WHERE id = ?",
            (json.dumps(evaluation, ensure_ascii=False), version_id),
        )
        connection.commit()
    return {"id": version_id, "version": item["version"], "evaluation": evaluation}


def list_style_versions(limit: int = 20) -> list[dict[str, Any]]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, version, status, source_document_id, evaluation_json,
                   created_at, published_at
            FROM style_skill_versions
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 100)),),
        ).fetchall()
    versions: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["evaluation"] = json.loads(item.pop("evaluation_json"))
        except json.JSONDecodeError:
            item["evaluation"] = {}
            item.pop("evaluation_json", None)
        versions.append(item)
    return versions


def get_style_version(version_id: int) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, version, status, source_document_id, skill_content,
                   evidence_json, evaluation_json, created_at, published_at
            FROM style_skill_versions WHERE id = ?
            """,
            (version_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    for key in ("evidence_json", "evaluation_json"):
        target = key.removesuffix("_json")
        try:
            item[target] = json.loads(item.pop(key) or "{}")
        except json.JSONDecodeError:
            item[target] = {}
            item.pop(key, None)
    return item


def get_published_style(
    default_content: str,
    default_version: str = BASELINE_STYLE_VERSION,
) -> tuple[str, str]:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT version, skill_content
            FROM style_skill_versions
            WHERE status = 'published'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row and _version_key(str(row["version"])) >= _version_key(default_version):
            return str(row["version"]), str(row["skill_content"])

        now = _now()
        connection.execute(
            "UPDATE style_skill_versions SET status = 'archived' WHERE status = 'published'"
        )
        baseline = connection.execute(
            "SELECT id FROM style_skill_versions WHERE version = ?",
            (default_version,),
        ).fetchone()
        metadata = json.dumps({"mode": "bundled_baseline"}, ensure_ascii=False)
        evaluation = json.dumps(
            {"reason": "Bundled v2 executable style grammar supersedes legacy v1."},
            ensure_ascii=False,
        )
        if baseline:
            connection.execute(
                """
                UPDATE style_skill_versions
                SET status = 'published', skill_content = ?, evidence_json = ?,
                    evaluation_json = ?, published_at = ?
                WHERE id = ?
                """,
                (default_content, metadata, evaluation, now, int(baseline["id"])),
            )
        else:
            connection.execute(
                """
                INSERT INTO style_skill_versions (
                    version, status, source_document_id, skill_content,
                    evidence_json, evaluation_json, created_at, published_at
                ) VALUES (?, 'published', NULL, ?, ?, ?, ?, ?)
                """,
                (default_version, default_content, metadata, evaluation, now, now),
            )
        connection.commit()
    return default_version, default_content


def publish_style_version(
    version_id: int,
    force: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    initialize_store()
    now = _now()
    with _connect() as connection:
        target = connection.execute(
            "SELECT id, version, status, evaluation_json FROM style_skill_versions WHERE id = ?",
            (version_id,),
        ).fetchone()
        if not target:
            raise ValueError("候选 Skill 版本不存在")
        try:
            evaluation = json.loads(target["evaluation_json"] or "{}")
        except json.JSONDecodeError:
            evaluation = {}
        requires_override = bool(
            evaluation.get("ab_test_required") and not _has_reviewable_ab(evaluation)
        )
        if requires_override and not force:
            raise ValueError("候选 Skill 必须先生成两版完整且通过事实门禁的 A/B 成稿才能发布")
        if requires_override:
            evaluation.update(
                {
                    "manual_publish_override": True,
                    "manual_publish_reason": reason.strip()
                    or "创作者完成 A/B 审核并确认候选版本效果满意",
                    "manual_publish_at": now,
                }
            )
        connection.execute(
            "UPDATE style_skill_versions SET status = 'archived' WHERE status = 'published'"
        )
        connection.execute(
            """
            UPDATE style_skill_versions
            SET status = 'published', evaluation_json = ?, published_at = ?
            WHERE id = ?
            """,
            (json.dumps(evaluation, ensure_ascii=False), now, version_id),
        )
        connection.commit()
    return {
        "id": int(target["id"]),
        "version": str(target["version"]),
        "status": "published",
        "published_at": now,
        "manual_publish_override": requires_override,
    }


def save_book_citations(project_id: str, citations: list[dict[str, Any]]) -> None:
    if not citations:
        return
    initialize_store()
    now = _now()
    with _connect() as connection:
        for citation in citations:
            quote = str(citation.get("quote", "")).strip()
            book = str(citation.get("book", "")).strip()
            book_id = str(citation.get("book_id") or "").strip() or _legacy_book_id(book)
            source_title = str(citation.get("source_title", "")).strip()
            source_url = str(citation.get("url", citation.get("source_url", ""))).strip()
            material_type = str(citation.get("material_type") or "direct_quote")
            quality_status = str(
                citation.get("quality_status")
                or ("valid" if str(project_id).strip() else "pending_review")
            )
            if material_type not in {"direct_quote", "reading_note", "context_excerpt", "metadata"}:
                material_type = "direct_quote"
            if quality_status not in {"valid", "pending_review", "quarantined"}:
                quality_status = "pending_review"
            if not quote or not book:
                continue
            duplicate = connection.execute(
                """
                SELECT id FROM book_citations
                WHERE project_id = ? AND book = ? AND quote = ? AND source_title = ?
                LIMIT 1
                """,
                (project_id, book, quote, source_title),
            ).fetchone()
            if duplicate:
                connection.execute(
                    """
                    UPDATE book_citations
                    SET attribution = ?, source_url = ?, evidence_text = ?, book_id = ?,
                        material_type = ?, quality_status = ?, quality_reason = ?,
                        source_locator = ?
                    WHERE id = ?
                    """,
                    (
                        str(citation.get("attribution", "")),
                        source_url,
                        str(citation.get("evidence_text", "")) or quote,
                        book_id,
                        material_type,
                        quality_status,
                        str(citation.get("quality_reason", "")),
                        str(citation.get("source_locator", "")),
                        int(duplicate["id"]),
                    ),
                )
                continue
            connection.execute(
                """
                INSERT INTO book_citations (
                    project_id, book_id, book, quote, attribution, source_title,
                    source_url, evidence_text, material_type, quality_status,
                    quality_reason, source_locator, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    book_id,
                    book,
                    quote,
                    str(citation.get("attribution", "")),
                    source_title,
                    source_url,
                    str(citation.get("evidence_text", "")) or quote,
                    material_type,
                    quality_status,
                    str(citation.get("quality_reason", "")),
                    str(citation.get("source_locator", "")),
                    now,
                ),
            )
        for book_id in {
            str(item.get("book_id") or _legacy_book_id(str(item.get("book") or ""))).strip()
            for item in citations
        } - {""}:
            _refresh_library_book_counts(connection, book_id, now=now)
        connection.commit()


def list_book_citations(project_id: str = "", limit: int = 30) -> list[dict[str, Any]]:
    initialize_store()
    clauses = []
    values: list[Any] = []
    if project_id:
        clauses.append("(project_id = ? OR project_id = '')")
        values.append(project_id)
    else:
        clauses.append("project_id = ''")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    values.append(max(1, min(limit, 2000)))
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT id, project_id, book_id, book, quote, attribution, source_title,
                   source_url, evidence_text, material_type, quality_status,
                   quality_reason, source_locator, created_at
            FROM book_citations
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def delete_book_citation(citation_id: int) -> bool:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT book_id FROM book_citations WHERE id = ?", (int(citation_id),)
        ).fetchone()
        cursor = connection.execute(
            "DELETE FROM book_citations WHERE id = ?",
            (int(citation_id),),
        )
        if row and str(row["book_id"] or ""):
            _refresh_library_book_counts(connection, str(row["book_id"]))
        connection.commit()
    return cursor.rowcount == 1


def update_book_citation_quality(
    citation_id: int,
    *,
    material_type: str,
    quality_status: str,
    quality_reason: str = "",
    source_locator: str = "",
    attribution: str | None = None,
) -> bool:
    initialize_store()
    if material_type not in {"direct_quote", "reading_note", "context_excerpt", "metadata"}:
        raise ValueError("未知的书库素材类型")
    if quality_status not in {"valid", "pending_review", "quarantined"}:
        raise ValueError("未知的书库质量状态")
    updates = [
        "material_type = ?",
        "quality_status = ?",
        "quality_reason = ?",
        "source_locator = ?",
    ]
    values: list[Any] = [material_type, quality_status, quality_reason, source_locator]
    if attribution is not None:
        updates.append("attribution = ?")
        values.append(attribution)
    values.append(int(citation_id))
    with _connect() as connection:
        row = connection.execute(
            "SELECT book_id FROM book_citations WHERE id = ?", (int(citation_id),)
        ).fetchone()
        cursor = connection.execute(
            f"UPDATE book_citations SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        if row and str(row["book_id"] or ""):
            _refresh_library_book_counts(connection, str(row["book_id"]))
        connection.commit()
    return cursor.rowcount == 1


def book_citation_summary(limit: int = 12) -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT book_id, book,
                   COUNT(*) AS count,
                   SUM(CASE WHEN material_type = 'direct_quote' AND quality_status = 'valid' THEN 1 ELSE 0 END) AS quotable_count,
                   SUM(CASE WHEN material_type = 'reading_note' AND quality_status != 'quarantined' THEN 1 ELSE 0 END) AS note_count,
                   SUM(CASE WHEN material_type = 'context_excerpt' AND quality_status != 'quarantined' THEN 1 ELSE 0 END) AS context_count,
                   SUM(CASE WHEN quality_status = 'pending_review' THEN 1 ELSE 0 END) AS pending_count,
                   SUM(CASE WHEN quality_status = 'quarantined' THEN 1 ELSE 0 END) AS quarantined_count,
                   MAX(created_at) AS updated_at
            FROM book_citations
            WHERE project_id = ''
            GROUP BY book_id, book
            ORDER BY count DESC, updated_at DESC
            """
        ).fetchall()
        recent = connection.execute(
            """
            SELECT id, book_id, book, quote, attribution, source_title, source_url,
                   evidence_text, material_type, quality_status, quality_reason,
                   source_locator, created_at
            FROM book_citations
            WHERE project_id = ''
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(limit, 2000)),),
        ).fetchall()
    return {
        "summary": [dict(row) for row in rows],
        "recent": [dict(row) for row in recent],
    }


def _library_book_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["metadata"] = _json_load(str(item.pop("metadata_json", "{}")), {})
    return item


def list_library_books(include_archived: bool = False) -> list[dict[str, Any]]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM library_books
            WHERE status = 'active' OR ? = 1
            ORDER BY status ASC, updated_at DESC, title ASC
            """,
            (1 if include_archived else 0,),
        ).fetchall()
    return [_library_book_row(row) for row in rows if row]


def get_library_book(book_id: str) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM library_books WHERE id = ?", (str(book_id).strip(),)
        ).fetchone()
    return _library_book_row(row)


def create_library_book(
    title: str,
    *,
    author: str = "",
    description: str = "",
    book_id: str = "",
    source_type: str = "user_import",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_title = str(title or "").strip()
    if not clean_title:
        raise ValueError("请填写书名")
    identifier = str(book_id or "").strip() or _legacy_book_id(clean_title) or _slug_id(clean_title, "book")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{1,79}", identifier):
        raise ValueError("书籍 ID 仅允许字母、数字、点、下划线和短横线")
    initialize_store()
    now = _now()
    with _connect() as connection:
        duplicate = connection.execute(
            "SELECT id FROM library_books WHERE id = ? OR title = ?",
            (identifier, clean_title),
        ).fetchone()
        if duplicate:
            raise ValueError("这本书已经存在")
        connection.execute(
            """
            INSERT INTO library_books (
                id, title, author, description, source_type, status,
                metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (
                identifier,
                clean_title,
                str(author or "").strip(),
                str(description or "").strip(),
                str(source_type or "user_import").strip(),
                json.dumps(metadata or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
    return get_library_book(identifier) or {}


def update_library_book(book_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    current = get_library_book(book_id)
    if not current:
        return None
    updates: list[str] = []
    values: list[Any] = []
    for field in ("title", "author", "description", "status"):
        if field not in payload:
            continue
        value = str(payload.get(field) or "").strip()
        if field == "title" and not value:
            raise ValueError("书名不能为空")
        if field == "status" and value not in {"active", "archived", "error"}:
            raise ValueError("未知的书籍状态")
        updates.append(f"{field} = ?")
        values.append(value)
    if "metadata" in payload and isinstance(payload.get("metadata"), dict):
        updates.append("metadata_json = ?")
        values.append(json.dumps(payload["metadata"], ensure_ascii=False))
    if not updates:
        return current
    updates.append("updated_at = ?")
    values.extend([_now(), book_id])
    with _connect() as connection:
        connection.execute(
            f"UPDATE library_books SET {', '.join(updates)} WHERE id = ?", values
        )
        if "title" in payload:
            connection.execute(
                "UPDATE book_citations SET book = ? WHERE project_id = '' AND book_id = ?",
                (str(payload["title"]).strip(), book_id),
            )
        connection.commit()
    return get_library_book(book_id)


def delete_library_book(book_id: str, *, permanent: bool = False) -> bool:
    initialize_store()
    with _connect() as connection:
        exists = connection.execute(
            "SELECT id FROM library_books WHERE id = ?", (book_id,)
        ).fetchone()
        if not exists:
            return False
        if not permanent:
            connection.execute(
                "UPDATE library_books SET status = 'archived', updated_at = ? WHERE id = ?",
                (_now(), book_id),
            )
            connection.commit()
            return True
        persona_rows = connection.execute(
            "SELECT id, book_ids_json FROM book_personas"
        ).fetchall()
        for row in persona_rows:
            if book_id in _json_load(str(row["book_ids_json"] or "[]"), []):
                connection.execute(
                    "UPDATE book_personas SET status = 'archived', updated_at = ? WHERE id = ?",
                    (_now(), row["id"]),
                )
        connection.execute(
            "DELETE FROM book_citations WHERE project_id = '' AND book_id = ?", (book_id,)
        )
        connection.execute("DELETE FROM library_books WHERE id = ?", (book_id,))
        connection.commit()
    return True


def _book_persona_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    item["book_ids"] = _json_load(str(item.pop("book_ids_json", "[]")), [])
    item["type"] = "book"
    item["label"] = item.get("description") or "来自个人精神书库"
    item["book_id"] = item["book_ids"][0] if item["book_ids"] else ""
    item["builtin"] = bool(item.get("builtin"))
    return item


def list_book_personas(include_archived: bool = False) -> list[dict[str, Any]]:
    initialize_store()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM book_personas
            WHERE status = 'active' OR ? = 1
            ORDER BY builtin DESC, updated_at DESC, name ASC
            """,
            (1 if include_archived else 0,),
        ).fetchall()
    return [_book_persona_row(row) for row in rows if row]


def get_book_persona(persona_id: str) -> dict[str, Any] | None:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM book_personas WHERE id = ?", (persona_id,)
        ).fetchone()
    return _book_persona_row(row)


def create_book_persona(
    name: str,
    book_ids: list[str],
    *,
    description: str = "",
    voice: str = "",
    boundaries: str = "",
    persona_id: str = "",
) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    clean_book_ids = list(dict.fromkeys(str(item).strip() for item in book_ids if str(item).strip()))
    if not clean_name:
        raise ValueError("请填写书中人名称")
    if not clean_book_ids:
        raise ValueError("至少选择一本已导入书籍")
    missing = [item for item in clean_book_ids if not get_library_book(item)]
    if missing:
        raise ValueError(f"书籍不存在：{', '.join(missing)}")
    identifier = str(persona_id or "").strip() or _slug_id(clean_name, "persona")
    initialize_store()
    now = _now()
    with _connect() as connection:
        if connection.execute("SELECT id FROM book_personas WHERE id = ?", (identifier,)).fetchone():
            identifier = f"{identifier}-{uuid.uuid4().hex[:6]}"
        connection.execute(
            """
            INSERT INTO book_personas (
                id, name, book_ids_json, description, voice, boundaries,
                builtin, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 'active', ?, ?)
            """,
            (
                identifier,
                clean_name,
                json.dumps(clean_book_ids, ensure_ascii=False),
                str(description or "").strip(),
                str(voice or "").strip(),
                str(boundaries or "").strip(),
                now,
                now,
            ),
        )
        connection.commit()
    return get_book_persona(identifier) or {}


def update_book_persona(persona_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    current = get_book_persona(persona_id)
    if not current:
        return None
    updates: list[str] = []
    values: list[Any] = []
    for field in ("name", "description", "voice", "boundaries", "status"):
        if field not in payload:
            continue
        value = str(payload.get(field) or "").strip()
        if field == "name" and not value:
            raise ValueError("书中人名称不能为空")
        if field == "status" and value not in {"active", "archived"}:
            raise ValueError("未知的书中人状态")
        updates.append(f"{field} = ?")
        values.append(value)
    if "book_ids" in payload:
        raw_ids = payload.get("book_ids") if isinstance(payload.get("book_ids"), list) else []
        book_ids = list(dict.fromkeys(str(item).strip() for item in raw_ids if str(item).strip()))
        if not book_ids or any(not get_library_book(item) for item in book_ids):
            raise ValueError("书中人必须绑定至少一本有效书籍")
        updates.append("book_ids_json = ?")
        values.append(json.dumps(book_ids, ensure_ascii=False))
    if not updates:
        return current
    updates.append("updated_at = ?")
    values.extend([_now(), persona_id])
    with _connect() as connection:
        connection.execute(
            f"UPDATE book_personas SET {', '.join(updates)} WHERE id = ?", values
        )
        connection.commit()
    return get_book_persona(persona_id)


def delete_book_persona(persona_id: str, *, permanent: bool = False) -> bool:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT id FROM book_personas WHERE id = ?", (persona_id,)
        ).fetchone()
        if not row:
            return False
        session_count = connection.execute(
            "SELECT COUNT(*) AS count FROM dialogue_sessions WHERE persona_id = ?",
            (persona_id,),
        ).fetchone()
        if permanent and not int(session_count["count"] or 0):
            connection.execute("DELETE FROM book_personas WHERE id = ?", (persona_id,))
        else:
            connection.execute(
                "UPDATE book_personas SET status = 'archived', updated_at = ? WHERE id = ?",
                (_now(), persona_id),
            )
        connection.commit()
    return True
