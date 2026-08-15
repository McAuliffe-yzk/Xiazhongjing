"""Local configuration and Skill administration routes."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from openai import OpenAI

from config import app_config, persist_settings, reload_settings
from services import cover_service, settings_store
from services.skill_runtime import (
    SkillExecutionError,
    create_skill,
    delete_skill,
    get_skill_detail,
    reset_skill,
    set_skill_enabled,
    skill_catalog,
    update_skill,
)
from services.xiangzhongjing_store import creation_quality_summary, recent_skill_runs


router = APIRouter(prefix="/api/xiangzhongjing", tags=["settings"])

CONFIG_FIELDS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_REASONER_MODEL",
    "DEEPSEEK_TIMEOUT_SECONDS",
    "TAVILY_API_KEY",
    "TAVILY_API_BASE",
    "IMAGE_API_KEY",
    "IMAGE_API_BASE",
    "IMAGE_MODEL",
)


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "••••"
    return f"{value[:4]}••••{value[-4:]}"


def _config_values(reveal: bool = False) -> dict[str, str]:
    values = {
        "DEEPSEEK_API_KEY": app_config.deepseek_api_key,
        "DEEPSEEK_API_BASE": app_config.deepseek_api_base,
        "DEEPSEEK_MODEL": app_config.deepseek_model,
        "DEEPSEEK_REASONER_MODEL": app_config.deepseek_reasoner_model,
        "DEEPSEEK_TIMEOUT_SECONDS": str(app_config.deepseek_timeout_seconds).rstrip("0").rstrip("."),
        "TAVILY_API_KEY": app_config.tavily_api_key,
        "TAVILY_API_BASE": app_config.tavily_api_base,
        "IMAGE_API_KEY": app_config.image_api_key,
        "IMAGE_API_BASE": app_config.image_api_base,
        "IMAGE_MODEL": app_config.image_model,
    }
    if reveal:
        return values
    return {
        key: (_mask_secret(value) if key.endswith("API_KEY") else value)
        for key, value in values.items()
    }


def _skill_error(exc: SkillExecutionError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": exc.code, "message": str(exc), "details": exc.details},
    )


def _probe_deepseek() -> dict[str, Any]:
    if not app_config.deepseek_api_key:
        return {"configured": False, "reachable": False, "message": "模型 API Key 未配置"}
    started = time.perf_counter()
    try:
        client = OpenAI(
            api_key=app_config.deepseek_api_key,
            base_url=app_config.deepseek_api_base.rstrip("/"),
            timeout=min(20.0, app_config.deepseek_timeout_seconds),
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=app_config.deepseek_model,
            messages=[{"role": "user", "content": "只回复 OK"}],
            max_tokens=4,
            temperature=0,
        )
        content = str(response.choices[0].message.content or "").strip()
        if not content:
            raise RuntimeError("模型返回空内容")
        verified_at = datetime.now().isoformat(timespec="seconds")
        signature = f"{app_config.deepseek_api_base.rstrip('/')}|{app_config.deepseek_model}"
        settings_store.set_setting("DEEPSEEK_LAST_VERIFIED_AT", verified_at)
        settings_store.set_setting("DEEPSEEK_LAST_VERIFIED_SIGNATURE", signature)
        return {
            "configured": True,
            "reachable": True,
            "verified_at": verified_at,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": "模型连接与文本生成已验证",
        }
    except Exception as exc:
        return {
            "configured": True,
            "reachable": False,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": f"模型连接失败：{exc.__class__.__name__}",
        }


@router.get("/settings/config")
async def get_config(reveal: int = 0):
    return {"fields": CONFIG_FIELDS, "values": _config_values(reveal=bool(reveal))}


@router.put("/settings/config")
async def put_config(payload: dict[str, Any]):
    updates: dict[str, str] = {}
    for key in CONFIG_FIELDS:
        if key not in payload:
            continue
        value = str(payload.get(key) or "").strip()
        if "••••" in value:
            continue
        updates[key] = value
    if updates:
        persist_settings(updates)
        reload_settings()
        if {"DEEPSEEK_API_KEY", "DEEPSEEK_API_BASE", "DEEPSEEK_MODEL"}.intersection(updates):
            settings_store.set_setting("DEEPSEEK_LAST_VERIFIED_AT", "")
            settings_store.set_setting("DEEPSEEK_LAST_VERIFIED_SIGNATURE", "")
    return {"ok": True, "updated": sorted(updates), "values": _config_values()}


@router.post("/settings/config/test")
async def test_config(payload: Optional[dict[str, Any]] = None):
    provider = str((payload or {}).get("provider") or "deepseek").strip().lower()
    if provider == "tavily":
        configured = bool(app_config.tavily_api_key)
        return {
            "provider": "tavily",
            "configured": configured,
            "api_base": app_config.tavily_api_base,
            "message": "Tavily API Key 已配置" if configured else "Tavily API Key 未配置",
        }
    if provider == "image":
        return {
            "provider": "image",
            "api_base": app_config.image_api_base,
            **cover_service.probe_image_service(),
        }
    result = await asyncio.to_thread(_probe_deepseek)
    return {
        "provider": "deepseek",
        "api_base": app_config.deepseek_api_base,
        "model": app_config.deepseek_model,
        **result,
    }


@router.get("/settings/stats")
async def settings_stats():
    return {
        "settings": len(settings_store.get_all_settings()),
        "skills": len(skill_catalog()),
        "recent_runs": recent_skill_runs(10),
        "quality": creation_quality_summary(limit=5),
    }


@router.get("/skills-admin/list")
async def list_skills_admin():
    rows = settings_store.list_skills_registry()
    return {
        "skills": [
            {
                "name": row["name"],
                "display_name": row["display_name"],
                "phase": row["phase"],
                "description": row["description"],
                "source": row["source"],
                "enabled": int(row["enabled"]),
                "core": int(row["core"]),
            }
            for row in rows
        ]
    }


@router.get("/skills/{name}")
async def get_skill_admin(name: str):
    try:
        return get_skill_detail(name)
    except SkillExecutionError as exc:
        raise _skill_error(exc) from exc


@router.post("/skills")
async def create_skill_admin(payload: dict[str, Any]):
    try:
        return create_skill(
            name=str(payload.get("name") or ""),
            display_name=str(payload.get("display_name") or ""),
            phase=str(payload.get("phase") or "自定义"),
            description=str(payload.get("description") or ""),
            instructions=str(payload.get("instructions") or ""),
        )
    except SkillExecutionError as exc:
        raise _skill_error(exc) from exc


@router.put("/skills/{name}")
async def update_skill_admin(name: str, payload: dict[str, Any]):
    try:
        return update_skill(
            name,
            display_name=str(payload.get("display_name") or ""),
            phase=str(payload.get("phase") or "其它"),
            description=str(payload.get("description") or ""),
            instructions=str(payload.get("instructions") or ""),
        )
    except SkillExecutionError as exc:
        raise _skill_error(exc) from exc


@router.delete("/skills/{name}")
async def delete_skill_admin(name: str):
    try:
        delete_skill(name)
        return {"ok": True}
    except SkillExecutionError as exc:
        raise _skill_error(exc) from exc


@router.post("/skills/{name}/enabled")
async def toggle_skill_admin(name: str, payload: dict[str, Any]):
    try:
        set_skill_enabled(name, bool(payload.get("enabled")))
        return get_skill_detail(name)
    except SkillExecutionError as exc:
        raise _skill_error(exc) from exc


@router.post("/skills/{name}/reset")
async def reset_skill_admin(name: str):
    try:
        return reset_skill(name)
    except SkillExecutionError as exc:
        raise _skill_error(exc) from exc
