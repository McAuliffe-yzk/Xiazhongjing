"""First-run readiness diagnostics for a portable creator installation."""

from __future__ import annotations

from typing import Any

from config import app_config
from services import settings_store
from services.cover_service import profile
from services.creator_memory_service import memory_engine_status
from services.xiangzhongjing_store import (
    list_book_personas,
    list_library_books,
    list_style_versions,
    load_state,
    reference_document_count,
)


def _stage(key: str, title: str, ready: bool, detail: str, action_page: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "ready": bool(ready),
        "detail": detail,
        "action_page": action_page,
    }


def onboarding_status() -> dict[str, Any]:
    creator = profile()
    documents = reference_document_count()
    versions = list_style_versions()
    published = next((item for item in versions if item.get("status") == "published"), None)
    books = list_library_books()
    personas = list_book_personas()
    memory = memory_engine_status()
    state = load_state()
    projects = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    created_projects = [item for item in projects.values() if isinstance(item, dict)]
    generated_projects = [
        item for item in created_projects
        if str(item.get("copy") or "").strip() or str(item.get("generation_id") or "").strip()
    ]

    model_configured = bool(app_config.deepseek_api_key and app_config.deepseek_api_base and app_config.deepseek_model)
    verified_at = str(settings_store.get_setting("DEEPSEEK_LAST_VERIFIED_AT", "") or "")
    verified_signature = str(settings_store.get_setting("DEEPSEEK_LAST_VERIFIED_SIGNATURE", "") or "")
    current_signature = f"{app_config.deepseek_api_base.rstrip('/')}|{app_config.deepseek_model}"
    model_verified = model_configured and bool(verified_at) and verified_signature == current_signature
    profile_ready = any(
        str(creator.get(key) or "").strip()
        for key in ("creator_positioning", "content_columns", "style_keywords", "avatar_path")
    ) or str(creator.get("display_name") or "").strip() not in {"", "创作者"}
    dna_ready = documents > 0 and bool(published)
    mirror_ready = profile_ready and dna_ready and int(memory.get("total_chunks") or 0) > 0
    quotable_total = sum(int(item.get("quotable_count") or 0) for item in books)

    stages = [
        _stage(
            "model",
            "连接创作模型",
            model_verified,
            f"{app_config.deepseek_model} · {'已验证' if model_verified else ('已填写，待验证' if model_configured else '尚未配置')}",
            "settings",
        ),
        _stage(
            "profile",
            "建立创作者身份",
            profile_ready,
            str(creator.get("display_name") or "创作者"),
            "profile",
        ),
        _stage(
            "dna",
            "导入历史文案并发布 DNA",
            dna_ready,
            f"{documents} 篇历史文案 · {published.get('version') if published else '尚无发布版本'}",
            "distill",
        ),
        _stage(
            "library",
            "导入精神书库",
            bool(books),
            f"{len(books)} 本书 · {quotable_total} 条可引用原句",
            "library",
        ),
        _stage(
            "mirror",
            "唤醒镜中人",
            mirror_ready,
            f"{int(memory.get('documents') or 0)} 篇文稿 · {int(memory.get('total_chunks') or 0)} 个记忆片段",
            "mirror",
        ),
        _stage(
            "book_persona",
            "创建书中人",
            bool(personas),
            f"{len(personas)} 位可交流人物",
            "book-person",
        ),
        _stage(
            "first_creation",
            "完成第一篇创作",
            bool(generated_projects),
            f"{len(created_projects)} 个项目 · {len(generated_projects)} 篇已有文案",
            "workspace",
        ),
    ]
    required = stages[:4]
    ready_count = sum(1 for item in stages if item["ready"])
    return {
        "version": "0.4.1-beta",
        "ready": all(item["ready"] for item in required),
        "is_blank_install": not any((documents, books, created_projects, profile_ready)),
        "progress": {"ready": ready_count, "total": len(stages)},
        "stages": stages,
        "next_stage": next((item for item in stages if not item["ready"]), None),
        "model": {
            "configured": model_configured,
            "verified": model_verified,
            "verified_at": verified_at,
            "api_base": app_config.deepseek_api_base,
            "model": app_config.deepseek_model,
        },
    }
