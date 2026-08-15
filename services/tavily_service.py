"""Tavily 实时检索，用于书本金句取证。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from typing import Any

import requests

from config import app_config
from services.skill_runtime import SkillExecutionError


BOOKS: dict[str, dict[str, str]] = {
    "jianlai": {
        "title": "《剑来》",
        "author": "烽火戏诸侯",
        "official_url": "https://book.qidian.com/info/1010468795/",
    },
    "musk": {
        "title": "《埃隆·马斯克传》",
        "author": "沃尔特·艾萨克森",
        "official_url": "https://www.simonandschuster.com/books/Elon-Musk/Walter-Isaacson/9781982181284",
    },
    "daode": {
        "title": "《道德经》",
        "author": "老子",
        "official_url": "https://ctext.org/dao-de-jing",
    },
}


def _require_key() -> str:
    if not app_config.tavily_api_key:
        raise SkillExecutionError("TAVILY_NOT_CONFIGURED", "未配置 Tavily API Key")
    return app_config.tavily_api_key


def search(
    query: str,
    max_results: int = 6,
    *,
    search_depth: str = "advanced",
    timeout: tuple[float, float] = (5, 25),
    include_raw_content: bool | str = "markdown",
) -> list[dict[str, Any]]:
    if not query.strip():
        raise SkillExecutionError("SEARCH_QUERY_EMPTY", "联网检索词为空")
    try:
        response = requests.post(
            f"{app_config.tavily_api_base.rstrip('/')}/search",
            headers={
                "Authorization": f"Bearer {_require_key()}",
                "Content-Type": "application/json",
            },
            json={
                "query": query.strip(),
                "topic": "general",
                "search_depth": search_depth,
                "max_results": max(1, min(max_results, 10)),
                "include_answer": False,
                "include_raw_content": include_raw_content,
                "include_images": False,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise SkillExecutionError(
            "TAVILY_REQUEST_FAILED",
            "Tavily 联网检索失败",
            str(exc),
        ) from exc
    except ValueError as exc:
        raise SkillExecutionError(
            "TAVILY_RESPONSE_INVALID",
            "Tavily 返回了无效数据",
            str(exc),
        ) from exc

    results = payload.get("results")
    if not isinstance(results, list):
        raise SkillExecutionError("TAVILY_RESPONSE_INVALID", "Tavily 结果缺少 results")
    normalized: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url or not title:
            continue
        normalized.append(
            {
                "title": title,
                "url": url,
                "content": str(item.get("content") or "").strip(),
                "raw_content": str(item.get("raw_content") or "").strip(),
                "score": item.get("score"),
                "query": query.strip(),
            }
        )
    if not normalized:
        raise SkillExecutionError("TAVILY_NO_RESULTS", "Tavily 没有返回可用搜索结果")
    return normalized


def search_book_queries(
    query_items: list[dict[str, str]],
    *,
    total_timeout_seconds: float = 8,
    per_request_timeout: tuple[float, float] = (2, 4),
    search_depth: str = "basic",
    include_raw_content: bool | str = False,
) -> list[dict[str, Any]]:
    if not query_items:
        raise SkillExecutionError("SEARCH_PLAN_EMPTY", "书库 Skill 没有生成检索计划")
    all_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    per_query_limit = 3 if len(query_items) > 3 else 6
    tasks: list[tuple[str, str, dict[str, str]]] = []
    for query_item in query_items:
        book_id = str(query_item.get("book_id") or "")
        query = str(query_item.get("query") or "").strip()
        book = BOOKS.get(book_id)
        if not book or not query:
            continue
        tasks.append((book_id, query, book))
    if not tasks:
        raise SkillExecutionError("SEARCH_PLAN_EMPTY", "书库 Skill 没有可执行检索计划")

    errors: list[str] = []
    executor = ThreadPoolExecutor(max_workers=min(3, len(tasks)))
    future_map = {
        executor.submit(
            search,
            query,
                per_query_limit,
                search_depth=search_depth,
                timeout=per_request_timeout,
                include_raw_content=include_raw_content,
            ): (book_id, book)
        for book_id, query, book in tasks
    }
    try:
        for future in as_completed(future_map, timeout=total_timeout_seconds):
            book_id, book = future_map[future]
            try:
                results = future.result()
            except Exception as exc:
                errors.append(str(exc))
                continue
            for result in results:
                if result["url"] in seen_urls:
                    continue
                seen_urls.add(result["url"])
                all_results.append(
                    {
                        **result,
                        "book_id": book_id,
                        "book": book["title"],
                        "author": book["author"],
                    }
                )
    except FuturesTimeoutError:
        errors.append("联网检索超过时间上限")
        for future in future_map:
            future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    if not all_results:
        detail = "；".join(errors[:3])
        raise SkillExecutionError("TAVILY_NO_RESULTS", "没有检索到三本书的可用来源", detail)
    return all_results
