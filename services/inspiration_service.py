"""Personalized, idempotent daily inspiration draws."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo

from services.book_library_quality import is_generation_ready_citation, normalize_material_text
from services.cover_service import profile as creator_profile
from services.creator_memory_service import retrieve_creator_context
from services.deepseek_service import load_writing_skill
from services.library_catalog import active_book_ids
from services.skill_runtime import SkillExecutionError, run_json
from services.xiangzhongjing_store import (
    _connect,
    _now,
    initialize_store,
    list_book_citations,
    load_state,
)


CREATOR_ID = "local_creator"
CREATOR_TIMEZONE = ZoneInfo("Asia/Shanghai")
PENDING_TTL = timedelta(minutes=2)
_LEGACY_IMPORT_LOCK = threading.Lock()
DRAW_TYPES: dict[str, dict[str, str]] = {
    "theme": {"label": "主题签", "target_group": "insight", "focus": "值得发展成完整作品的中心命题"},
    "emotion": {"label": "情绪签", "target_group": "opening", "focus": "尚未说透的情绪张力"},
    "event": {"label": "事件签", "target_group": "event", "focus": "近期生活里真实、可拍的变化"},
    "book": {"label": "书库签", "target_group": "quotes", "focus": "有效书库原句与它最合适的叙事时机"},
    "mirror": {"label": "镜中签", "target_group": "insight", "focus": "过去的自己与现在的自己都必须回答的问题"},
    "action": {"label": "行动签", "target_group": "daily", "focus": "今天半小时到一小时内可完成的创作动作"},
}
FEEDBACK_VERDICTS = {"useful", "not_useful"}
FEEDBACK_REASONS = {
    "too_vague",
    "repetitive",
    "irrelevant",
    "unlike_me",
    "not_shootable",
}


class InspirationDrawInProgress(RuntimeError):
    pass


class InspirationDrawNotFound(RuntimeError):
    pass


def local_date() -> str:
    return datetime.now(CREATOR_TIMEZONE).date().isoformat()


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (json.JSONDecodeError, TypeError):
        return fallback


def _clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        clean = _clean_text(item, item_limit)
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= limit:
            break
    return result


def _row_to_draw(row: Any) -> dict[str, Any] | None:
    if not row or str(row["status"] or "") != "completed":
        return None
    result = _json_load(str(row["result_json"] or "{}"), {})
    if not isinstance(result, dict):
        result = {}
    conversions = _json_load(str(row["conversions_json"] or "[]"), [])
    if not isinstance(conversions, list):
        conversions = []
    feedback_reasons = _json_load(str(row["feedback_reasons_json"] or "[]"), [])
    if not isinstance(feedback_reasons, list):
        feedback_reasons = []
    feedback_verdict = str(row["feedback_verdict"] or "")
    result.update(
        {
            "id": str(row["id"]),
            "date": str(row["local_date"]),
            "type": str(row["draw_type"]),
            "type_label": DRAW_TYPES.get(str(row["draw_type"]), {}).get("label", "灵感签"),
            "favorited": bool(row["favorited"]),
            "converted_to": [str(item) for item in conversions if str(item).strip()],
            "conversion_status": "converted" if conversions else "unused",
            "feedback": {
                "verdict": feedback_verdict,
                "reasons": [str(item) for item in feedback_reasons if str(item) in FEEDBACK_REASONS],
                "note": str(row["feedback_note"] or ""),
                "updated_at": str(row["feedback_at"] or ""),
            } if feedback_verdict in FEEDBACK_VERDICTS else {},
            "locked": True,
            "created_at": str(row["created_at"]),
            "completed_at": str(row["completed_at"] or ""),
            "deleted_at": str(row["deleted_at"] or ""),
        }
    )
    return result


def _verified_quote_lookup() -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for citation in list_book_citations("", limit=2000):
        if not is_generation_ready_citation(citation):
            continue
        signature = normalize_material_text(str(citation.get("quote") or ""))
        if signature:
            lookup[signature] = citation
    return lookup


def _import_legacy_draws() -> None:
    """Move the old workspace-array archive once, while dropping unverified quotes."""
    with _LEGACY_IMPORT_LOCK:
        state = load_state()
        legacy = [item for item in state.get("inspirationDraws", []) if isinstance(item, dict)]
        legacy_dates = {
            str(item.get("date") or "")
            for item in legacy[:365]
            if str(item.get("type") or "") in DRAW_TYPES
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item.get("date") or ""))
        }
        if not legacy_dates:
            return
        with _connect() as connection:
            stored_dates = {
                str(row["local_date"])
                for row in connection.execute(
                    "SELECT local_date FROM inspiration_draws WHERE creator_id = ?",
                    (CREATOR_ID,),
                ).fetchall()
            }
        if legacy_dates.issubset(stored_dates):
            return
        verified_quotes = _verified_quote_lookup()
        now = _now()
        with _connect() as connection:
            for item in legacy[:365]:
                draw_type = str(item.get("type") or "")
                draw_date = str(item.get("date") or "")
                if draw_type not in DRAW_TYPES or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", draw_date):
                    continue
                quote = _clean_text(item.get("quote"), 500)
                citation = verified_quotes.get(normalize_material_text(quote)) if quote else None
                result = {
                    "title": _clean_text(item.get("title"), 40) or DRAW_TYPES[draw_type]["label"],
                    "keywords": _string_list(item.get("keywords"), limit=4, item_limit=16),
                    "core_insight": _clean_text(item.get("core_insight") or item.get("text"), 500),
                    "text": _clean_text(item.get("core_insight") or item.get("text"), 500),
                    "why_today": "这支签来自旧版灵感匣签记录，已迁移到新的个人灵感档案。",
                    "three_questions": _string_list(item.get("prompts"), limit=3, item_limit=160)
                    or [_clean_text(item.get("question"), 160)],
                    "prompts": _string_list(item.get("prompts"), limit=3, item_limit=160)
                    or [_clean_text(item.get("question"), 160)],
                    "question": _clean_text(item.get("question"), 160),
                    "shootable_scenes": [],
                    "action": _clean_text(item.get("action"), 220),
                    "quote": str(citation.get("quote") or "") if citation else "",
                    "quote_source": str(citation.get("book") or "") if citation else "",
                    "source": str(citation.get("book") or "") if citation else "",
                    "quote_locator": str(citation.get("source_locator") or "") if citation else "",
                    "context_sources": ["历史版本迁移"],
                    "target_group": DRAW_TYPES[draw_type]["target_group"],
                }
                connection.execute(
                    """
                    INSERT OR IGNORE INTO inspiration_draws (
                        id, creator_id, local_date, draw_type, status, result_json,
                        favorited, conversions_json, created_at, updated_at, completed_at
                    ) VALUES (?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(item.get("id") or f"legacy_{uuid.uuid4().hex}"),
                        CREATOR_ID,
                        draw_date,
                        draw_type,
                        json.dumps(result, ensure_ascii=False),
                        1 if item.get("favorited") else 0,
                        json.dumps(item.get("converted_to") or [], ensure_ascii=False),
                        str(item.get("created_at") or now),
                        now,
                        str(item.get("created_at") or now),
                    ),
                )
            connection.commit()


def _recent_workspace_context() -> dict[str, Any]:
    state = load_state()
    raw_projects = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    project_summaries: list[dict[str, str]] = []
    for project in reversed(list(raw_projects.values())):
        if not isinstance(project, dict) or project.get("archived"):
            continue
        materials = project.get("materials") if isinstance(project.get("materials"), dict) else {}
        summary = {
            "title": _clean_text(project.get("title"), 80),
            "description": _clean_text(project.get("description"), 180),
            "theme": _clean_text(materials.get("theme"), 180),
            "insight": _clean_text(materials.get("insight"), 240),
            "event": _clean_text(materials.get("event"), 240),
        }
        if any(summary.values()):
            project_summaries.append(summary)
        if len(project_summaries) >= 5:
            break

    diaries = state.get("diaryEntries") if isinstance(state.get("diaryEntries"), list) else []
    diary_summaries: list[dict[str, str]] = []
    for entry in sorted(
        (item for item in diaries if isinstance(item, dict)),
        key=lambda item: str(item.get("published_at") or ""),
        reverse=True,
    )[:5]:
        diary_summaries.append(
            {
                "title": _clean_text(entry.get("project_title") or entry.get("title"), 80),
                "published_at": _clean_text(entry.get("published_at"), 32),
                "excerpt": _clean_text(entry.get("copy"), 420),
            }
        )
    return {"projects": project_summaries, "diary": diary_summaries}


def _recent_draw_summaries(limit: int = 30) -> list[dict[str, str]]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT local_date, draw_type, result_json
            FROM inspiration_draws
            WHERE creator_id = ? AND status = 'completed'
            ORDER BY local_date DESC
            LIMIT ?
            """,
            (CREATOR_ID, max(1, min(limit, 60))),
        ).fetchall()
    summaries: list[dict[str, str]] = []
    for row in rows:
        result = _json_load(str(row["result_json"] or "{}"), {})
        summaries.append(
            {
                "date": str(row["local_date"]),
                "type": str(row["draw_type"]),
                "title": _clean_text(result.get("title"), 50),
                "core_insight": _clean_text(result.get("core_insight") or result.get("text"), 180),
            }
        )
    return summaries


def _quote_candidates(query: str) -> list[dict[str, str]]:
    rows = list_book_citations("", limit=2000)
    active_ids = set(active_book_ids())
    terms = {item for item in re.findall(r"[\u4e00-\u9fff]{2,4}|[A-Za-z0-9]+", query) if len(item) >= 2}
    scored: list[tuple[int, int, dict[str, str]]] = []
    seen: set[str] = set()
    for row in rows:
        if not is_generation_ready_citation(row):
            continue
        book_id = str(row.get("book_id") or "")
        if active_ids and book_id and book_id not in active_ids:
            continue
        quote = _clean_text(row.get("quote"), 500)
        signature = normalize_material_text(quote)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        body = " ".join(
            [quote, _clean_text(row.get("evidence_text"), 600), _clean_text(row.get("quality_reason"), 160)]
        )
        score = sum(1 for term in terms if term in body)
        scored.append(
            (
                score,
                int(row.get("id") or 0),
                {
                    "id": str(row.get("id") or ""),
                    "book": _clean_text(row.get("book"), 80),
                    "attribution": _clean_text(row.get("attribution"), 80),
                    "quote": quote,
                    "source_locator": _clean_text(row.get("source_locator"), 160),
                },
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item for _, _, item in scored[:12]]


def _build_generation_context(draw_type: str) -> dict[str, Any]:
    workspace = _recent_workspace_context()
    profile = creator_profile()
    style_version, style = load_writing_skill()
    query_parts = [DRAW_TYPES[draw_type]["focus"]]
    query_parts.extend(item.get("title", "") for item in workspace["projects"][:4])
    query_parts.extend(item.get("title", "") for item in workspace["diary"][:3])
    query = "；".join(item for item in query_parts if item)
    memory = retrieve_creator_context(query, limit=7)
    quotes = _quote_candidates(query)
    sources = ["已发布个人 DNA"]
    if any(str(profile.get(key) or "").strip() for key in ("display_name", "creator_positioning", "content_columns", "style_keywords")):
        sources.append("个人创作者资料")
    if workspace["projects"]:
        sources.append(f"近期项目主题 {len(workspace['projects'])} 条")
    if workspace["diary"]:
        sources.append(f"已发布日记 {len(workspace['diary'])} 篇")
    for item in memory.get("sources", []):
        label = _clean_text(item.get("title") or item.get("source_filename") or "个人记忆", 60)
        if label and label not in sources:
            sources.append(label)
    return {
        "profile": {
            key: _clean_text(profile.get(key), 300)
            for key in ("display_name", "bio", "creator_positioning", "content_columns", "style_keywords")
        },
        "style_version": style_version,
        "style": style[:5200],
        "workspace": workspace,
        "memories": [
            {
                "title": _clean_text(item.get("title") or item.get("source_filename"), 80),
                "content": _clean_text(item.get("content"), 420),
                "source_type": _clean_text(item.get("source_type"), 40),
            }
            for item in memory.get("sources", [])[:6]
        ],
        "quotes": quotes,
        "recent_draws": _recent_draw_summaries(30),
        "context_sources": sources[:12],
    }


def _generate_candidates(draw_type: str, context: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    recent_draws = [
        {
            "date": item.get("date", ""),
            "type": item.get("type", ""),
            "title": item.get("title", ""),
            "core_insight": _clean_text(item.get("core_insight"), 100),
        }
        for item in context["recent_draws"]
    ]
    prompt_payload = {
        "today": local_date(),
        "draw_type": draw_type,
        "draw_type_label": DRAW_TYPES[draw_type]["label"],
        "draw_focus": DRAW_TYPES[draw_type]["focus"],
        "creator_profile": context["profile"],
        "recent_projects": context["workspace"]["projects"],
        "recent_diary": context["workspace"]["diary"],
        "retrieved_personal_memory": context["memories"],
        "verified_quote_candidates": context["quotes"][:10 if draw_type == "book" else 6],
        "last_30_draws_to_avoid": recent_draws,
    }
    response = run_json(
        "draw-daily-inspiration",
        "请为今天生成 3 个不同的候选灵感签。输入如下：\n"
        + json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":")),
        system_context=context["style"],
        max_tokens=1500,
        temperature=0.68,
    )
    raw_candidates = response["data"].get("candidates")
    if not isinstance(raw_candidates, list):
        raise SkillExecutionError("INSPIRATION_SCHEMA_INVALID", "每日灵感 Skill 未返回候选数组")
    return [item for item in raw_candidates if isinstance(item, dict)], response


def _candidate_payload(candidate: dict[str, Any]) -> dict[str, Any] | None:
    title = _clean_text(candidate.get("title"), 40)
    insight = _clean_text(candidate.get("core_insight"), 500)
    why_today = _clean_text(candidate.get("why_today"), 320)
    questions = _string_list(candidate.get("three_questions"), limit=3, item_limit=180)
    scenes = _string_list(candidate.get("shootable_scenes"), limit=3, item_limit=180)
    action = _clean_text(candidate.get("action"), 240)
    if not title or len(insight) < 24 or len(why_today) < 16 or len(questions) < 3 or not action:
        return None
    return {
        "title": title,
        "core_insight": insight,
        "why_today": why_today,
        "keywords": _string_list(candidate.get("keywords"), limit=4, item_limit=16)[:4],
        "three_questions": questions,
        "shootable_scenes": scenes,
        "action": action,
        "quote_id": _clean_text(candidate.get("quote_id"), 40),
    }


def _signature(item: dict[str, Any]) -> str:
    return normalize_material_text(f"{item.get('title', '')}{item.get('core_insight') or item.get('text') or ''}")


def _max_similarity(candidate: dict[str, Any], history: list[dict[str, Any]]) -> float:
    candidate_signature = _signature(candidate)
    if not candidate_signature:
        return 1.0
    return max(
        (
            SequenceMatcher(None, candidate_signature, _signature(item)).ratio()
            for item in history
            if _signature(item)
        ),
        default=0.0,
    )


def _choose_candidate(raw: list[dict[str, Any]], history: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [item for item in (_candidate_payload(value) for value in raw) if item]
    if not candidates:
        raise SkillExecutionError("INSPIRATION_SCHEMA_INVALID", "每日灵感 Skill 返回内容不完整")
    ranked = sorted(candidates, key=lambda item: _max_similarity(item, history))
    if _max_similarity(ranked[0], history) >= 0.78:
        raise SkillExecutionError("INSPIRATION_TOO_REPETITIVE", "候选灵感与近 30 天内容过于重复，请重新抽取")
    return ranked[0]


def _complete_result(
    draw_type: str,
    candidate: dict[str, Any],
    context: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    quote_map = {str(item["id"]): item for item in context["quotes"]}
    quote = quote_map.get(str(candidate.pop("quote_id", "")))
    questions = candidate["three_questions"]
    result = {
        **candidate,
        "text": candidate["core_insight"],
        "question": questions[0],
        "prompts": questions,
        "quote": str(quote.get("quote") or "") if quote else "",
        "quote_source": str(quote.get("book") or "") if quote else "",
        "source": str(quote.get("book") or "") if quote else "",
        "quote_attribution": str(quote.get("attribution") or "") if quote else "",
        "quote_locator": str(quote.get("source_locator") or "") if quote else "",
        "context_sources": context["context_sources"]
        + ([f"{quote.get('book')}有效原句"] if quote else []),
        "target_group": DRAW_TYPES[draw_type]["target_group"],
        "engine": "personalized_daily_inspiration_v1",
        "style_version": context["style_version"],
        "model": str(runtime.get("model") or ""),
        "latency_ms": int(runtime.get("latency_ms") or 0),
    }
    return result


def _claim_draw(draw_type: str) -> tuple[str, dict[str, Any] | None]:
    today = local_date()
    now = _now()
    with _connect() as connection:
        existing = connection.execute(
            "SELECT * FROM inspiration_draws WHERE creator_id = ? AND local_date = ?",
            (CREATOR_ID, today),
        ).fetchone()
        completed = _row_to_draw(existing)
        if completed:
            return "", completed
        if existing:
            try:
                started = datetime.fromisoformat(str(existing["updated_at"]))
            except ValueError:
                started = datetime.min
            if datetime.now() - started < PENDING_TTL:
                raise InspirationDrawInProgress("今天的灵感签正在生成，请稍候")
            connection.execute("DELETE FROM inspiration_draws WHERE id = ?", (str(existing["id"]),))
        draw_id = f"inspiration_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO inspiration_draws (
                id, creator_id, local_date, draw_type, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
            """,
            (draw_id, CREATOR_ID, today, draw_type, now, now),
        )
        connection.commit()
    return draw_id, None


def draw_daily(draw_type: str) -> dict[str, Any]:
    if draw_type not in DRAW_TYPES:
        raise ValueError("未知的灵感签类型")
    initialize_store()
    _import_legacy_draws()
    draw_id, existing = _claim_draw(draw_type)
    if existing:
        return {"draw": existing, "created": False, "server_date": local_date()}
    started = time.perf_counter()
    try:
        context = _build_generation_context(draw_type)
        raw_candidates, runtime = _generate_candidates(draw_type, context)
        candidate = _choose_candidate(raw_candidates, context["recent_draws"])
        result = _complete_result(draw_type, candidate, context, runtime)
        result["total_latency_ms"] = int((time.perf_counter() - started) * 1000)
        digest_payload = {
            "profile": context["profile"],
            "workspace": context["workspace"],
            "memory_titles": [item["title"] for item in context["memories"]],
            "quote_ids": [item["id"] for item in context["quotes"]],
        }
        context_digest = hashlib.sha256(
            json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        now = _now()
        with _connect() as connection:
            connection.execute(
                """
                UPDATE inspiration_draws
                SET status = 'completed', result_json = ?, context_digest = ?,
                    updated_at = ?, completed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (json.dumps(result, ensure_ascii=False), context_digest, now, now, draw_id),
            )
            row = connection.execute("SELECT * FROM inspiration_draws WHERE id = ?", (draw_id,)).fetchone()
            connection.commit()
        draw = _row_to_draw(row)
        if not draw:
            raise SkillExecutionError("INSPIRATION_SAVE_FAILED", "今日灵感签保存失败")
        return {"draw": draw, "created": True, "server_date": local_date()}
    except Exception:
        with _connect() as connection:
            connection.execute(
                "DELETE FROM inspiration_draws WHERE id = ? AND status = 'pending'", (draw_id,)
            )
            connection.commit()
        raise


def today_draw() -> dict[str, Any]:
    initialize_store()
    _import_legacy_draws()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM inspiration_draws WHERE creator_id = ? AND local_date = ?",
            (CREATOR_ID, local_date()),
        ).fetchone()
    return {"draw": _row_to_draw(row), "server_date": local_date()}


def list_draws(
    *, draw_type: str = "", status: str = "all", include_deleted: bool = False, limit: int = 365
) -> dict[str, Any]:
    initialize_store()
    _import_legacy_draws()
    clauses = ["creator_id = ?", "status = 'completed'"]
    values: list[Any] = [CREATOR_ID]
    if draw_type in DRAW_TYPES:
        clauses.append("draw_type = ?")
        values.append(draw_type)
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    elif status == "deleted":
        clauses.append("deleted_at IS NOT NULL")
    if status == "favorite":
        clauses.append("favorited = 1")
    elif status == "unused":
        clauses.append("conversions_json = '[]'")
    elif status == "converted":
        clauses.append("conversions_json != '[]'")
    elif status == "useful":
        clauses.append("feedback_verdict = 'useful'")
    elif status == "not_useful":
        clauses.append("feedback_verdict = 'not_useful'")
    values.append(max(1, min(limit, 365)))
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM inspiration_draws
            WHERE {' AND '.join(clauses)}
            ORDER BY local_date DESC, created_at DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
    items = [draw for draw in (_row_to_draw(row) for row in rows) if draw]
    return {"items": items, "total": len(items), "server_date": local_date()}


def update_draw(draw_id: str, *, favorited: bool | None = None, conversion: str = "") -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM inspiration_draws WHERE id = ? AND creator_id = ? AND status = 'completed'",
            (draw_id, CREATOR_ID),
        ).fetchone()
        if not row:
            raise InspirationDrawNotFound("灵感签不存在")
        conversions = _json_load(str(row["conversions_json"] or "[]"), [])
        if not isinstance(conversions, list):
            conversions = []
        clean_conversion = _clean_text(conversion, 160)
        if clean_conversion and clean_conversion not in conversions:
            conversions.append(clean_conversion)
        next_favorite = int(bool(favorited)) if favorited is not None else int(row["favorited"] or 0)
        connection.execute(
            """
            UPDATE inspiration_draws
            SET favorited = ?, conversions_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_favorite, json.dumps(conversions[:100], ensure_ascii=False), _now(), draw_id),
        )
        updated = connection.execute("SELECT * FROM inspiration_draws WHERE id = ?", (draw_id,)).fetchone()
        connection.commit()
    draw = _row_to_draw(updated)
    if not draw:
        raise InspirationDrawNotFound("灵感签不存在")
    return draw


def save_feedback(
    draw_id: str,
    *,
    verdict: str,
    reasons: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    initialize_store()
    if verdict not in FEEDBACK_VERDICTS:
        raise ValueError("未知的灵感反馈")
    clean_reasons = []
    for reason in reasons or []:
        if reason in FEEDBACK_REASONS and reason not in clean_reasons:
            clean_reasons.append(reason)
    if verdict == "useful":
        clean_reasons = []
    now = _now()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE inspiration_draws
            SET feedback_verdict = ?, feedback_reasons_json = ?, feedback_note = ?,
                feedback_at = ?, updated_at = ?
            WHERE id = ? AND creator_id = ? AND status = 'completed'
            """,
            (
                verdict,
                json.dumps(clean_reasons, ensure_ascii=False),
                _clean_text(note, 400),
                now,
                now,
                draw_id,
                CREATOR_ID,
            ),
        )
        row = connection.execute("SELECT * FROM inspiration_draws WHERE id = ?", (draw_id,)).fetchone()
        connection.commit()
    if cursor.rowcount != 1:
        raise InspirationDrawNotFound("灵感签不存在")
    draw = _row_to_draw(row)
    if not draw:
        raise InspirationDrawNotFound("灵感签不存在")
    return draw


def _conversion_project_ids(conversions: list[Any]) -> set[str]:
    project_ids: set[str] = set()
    for value in conversions:
        parts = str(value or "").split(":")
        if len(parts) >= 2 and parts[0] in {"project", "material"} and parts[1]:
            project_ids.add(parts[1])
    return project_ids


def inspiration_metrics(days: int = 14) -> dict[str, Any]:
    initialize_store()
    safe_days = max(7, min(int(days), 90))
    cutoff = (datetime.now(CREATOR_TIMEZONE).date() - timedelta(days=safe_days - 1)).isoformat()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM inspiration_draws
            WHERE creator_id = ? AND status = 'completed' AND local_date >= ?
            ORDER BY local_date DESC
            """,
            (CREATOR_ID, cutoff),
        ).fetchall()
        quality_rows = connection.execute(
            """
            SELECT project_id, edit_distance_ratio, adoption_status, published_at
            FROM creation_quality_outcomes
            ORDER BY id DESC
            """
        ).fetchall()
    draws = [draw for draw in (_row_to_draw(row) for row in rows) if draw]
    state = load_state()
    diary = state.get("diaryEntries") if isinstance(state.get("diaryEntries"), list) else []
    published_project_ids = {
        str(item.get("project_id") or "")
        for item in diary
        if isinstance(item, dict) and str(item.get("project_id") or "")
    }
    quality_by_project: dict[str, dict[str, Any]] = {}
    for row in quality_rows:
        project_id = str(row["project_id"] or "")
        if project_id and project_id not in quality_by_project:
            quality_by_project[project_id] = dict(row)
            published_project_ids.add(project_id)

    feedback_count = 0
    useful_count = 0
    converted_count = 0
    published_count = 0
    favorite_count = 0
    reason_counts = {reason: 0 for reason in FEEDBACK_REASONS}
    latencies: list[int] = []
    edit_distances: list[float] = []
    per_type: dict[str, dict[str, int]] = {
        draw_type: {"draws": 0, "useful": 0, "converted": 0, "published": 0}
        for draw_type in DRAW_TYPES
    }
    for draw in draws:
        draw_type = str(draw.get("type") or "")
        type_stats = per_type.get(draw_type)
        if type_stats:
            type_stats["draws"] += 1
        if draw.get("favorited"):
            favorite_count += 1
        feedback = draw.get("feedback") if isinstance(draw.get("feedback"), dict) else {}
        verdict = str(feedback.get("verdict") or "")
        if verdict in FEEDBACK_VERDICTS:
            feedback_count += 1
        if verdict == "useful":
            useful_count += 1
            if type_stats:
                type_stats["useful"] += 1
        for reason in feedback.get("reasons", []) if isinstance(feedback.get("reasons"), list) else []:
            if reason in reason_counts:
                reason_counts[reason] += 1
        conversions = draw.get("converted_to") if isinstance(draw.get("converted_to"), list) else []
        project_ids = _conversion_project_ids(conversions)
        if conversions:
            converted_count += 1
            if type_stats:
                type_stats["converted"] += 1
        published_ids = project_ids & published_project_ids
        if published_ids:
            published_count += 1
            if type_stats:
                type_stats["published"] += 1
            for project_id in published_ids:
                distance = quality_by_project.get(project_id, {}).get("edit_distance_ratio")
                if distance is not None:
                    edit_distances.append(float(distance))
        latency = int(draw.get("total_latency_ms") or draw.get("latency_ms") or 0)
        if latency > 0:
            latencies.append(latency)

    total = len(draws)
    sorted_latency = sorted(latencies)
    p95_index = max(0, min(len(sorted_latency) - 1, int(len(sorted_latency) * 0.95))) if sorted_latency else 0
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0
    return {
        "period_days": safe_days,
        "from_date": cutoff,
        "to_date": local_date(),
        "draw_count": total,
        "feedback_count": feedback_count,
        "useful_count": useful_count,
        "favorite_count": favorite_count,
        "converted_count": converted_count,
        "published_count": published_count,
        "rates": {
            "feedback": round(feedback_count / total, 4) if total else 0,
            "useful": round(useful_count / feedback_count, 4) if feedback_count else 0,
            "conversion": round(converted_count / total, 4) if total else 0,
            "publication": round(published_count / total, 4) if total else 0,
            "under_9_seconds": round(sum(1 for value in latencies if value <= 9000) / len(latencies), 4) if latencies else 0,
        },
        "latency": {
            "samples": len(latencies),
            "average_ms": avg_latency,
            "p95_ms": sorted_latency[p95_index] if sorted_latency else 0,
        },
        "average_published_edit_distance": round(sum(edit_distances) / len(edit_distances), 4) if edit_distances else None,
        "reason_counts": {key: value for key, value in reason_counts.items() if value},
        "per_type": per_type,
        "targets": {
            "useful_rate": 0.5,
            "conversion_rate": 0.25,
            "regular_latency_ms": 9000,
        },
    }


def delete_draw(draw_id: str) -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE inspiration_draws SET deleted_at = ?, updated_at = ?
            WHERE id = ? AND creator_id = ? AND status = 'completed'
            """,
            (_now(), _now(), draw_id, CREATOR_ID),
        )
        connection.commit()
    if cursor.rowcount != 1:
        raise InspirationDrawNotFound("灵感签不存在")
    return {"deleted": True, "id": draw_id}


def restore_draw(draw_id: str) -> dict[str, Any]:
    initialize_store()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE inspiration_draws SET deleted_at = NULL, updated_at = ?
            WHERE id = ? AND creator_id = ? AND status = 'completed'
            """,
            (_now(), draw_id, CREATOR_ID),
        )
        row = connection.execute("SELECT * FROM inspiration_draws WHERE id = ?", (draw_id,)).fetchone()
        connection.commit()
    draw = _row_to_draw(row)
    if not draw:
        raise InspirationDrawNotFound("灵感签不存在")
    return draw
