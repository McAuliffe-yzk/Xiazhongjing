"""精神书库管理路由。"""

import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from config import DATA_DIR
from services.book_notes_service import book_notes_state, ingest_book_note_bytes, ingest_book_note_path
from services.xiangzhongjing_store import (
    book_citation_summary,
    create_library_book,
    delete_book_citation,
    delete_library_book,
    get_library_book,
    list_book_citations,
    list_library_books,
    update_book_citation_quality,
    update_library_book,
)


router = APIRouter(prefix="/api/xiangzhongjing", tags=["library"])


DEFAULT_SEEDED_NOTE_PATHS: tuple[tuple[Path, str], ...] = (
    (DATA_DIR / "source_documents" / "埃隆·马斯克传.pdf", "musk"),
    (DATA_DIR / "source_documents" / "剑来摘录.docx", "jianlai"),
    (DATA_DIR / "source_documents" / "道德经再读.docx", "daode"),
)


def _seeded_note_paths() -> list[tuple[str, str]]:
    configured = (
        (os.getenv("XIANGZHONGJING_MUSK_NOTE_PATH", "").strip(), "musk"),
        (os.getenv("XIANGZHONGJING_JIANLAI_NOTE_PATH", "").strip(), "jianlai"),
        (os.getenv("XIANGZHONGJING_DAODE_NOTE_PATH", "").strip(), "daode"),
    )
    paths: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path_value, book_id in (*configured, *DEFAULT_SEEDED_NOTE_PATHS):
        path = str(path_value)
        if not path or not os.path.exists(path):
            continue
        key = (path, book_id)
        if key in seen:
            continue
        seen.add(key)
        paths.append(key)
    return paths


@router.get("/book-notes")
async def get_book_notes():
    return {**book_notes_state(), "books": list_library_books()}


@router.get("/library/books")
async def get_library_books(include_archived: bool = False):
    return {"books": list_library_books(include_archived=include_archived)}


@router.post("/library/books")
async def add_library_book(payload: dict):
    try:
        return {"book": create_library_book(
            str(payload.get("title") or ""),
            author=str(payload.get("author") or ""),
            description=str(payload.get("description") or ""),
            book_id=str(payload.get("id") or ""),
        )}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/library/books/{book_id}")
async def patch_library_book(book_id: str, payload: dict):
    try:
        book = update_library_book(book_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"book": book}


@router.delete("/library/books/{book_id}")
async def remove_library_book(book_id: str, permanent: bool = False):
    if not delete_library_book(book_id, permanent=permanent):
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"deleted": True, "permanent": permanent, "book_id": book_id}


@router.post("/book-notes/upload")
async def upload_book_notes(
    files: list[UploadFile] = File(...),
    book_id: str = Form(""),
    title: str = Form(""),
    author: str = Form(""),
    description: str = Form(""),
):
    if not files:
        raise HTTPException(status_code=400, detail="请上传阅读笔记文件")
    imported = []
    errors = []
    for file in files:
        try:
            imported.append(
                ingest_book_note_bytes(
                    file.filename or "reading-note",
                    await file.read(),
                    book_id,
                    title=title,
                    author=author,
                    description=description,
                )
            )
            if not book_id:
                book_id = str(imported[-1].get("book_id") or "")
        except Exception as exc:
            errors.append({"filename": file.filename, "message": str(exc)})
    if not imported:
        raise HTTPException(status_code=400, detail={"message": "阅读笔记导入失败", "errors": errors})
    return {"imported": imported, "errors": errors, "books": list_library_books(), **book_notes_state()}


@router.post("/book-notes/seed")
async def seed_book_notes():
    seeded_paths = _seeded_note_paths()
    if not seeded_paths:
        state = book_notes_state()
        if sum(int(item.get("count") or 0) for item in state.get("summary", [])):
            return {
                "imported": [],
                "errors": [],
                "already_available": True,
                "message": "已提供的阅读笔记素材已经在书库中",
                **state,
            }
        raise HTTPException(
            status_code=400,
            detail="未配置本机阅读笔记路径，请在书库页上传文件。",
        )
    imported = []
    errors = []
    for path, book_id in seeded_paths:
        try:
            imported.append(ingest_book_note_path(path, book_id))
        except Exception as exc:
            errors.append({"path": path, "message": str(exc)})
    if not imported:
        state = book_notes_state()
        if sum(int(item.get("count") or 0) for item in state.get("summary", [])):
            return {
                "imported": [],
                "errors": errors,
                "already_available": True,
                "message": "已提供的阅读笔记素材已经在书库中",
                **state,
            }
        raise HTTPException(
            status_code=400,
            detail={"message": "后台服务无法读取阅读笔记，请在书库页手动上传", "errors": errors},
        )
    return {"imported": imported, "errors": errors, "already_available": False, **book_notes_state()}


@router.get("/book-library")
async def get_book_library():
    return {
        "books": list_library_books(),
        "citations": book_citation_summary(limit=2000),
        "all_citations": list_book_citations("", limit=2000),
    }


@router.delete("/book-library/citations/{citation_id}")
async def remove_book_citation(citation_id: int):
    if not delete_book_citation(citation_id):
        raise HTTPException(status_code=404, detail="引文不存在")
    return {"deleted": True, "citation_id": citation_id}


@router.patch("/book-library/citations/{citation_id}")
async def patch_book_citation(citation_id: int, payload: dict):
    try:
        updated = update_book_citation_quality(
            citation_id,
            material_type=str(payload.get("material_type") or "direct_quote"),
            quality_status=str(payload.get("quality_status") or "pending_review"),
            quality_reason=str(payload.get("quality_reason") or ""),
            source_locator=str(payload.get("source_locator") or ""),
            attribution=(str(payload.get("attribution") or "") if "attribution" in payload else None),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="引文不存在")
    return {"updated": True, "citation_id": citation_id}
