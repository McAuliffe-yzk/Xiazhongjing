"""Daily personalized inspiration routes."""

from __future__ import annotations

import asyncio
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.inspiration_service import (
    InspirationDrawInProgress,
    InspirationDrawNotFound,
    delete_draw,
    draw_daily,
    inspiration_metrics,
    list_draws,
    restore_draw,
    save_feedback,
    today_draw,
    update_draw,
)
from services.skill_runtime import SkillExecutionError


router = APIRouter(prefix="/api/xiangzhongjing/inspiration", tags=["inspiration"])

DrawType = Literal["theme", "emotion", "event", "book", "mirror", "action"]


class DrawRequest(BaseModel):
    type: DrawType


class DrawUpdateRequest(BaseModel):
    favorited: Optional[bool] = None
    conversion: str = Field(default="", max_length=160)


class DrawFeedbackRequest(BaseModel):
    verdict: Literal["useful", "not_useful"]
    reasons: List[Literal["too_vague", "repetitive", "irrelevant", "unlike_me", "not_shootable"]] = Field(default_factory=list)
    note: str = Field(default="", max_length=400)


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InspirationDrawInProgress):
        return HTTPException(status_code=409, detail={"code": "DRAW_IN_PROGRESS", "message": str(exc)})
    if isinstance(exc, InspirationDrawNotFound):
        return HTTPException(status_code=404, detail={"code": "DRAW_NOT_FOUND", "message": str(exc)})
    if isinstance(exc, SkillExecutionError):
        return HTTPException(
            status_code=503,
            detail={"code": exc.code, "message": str(exc), "details": exc.details},
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail={"code": "INVALID_DRAW_INPUT", "message": str(exc)})
    return HTTPException(status_code=500, detail={"code": "DRAW_FAILED", "message": str(exc)})


@router.get("/today")
async def get_today_draw():
    return await asyncio.to_thread(today_draw)


@router.post("/draw")
async def create_daily_draw(payload: DrawRequest):
    try:
        return await asyncio.to_thread(draw_daily, payload.type)
    except (InspirationDrawInProgress, InspirationDrawNotFound, SkillExecutionError, ValueError) as exc:
        raise _service_error(exc) from exc


@router.get("/archive")
async def get_draw_archive(
    draw_type: str = Query(default="", alias="type"),
    status: Literal["all", "favorite", "unused", "converted", "useful", "not_useful", "deleted"] = "all",
    include_deleted: bool = False,
    limit: int = Query(default=365, ge=1, le=365),
):
    return await asyncio.to_thread(
        list_draws,
        draw_type=draw_type,
        status=status,
        include_deleted=include_deleted,
        limit=limit,
    )


@router.patch("/draws/{draw_id}")
async def patch_draw(draw_id: str, payload: DrawUpdateRequest):
    try:
        return await asyncio.to_thread(
            update_draw,
            draw_id,
            favorited=payload.favorited,
            conversion=payload.conversion,
        )
    except InspirationDrawNotFound as exc:
        raise _service_error(exc) from exc


@router.put("/draws/{draw_id}/feedback")
async def put_draw_feedback(draw_id: str, payload: DrawFeedbackRequest):
    try:
        return await asyncio.to_thread(
            save_feedback,
            draw_id,
            verdict=payload.verdict,
            reasons=list(payload.reasons),
            note=payload.note,
        )
    except (InspirationDrawNotFound, ValueError) as exc:
        raise _service_error(exc) from exc


@router.get("/metrics")
async def get_inspiration_metrics(days: int = Query(default=14, ge=7, le=90)):
    return await asyncio.to_thread(inspiration_metrics, days)


@router.delete("/draws/{draw_id}")
async def remove_draw(draw_id: str):
    try:
        return await asyncio.to_thread(delete_draw, draw_id)
    except InspirationDrawNotFound as exc:
        raise _service_error(exc) from exc


@router.post("/draws/{draw_id}/restore")
async def restore_deleted_draw(draw_id: str):
    try:
        return await asyncio.to_thread(restore_draw, draw_id)
    except InspirationDrawNotFound as exc:
        raise _service_error(exc) from exc
