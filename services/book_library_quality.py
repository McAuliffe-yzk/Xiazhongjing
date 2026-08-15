"""精神书库素材的统一类型、质量与生成准入规则。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


MATERIAL_TYPES = {
    "direct_quote",
    "reading_note",
    "context_excerpt",
    "metadata",
}
QUALITY_STATUSES = {"valid", "pending_review", "quarantined"}

MATERIAL_TYPE_LABELS = {
    "direct_quote": "可引用原句",
    "reading_note": "阅读笔记",
    "context_excerpt": "上下文摘录",
    "metadata": "目录信息",
}
QUALITY_STATUS_LABELS = {
    "valid": "已通过",
    "pending_review": "待复核",
    "quarantined": "已隔离",
}


def normalize_material_text(value: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", str(value or "")).lower()


def trusted_daode_chapter_source(citation: dict[str, Any]) -> bool:
    """识别已带章号证据的 Chinese Text Project《道德经》原文。"""
    source_url = str(citation.get("source_url") or citation.get("url") or "").strip()
    parsed = urlparse(source_url)
    source_title = str(citation.get("source_title") or "")
    evidence = str(citation.get("evidence_text") or "")
    quote = str(citation.get("quote") or "")
    return bool(
        parsed.hostname in {"ctext.org", "www.ctext.org"}
        and parsed.path.startswith("/dao-de-jing")
        and "Chinese Text Project" in source_title
        and re.search(r"第\s*\d{1,2}\s*章", f"{source_title} {evidence}")
        and normalize_material_text(quote)
        and normalize_material_text(quote) in normalize_material_text(evidence)
    )


def trusted_global_source(citation: dict[str, Any]) -> bool:
    source_url = str(citation.get("source_url") or citation.get("url") or "").strip()
    parsed = urlparse(source_url)
    return bool(
        source_url.startswith("local-note://")
        or trusted_daode_chapter_source(citation)
        or (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and str(citation.get("project_id") or "").strip()
            and normalize_material_text(str(citation.get("quote") or ""))
            in normalize_material_text(str(citation.get("evidence_text") or citation.get("quote") or ""))
        )
    )


def is_generation_ready_citation(citation: dict[str, Any]) -> bool:
    """只有已通过的可引用原句可以进入文案生成候选池。"""
    material_type = str(citation.get("material_type") or "").strip()
    quality_status = str(citation.get("quality_status") or "").strip()
    if material_type != "direct_quote" or quality_status != "valid":
        return False
    quote = str(citation.get("quote") or "").strip()
    evidence = str(citation.get("evidence_text") or quote)
    if not quote or normalize_material_text(quote) not in normalize_material_text(evidence):
        return False
    return trusted_global_source(citation)


def normalized_material_type(value: str, default: str = "direct_quote") -> str:
    return value if value in MATERIAL_TYPES else default


def normalized_quality_status(value: str, default: str = "pending_review") -> str:
    return value if value in QUALITY_STATUSES else default
