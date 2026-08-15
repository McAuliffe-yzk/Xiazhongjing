"""个人创作 Skill 蒸馏、审核与发布路由。"""

from io import BytesIO
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.contracts import StyleFeedbackRequest, StylePublishRequest
from api.dependencies import skill_error_detail
from application.style import (
    analyze_style_batch,
    analyze_style_update,
    compare_style_candidate,
    writing_skill_stats,
)
from services.skill_runtime import SkillExecutionError, skill_catalog
from services.xiangzhongjing_store import (
    creation_quality_summary,
    get_style_version,
    list_style_versions,
    publish_style_version,
    recent_skill_runs,
    save_style_feedback,
)
from config import app_config


router = APIRouter(prefix="/api/xiangzhongjing", tags=["style"])


def _extract_docx_text(source: Union[str, Path, BytesIO]) -> str:
    try:
        from docx import Document
    except Exception as exc:
        raise RuntimeError("当前环境缺少 python-docx，无法解析 DOCX") from exc
    document = Document(source)
    return "\n".join(
        paragraph.text.strip()
        for paragraph in document.paragraphs
        if paragraph.text.strip()
    )


def _extract_reference_text(filename: str, content: bytes) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".docx":
        return _extract_docx_text(BytesIO(content))
    if suffix == ".pdf":
        try:
            from PyPDF2 import PdfReader
        except Exception as exc:
            raise RuntimeError("当前环境缺少 PyPDF2，无法解析 PDF") from exc
        reader = PdfReader(BytesIO(content))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n".join(page for page in pages if page)
    if suffix in {".txt", ".md"}:
        return content.decode("utf-8-sig", errors="ignore").strip()
    raise RuntimeError("历史文案支持 .docx、.pdf、.txt、.md")


@router.get("/writing-skill")
async def get_writing_skill():
    return writing_skill_stats()


@router.get("/skills")
async def get_skills():
    return {
        "skills": skill_catalog(),
        "providers": {
            "llm": {
                "name": "DeepSeek",
                "configured": bool(app_config.deepseek_api_key),
                "model": app_config.deepseek_model,
            },
            "book_library": {"name": "本地精神书库", "configured": True},
        },
        "failure_policy": "fail_closed",
    }


@router.get("/skill-runs")
async def get_skill_runs(limit: int = 30):
    return {"runs": recent_skill_runs(limit)}


@router.get("/style-versions")
async def get_style_versions():
    return {"versions": list_style_versions()}


@router.get("/quality-summary")
async def get_quality_summary():
    return creation_quality_summary(limit=5)


@router.get("/style-versions/{version_id}")
async def get_style_version_route(version_id: int):
    version = get_style_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail="Skill 版本不存在")
    return version


@router.post("/style-versions/{version_id}/compare")
async def compare_style_version(version_id: int, payload: dict[str, Any]):
    try:
        return await compare_style_candidate(version_id, payload.get("materials") or {})
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc


@router.post("/style-versions/{version_id}/publish")
async def publish_style(version_id: int, payload: Optional[StylePublishRequest] = None):
    request_data = payload or StylePublishRequest()
    try:
        return publish_style_version(
            version_id,
            force=request_data.force,
            reason=request_data.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/upload-reference")
async def upload_reference(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() not in {".docx", ".pdf", ".txt", ".md"}:
        raise HTTPException(status_code=400, detail="请上传 DOCX、PDF、TXT 或 Markdown 历史文案")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    try:
        text = _extract_reference_text(file.filename, content)
        if len(text.strip()) < 80:
            raise RuntimeError("提取到的正文过短，无法蒸馏风格")
        result = await analyze_style_update(file.filename, text)
        result.update(
            {
                "paragraphs": len([line for line in text.splitlines() if line.strip()]),
                "chars": len(text),
            }
        )
        return result
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"稿件蒸馏失败：{exc}") from exc


@router.post("/upload-reference-batch")
async def upload_reference_batch(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="请选择历史稿件")
    documents: list[dict[str, str]] = []
    try:
        for file in files:
            if not file.filename or Path(file.filename).suffix.lower() not in {".docx", ".pdf", ".txt", ".md"}:
                raise HTTPException(status_code=400, detail="批量蒸馏支持 DOCX、PDF、TXT、Markdown")
            content = await file.read()
            if not content:
                raise HTTPException(status_code=400, detail=f"{file.filename} 为空")
            text = _extract_reference_text(file.filename, content)
            if len(text.strip()) < 80:
                raise HTTPException(status_code=400, detail=f"{file.filename} 提取到的正文过短")
            documents.append({"filename": file.filename, "text": text})
        return await analyze_style_batch(documents)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc


@router.post("/style-feedback")
async def create_style_feedback(payload: StyleFeedbackRequest):
    return save_style_feedback(
        payload.project_id,
        payload.style_version,
        payload.decision,
        payload.feedback,
        payload.copy_snapshot,
    )
