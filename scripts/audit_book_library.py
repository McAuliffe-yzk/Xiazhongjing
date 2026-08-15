#!/usr/bin/env python3
"""Classify the existing three-book library without deleting source records."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import DATA_DIR
from services.book_library_quality import normalize_material_text, trusted_daode_chapter_source
from services.book_notes_service import _material_records, _read_lines, ingest_book_note_path
from services.xiangzhongjing_store import (
    DB_PATH,
    book_citation_summary,
    list_book_citations,
    update_book_citation_quality,
)


SOURCE_PATHS = {
    "《剑来》": ("jianlai", DATA_DIR / "source_documents" / "剑来摘录.docx"),
    "《埃隆·马斯克传》": ("musk", DATA_DIR / "source_documents" / "埃隆·马斯克传.pdf"),
    "《道德经》": ("daode", DATA_DIR / "source_documents" / "道德经再读.docx"),
}


def _default_result(reason: str) -> dict[str, str]:
    return {
        "material_type": "context_excerpt",
        "quality_status": "pending_review",
        "quality_reason": reason,
        "source_locator": "",
        "attribution": "",
    }


def _source_record_maps() -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for title, (book_id, path) in SOURCE_PATHS.items():
        if not path.exists():
            result[title] = []
            continue
        lines = _read_lines(path.name, path.read_bytes())
        result[title] = _material_records(book_id, lines)
    return result


def _match_source_record(
    citation: dict[str, Any],
    records: list[dict[str, str]],
) -> dict[str, str] | None:
    quote = normalize_material_text(str(citation.get("quote") or ""))
    if not quote:
        return None
    exact = [record for record in records if normalize_material_text(record["quote"]) == quote]
    if exact:
        return max(
            exact,
            key=lambda item: (
                item["material_type"] == "direct_quote",
                item["quality_status"] == "valid",
            ),
        )
    contained = [
        record
        for record in records
        if len(normalize_material_text(record["quote"])) >= 8
        and normalize_material_text(record["quote"]) in quote
    ]
    if contained:
        return max(contained, key=lambda item: len(normalize_material_text(item["quote"])))
    return None


def _classify(citation: dict[str, Any], records: list[dict[str, str]]) -> dict[str, str]:
    quote = str(citation.get("quote") or "").strip()
    source_url = str(citation.get("source_url") or "").strip()
    if trusted_daode_chapter_source(citation):
        return {
            "material_type": "direct_quote",
            "quality_status": "valid",
            "quality_reason": "Chinese Text Project 章号与证据文本完整，可用于逐字引用",
            "source_locator": re.search(
                r"第\s*\d{1,2}\s*章",
                f"{citation.get('source_title', '')} {citation.get('evidence_text', '')}",
            ).group(0),
            "attribution": "老子",
        }
    if source_url.startswith("local-note://"):
        matched = _match_source_record(citation, records)
        if matched:
            result = dict(matched)
            exact_match = normalize_material_text(matched["quote"]) == normalize_material_text(quote)
            if not exact_match and any(
                marker in quote
                for marker in ("（描写", "（我想", "（化用", "不过我还想说", "绝非“")
            ):
                result.update({
                    "material_type": "reading_note",
                    "quality_status": "valid",
                    "quality_reason": "旧记录混有用户注释；清洁后的原句已另行保存",
                })
            result["attribution"] = matched.get("attribution") or str(citation.get("attribution") or "")
            return result
        if quote.endswith(("：", ":")) or re.match(r"^(?:序章|\d{2}\D)", quote):
            return {
                "material_type": "metadata",
                "quality_status": "quarantined",
                "quality_reason": "旧解析产生的章节或分区标题",
                "source_locator": "旧版导入记录",
                "attribution": "",
            }
        if citation.get("book") == "《埃隆·马斯克传》":
            return {
                "material_type": "context_excerpt",
                "quality_status": "quarantined",
                "quality_reason": "旧版 PDF 片段未能对应当前完整段落，已由重解析内容替代",
                "source_locator": "旧版导入记录",
                "attribution": "",
            }
        if len(quote) < 8 or not re.search(r"[。！？；.!?]$", quote):
            return {
                "material_type": "context_excerpt",
                "quality_status": "quarantined",
                "quality_reason": "旧版 PDF 断行或不完整片段，完整内容已重新解析",
                "source_locator": "旧版导入记录",
                "attribution": "",
            }
        return _default_result("未能与当前源文件的完整段落稳定对应，保留待人工复核")
    return {
        "material_type": "direct_quote",
        "quality_status": "pending_review",
        "quality_reason": "历史项目或外部来源引文，保留记录但需人工确认逐字出处",
        "source_locator": "历史记录",
        "attribution": str(citation.get("attribution") or ""),
    }


def _quarantine_subset_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        chapter_match = re.search(
            r"第\s*\d{1,2}\s*章",
            f"{row.get('source_title', '')} {row.get('evidence_text', '')}",
        )
        if chapter_match and str(row.get("quality_status")) == "valid":
            grouped[(str(row.get("book") or ""), chapter_match.group(0))].append(row)
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: len(normalize_material_text(item.get("quote", ""))), reverse=True)
        kept: list[str] = []
        for item in ordered:
            normalized = normalize_material_text(item.get("quote", ""))
            if any(normalized and normalized in longer for longer in kept):
                update_book_citation_quality(
                    int(item["id"]),
                    material_type="direct_quote",
                    quality_status="quarantined",
                    quality_reason="同章已有更完整的原文，本条为其子句重复",
                    source_locator=re.search(r"第\s*\d{1,2}\s*章", str(item.get("source_title") or "")).group(0),
                    attribution=str(item.get("attribution") or ""),
                )
                updates.append({"id": int(item["id"]), "reason": "subset_duplicate"})
            else:
                kept.append(normalized)
    return updates


def _quarantine_exact_duplicates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("material_type") != "direct_quote" or row.get("quality_status") != "valid":
            continue
        signature = normalize_material_text(str(row.get("quote") or ""))
        if signature:
            grouped[(str(row.get("book") or ""), signature)].append(row)
    updates: list[dict[str, Any]] = []
    for items in grouped.values():
        if len(items) < 2:
            continue
        keeper = max(
            items,
            key=lambda item: (
                trusted_daode_chapter_source(item),
                bool(item.get("source_locator")),
                len(str(item.get("evidence_text") or "")),
                int(item.get("id") or 0),
            ),
        )
        for item in items:
            if item["id"] == keeper["id"]:
                continue
            update_book_citation_quality(
                int(item["id"]),
                material_type="direct_quote",
                quality_status="quarantined",
                quality_reason=f"同书已有规范化后相同的完整原句（保留 ID {keeper['id']}）",
                source_locator=str(item.get("source_locator") or "历史重复记录"),
                attribution=str(item.get("attribution") or ""),
            )
            updates.append({"id": int(item["id"]), "kept_id": int(keeper["id"]), "reason": "exact_duplicate"})
    return updates


def run(report_dir: Path, ingest_sources: bool = True) -> dict[str, Any]:
    source_maps = _source_record_maps()
    before = list_book_citations("", limit=2000)
    changes: list[dict[str, Any]] = []
    for citation in before:
        result = _classify(citation, source_maps.get(str(citation.get("book") or ""), []))
        update_book_citation_quality(
            int(citation["id"]),
            material_type=result["material_type"],
            quality_status=result["quality_status"],
            quality_reason=result["quality_reason"],
            source_locator=result["source_locator"],
            attribution=result.get("attribution"),
        )
        changes.append({"id": int(citation["id"]), "book": citation["book"], **result})

    imports: list[dict[str, Any]] = []
    if ingest_sources:
        for _title, (book_id, path) in SOURCE_PATHS.items():
            if path.exists():
                imports.append(ingest_book_note_path(path, book_id))

    refreshed = list_book_citations("", limit=2000)
    exact_duplicates = _quarantine_exact_duplicates(refreshed)
    refreshed = list_book_citations("", limit=2000)
    subset_duplicates = _quarantine_subset_duplicates(refreshed)
    duplicates = exact_duplicates + subset_duplicates
    final_rows = list_book_citations("", limit=2000)
    counts = Counter((row["book"], row["material_type"], row["quality_status"]) for row in final_rows)
    report = {
        "audited_at": datetime.now().isoformat(timespec="seconds"),
        "database": str(DB_PATH),
        "before_count": len(before),
        "after_count": len(final_rows),
        "imports": imports,
        "subset_duplicates_quarantined": duplicates,
        "counts": [
            {"book": key[0], "material_type": key[1], "quality_status": key[2], "count": count}
            for key, count in sorted(counts.items())
        ],
        "summary": book_citation_summary(limit=2000)["summary"],
        "changes": changes,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = report_dir / f"book-library-audit-{stamp}.json"
    md_path = report_dir / f"book-library-audit-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 精神书库素材审计报告",
        "",
        f"- 审计时间：{report['audited_at']}",
        f"- 审计前：{report['before_count']} 条",
        f"- 审计后：{report['after_count']} 条（含重新解析补全，未删除原始记录）",
        f"- 子句重复隔离：{len(duplicates)} 条",
        "",
        "## 各书状态",
        "",
    ]
    for item in report["summary"]:
        lines.append(
            f"- {item['book']}：共 {item['count']}；可引用 {item['quotable_count']}；"
            f"待复核 {item['pending_count']}；已隔离 {item['quarantined_count']}"
        )
    lines.extend(["", f"完整逐条记录见 `{json_path.name}`。", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    report["report_json"] = str(json_path)
    report["report_markdown"] = str(md_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-dir", default="artifacts/book-library-audits")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()
    report = run(Path(args.report_dir), ingest_sources=not args.no_ingest)
    print(json.dumps({key: report[key] for key in (
        "before_count", "after_count", "summary", "report_json", "report_markdown"
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
