"""单人创作工作区状态与健康检查路由。"""

from typing import Any

from fastapi import APIRouter, HTTPException

from services.xiangzhongjing_store import StateConflictError, load_state, save_state


router = APIRouter(prefix="/api/xiangzhongjing", tags=["workspace"])


@router.get("/health")
async def health():
    return {"status": "ok", "mode": "single_creator", "architecture": "modular_monolith"}


@router.get("/state")
async def get_state():
    return load_state()


@router.put("/state")
async def put_state(payload: dict[str, Any]):
    try:
        return save_state(payload)
    except StateConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "STATE_REVISION_CONFLICT",
                "message": "另一个窗口已更新工作区，当前修改未覆盖新数据。",
                "current_revision": exc.current_revision,
            },
        ) from exc

