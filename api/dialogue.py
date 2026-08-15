"""镜中人与书中人对话路由。"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.contracts import (
    DialogueFeedbackRequest,
    DialogueSessionBulkDeleteRequest,
    DialogueExtractRequest,
    DialogueMessageRequest,
    DialogueSessionPatch,
    DialogueSessionRequest,
)
from api.dependencies import require_deepseek, skill_error_detail
from services.dialogue_service import (
    bulk_delete_sessions,
    clear_session,
    create_book_persona_config,
    create_session,
    delete_session,
    delete_book_persona_config,
    dialogue_personas,
    extract_dialogue_item,
    forget_memory,
    get_memory_status,
    get_messages,
    get_session,
    list_assets,
    list_sessions,
    patch_session,
    restore_session,
    send_message,
    stream_message_events,
    suggest_book_persona,
    submit_message_feedback,
    update_asset,
    update_book_persona_config,
)
from services.skill_runtime import SkillExecutionError


router = APIRouter(prefix="/api/xiangzhongjing/dialogue", tags=["dialogue"])


@router.get("/personas")
async def personas():
    return dialogue_personas()


@router.post("/personas/suggest")
async def suggest_persona(payload: dict):
    try:
        book_ids = payload.get("book_ids") if isinstance(payload.get("book_ids"), list) else []
        return {"suggestion": await suggest_book_persona(book_ids)}
    except SkillExecutionError as exc:
        raise HTTPException(status_code=400, detail=skill_error_detail(exc)) from exc


@router.post("/personas")
async def create_persona(payload: dict):
    try:
        return {"persona": await create_book_persona_config(payload)}
    except (SkillExecutionError, ValueError) as exc:
        detail = skill_error_detail(exc) if isinstance(exc, SkillExecutionError) else str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc


@router.patch("/personas/{persona_id}")
async def patch_persona(persona_id: str, payload: dict):
    try:
        return {"persona": await update_book_persona_config(persona_id, payload)}
    except (SkillExecutionError, ValueError) as exc:
        detail = skill_error_detail(exc) if isinstance(exc, SkillExecutionError) else str(exc)
        raise HTTPException(status_code=400, detail=detail) from exc


@router.delete("/personas/{persona_id}")
async def remove_persona(persona_id: str, permanent: bool = False):
    try:
        return await delete_book_persona_config(persona_id, permanent=permanent)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.get("/memory/status")
async def dialogue_memory_status():
    return await get_memory_status()


@router.delete("/memory/{memory_id}")
async def forget_dialogue_memory(memory_id: str):
    try:
        return {"memory": await forget_memory(memory_id), "forgotten": True}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions")
async def create_dialogue_session(payload: DialogueSessionRequest):
    require_deepseek()
    try:
        return await create_session(payload.model_dump())
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions")
async def list_dialogue_sessions(
    project_id: str = "",
    query: str = "",
    mode: str = "",
    persona_id: str = "",
    include_deleted: bool = False,
):
    return await list_sessions(
        project_id,
        query=query,
        mode=mode,
        persona_id=persona_id,
        include_deleted=include_deleted,
    )


@router.post("/sessions/bulk-delete")
async def bulk_delete_dialogue_sessions(payload: DialogueSessionBulkDeleteRequest):
    try:
        return await bulk_delete_sessions(payload.model_dump())
    except SkillExecutionError as exc:
        raise HTTPException(status_code=400, detail=skill_error_detail(exc)) from exc


@router.get("/assets")
async def dialogue_assets(limit: int = 100):
    return await list_assets(limit)


@router.patch("/assets/{asset_id}")
async def update_dialogue_asset(asset_id: str, payload: dict):
    try:
        return await update_asset(asset_id, payload)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404 if exc.code == "ASSET_NOT_FOUND" else 400, detail=skill_error_detail(exc)) from exc


@router.get("/sessions/{session_id}")
async def dialogue_session(session_id: str):
    try:
        return await get_session(session_id)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.get("/sessions/{session_id}/messages")
async def dialogue_messages(session_id: str, before: str = "", limit: int = 30):
    try:
        return await get_messages(session_id, before=before, limit=limit)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.patch("/sessions/{session_id}")
async def update_dialogue_session(session_id: str, payload: DialogueSessionPatch):
    try:
        return await patch_session(session_id, payload.model_dump(exclude_none=True))
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.delete("/sessions/{session_id}")
async def remove_dialogue_session(session_id: str, permanent: bool = False):
    try:
        return await delete_session(session_id, permanent=permanent)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.post("/sessions/{session_id}/restore")
async def restore_dialogue_session_route(session_id: str):
    try:
        return await restore_session(session_id)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.delete("/sessions/{session_id}/messages")
async def clear_dialogue_messages(session_id: str):
    try:
        return await clear_session(session_id)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=404, detail=skill_error_detail(exc)) from exc


@router.post("/sessions/{session_id}/messages")
async def send_dialogue_message_route(session_id: str, payload: DialogueMessageRequest):
    require_deepseek()
    try:
        return await send_message(session_id, payload.model_dump())
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc


@router.post("/sessions/{session_id}/messages/stream")
async def stream_dialogue_message_route(session_id: str, payload: DialogueMessageRequest):
    require_deepseek()

    async def event_source():
        async for event in stream_message_events(session_id, payload.model_dump()):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/messages/{message_id}/retry")
async def retry_dialogue_message(session_id: str, message_id: str):
    require_deepseek()
    try:
        return await send_message(session_id, {"retry_message_id": message_id})
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc


@router.post("/sessions/{session_id}/messages/{message_id}/feedback")
async def dialogue_message_feedback(
    session_id: str,
    message_id: str,
    payload: DialogueFeedbackRequest,
):
    try:
        return await submit_message_feedback(
            session_id, message_id, payload.action, payload.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/extract")
async def extract_dialogue(payload: DialogueExtractRequest):
    try:
        return await extract_dialogue_item(payload.model_dump())
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc
    forget_memory,
    get_memory_status,
