"""Creator long-term memory indexing and grounded retrieval.

The personal memory engine deliberately stays local and dependency-light. Raw
reference documents are chunked into SQLite, FTS5 is used when available, and
a deterministic scorer remains as a fallback for every supported platform.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from typing import Any

from services import xiangzhongjing_store as store
from services.book_library_quality import is_generation_ready_citation


_HAN_SEQUENCE = re.compile(r"[\u3400-\u9fff]+")
_ASCII_WORD = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{1,}")
_SPACE = re.compile(r"\s+")
_COMMON_NGRAMS = {
    "什么", "怎么", "为什么", "可以", "一个", "这个", "那个", "还是", "就是",
    "现在", "最近", "觉得", "真的", "自己", "我们", "你们", "他们", "有没有",
    "时候", "事情", "如果", "但是", "因为", "所以", "已经", "不是", "没有",
}


def _now() -> str:
    return store._now()


def _connect():
    store.initialize_store()
    return store._connect()


def _normalize_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _search_signature(value: str) -> str:
    return re.sub(r"[^\u3400-\u9fffa-zA-Z0-9]+", "", str(value or "").lower())


def _boundary(text: str, start: int, target: int = 720, maximum: int = 920) -> int:
    if start + maximum >= len(text):
        return len(text)
    lower = min(len(text), start + max(360, target - 180))
    upper = min(len(text), start + maximum)
    preferred = min(len(text), start + target)
    marks = "\n。！？；!?;"
    candidates = [index + 1 for index in range(lower, upper) if text[index] in marks]
    if not candidates:
        return upper
    after = [index for index in candidates if index >= preferred]
    return after[0] if after else candidates[-1]


def chunk_reference_text(text: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(normalized):
        end = _boundary(normalized, start)
        content = normalized[start:end].strip()
        if content:
            chunks.append(
                {
                    "chunk_index": len(chunks),
                    "content": content,
                    "char_start": start,
                    "char_end": end,
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                }
            )
        if end >= len(normalized):
            break
        next_start = max(start + 1, end - 96)
        paragraph_break = normalized.find("\n", next_start, min(end + 40, len(normalized)))
        start = paragraph_break + 1 if paragraph_break >= 0 else next_start
    return chunks


def _ensure_fts(connection: sqlite3.Connection) -> str:
    existing = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'creator_memory_search'"
    ).fetchone()
    if existing:
        sql = str(existing["sql"] or "").lower()
        return "trigram" if "trigram" in sql else "unicode61"
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE creator_memory_search USING fts5(
                chunk_id UNINDEXED,
                source_filename,
                content,
                tokenize='trigram'
            )
            """
        )
        return "trigram"
    except sqlite3.OperationalError:
        connection.execute(
            """
            CREATE VIRTUAL TABLE creator_memory_search USING fts5(
                chunk_id UNINDEXED,
                source_filename,
                content,
                tokenize='unicode61'
            )
            """
        )
        return "unicode61"


def sync_reference_document_chunks() -> dict[str, Any]:
    documents = store.list_reference_documents(limit=50)
    changed_documents = 0
    inserted_chunks = 0
    with _connect() as connection:
        tokenizer = _ensure_fts(connection)
        document_ids = {int(item["id"]) for item in documents}
        existing_ids = {
            int(row["source_document_id"])
            for row in connection.execute(
                "SELECT DISTINCT source_document_id FROM creator_memory_chunks"
            ).fetchall()
        }
        for stale_id in existing_ids - document_ids:
            stale_chunks = connection.execute(
                "SELECT id FROM creator_memory_chunks WHERE source_document_id = ?",
                (stale_id,),
            ).fetchall()
            for row in stale_chunks:
                connection.execute(
                    "DELETE FROM creator_memory_search WHERE chunk_id = ?", (row["id"],)
                )
            connection.execute(
                "DELETE FROM creator_memory_chunks WHERE source_document_id = ?", (stale_id,)
            )
        for document in documents:
            document_id = int(document["id"])
            chunks = chunk_reference_text(str(document.get("text_content") or ""))
            expected = [(item["chunk_index"], item["content_hash"]) for item in chunks]
            stored = [
                (int(row["chunk_index"]), str(row["content_hash"]))
                for row in connection.execute(
                    """
                    SELECT chunk_index, content_hash
                    FROM creator_memory_chunks
                    WHERE source_document_id = ?
                    ORDER BY chunk_index ASC
                    """,
                    (document_id,),
                ).fetchall()
            ]
            if stored == expected:
                continue
            changed_documents += 1
            old_rows = connection.execute(
                "SELECT id FROM creator_memory_chunks WHERE source_document_id = ?",
                (document_id,),
            ).fetchall()
            for row in old_rows:
                connection.execute(
                    "DELETE FROM creator_memory_search WHERE chunk_id = ?", (row["id"],)
                )
            connection.execute(
                "DELETE FROM creator_memory_chunks WHERE source_document_id = ?", (document_id,)
            )
            now = _now()
            filename = str(document.get("filename") or "历史文稿")
            for item in chunks:
                chunk_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"xiangzhongjing:reference:{document_id}:{item['chunk_index']}:{item['content_hash']}",
                ).hex
                connection.execute(
                    """
                    INSERT INTO creator_memory_chunks (
                        id, source_document_id, source_filename, chunk_index,
                        content, content_hash, char_start, char_end, metadata_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        document_id,
                        filename,
                        item["chunk_index"],
                        item["content"],
                        item["content_hash"],
                        item["char_start"],
                        item["char_end"],
                        json.dumps({"source": "reference_document"}, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO creator_memory_search (chunk_id, source_filename, content)
                    VALUES (?, ?, ?)
                    """,
                    (chunk_id, filename, item["content"]),
                )
                inserted_chunks += 1
        connection.commit()
        total = connection.execute(
            "SELECT COUNT(*) AS count FROM creator_memory_chunks"
        ).fetchone()
    return {
        "documents": len(documents),
        "changed_documents": changed_documents,
        "inserted_chunks": inserted_chunks,
        "total_chunks": int(total["count"] if total else 0),
        "search_backend": f"sqlite-fts5-{tokenizer}",
    }


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for word in _ASCII_WORD.findall(query.lower()):
        if word not in terms:
            terms.append(word)
    for sequence in _HAN_SEQUENCE.findall(query):
        if len(sequence) <= 4:
            if len(sequence) >= 2 and sequence not in _COMMON_NGRAMS and sequence not in terms:
                terms.append(sequence)
            continue
        for size in (3, 2):
            for index in range(0, len(sequence) - size + 1):
                term = sequence[index : index + size]
                if term in _COMMON_NGRAMS or term in terms:
                    continue
                terms.append(term)
                if len(terms) >= 32:
                    return terms
    return terms


def _score_text(query: str, text: str, title: str = "") -> float:
    signature = _search_signature(text)
    title_signature = _search_signature(title)
    query_signature = _search_signature(query)
    if not signature:
        return 0.0
    score = 0.0
    if query_signature and len(query_signature) >= 3 and query_signature in signature:
        score += 18.0
    distinct_hits = 0
    for term in _query_terms(query):
        needle = _search_signature(term)
        if not needle:
            continue
        count = signature.count(needle)
        if count:
            distinct_hits += 1
            score += 1.5 + min(3, count) * (0.55 + min(len(needle), 5) * 0.12)
        if needle in title_signature:
            score += 2.5
    if distinct_hits:
        score += min(8.0, distinct_hits * 0.45)
    return score


def _fts_chunk_ids(connection: sqlite3.Connection, query: str, limit: int = 120) -> list[str]:
    terms = [term for term in _query_terms(query) if len(_search_signature(term)) >= 3][:16]
    if not terms:
        return []
    expression = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
    try:
        rows = connection.execute(
            """
            SELECT chunk_id
            FROM creator_memory_search
            WHERE creator_memory_search MATCH ?
            ORDER BY bm25(creator_memory_search)
            LIMIT ?
            """,
            (expression, max(1, min(limit, 300))),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(row["chunk_id"]) for row in rows]


def _excerpt(text: str, query: str, limit: int = 620) -> str:
    clean = _normalize_text(text)
    if len(clean) <= limit:
        return clean
    signature_terms = [term for term in _query_terms(query) if len(term) >= 2]
    positions = [clean.find(term) for term in signature_terms if clean.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - limit // 3)
    end = min(len(clean), start + limit)
    snippet = clean[start:end].strip()
    return ("…" if start else "") + snippet + ("…" if end < len(clean) else "")


def retrieve_creator_context(query: str, limit: int = 8) -> dict[str, Any]:
    index_status = sync_reference_document_chunks()
    safe_limit = max(1, min(limit, 12))
    candidates: list[dict[str, Any]] = []
    with _connect() as connection:
        chunk_ids = _fts_chunk_ids(connection, query)
        if chunk_ids:
            placeholders = ",".join("?" for _ in chunk_ids)
            chunk_rows = connection.execute(
                f"""
                SELECT id, source_document_id, source_filename, chunk_index, content
                FROM creator_memory_chunks
                WHERE id IN ({placeholders})
                """,
                chunk_ids,
            ).fetchall()
        else:
            chunk_rows = connection.execute(
                """
                SELECT id, source_document_id, source_filename, chunk_index, content
                FROM creator_memory_chunks
                ORDER BY source_document_id ASC, chunk_index ASC
                LIMIT 2000
                """
            ).fetchall()
        for row in chunk_rows:
            content = str(row["content"] or "")
            score = _score_text(query, content, str(row["source_filename"] or ""))
            candidates.append(
                {
                    "id": str(row["id"]),
                    "source_type": "history_document",
                    "title": str(row["source_filename"] or "历史文稿"),
                    "content": _excerpt(content, query),
                    "source_filename": str(row["source_filename"] or ""),
                    "source_document_id": int(row["source_document_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "confidence": 1.0,
                    "score": score,
                }
            )
        memory_rows = connection.execute(
            """
            SELECT id, memory_type, title, content, evidence_json,
                   source_document_id, source_filename, source_session_id,
                   source_message_id, tags_json, confidence, occurred_at, updated_at
            FROM creator_memories
            WHERE status = 'active'
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ).fetchall()
        for row in memory_rows:
            content = str(row["content"] or "")
            confidence = float(row["confidence"] or 0.7)
            score = _score_text(query, content, str(row["title"] or "")) + confidence * 2.5
            candidates.append(
                {
                    "id": str(row["id"]),
                    "source_type": "creator_memory",
                    "memory_type": str(row["memory_type"] or "reflection"),
                    "title": str(row["title"] or "长期记忆"),
                    "content": _excerpt(content, query),
                    "source_filename": str(row["source_filename"] or ""),
                    "source_session_id": str(row["source_session_id"] or ""),
                    "source_message_id": str(row["source_message_id"] or ""),
                    "confidence": confidence,
                    "score": score,
                }
            )

    for asset in store.list_persona_assets("", limit=100):
        content = str(asset.get("content") or "")
        confidence = float(asset.get("confidence") or 0.7)
        candidates.append(
            {
                "id": str(asset.get("id") or ""),
                "source_type": "persona_asset",
                "memory_type": str(asset.get("asset_type") or "persona_asset"),
                "title": str(asset.get("title") or "人设资产"),
                "content": _excerpt(content, query),
                "source_filename": "",
                "source_session_id": str(asset.get("source") or ""),
                "confidence": confidence,
                "score": _score_text(query, content, str(asset.get("title") or "")) + confidence * 3,
            }
        )

    candidates.sort(
        key=lambda item: (
            float(item.get("score") or 0),
            item.get("source_type") in {"creator_memory", "persona_asset"},
            float(item.get("confidence") or 0),
        ),
        reverse=True,
    )
    selected: list[dict[str, Any]] = []
    document_counts: dict[int, int] = {}
    for item in candidates:
        document_id = int(item.get("source_document_id") or 0)
        if document_id and document_counts.get(document_id, 0) >= 2:
            continue
        if document_id:
            document_counts[document_id] = document_counts.get(document_id, 0) + 1
        selected.append(item)
        if len(selected) >= safe_limit:
            break
    return {
        "query": query,
        "sources": selected,
        "calibration": retrieve_dialogue_calibration(query, limit=6),
        "index": index_status,
        "retrieval": "hybrid_fts5_local_score",
    }


def retrieve_dialogue_calibration(query: str, limit: int = 6) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT df.verdict, df.note, df.updated_at, dm.content
            FROM dialogue_feedback df
            JOIN dialogue_messages dm ON dm.id = df.message_id
            JOIN dialogue_sessions ds ON ds.id = df.session_id
            WHERE ds.mode = 'mirror'
            ORDER BY df.updated_at DESC
            LIMIT 100
            """
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        content = str(row["content"] or "")
        verdict = str(row["verdict"] or "")
        score = _score_text(query, content) + (
            2.0 if verdict in {"unlike_self", "forget"} else 1.0
        )
        items.append(
            {
                "verdict": verdict,
                "content": content[:800],
                "note": str(row["note"] or "")[:400],
                "updated_at": str(row["updated_at"] or ""),
                "score": score,
            }
        )
    items.sort(
        key=lambda item: (float(item["score"]), str(item["updated_at"])),
        reverse=True,
    )
    return items[: max(1, min(limit, 10))]


def _citation_book_id(item: dict[str, Any]) -> str:
    stored_id = str(item.get("book_id") or "").strip()
    if stored_id:
        return stored_id
    title = str(item.get("book") or "").replace("《", "").replace("》", "")
    if "马斯克" in title:
        return "musk"
    if "剑来" in title:
        return "jianlai"
    if "道德经" in title:
        return "daode"
    return ""


def retrieve_book_citations(query: str, book_id: str, limit: int = 10) -> list[dict[str, Any]]:
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    for order, item in enumerate(store.list_book_citations("", limit=1000)):
        if _citation_book_id(item) != book_id or not is_generation_ready_citation(item):
            continue
        body = "\n".join(
            [
                str(item.get("quote") or ""),
                str(item.get("evidence_text") or ""),
                str(item.get("quality_reason") or ""),
            ]
        )
        source_bonus = 1.2 if str(item.get("source_locator") or "").strip() else 0.0
        ranked.append((_score_text(query, body, str(item.get("book") or "")) + source_bonus, -order, item))
    ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [item for _, _, item in ranked[: max(1, min(limit, 16))]]


def upsert_session_summary_memory(
    session: dict[str, Any], summary: dict[str, Any], last_message_id: str = ""
) -> dict[str, Any]:
    session_id = str(session.get("id") or "")
    if not session_id:
        raise ValueError("会话不存在")
    parts = [str(summary.get("summary") or "").strip()]
    preferences = summary.get("stable_user_preferences")
    if isinstance(preferences, list) and preferences:
        parts.append("稳定偏好：" + "；".join(str(item) for item in preferences[:12]))
    questions = summary.get("open_questions")
    if isinstance(questions, list) and questions:
        parts.append("仍在思考：" + "；".join(str(item) for item in questions[:8]))
    content = "\n".join(part for part in parts if part).strip()
    if not content:
        return {}
    memory_id = uuid.uuid5(uuid.NAMESPACE_URL, f"xiangzhongjing:session:{session_id}").hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO creator_memories (
                id, memory_type, title, content, evidence_json,
                source_session_id, source_message_id, tags_json,
                confidence, status, created_at, updated_at
            ) VALUES (?, 'session_summary', ?, ?, ?, ?, ?, ?, 0.76, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                content = excluded.content,
                evidence_json = excluded.evidence_json,
                source_message_id = excluded.source_message_id,
                status = 'active',
                updated_at = excluded.updated_at
            """,
            (
                memory_id,
                str(session.get("title") or "跨会话记忆")[:80],
                content,
                json.dumps(summary, ensure_ascii=False),
                session_id,
                last_message_id,
                json.dumps([str(session.get("mode") or "dialogue")], ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
    return get_creator_memory(memory_id) or {}


def get_creator_memory(memory_id: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM creator_memories WHERE id = ?", (memory_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["evidence"] = store._json_load(item.pop("evidence_json"), [])
    item["tags"] = store._json_load(item.pop("tags_json"), [])
    return item


def should_refresh_session_summary(session_id: str, message_count: int) -> bool:
    if message_count < 18:
        return False
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT summarized_message_count
            FROM dialogue_memory_checkpoints
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    previous = int(row["summarized_message_count"] if row else 0)
    return previous == 0 or message_count - previous >= 12


def save_summary_checkpoint(session_id: str, message_count: int, last_message_id: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO dialogue_memory_checkpoints (
                session_id, summarized_message_count, last_message_id, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                summarized_message_count = excluded.summarized_message_count,
                last_message_id = excluded.last_message_id,
                updated_at = excluded.updated_at
            """,
            (session_id, int(message_count), last_message_id, _now()),
        )
        connection.commit()


def _remember_message(message: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    message_id = str(message.get("id") or "")
    memory_id = uuid.uuid5(uuid.NAMESPACE_URL, f"xiangzhongjing:message:{message_id}").hex
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO creator_memories (
                id, memory_type, title, content, evidence_json,
                source_session_id, source_message_id, tags_json,
                confidence, status, created_at, updated_at
            ) VALUES (?, 'remembered_reply', ?, ?, ?, ?, ?, ?, 0.9, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET status = 'active', updated_at = excluded.updated_at
            """,
            (
                memory_id,
                str(session.get("title") or "对话记忆")[:80],
                str(message.get("content") or "")[:4000],
                json.dumps(message.get("payload") or {}, ensure_ascii=False),
                str(session.get("id") or ""),
                message_id,
                json.dumps([str(session.get("mode") or "dialogue"), "user_confirmed"], ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
    return get_creator_memory(memory_id) or {}


def record_dialogue_feedback(message_id: str, action: str, note: str = "") -> dict[str, Any]:
    if action not in {"like_self", "unlike_self", "remember", "forget"}:
        raise ValueError("反馈类型无效")
    message = store.get_dialogue_message(message_id)
    if not message or message.get("role") != "assistant":
        raise ValueError("只能评价镜中人或书中人的回复")
    session = store.get_dialogue_session(str(message.get("session_id") or ""))
    if not session:
        raise ValueError("会话不存在")
    feedback_id = uuid.uuid5(uuid.NAMESPACE_URL, f"xiangzhongjing:feedback:{message_id}").hex
    now = _now()
    memory: dict[str, Any] = {}
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO dialogue_feedback (
                id, message_id, session_id, verdict, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                verdict = excluded.verdict,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (feedback_id, message_id, session["id"], action, note[:1000], now, now),
        )
        if action == "forget":
            connection.execute(
                """
                UPDATE creator_memories
                SET status = 'forgotten', updated_at = ?
                WHERE source_message_id = ?
                """,
                (now, message_id),
            )
        connection.commit()
    if action == "remember":
        memory = _remember_message(message, session)
    return {
        "message_id": message_id,
        "action": action,
        "note": note[:1000],
        "memory": memory,
    }


def forget_creator_memory(memory_id: str) -> dict[str, Any]:
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE creator_memories
            SET status = 'forgotten', updated_at = ?
            WHERE id = ? AND status = 'active'
            """,
            (_now(), memory_id),
        )
        connection.commit()
    if not cursor.rowcount:
        raise ValueError("长期记忆不存在或已忘记")
    return get_creator_memory(memory_id) or {}


def memory_engine_status() -> dict[str, Any]:
    index = sync_reference_document_chunks()
    with _connect() as connection:
        memories = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN status = 'forgotten' THEN 1 ELSE 0 END) AS forgotten
            FROM creator_memories
            """
        ).fetchone()
        feedback = connection.execute(
            "SELECT COUNT(*) AS count FROM dialogue_feedback"
        ).fetchone()
    return {
        **index,
        "active_memories": int(memories["active"] or 0) if memories else 0,
        "forgotten_memories": int(memories["forgotten"] or 0) if memories else 0,
        "feedback_count": int(feedback["count"] or 0) if feedback else 0,
    }
