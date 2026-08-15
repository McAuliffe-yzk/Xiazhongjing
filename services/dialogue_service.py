"""镜中人 / 书中人的对话业务层。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from services.book_library_quality import is_generation_ready_citation
from services.cover_service import profile as creator_profile
from services.creator_memory_service import (
    forget_creator_memory,
    memory_engine_status,
    record_dialogue_feedback,
    retrieve_book_citations,
    retrieve_creator_context,
    save_summary_checkpoint,
    should_refresh_session_summary,
    upsert_session_summary_memory,
)
from services.deepseek_service import load_writing_skill
from services.library_catalog import book_map
from services.skill_runtime import SkillExecutionError, run_json
from services.tavily_service import search
from services.xiangzhongjing_store import (
    add_dialogue_message,
    clear_dialogue_messages,
    create_dialogue_session,
    create_book_persona as store_create_book_persona,
    create_persona_asset,
    delete_dialogue_session,
    get_dialogue_memory,
    get_dialogue_message,
    get_dialogue_session,
    get_book_persona,
    list_book_citations,
    list_dialogue_messages,
    list_dialogue_messages_page,
    list_dialogue_sessions,
    list_persona_assets,
    list_book_personas,
    list_reference_documents,
    save_dialogue_memory,
    update_dialogue_message,
    update_dialogue_session,
    update_persona_asset_type,
    update_book_persona as store_update_book_persona,
    delete_book_persona as store_delete_book_persona,
)


def dialogue_personas() -> dict[str, Any]:
    personas = list_book_personas()
    return {
        "personas": [
            {
                "id": "mirror-self",
                "type": "mirror",
                "name": "镜中人",
                "label": "被蒸馏出来的自己",
                "description": "基于个人风格 Skill、人设资产和长期对话记忆，像另一个时空里的自己一样交流。",
            },
            *personas,
        ],
        "books": book_map(),
    }


def _book_persona_map() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in list_book_personas()}


def _suggest_book_persona_sync(book_ids: list[str]) -> dict[str, Any]:
    catalog = book_map()
    selected = [catalog[item] for item in book_ids if item in catalog]
    if not selected:
        raise SkillExecutionError("BOOK_REQUIRED", "请先选择至少一本已导入书籍")
    primary = selected[0]
    name = str(primary.get("author") or "").strip()
    if not name:
        name = str(primary.get("title") or "书中人").replace("《", "").replace("》", "")
    titles = "、".join(str(item.get("title") or "") for item in selected)
    return {
        "name": name,
        "book_ids": [str(item["id"]) for item in selected],
        "description": f"基于{titles}的原文、上下文与阅读笔记进行交流。",
        "voice": "先理解问题，再从书中的判断方式出发回应；保持人物气质，但不表演腔。",
        "boundaries": "只把书库中已核验的原句作为直接引文；其余内容明确属于思想推演，不虚构人物经历。",
    }


def _create_book_persona_sync(payload: dict[str, Any]) -> dict[str, Any]:
    return store_create_book_persona(
        str(payload.get("name") or ""),
        payload.get("book_ids") if isinstance(payload.get("book_ids"), list) else [],
        description=str(payload.get("description") or ""),
        voice=str(payload.get("voice") or ""),
        boundaries=str(payload.get("boundaries") or ""),
        persona_id=str(payload.get("id") or ""),
    )


def _update_book_persona_sync(persona_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    persona = store_update_book_persona(persona_id, payload)
    if not persona:
        raise SkillExecutionError("BOOK_PERSONA_NOT_FOUND", "书中人不存在")
    return persona


def _delete_book_persona_sync(persona_id: str, permanent: bool = False) -> dict[str, Any]:
    if not store_delete_book_persona(persona_id, permanent=permanent):
        raise SkillExecutionError("BOOK_PERSONA_NOT_FOUND", "书中人不存在")
    return {"deleted": True, "permanent": permanent, "persona_id": persona_id}


def _book_id_from_citation(citation: dict[str, Any]) -> str:
    stored_id = str(citation.get("book_id") or "").strip()
    if stored_id:
        return stored_id
    title = str(citation.get("book") or "").replace("《", "").replace("》", "")
    for book_id, book in book_map().items():
        expected = str(book.get("title") or "").replace("《", "").replace("》", "")
        if title and (title in expected or expected in title):
            return book_id
    return ""


def _recent_messages(session_id: str) -> list[dict[str, str]]:
    messages = list_dialogue_messages(session_id, limit=30)
    return [
        {
            "role": str(item.get("role") or ""),
            "content": str(item.get("content") or "")[:1600],
        }
        for item in messages[-12:]
    ]


def _trace_item(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": result.get("run_id"),
        "skill": result.get("skill"),
        "version": result.get("version"),
        "model": result.get("model"),
        "latency_ms": result.get("latency_ms"),
    }


def _clean_extractable(items: Any) -> list[dict[str, str]]:
    allowed = {"theme", "insight", "opening", "daily", "event", "quote", "ending_reference", "persona_asset"}
    if not isinstance(items, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        text = str(item.get("text") or "").strip()
        if item_type not in allowed or not text:
            continue
        cleaned.append(
            {
                "type": item_type,
                "text": text[:1200],
                "reason": str(item.get("reason") or "").strip()[:500],
            }
        )
    return cleaned[:8]


def _compact_reference_memory(limit: int = 11) -> list[dict[str, Any]]:
    documents = list_reference_documents(limit=limit)
    memory: list[dict[str, Any]] = []
    for document in documents:
        analysis = document.get("analysis") if isinstance(document.get("analysis"), dict) else {}
        stable_evidence = analysis.get("stable_evidence")
        if not isinstance(stable_evidence, list):
            stable_evidence = analysis.get("evidence") if isinstance(analysis.get("evidence"), list) else []
        narrative_patterns = analysis.get("narrative_patterns")
        if not isinstance(narrative_patterns, list):
            narrative_patterns = []
        strengths = analysis.get("strengths") if isinstance(analysis.get("strengths"), list) else []
        memory.append(
            {
                "filename": document.get("filename", ""),
                "maturity": analysis.get("maturity", "final_script"),
                "strengths": [str(item)[:160] for item in strengths[:3]],
                "stable_evidence": [
                    {
                        "dimension": str(item.get("dimension") or item.get("pattern") or "")[:80],
                        "evidence": str(item.get("evidence") or item.get("description") or "")[:220],
                    }
                    for item in stable_evidence[:4]
                    if isinstance(item, dict)
                ],
                "narrative_patterns": [
                    {
                        "pattern": str(item.get("pattern") or "")[:120],
                        "evidence": str(item.get("evidence") or "")[:220],
                    }
                    for item in narrative_patterns[:3]
                    if isinstance(item, dict)
                ],
            }
        )
    return memory


def _dialogue_asset_source_label(source: str) -> str:
    if not source.startswith("dialogue:"):
        return source or "手动沉淀"
    session_id = source.split(":", 1)[1].strip()
    session = get_dialogue_session(session_id) if session_id else None
    if not session:
        return "对话会话"
    if session.get("mode") == "book":
        persona = BOOK_PERSONAS.get(str(session.get("persona_id") or ""))
        actor = persona["name"] if persona else "书中人"
    else:
        actor = "镜中人"
    title = str(session.get("title") or "").strip()
    return f"{actor} · {title}" if title else actor


def _dialogue_asset_origin(source: str) -> dict[str, str]:
    if not source.startswith("dialogue:"):
        return {"mode": "manual", "persona_id": "", "persona_name": "手动沉淀"}
    session_id = source.split(":", 1)[1].strip()
    session = get_dialogue_session(session_id) if session_id else None
    if not session:
        return {"mode": "unknown", "persona_id": "", "persona_name": "对话会话"}
    if session.get("mode") == "book":
        persona_id = str(session.get("persona_id") or "")
        persona = BOOK_PERSONAS.get(persona_id)
        return {
            "mode": "book",
            "persona_id": persona_id,
            "persona_name": persona["name"] if persona else "书中人",
        }
    return {"mode": "mirror", "persona_id": "mirror-self", "persona_name": "镜中人"}


def _list_assets_sync(limit: int = 100) -> dict[str, Any]:
    assets = list_persona_assets("", limit=limit)
    return {
        "assets": [
            {
                **asset,
                "source_label": _dialogue_asset_source_label(str(asset.get("source") or "")),
                "origin": _dialogue_asset_origin(str(asset.get("source") or "")),
            }
            for asset in assets
        ],
        "reference_memory_count": len(_compact_reference_memory()),
    }


ALLOWED_ASSET_TYPES = {
    "dialogue_theme",
    "dialogue_insight",
    "dialogue_opening",
    "dialogue_daily",
    "dialogue_event",
    "dialogue_quote",
    "dialogue_ending_reference",
    "creator_belief",
}


def _decorate_asset(asset: dict[str, Any]) -> dict[str, Any]:
    source = str(asset.get("source") or "")
    return {
        **asset,
        "source_label": _dialogue_asset_source_label(source),
        "origin": _dialogue_asset_origin(source),
    }


def _update_asset_sync(asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    asset_type = str(payload.get("asset_type") or "").strip()
    if asset_type not in ALLOWED_ASSET_TYPES:
        raise SkillExecutionError("ASSET_TYPE_INVALID", "请选择有效的沉淀素材类别")
    asset = update_persona_asset_type(asset_id, asset_type)
    if not asset:
        raise SkillExecutionError("ASSET_NOT_FOUND", "沉淀素材不存在")
    return {"asset": _decorate_asset(asset)}


def _normalize_evidence_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _book_quote_evidence(
    citations: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for item in citations:
        if not isinstance(item, dict):
            continue
        url = str(item.get("source_url") or item.get("url") or "").strip()
        if not url:
            continue
        evidence[url] = "\n".join(
            [
                str(item.get("quote") or ""),
                str(item.get("evidence_text") or ""),
            ]
        )
    for item in search_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        evidence[url] = "\n".join(
            [
                evidence.get(url, ""),
                str(item.get("content") or ""),
                str(item.get("raw_content") or ""),
            ]
        )
    return evidence


def _has_unverified_book_quote(
    data: dict[str, Any],
    verified_evidence: dict[str, str] | None = None,
) -> bool:
    evidence = verified_evidence or {}
    book_support = data.get("book_support")
    has_verified_quote = False
    if isinstance(book_support, list):
        for item in book_support:
            if not isinstance(item, dict):
                continue
            source_status = str(item.get("source_status") or "").strip()
            support_type = str(item.get("type") or "").strip()
            source_url = str(item.get("source_url") or "").strip()
            quote_text = str(item.get("text") or "").strip()
            if source_status == "verified":
                source_text = evidence.get(source_url, "")
                if not source_url or not source_text:
                    return True
                if quote_text and _normalize_evidence_text(quote_text) not in _normalize_evidence_text(source_text):
                    return True
                has_verified_quote = True
                continue
            if support_type == "quote":
                return True
    reply = str(data.get("reply") or "")
    quote_pattern = re.compile(
        r"(老子|道德经|《道德经》|马斯克|埃隆|艾萨克森|剑来|《剑来》|陈平安|烽火戏诸侯)"
        r".{0,16}(说|讲|写|提到|有句话|有一句|里说|里提到|说过|讲过|写过)"
        r".{0,10}[“\"'‘「『]",
    )
    return bool(quote_pattern.search(reply) and not has_verified_quote)


def _run_book_dialogue(
    user_prompt: str,
    *,
    verified_evidence: dict[str, str],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    result = run_json(
        "book-person-dialogue",
        user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if not _has_unverified_book_quote(result["data"], verified_evidence):
        return result
    repaired = run_json(
        "book-person-dialogue",
        f"""
上一轮输出存在未核验引文风险：未提供 verified citation 时，不能写“某某说/讲/写/提到”并接引号原文，也不能把未核验内容标成 quote。

请重新执行原始任务：
- 删除所有未核验的原文式表达。
- 本轮允许标记为 verified 的来源 URL 只有：{json.dumps(list(verified_evidence.keys()), ensure_ascii=False)}。
- 如果上面列表为空，`book_support` 不得出现 `type: "quote"` 或 `source_status: "verified"`。
- 如果只是思想支撑，用“用《某书》的思想来说 / 可以转译为”表达。
- `book_support` 中未核验内容必须是 `type: "paraphrase"` 且 `source_status: "paraphrase"`。
- 只返回合法 JSON。

原始任务：
{user_prompt.strip()}

上一轮输出：
{json.dumps(result["data"], ensure_ascii=False, indent=2)[:6000]}
""".strip(),
        max_tokens=max_tokens,
        temperature=min(temperature, 0.2),
    )
    if _has_unverified_book_quote(repaired["data"], verified_evidence):
        raise SkillExecutionError(
            "UNVERIFIED_BOOK_QUOTE",
            "书中人返回了未核验引文，已按失败不兜底策略停止",
        )
    return repaired


def _book_search_results(
    user_message: str,
    persona: dict[str, str],
    enabled: bool,
) -> list[dict[str, Any]]:
    if not enabled:
        return []
    book = book_map().get(persona.get("book_id", ""))
    if not book:
        return []
    query = " ".join(
        [
            book["title"],
            book["author"],
            "原文 语录 思想",
            user_message[:80],
        ]
    )
    try:
        return search(
            query,
            max_results=4,
            search_depth="basic",
            timeout=(3, 8),
            include_raw_content=False,
        )
    except SkillExecutionError:
        return []


def _create_session_sync(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "mirror")
    personas = _book_persona_map()
    default_persona = next(iter(personas), "")
    persona_id = str(payload.get("persona_id") or ("mirror-self" if mode == "mirror" else default_persona))
    title = str(payload.get("title") or "").strip()
    if mode == "mirror":
        persona_id = "mirror-self"
    elif persona_id not in personas:
        if not default_persona:
            raise SkillExecutionError("BOOK_PERSONA_REQUIRED", "请先从已导入书籍创建一位书中人")
        persona_id = default_persona
    return create_dialogue_session(
        "",
        mode,
        persona_id,
        title=title,
        source_scope={"created_from": "xiangzhongjing-demo"},
    )


def _list_sessions_sync(
    project_id: str = "",
    *,
    query: str = "",
    mode: str = "",
    persona_id: str = "",
    include_deleted: bool = False,
) -> dict[str, Any]:
    return {
        "sessions": list_dialogue_sessions(
            project_id=project_id,
            query=query,
            mode=mode,
            persona_id=persona_id,
            include_deleted=include_deleted,
            global_only=not bool(project_id),
            limit=100,
        )
    }


def _get_session_sync(session_id: str) -> dict[str, Any]:
    session = get_dialogue_session(session_id)
    if not session:
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "对话会话不存在")
    page = list_dialogue_messages_page(session_id, limit=30)
    return {
        "session": session,
        "messages": page["messages"],
        "messages_page": page,
        "memory": get_dialogue_memory(session_id),
    }


def _get_messages_sync(session_id: str, *, before: str = "", limit: int = 30) -> dict[str, Any]:
    if not get_dialogue_session(session_id):
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "对话会话不存在")
    return list_dialogue_messages_page(session_id, limit=limit, before=before)


def _patch_session_sync(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    session = get_dialogue_session(session_id)
    if not session or session.get("deleted_at"):
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "对话会话不存在")
    title = payload.get("title")
    if title is not None:
        title = str(title).strip()[:80]
        if not title:
            raise SkillExecutionError("DIALOGUE_TITLE_EMPTY", "会话标题不能为空")
    pinned = payload.get("pinned") if isinstance(payload.get("pinned"), bool) else None
    return update_dialogue_session(session_id, title=title, pinned=pinned)


def _delete_session_sync(session_id: str, *, permanent: bool = False) -> dict[str, Any]:
    deleted = delete_dialogue_session(session_id, permanent=permanent)
    if not deleted:
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "对话会话不存在")
    return {"deleted": True, "permanent": permanent, "session": deleted}


def _bulk_delete_sessions_sync(payload: dict[str, Any]) -> dict[str, Any]:
    raw_ids = payload.get("session_ids")
    if not isinstance(raw_ids, list):
        raw_ids = []
    session_ids = []
    seen: set[str] = set()
    for value in raw_ids:
        session_id = str(value or "").strip()
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        session_ids.append(session_id)
    if not session_ids:
        raise SkillExecutionError("DIALOGUE_BULK_EMPTY", "没有可清空的会话")
    permanent = bool(payload.get("permanent"))
    deleted_sessions = []
    for session_id in session_ids[:200]:
        session = get_dialogue_session(session_id)
        if not session:
            continue
        if permanent and not session.get("deleted_at"):
            continue
        if not permanent and session.get("deleted_at"):
            continue
        deleted = delete_dialogue_session(session_id, permanent=permanent)
        if deleted:
            deleted_sessions.append(deleted)
    if not deleted_sessions:
        raise SkillExecutionError("DIALOGUE_BULK_EMPTY", "没有可清空的会话")
    return {
        "deleted": True,
        "permanent": permanent,
        "count": len(deleted_sessions),
        "sessions": deleted_sessions,
    }


def _restore_session_sync(session_id: str) -> dict[str, Any]:
    session = get_dialogue_session(session_id)
    if not session or not session.get("deleted_at"):
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "最近删除中没有这段会话")
    return update_dialogue_session(session_id, deleted=False)


def _clear_session_sync(session_id: str) -> dict[str, Any]:
    session = get_dialogue_session(session_id)
    if not session or session.get("deleted_at"):
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "对话会话不存在")
    return {"cleared": True, "session": clear_dialogue_messages(session_id)}


def _send_message_sync(
    session_id: str,
    payload: dict[str, Any],
    progress: Callable[[str, str, dict[str, Any] | None], None] | None = None,
) -> dict[str, Any]:
    def emit(stage: str, label: str, meta: dict[str, Any] | None = None) -> None:
        if progress:
            progress(stage, label, meta)

    session = get_dialogue_session(session_id)
    if not session or session.get("deleted_at"):
        raise SkillExecutionError("DIALOGUE_SESSION_NOT_FOUND", "对话会话不存在")
    user_message = str(payload.get("message") or "").strip()
    retry_message_id = str(payload.get("retry_message_id") or "").strip()
    turn_id = ""
    user_message_id = ""
    if retry_message_id:
        previous = get_dialogue_message(retry_message_id)
        if not previous or previous.get("session_id") != session_id or previous.get("role") != "user":
            raise SkillExecutionError("DIALOGUE_RETRY_NOT_FOUND", "找不到可重试的消息")
        if previous.get("status") != "failed":
            raise SkillExecutionError("DIALOGUE_RETRY_NOT_ALLOWED", "这条消息当前不需要重试")
        user_message = str(previous.get("content") or "").strip()
        user_message_id = retry_message_id
        turn_id = str(previous.get("turn_id") or uuid.uuid4().hex)
        update_dialogue_message(user_message_id, status="pending")
    else:
        if not user_message:
            raise SkillExecutionError("DIALOGUE_MESSAGE_EMPTY", "请输入要交流的问题")
        turn_id = uuid.uuid4().hex
        user_message = user_message[:8000]
        created = add_dialogue_message(
            session_id,
            "user",
            user_message,
            payload={"context_scope": "global_dialogue"},
            turn_id=turn_id,
            status="pending",
        )
        user_message_id = created["id"]

    emit("accepted", "问题已进入当前会话", {"mode": session["mode"]})

    memory = get_dialogue_memory(session_id)
    recent = _recent_messages(session_id)
    trace: list[dict[str, Any]] = []
    grounding: dict[str, Any]

    if session["mode"] == "mirror":
        style_version, style = load_writing_skill()
        profile = creator_profile()
        emit("retrieving_memory", "正在检索相关个人记忆", None)
        grounding = retrieve_creator_context(user_message, limit=8)
        reference_memory = grounding["sources"]
        emit(
            "memory_ready",
            f"已找到 {len(reference_memory)} 条相关个人依据",
            {"source_count": len(reference_memory)},
        )
        emit("generating", "镜中人正在组织回答", {"skill": "mirror-self-dialogue"})
        result = run_json(
            "mirror-self-dialogue",
            f"""
用户消息：
{user_message}

当前创作者身份：
{json.dumps({key: profile.get(key, "") for key in ("display_name", "handle", "bio", "location", "creator_positioning", "content_columns", "style_keywords")}, ensure_ascii=False, indent=2)}

个人历史文稿与长期记忆（当前索引 {grounding['index']['documents']} 篇文稿；本轮按问题召回）：
{json.dumps(reference_memory, ensure_ascii=False, indent=2)[:14000]}

记忆使用规则：
- 只把召回内容当成可核查的过往，不要把没出现的细节补全。
- 与用户问题无关的记忆不要强行提及。
- 回答可以自然地说“我记得”，但不能说出超出依据的具体事实。

用户对历史回复的校准：
{json.dumps(grounding.get("calibration", []), ensure_ascii=False, indent=2)[:5000]}

校准使用规则：
- `like_self` 是可保留的声音证据；`unlike_self` 是必须避免复现的表达。
- `remember` 已作为长期记忆按相关性召回；`forget` 内容不得作为身份或事实依据。
- 校准只改变回应方式，不得覆盖本轮用户明确表达。

会话记忆：
{json.dumps(memory, ensure_ascii=False, indent=2)[:4000]}

最近消息：
{json.dumps(recent, ensure_ascii=False, indent=2)[:7000]}

当前发布风格版本：{style_version}

只返回符合 Skill contract 的 JSON。
""".strip(),
            system_context=style,
            max_tokens=1800,
            temperature=0.58,
        )
        data = result["data"]
        trace.append(_trace_item(result))
        reply = str(data.get("reply") or "").strip()
        extractable = _clean_extractable(data.get("extractable"))
        citations: list[dict[str, Any]] = []
    else:
        personas = _book_persona_map()
        persona = personas.get(session["persona_id"])
        if not persona:
            raise SkillExecutionError("BOOK_PERSONA_NOT_FOUND", "当前书中人已归档或不存在")
        emit("retrieving_library", f"正在检索{persona['name']}的本地书库依据", None)
        retrieval_query = " ".join(
            [user_message, persona.get("label", ""), persona.get("description", "")]
        )
        citations = []
        for book_id in persona.get("book_ids") or [persona.get("book_id", "")]:
            if not book_id:
                continue
            citations.extend(retrieve_book_citations(retrieval_query, book_id, limit=8))
        citations = citations[:12]
        search_results = _book_search_results(
            user_message,
            persona,
            bool(payload.get("use_search")),
        )
        emit(
            "library_ready",
            f"已找到 {len(citations)} 条本地依据",
            {
                "source_count": len(citations),
                "search_requested": bool(payload.get("use_search")),
                "search_result_count": len(search_results),
            },
        )
        grounding = {
            "query": user_message,
            "retrieval": "local_book_relevance_rank",
            "sources": [
                {
                    "id": str(item.get("id") or ""),
                    "source_type": "book_citation",
                    "title": str(item.get("book") or persona["name"]),
                    "content": str(item.get("quote") or item.get("evidence_text") or "")[:700],
                    "attribution": str(item.get("attribution") or ""),
                    "source_url": str(item.get("source_url") or ""),
                    "source_locator": str(item.get("source_locator") or ""),
                    "confidence": 1.0,
                }
                for item in citations
            ],
            "search": {
                "requested": bool(payload.get("use_search")),
                "result_count": len(search_results),
                "used": bool(search_results),
            },
        }
        verified_evidence = _book_quote_evidence(citations, search_results)
        emit("generating", f"{persona['name']}正在组织回答", {"skill": "book-person-dialogue"})
        result = _run_book_dialogue(
            f"""
用户消息：
{user_message}

选中书中人格：
{json.dumps(persona, ensure_ascii=False, indent=2)}

已核验引文：
{json.dumps(citations, ensure_ascii=False, indent=2)[:6000]}

联网检索片段（可能为空；未逐字核验不得包装成原文）：
{json.dumps(search_results, ensure_ascii=False, indent=2)[:7000]}

本轮允许标记为 verified 的来源 URL：
{json.dumps(list(verified_evidence.keys()), ensure_ascii=False, indent=2)}

如果上面列表为空，不得输出 `type: "quote"` 或 `source_status: "verified"`，也不得写“某某说/讲/写/提到”并接引号原文。

会话记忆：
{json.dumps(memory, ensure_ascii=False, indent=2)[:4000]}

最近消息：
{json.dumps(recent, ensure_ascii=False, indent=2)[:7000]}

只返回符合 Skill contract 的 JSON。
""".strip(),
            verified_evidence=verified_evidence,
            max_tokens=1900,
            temperature=0.54,
        )
        data = result["data"]
        trace.append(_trace_item(result))
        reply = str(data.get("reply") or "").strip()
        extractable = _clean_extractable(data.get("extractable"))
        citations = data.get("book_support") if isinstance(data.get("book_support"), list) else []

    if not reply:
        raise SkillExecutionError("DIALOGUE_EMPTY_REPLY", "对话 Skill 没有返回有效回复")
    update_dialogue_message(user_message_id, status="completed")
    assistant_payload = {**data, "grounding": grounding}
    assistant_message = add_dialogue_message(
        session_id,
        "assistant",
        reply,
        payload=assistant_payload,
        citations=citations,
        extractable=extractable,
        skill_trace=trace,
        turn_id=turn_id,
        status="completed",
    )

    if session.get("title", "").endswith("新会话") or session.get("title") in {"镜中人对话", "书中人对话"}:
        title = re.sub(r"\s+", " ", user_message).strip()[:22]
        if title:
            session = update_dialogue_session(session_id, title=title)

    session_messages = list_dialogue_messages(session_id, limit=200)
    message_count = len(session_messages)
    if should_refresh_session_summary(session_id, message_count):
        emit("updating_memory", "正在增量更新跨会话记忆", None)
        summary = run_json(
            "summarize-dialogue-memory",
            f"""
会话消息：
{json.dumps(session_messages[-80:], ensure_ascii=False, indent=2)[:14000]}

旧记忆：
{json.dumps(memory, ensure_ascii=False, indent=2)[:4000]}

只返回 JSON。
""".strip(),
            max_tokens=1200,
            temperature=0.12,
        )
        trace.append(_trace_item(summary))
        save_dialogue_memory(session_id, summary["data"])
        latest_session = get_dialogue_session(session_id) or session
        upsert_session_summary_memory(latest_session, summary["data"], assistant_message["id"])
        save_summary_checkpoint(session_id, message_count, assistant_message["id"])

    response = {
        "session": get_dialogue_session(session_id),
        "message": assistant_message,
        "reply": reply,
        "extractable": extractable,
        "citations": citations,
        "trace": trace,
    }
    emit("completed", "回答已完成", {"message_id": assistant_message["id"]})
    return response


def _extract_sync(payload: dict[str, Any]) -> dict[str, Any]:
    target = str(payload.get("target") or "material")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise SkillExecutionError("EXTRACT_TEXT_EMPTY", "沉淀内容为空")
    if target == "persona_asset":
        asset = create_persona_asset(
            str(payload.get("asset_type") or "voice_rule"),
            text,
            title=str(payload.get("title") or "")[:80],
            project_id=str(payload.get("project_id") or ""),
            source=str(payload.get("source") or "dialogue"),
            confidence=0.7,
        )
        return {"saved": True, "target": target, "asset": asset}
    return {
        "saved": True,
        "target": "material",
        "material_group": str(payload.get("material_group") or "insight"),
        "text": text,
    }


async def create_session(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_session_sync, payload)


async def list_sessions(
    project_id: str = "",
    *,
    query: str = "",
    mode: str = "",
    persona_id: str = "",
    include_deleted: bool = False,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _list_sessions_sync,
        project_id,
        query=query,
        mode=mode,
        persona_id=persona_id,
        include_deleted=include_deleted,
    )


async def get_session(session_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_session_sync, session_id)


async def get_messages(session_id: str, *, before: str = "", limit: int = 30) -> dict[str, Any]:
    return await asyncio.to_thread(_get_messages_sync, session_id, before=before, limit=limit)


async def patch_session(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_patch_session_sync, session_id, payload)


async def delete_session(session_id: str, *, permanent: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(_delete_session_sync, session_id, permanent=permanent)


async def bulk_delete_sessions(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_bulk_delete_sessions_sync, payload)


async def restore_session(session_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_restore_session_sync, session_id)


async def clear_session(session_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_clear_session_sync, session_id)


async def send_message(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_send_message_sync, session_id, payload)
    except Exception:
        pending = await asyncio.to_thread(list_dialogue_messages, session_id, 8)
        for message in reversed(pending):
            if message.get("role") == "user" and message.get("status") == "pending":
                await asyncio.to_thread(
                    update_dialogue_message,
                    message["id"],
                    status="failed",
                    payload={"error_code": "DIALOGUE_REPLY_FAILED"},
                )
                break
        raise


async def stream_message_events(
    session_id: str, payload: dict[str, Any]
) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def progress(stage: str, label: str, meta: dict[str, Any] | None = None) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {"type": "stage", "stage": stage, "label": label, "meta": meta or {}},
        )

    async def produce() -> None:
        try:
            result = await asyncio.to_thread(_send_message_sync, session_id, payload, progress)
            await queue.put({"type": "result", "data": result})
        except Exception as exc:
            pending = await asyncio.to_thread(list_dialogue_messages, session_id, 8)
            for message in reversed(pending):
                if message.get("role") == "user" and message.get("status") == "pending":
                    await asyncio.to_thread(
                        update_dialogue_message,
                        message["id"],
                        status="failed",
                        payload={"error_code": "DIALOGUE_REPLY_FAILED"},
                    )
                    break
            if isinstance(exc, SkillExecutionError):
                error = {"code": exc.code, "message": str(exc)}
            else:
                error = {"code": "DIALOGUE_REPLY_FAILED", "message": str(exc)}
            await queue.put({"type": "error", "error": error})
        finally:
            await queue.put({"type": "end"})

    task = asyncio.create_task(produce())
    try:
        while True:
            event = await queue.get()
            if event.get("type") == "end":
                break
            yield event
    finally:
        if not task.done():
            task.cancel()


async def extract_dialogue_item(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_extract_sync, payload)


async def list_assets(limit: int = 100) -> dict[str, Any]:
    return await asyncio.to_thread(_list_assets_sync, limit)


async def update_asset(asset_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_update_asset_sync, asset_id, payload)


async def submit_message_feedback(
    session_id: str, message_id: str, action: str, note: str = ""
) -> dict[str, Any]:
    message = await asyncio.to_thread(get_dialogue_message, message_id)
    if not message or str(message.get("session_id") or "") != session_id:
        raise ValueError("消息不属于当前会话")
    return await asyncio.to_thread(record_dialogue_feedback, message_id, action, note)


async def forget_memory(memory_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(forget_creator_memory, memory_id)


async def get_memory_status() -> dict[str, Any]:
    return await asyncio.to_thread(memory_engine_status)


async def suggest_book_persona(book_ids: list[str]) -> dict[str, Any]:
    return await asyncio.to_thread(_suggest_book_persona_sync, book_ids)


async def create_book_persona_config(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_book_persona_sync, payload)


async def update_book_persona_config(persona_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_update_book_persona_sync, persona_id, payload)


async def delete_book_persona_config(persona_id: str, permanent: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(_delete_book_persona_sync, persona_id, permanent)
