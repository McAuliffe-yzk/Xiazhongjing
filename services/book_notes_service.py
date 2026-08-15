"""精神书库的本地阅读笔记接入。"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from docx import Document
from PyPDF2 import PdfReader

from services.library_catalog import book_map, resolve_book
from services.xiangzhongjing_store import (
    LEGACY_LIBRARY_BOOKS,
    book_citation_summary,
    create_library_book,
    save_book_citations,
)


BOOK_ALIASES = {
    "jianlai": ("剑来", "烽火戏诸侯", "陈平安"),
    "musk": ("埃隆", "马斯克", "Elon", "Musk", "艾萨克森"),
    "daode": ("道德经", "老子", "Dao De Jing"),
}

JIANLAI_SPEAKERS = {
    "齐静春", "阿良", "陈平安", "李宝瓶", "林守一", "魏檗", "崔东山",
    "崔瀺", "绣虎", "李希圣", "陆沉", "杨老头", "崔诚", "贺小凉",
    "宋正醇", "老秀才",
}

JIANLAI_EXTERNAL_QUOTES = {
    "醉后不知天在水，满船清梦压星河。": "唐珙《题龙阳县青草湖》",
    "吹灭读书灯，一身都是月。": "常见诗句，尚不能作为《剑来》独立原句归因",
    "人生不满百，常怀千岁忧。": "化用《古诗十九首·生年不满百》",
    "与善人居，如入芝兰之室，久而自芳矣。": "化用《孔子家语》",
    "天行健，君子以自强不息。": "《周易》",
    "行到水穷处，坐看云起时。到时候你自然而然会知道答案。": "含王维《终南别业》原句",
    "君子可欺之以方。": "《孟子》",
    "背后说人是非者，必是是非人。": "传统劝世格言",
    "见贤思齐，天经地义。": "含《论语》原句",
    "尽信书不如无书。": "《孟子》",
    "天人相分，化性起伪。人性本恶，教而向善。": "含荀子思想与原句",
    "我见青山多妩媚。料青山见我应如是？": "辛弃疾《贺新郎》",
    "君子慎其独也，克己复礼。": "含《礼记》《论语》原句",
}


def _clean_text(value: str) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", str(value or "")).strip()


def _read_docx(data: bytes) -> list[str]:
    document = Document(BytesIO(data))
    return [_clean_text(paragraph.text) for paragraph in document.paragraphs if _clean_text(paragraph.text)]


def _read_pdf(data: bytes) -> list[str]:
    reader = PdfReader(BytesIO(data))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            cleaned = _clean_text(line)
            if cleaned:
                lines.append(cleaned)
    return _join_pdf_lines(lines)


def _is_musk_chapter_heading(line: str) -> bool:
    text = line.strip()
    return bool(re.match(r"^(?:序章|\d{2}(?![\d.、）)]))", text))


def _join_pdf_lines(lines: list[str]) -> list[str]:
    """Reconstruct paragraphs split by PDF text extraction without merging headings."""
    joined: list[str] = []
    buffer = ""

    def complete(text: str) -> bool:
        return bool(re.search(r"[。！？；：.!?][”’」』）)]?$", text.strip()))

    def boundary(text: str) -> bool:
        normalized = text.strip("-— ")
        return bool(
            normalized in {"我的思考", "方法论", "衍生推论"}
            or "人生小课堂" in normalized
            or _is_musk_chapter_heading(normalized)
            or re.match(r"^(?:[\u2022\uf06c]|\d+[.、）)])", normalized)
        )

    def heading_boundary(text: str) -> bool:
        normalized = text.strip("-— ")
        return bool(
            normalized in {"我的思考", "方法论", "衍生推论"}
            or "人生小课堂" in normalized
            or _is_musk_chapter_heading(normalized)
        )

    for line in lines:
        if not buffer:
            buffer = line
            continue
        if boundary(line) or heading_boundary(buffer) or complete(buffer):
            joined.append(buffer)
            buffer = line
        else:
            buffer += line
    if buffer:
        joined.append(buffer)
    return joined


def _read_plain_text(data: bytes) -> list[str]:
    text = data.decode("utf-8", errors="ignore")
    return [_clean_text(line) for line in text.splitlines() if _clean_text(line)]


def detect_book_id(filename: str, lines: list[str], explicit_book_id: str = "") -> str:
    if explicit_book_id and resolve_book(explicit_book_id):
        return explicit_book_id
    haystack = f"{filename}\n{' '.join(lines[:40])}"
    for book_id, aliases in BOOK_ALIASES.items():
        if any(alias in haystack for alias in aliases):
            return book_id
    return ""


def _strip_marker(line: str) -> str:
    return re.sub(r"^\s*(?:[\u2022\uf06c\-]|\d+[\.、）)]|[一二三四五六七八九十]+[、）)])\s*", "", line).strip()


def _quote_strings(line: str) -> list[str]:
    results: list[str] = []
    for pattern in (r"“([^”]{2,140})”", r"「([^」]{2,140})」", r"『([^』]{2,140})』"):
        results.extend(_clean_text(match) for match in re.findall(pattern, line))
    return [item for item in results if _usable_candidate(item)]


def _usable_candidate(line: str) -> bool:
    text = _strip_marker(line)
    if not text or len(text) < 4 or len(text) > 180:
        return False
    if text in {"好句", "成语", "方法论", "我的思考", "衍生推论"}:
        return False
    if re.search(r"[:：]\s*指", text) or "多作" in text or "泛指" in text:
        return False
    if re.fullmatch(r"[\u4e00-\u9fffA-Za-z·]{1,5}", text):
        return False
    return True


def _record(
    quote: str,
    material_type: str,
    quality_status: str,
    reason: str,
    locator: str,
    *,
    evidence_text: str = "",
    attribution: str = "",
) -> dict[str, str]:
    return {
        "quote": _clean_text(quote),
        "material_type": material_type,
        "quality_status": quality_status,
        "quality_reason": reason,
        "source_locator": locator,
        "evidence_text": _clean_text(evidence_text or quote),
        "attribution": attribution,
    }


def _strip_trailing_annotation(line: str) -> tuple[str, str]:
    match = re.search(r"（([^（）]{2,90})）\s*$", line)
    if not match:
        return line, ""
    return line[: match.start()].rstrip(), match.group(1).strip()


def _jianlai_materials(lines: list[str]) -> list[dict[str, str]]:
    try:
        start = lines.index("好句") + 1
    except ValueError:
        start = 0
    records: list[dict[str, str]] = []
    speaker = ""
    for index, raw in enumerate(lines[start:], start=start + 1):
        line = _strip_marker(raw)
        locator = f"第 {index} 段"
        if not line:
            continue
        speaker_match = re.fullmatch(r"([^（）]{1,8})(?:（[^（）]+）)?", line)
        if line in JIANLAI_SPEAKERS or (speaker_match and line.split("（", 1)[0] in JIANLAI_SPEAKERS):
            speaker = line.split("（", 1)[0]
            records.append(_record(line, "metadata", "valid", "人物分组标签，不参与原句植入", locator))
            continue
        clean_quote, annotation = _strip_trailing_annotation(line)
        if line in JIANLAI_EXTERNAL_QUOTES:
            records.append(_record(
                line,
                "context_excerpt",
                "valid",
                f"摘录中引用了其他典籍或诗词：{JIANLAI_EXTERNAL_QUOTES[line]}",
                locator,
                attribution=JIANLAI_EXTERNAL_QUOTES[line],
            ))
            continue
        if annotation and any(marker in annotation for marker in ("化用", "强调", "解释")):
            records.append(_record(
                clean_quote,
                "reading_note",
                "valid",
                f"用户注释：{annotation}",
                locator,
                evidence_text=line,
                attribution=speaker,
            ))
            continue
        if any(marker in line for marker in ("不过我还想说", "我想自己做决定")):
            records.append(_record(
                clean_quote,
                "reading_note",
                "valid",
                "包含用户解释或个人判断，仅作为阅读笔记",
                locator,
                evidence_text=line,
                attribution=speaker,
            ))
            continue
        narrative_dialogue = bool(
            re.search(r"(?:点点头|问道|笑问|答曰|回答|面无表情道|欣慰道).*[“：]", clean_quote)
        )
        if len(clean_quote) > 220 or narrative_dialogue or clean_quote.count("：“") + clean_quote.count("问道") >= 2:
            records.append(_record(
                clean_quote,
                "context_excerpt",
                "valid",
                "长对话或叙事上下文，不作为独立金句",
                locator,
                evidence_text=line,
                attribution=speaker,
            ))
            continue
        if not _usable_candidate(clean_quote):
            records.append(_record(line, "metadata", "quarantined", "不构成完整可用素材", locator))
            continue
        records.append(_record(
            clean_quote,
            "direct_quote",
            "valid",
            "阅读摘录中的完整独立原句",
            locator,
            evidence_text=line,
            attribution=speaker,
        ))
    return records


def _musk_materials(lines: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    section = ""
    for index, raw in enumerate(lines, start=1):
        line = _strip_marker(raw)
        normalized = line.strip("-— ")
        locator = f"第 {index} 段"
        if not line or line == "《埃隆·马斯克传》":
            continue
        if normalized in {"我的思考", "方法论", "衍生推论"} or "人生小课堂" in normalized:
            section = normalized
            records.append(_record(line, "metadata", "valid", "阅读笔记分区标题", locator))
            continue
        if _is_musk_chapter_heading(normalized):
            section = "正文"
            records.append(_record(line, "metadata", "valid", "书籍章节标题", locator))
            continue
        if section in {"我的思考", "方法论", "衍生推论"} or "人生小课堂" in section:
            records.append(_record(
                line,
                "reading_note",
                "valid",
                "个人思考或方法论整理，不冒充书中逐字引文",
                locator,
            ))
            continue
        if line.startswith("（") and line.endswith("）"):
            records.append(_record(line.strip("（）"), "reading_note", "valid", "用户补充说明", locator))
            continue
        quoted = _quote_strings(line)
        if quoted:
            for quote in quoted:
                attribution = "马斯克" if re.search(r"马斯克(?:说|回答|谈到)|埃隆(?:说|回答)", line) else "书中人物"
                records.append(_record(
                    quote,
                    "direct_quote",
                    "valid",
                    "PDF 正文中带引号的完整原句",
                    locator,
                    evidence_text=line,
                    attribution=attribution,
                ))
            outside = re.sub(r"[“「『].*?[”」』]", "", line)
            if len(_clean_text(outside)) >= 28:
                records.append(_record(
                    line,
                    "context_excerpt",
                    "valid",
                    "引文所在叙事上下文",
                    locator,
                    attribution="沃尔特·艾萨克森",
                ))
            continue
        material_type = "context_excerpt"
        status = "valid" if _usable_candidate(line) or len(line) > 180 else "quarantined"
        records.append(_record(
            line,
            material_type if status == "valid" else "metadata",
            status,
            "传记叙述上下文，不作为人物直接引语" if status == "valid" else "不构成完整可用素材",
            locator,
            attribution="沃尔特·艾萨克森" if status == "valid" else "",
        ))
    return records


def _daode_materials(lines: list[str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for index, raw in enumerate(lines, start=1):
        line = _strip_marker(raw)
        locator = f"第 {index} 段"
        if not line:
            continue
        if re.fullmatch(r"(?:重读|整理于|摘录于).*\d{4}[.年/-]", line) or re.match(r"^重读\s*\d{4}", line):
            records.append(_record(line, "metadata", "quarantined", "日期标记，不是书籍素材", locator))
        elif line.startswith("绝非") or any(marker in line for marker in ("我们会通过", "因为圣人", "方向一旦")):
            records.append(_record(
                line,
                "reading_note",
                "valid",
                "个人重读解释，不作为《道德经》逐字原文",
                locator,
                attribution="阅读笔记",
            ))
        elif _usable_candidate(line):
            records.append(_record(
                line,
                "direct_quote",
                "valid",
                "本地阅读摘录中的完整原句",
                locator,
                attribution="老子",
            ))
        else:
            records.append(_record(line, "metadata", "quarantined", "不构成完整可用素材", locator))
    return records


def _generic_materials(lines: list[str], author: str = "") -> list[dict[str, str]]:
    """Conservatively classify arbitrary books and personal reading notes."""
    records: list[dict[str, str]] = []
    note_markers = ("我的思考", "我的笔记", "阅读笔记", "心得", "感想", "批注", "启发")
    section = ""
    for index, raw in enumerate(lines, start=1):
        line = _strip_marker(raw)
        locator = f"第 {index} 段"
        if not line:
            continue
        if any(line.startswith(marker) for marker in note_markers):
            section = "reading_note"
            content = re.sub(r"^(?:我的思考|我的笔记|阅读笔记|心得|感想|批注|启发)\s*[:：]?\s*", "", line)
            if content:
                records.append(_record(content, "reading_note", "valid", "用户标注的阅读笔记", locator, attribution="阅读笔记"))
            else:
                records.append(_record(line, "metadata", "valid", "阅读笔记分区标题", locator))
            continue
        quoted = _quote_strings(line)
        if quoted:
            for quote in quoted:
                records.append(_record(
                    quote,
                    "direct_quote",
                    "valid",
                    "上传资料中带引号的完整原句",
                    locator,
                    evidence_text=line,
                    attribution=author,
                ))
            if len(_clean_text(re.sub(r"[“「『].*?[”」』]", "", line))) >= 28:
                records.append(_record(line, "context_excerpt", "valid", "原句所在上下文", locator, attribution=author))
            continue
        if section == "reading_note":
            records.append(_record(line, "reading_note", "valid", "用户阅读笔记内容", locator, attribution="阅读笔记"))
            continue
        if len(line) <= 180 and _usable_candidate(line):
            records.append(_record(
                line,
                "direct_quote",
                "pending_review",
                "短句可能是可引用原句，需用户确认后参与生成",
                locator,
                attribution=author,
            ))
        elif len(line) > 12:
            records.append(_record(line, "context_excerpt", "valid", "书籍或笔记上下文，仅供检索理解", locator, attribution=author))
        else:
            records.append(_record(line, "metadata", "quarantined", "不构成完整可用素材", locator))
    return records


def _material_records(book_id: str, lines: list[str], author: str = "") -> list[dict[str, str]]:
    if book_id == "jianlai":
        records = _jianlai_materials(lines)
    elif book_id == "musk":
        records = _musk_materials(lines)
    elif book_id == "daode":
        records = _daode_materials(lines)
    else:
        records = _generic_materials(lines, author=author)
    cleaned: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        signature = re.sub(r"\W+", "", record["quote"])
        key = (record["material_type"], signature)
        if not signature or key in seen:
            continue
        seen.add(key)
        cleaned.append(record)
    return cleaned


def _candidate_lines(book_id: str, lines: list[str]) -> list[str]:
    """Compatibility helper: return every parsed material without the old 80-row cap."""
    return [record["quote"] for record in _material_records(book_id, lines)]


def _read_lines(filename: str, data: bytes) -> list[str]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        return _read_docx(data)
    if suffix == ".pdf":
        return _read_pdf(data)
    if suffix in {".txt", ".md"}:
        return _read_plain_text(data)
    raise ValueError("暂只支持 .docx、.pdf、.txt、.md 阅读笔记")


def ingest_book_note_bytes(
    filename: str,
    data: bytes,
    explicit_book_id: str = "",
    *,
    title: str = "",
    author: str = "",
    description: str = "",
) -> dict[str, Any]:
    if not data:
        raise ValueError("阅读笔记文件为空")
    lines = _read_lines(filename, data)
    book_id = detect_book_id(filename, lines, explicit_book_id)
    if not book_id:
        if not str(title or "").strip():
            raise ValueError("无法自动识别书籍，请填写书名后重新上传")
        book = create_library_book(
            title,
            author=author,
            description=description,
            book_id=explicit_book_id,
            source_type="user_import",
        )
        book_id = str(book["id"])
    else:
        book = resolve_book(book_id)
        if not book:
            legacy = LEGACY_LIBRARY_BOOKS.get(book_id)
            if not legacy:
                raise ValueError("指定书籍不存在，请先在书库中新建")
            book = create_library_book(
                legacy["title"],
                author=legacy["author"],
                book_id=book_id,
                source_type="legacy",
            )
    materials = _material_records(book_id, lines, author=str(book.get("author") or author))
    if not materials:
        raise ValueError("未从阅读笔记中提取到可沉淀的短句或方法论素材")
    digest = hashlib.sha1(data).hexdigest()[:12]
    citations = [
        {
            "book": book["title"],
            "book_id": book_id,
            "quote": material["quote"],
            "attribution": material.get("attribution") or ("阅读笔记" if book_id == "musk" else book.get("author", "")),
            "source_title": filename,
            "url": f"local-note://{book_id}/{digest}/{index + 1}",
            "evidence_text": material.get("evidence_text") or material["quote"],
            "material_type": material["material_type"],
            "quality_status": material["quality_status"],
            "quality_reason": material["quality_reason"],
            "source_locator": material["source_locator"],
        }
        for index, material in enumerate(materials)
    ]
    save_book_citations("", citations)
    return {
        "book_id": book_id,
        "book": book["title"],
        "filename": filename,
        "count": len(citations),
        "quotable_count": sum(
            item["material_type"] == "direct_quote" and item["quality_status"] == "valid"
            for item in citations
        ),
        "examples": citations[:5],
    }


def ingest_book_note_path(path: str | Path, explicit_book_id: str = "") -> dict[str, Any]:
    note_path = Path(path).expanduser()
    return ingest_book_note_bytes(note_path.name, note_path.read_bytes(), explicit_book_id)


def book_notes_state(limit: int = 2000) -> dict[str, Any]:
    return book_citation_summary(limit=limit)
