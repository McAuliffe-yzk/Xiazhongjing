"""Optional external blogger DNA reagent routes."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.style import _extract_docx_text
from services.dna_store import (
    create_dna_reagent,
    delete_dna_reagent,
    get_dna_reagent,
    list_dna_reagents,
    update_dna_reagent,
)
from services.deepseek_service import distill_blogger_dna
from services.skill_runtime import SkillExecutionError


router = APIRouter(prefix="/api/xiangzhongjing", tags=["dna"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, SkillExecutionError):
        return HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": str(exc), "details": exc.details},
        )
    return HTTPException(status_code=400, detail=str(exc))


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:8]
    return [item.strip() for item in str(value or "").split(",") if item.strip()][:8]


@router.get("/dna-reagents")
async def get_dna_reagents():
    return {"reagents": list_dna_reagents()}


@router.post("/dna-reagents")
async def create_dna(payload: dict[str, Any]):
    name = str(payload.get("name") or "").strip()
    source_text = str(payload.get("source_text") or "").strip()
    if not name or not source_text:
        raise HTTPException(status_code=400, detail="请提供试剂名称和样本文字")
    try:
        distilled = await distill_blogger_dna(name, source_text)
        return create_dna_reagent(
            name=name,
            notes=str(payload.get("notes") or "").strip(),
            content=distilled["content_markdown"],
            tags=_normalize_tags(distilled.get("tags")),
            source_text=source_text,
            source_kind=str(payload.get("source_kind") or "paste"),
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/dna-reagents/upload")
async def upload_dna(
    file: UploadFile = File(...),
    name: str = "",
    notes: str = "",
):
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="外部博主样本目前仅支持 .docx")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    temp_path = ""
    try:
        with NamedTemporaryFile(suffix=".docx", delete=False) as temp:
            temp.write(content)
            temp_path = temp.name
        source_text = _extract_docx_text(Path(temp_path))
        reagent_name = name.strip() or Path(file.filename).stem
        distilled = await distill_blogger_dna(reagent_name, source_text)
        return create_dna_reagent(
            name=reagent_name,
            notes=notes.strip(),
            content=distilled["content_markdown"],
            tags=_normalize_tags(distilled.get("tags")),
            source_text=source_text,
            source_kind="docx",
        )
    except Exception as exc:
        raise _error(exc) from exc
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


@router.get("/dna-reagents/{reagent_id}")
async def get_dna(reagent_id: int):
    reagent = get_dna_reagent(reagent_id)
    if reagent is None:
        raise HTTPException(status_code=404, detail="DNA 试剂不存在")
    return reagent


@router.put("/dna-reagents/{reagent_id}")
async def update_dna(reagent_id: int, payload: dict[str, Any]):
    reagent = get_dna_reagent(reagent_id)
    if reagent is None:
        raise HTTPException(status_code=404, detail="DNA 试剂不存在")
    return update_dna_reagent(
        reagent_id,
        name=str(payload.get("name") or reagent["name"]).strip(),
        notes=str(payload.get("notes") or "").strip(),
        content=str(payload.get("content") or reagent["content"]).strip(),
        tags=_normalize_tags(payload.get("tags")),
    )


@router.delete("/dna-reagents/{reagent_id}")
async def delete_dna(reagent_id: int):
    if get_dna_reagent(reagent_id) is None:
        raise HTTPException(status_code=404, detail="DNA 试剂不存在")
    delete_dna_reagent(reagent_id)
    return {"ok": True}


@router.post("/dna-reagents/{reagent_id}/redistill")
async def redistill_dna(reagent_id: int):
    reagent = get_dna_reagent(reagent_id)
    if reagent is None:
        raise HTTPException(status_code=404, detail="DNA 试剂不存在")
    try:
        distilled = await distill_blogger_dna(str(reagent["name"]), str(reagent["source_text"]))
        return update_dna_reagent(
            reagent_id,
            name=str(reagent["name"]),
            notes=str(reagent.get("notes") or ""),
            content=distilled["content_markdown"],
            tags=_normalize_tags(distilled.get("tags")),
        )
    except Exception as exc:
        raise _error(exc) from exc
