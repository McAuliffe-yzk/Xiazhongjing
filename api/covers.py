"""Image 2.0 封面图生成路由。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from services import cover_service


router = APIRouter(prefix="/api/xiangzhongjing/covers", tags=["covers"])


def _service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/profile")
async def get_profile():
    return cover_service.profile()


@router.put("/profile")
async def put_profile(payload: dict):
    try:
        return cover_service.update_profile(payload)
    except Exception as exc:
        raise _service_error(exc) from exc


@router.post("/profile/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    try:
        return cover_service.update_avatar(file.filename or "avatar.png", await file.read())
    except Exception as exc:
        raise _service_error(exc) from exc


@router.get("/presets")
async def get_presets():
    return {"presets": cover_service.list_presets()}


@router.post("/presets")
async def post_preset(payload: dict):
    try:
        return cover_service.create_preset(payload)
    except Exception as exc:
        raise _service_error(exc) from exc


@router.get("/images")
async def get_images():
    return {"covers": cover_service.list_covers()}


@router.post("/images")
async def post_image(payload: dict):
    try:
        return cover_service.create_cover(payload)
    except Exception as exc:
        raise _service_error(exc) from exc


@router.put("/images/{cover_id}")
async def put_image(cover_id: str, payload: dict):
    try:
        return cover_service.update_cover(cover_id, payload)
    except Exception as exc:
        raise _service_error(exc) from exc


@router.post("/images/{cover_id}/reference")
async def upload_reference(cover_id: str, file: UploadFile = File(...)):
    try:
        return cover_service.update_cover_reference(
            cover_id,
            file.filename or "reference.png",
            await file.read(),
        )
    except Exception as exc:
        raise _service_error(exc) from exc


@router.post("/images/{cover_id}/generate")
async def generate_image(cover_id: str, payload: Optional[dict] = None):
    try:
        return cover_service.generate_cover(cover_id, payload or {})
    except Exception as exc:
        raise _service_error(exc) from exc


@router.get("/media/{kind}/{filename}")
async def get_media(kind: str, filename: str):
    try:
        path = cover_service.media_path(kind, filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)
