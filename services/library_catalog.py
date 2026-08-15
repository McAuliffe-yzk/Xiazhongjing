"""Dynamic spiritual-library catalog shared by generation and dialogue."""

from __future__ import annotations

from typing import Any

from services.tavily_service import BOOKS as LEGACY_ONLINE_BOOKS
from services.xiangzhongjing_store import get_library_book, list_library_books


def book_catalog(include_archived: bool = False) -> list[dict[str, Any]]:
    return list_library_books(include_archived=include_archived)


def book_map(include_archived: bool = False) -> dict[str, dict[str, Any]]:
    books: dict[str, dict[str, Any]] = {}
    for item in book_catalog(include_archived=include_archived):
        book_id = str(item.get("id") or "")
        if not book_id:
            continue
        legacy = LEGACY_ONLINE_BOOKS.get(book_id, {})
        books[book_id] = {
            **item,
            "official_url": str(item.get("metadata", {}).get("official_url") or legacy.get("official_url") or ""),
        }
    return books


def active_book_ids() -> list[str]:
    return list(book_map())


def resolve_book(book_id: str) -> dict[str, Any] | None:
    return get_library_book(str(book_id or "").strip())

