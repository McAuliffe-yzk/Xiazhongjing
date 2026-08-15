"""文案生成、编辑与素材理解路由。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.contracts import GenerateCopyRequest, TextPayload
from api.dependencies import require_deepseek, skill_error_detail
from config import app_config
from application.generation import (
    edit_copy,
    generate_copy,
    generate_copy_with_progress,
    parse_creation_materials,
    rewrite_selection,
)
from application.library_support import (
    auto_insert_books,
    research_books,
    selected_book_sources,
)
from services.skill_runtime import SkillExecutionError, skill_catalog
from services.xiangzhongjing_store import (
    create_generation_job,
    get_generation_job,
    update_generation_job,
)


router = APIRouter(prefix="/api/xiangzhongjing", tags=["generation"])


def _result_payload(result: dict[str, Any], selected_books: list[str]) -> dict[str, Any]:
    return {
        **result,
        "sources": selected_book_sources(selected_books),
        "model": app_config.deepseek_model,
    }


@router.post("/generate-copy")
async def generate_copy_route(payload: GenerateCopyRequest):
    require_deepseek()
    data = payload.service_payload()
    try:
        result = await generate_copy(data)
        return _result_payload(result, data["selected_books"])
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"DeepSeek 生成失败：{exc}") from exc


@router.post("/generate-copy-stream")
async def generate_copy_stream_route(payload: GenerateCopyRequest, request: Request):
    require_deepseek()
    generation_payload = payload.service_payload()
    generation_id = payload.generation_id
    if generation_id:
        existing_job = get_generation_job(generation_id)
        if not existing_job:
            raise HTTPException(status_code=404, detail="生成任务不存在")
        generation_payload = {**(existing_job.get("payload") or {}), **generation_payload}
        update_generation_job(generation_id, payload=generation_payload)
    else:
        generation_id = create_generation_job(generation_payload)["generation_id"]

    selected_books = generation_payload.get("selected_books") or []
    generation_payload["selected_books"] = selected_books

    async def event_stream():
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def stage_meta(stage_name: str) -> dict[str, Any]:
            return next((item for item in skill_catalog() if item["name"] == stage_name), {})

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        async def runner() -> None:
            try:
                await queue.put({"event": "generation_created", "generation_id": generation_id})
                result = await generate_copy_with_progress(generation_payload, emit, generation_id)
                await queue.put(
                    {
                        "event": "final",
                        "result": _result_payload(result, selected_books),
                    }
                )
            except SkillExecutionError as exc:
                job = get_generation_job(generation_id) or {}
                failed_stage = str(job.get("current_stage") or job.get("failed_stage") or "")
                meta = stage_meta(failed_stage)
                await queue.put(
                    {
                        "event": "stage_failed",
                        "skill": failed_stage or "skill-chain",
                        "label": meta.get("display_name") or "Skill 链路",
                        "phase": meta.get("phase") or "失败",
                        "detail": {**skill_error_detail(exc), "failed_stage": failed_stage},
                        "generation_id": generation_id,
                    }
                )
            except Exception as exc:
                job = get_generation_job(generation_id) or {}
                failed_stage = str(job.get("current_stage") or job.get("failed_stage") or "")
                meta = stage_meta(failed_stage)
                await queue.put(
                    {
                        "event": "stage_failed",
                        "skill": failed_stage or "skill-chain",
                        "label": meta.get("display_name") or "Skill 链路",
                        "phase": meta.get("phase") or "失败",
                        "detail": {
                            "code": "GENERATION_FAILED",
                            "message": f"DeepSeek 生成失败：{exc}",
                            "failed_stage": failed_stage,
                        },
                        "generation_id": generation_id,
                    }
                )
            finally:
                await queue.put({"event": "done"})

        task = asyncio.create_task(runner())
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item.get("event") == "done":
                    break
                event_name = str(item.get("event") or "message")
                yield f"event: {event_name}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/generations/{generation_id}")
async def get_generation(generation_id: str):
    job = get_generation_job(generation_id)
    if not job:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    return job


async def _run_skill_action(action, payload: dict[str, Any], failure_label: str):
    require_deepseek()
    try:
        return await action(payload)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{failure_label}：{exc}") from exc


@router.post("/rewrite-selection")
async def rewrite_selection_route(payload: dict[str, Any]):
    text = await _run_skill_action(rewrite_selection, payload, "局部改写失败")
    return {"text": text, "model": app_config.deepseek_model}


@router.post("/edit-copy")
async def edit_copy_route(payload: dict[str, Any]):
    return await _run_skill_action(edit_copy, payload, "AI 编辑失败")


@router.post("/parse-materials")
async def parse_materials_route(payload: TextPayload):
    require_deepseek()
    try:
        return await parse_creation_materials(payload.text)
    except SkillExecutionError as exc:
        raise HTTPException(status_code=502, detail=skill_error_detail(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"素材识别失败：{exc}") from exc


@router.post("/research-books")
async def research_books_route(payload: dict[str, Any]):
    return await _run_skill_action(research_books, payload, "书库检索建议失败")


@router.post("/auto-insert-books")
async def auto_insert_books_route(payload: dict[str, Any]):
    return await _run_skill_action(auto_insert_books, payload, "自动植入失败")
