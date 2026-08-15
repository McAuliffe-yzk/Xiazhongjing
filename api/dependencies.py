"""API 路由共享的配置检查与错误序列化。"""

from __future__ import annotations

import json

from fastapi import HTTPException

from config import app_config
from services.skill_runtime import SkillExecutionError


def require_deepseek() -> None:
    if not app_config.deepseek_api_key:
        raise HTTPException(status_code=503, detail="未配置 DeepSeek API Key")


def skill_error_detail(exc: SkillExecutionError) -> dict:
    detail = {"code": exc.code, "message": str(exc)}
    if getattr(exc, "details", ""):
        try:
            detail["details"] = json.loads(exc.details)
        except (TypeError, json.JSONDecodeError):
            detail["details"] = exc.details
    return detail

