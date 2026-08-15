"""匣中镜多 Skill 创作、编辑、蒸馏与书库服务。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Callable

from config import BASE_DIR
from services.book_library_quality import is_generation_ready_citation
from services.library_catalog import book_map
from services.skill_runtime import SkillExecutionError, run_json, run_text
from services.dna_store import get_dna_reagents_by_ids
from services.xiangzhongjing_store import (
    create_generation_job,
    create_style_candidate,
    get_generation_job,
    get_published_style,
    get_style_version,
    list_book_citations,
    list_style_versions,
    mark_style_comparison_completed,
    recent_style_feedback,
    reference_document_count,
    save_book_citations,
    save_reference_document,
    update_generation_job,
)


BASELINE_STYLE_PATH = BASE_DIR / "knowledge" / "generic_creator_writing_skill.md"
BUNDLED_REFERENCE_DOCUMENTS = 0

ProgressCallback = Callable[[dict[str, Any]], None]


def _available_books() -> dict[str, dict[str, Any]]:
    """Return the persisted user library; blank installs intentionally have no books."""
    return book_map()

GENERATION_STAGE_META: dict[str, dict[str, str]] = {
    "architect-vlog-narrative": {
        "label": "叙事架构",
        "phase": "创作",
        "message": "拆开事实与观点，先搭出六段叙事骨架，再分配段落任务。",
    },
    "write-personal-vlog": {
        "label": "个人声音写作",
        "phase": "创作",
        "message": "调用已发布的个人风格语法，把素材按主题、蒙太奇、高潮和回扣发展成完整叙事。",
    },
    "optimize-douyin-vlog": {
        "label": "抖音 Vlog 优化",
        "phase": "提效",
        "message": "保留个人声音，优化开头钩子、口语节奏、情绪推进和结尾钩子。",
    },
    "insert-book-quotes": {
        "label": "书库支撑",
        "phase": "书库",
        "message": "先判断引文该落在哪个转念时机，再用本地书库原文直引，不创造引文。",
    },
    "audit-writing-quality": {
        "label": "综合审校",
        "phase": "审校",
        "message": "一次检查个人风格、叙事展开、事实边界、素材覆盖和原创表达。",
    },
}


def _emit_progress(
    progress: ProgressCallback | None,
    event: str,
    skill: str,
    **payload: Any,
) -> None:
    if not progress:
        return
    meta = GENERATION_STAGE_META.get(skill, {})
    progress(
        {
            "event": event,
            "skill": skill,
            "label": meta.get("label", skill),
            "phase": meta.get("phase", ""),
            "message": payload.pop("message", meta.get("message", "")),
            **payload,
        }
    )

EDIT_ACTIONS = {
    "shorten": {
        "label": "全文收束",
        "instruction": "自动选择全文中最冗余的一段，删除重复解释、同义递进和不再推进叙事的句子，压缩到该段原长度的 55%-75%；保留事实、真实细节、转念和主题作用。",
        "execution_contract": "只收束一个有足够体量的段落；必须真实减少该段体量，不能删除承载事实、转念和主题作用的内容，也不能只删全篇几个词。",
        "min_changes": 1,
        "mode": "paragraph_patch",
        "max_tokens": 2400,
        "temperature": 0.52,
    },
    "more-personal": {
        "label": "更像我",
        "instruction": "在不新增事实的前提下，优先选择两段真正影响全文气质的平整表达，分别使用不同的结构动作重写：事件与判断换序、对照重组、自问自答、判断降调或主题回扣。让观点从事件中长出来，并形成第一人称长短句呼吸与克制收束。",
        "execution_contract": "至少交付 1 段、优先交付 2 段高价值结构重写，不以数量凑修改。只处理至少 14 个非标点字符、具备事实或思考展开空间的正文段，不选择一句话过渡段。优先覆盖“事件 -> 感受 -> 此刻判断”，以及真正的自我追问、自我反驳或删除泛化结论后的克制落点。每段都必须改变句子骨架或思考推进，不能只删词、缩写短语、替换口头禅或连接词。",
        "min_changes": 1,
        "mode": "paragraph_patch",
        "max_tokens": 2200,
        "temperature": 0.62,
    },
    "rebuild-opening": {
        "label": "重写开头",
        "instruction": "只重写开头一至两段，给出三个真正不同且能接回正文的开头。不得新增事实。",
        "execution_contract": "三个开头必须分别使用不同的叙事入口，并分别说明其核心变化。",
        "min_changes": 1,
        "mode": "opening_options",
        "max_tokens": 1600,
        "temperature": 0.68,
    },
    "selection-polish": {
        "label": "局部改写",
        "instruction": "判断选中段落在全文中的叙事作用，先提取事实骨架，再丢开原句重写；至少重排两处句子之间的先后、对照、因果或自我修正关系。只输出选区替换结果，保留事实但不得只换同义词或标点。",
        "execution_contract": "必须改变句子骨架和思考推进关系，使非标点文本至少产生约 10% 的变化；不得只替换词语、连接词、语气词或标点，也不得原样返回后在 changes 中声称发生变化。",
        "min_changes": 1,
        "mode": "selection",
        "max_tokens": 1100,
        "temperature": 0.74,
    },
}


def _baseline_style() -> str:
    if not BASELINE_STYLE_PATH.exists():
        raise SkillExecutionError("STYLE_NOT_FOUND", "基础个人创作风格文件不存在")
    return BASELINE_STYLE_PATH.read_text(encoding="utf-8").strip()


def load_writing_skill() -> tuple[str, str]:
    return get_published_style(_baseline_style())


def writing_skill_stats() -> dict[str, Any]:
    version, skill = load_writing_skill()
    versions = list_style_versions()
    stored_reference_documents = reference_document_count()
    return {
        "chars": len(skill),
        "rules": len([line for line in skill.splitlines() if line.strip().startswith("- ")]),
        "mode": "versioned_writing_skill",
        "published_version": version,
        "reference_documents": stored_reference_documents or BUNDLED_REFERENCE_DOCUMENTS,
        "baseline_sources": BUNDLED_REFERENCE_DOCUMENTS,
        "candidate_versions": len([item for item in versions if item["status"] == "candidate"]),
        "versions": versions,
    }


def load_active_dna_context(payload: dict[str, Any]) -> str:
    """Return optional external style reagents. Empty selection means zero regression."""
    raw_ids = payload.get("active_dna_ids") or []
    if not isinstance(raw_ids, list):
        return ""
    if not raw_ids:
        return ""
    reagents = get_dna_reagents_by_ids(raw_ids)
    if not reagents:
        return ""
    blocks: list[str] = []
    for reagent in reagents[:3]:
        content = str(reagent.get("content") or "").strip()
        if not content:
            continue
        name = str(reagent.get("name") or "外部 DNA").strip()
        tags = reagent.get("tags") if isinstance(reagent.get("tags"), list) else []
        tag_text = " / ".join(str(tag) for tag in tags[:4] if str(tag).strip())
        blocks.append(
            f"### {name}{f'（{tag_text}）' if tag_text else ''}\n{content[:1200]}"
        )
    if not blocks:
        return ""
    return (
        "以下是用户主动选择的外部博主 DNA 试剂。它们只能作为轻量语言风味参考，"
        "不得覆盖当前创作者的个人 DNA，不得引入外部博主的事实、身份、人物、事件、观点或原句。\n\n"
        + "\n\n".join(blocks)
    )


def writing_context(payload: dict[str, Any], *, exclude_dna: bool = False) -> tuple[str, str]:
    style_version, style = load_writing_skill()
    if exclude_dna:
        return style_version, style
    dna_context = load_active_dna_context(payload)
    if not dna_context:
        return style_version, style
    return style_version, f"{style}\n\n## 可选外部博主 DNA 试剂\n{dna_context}"


def _distill_blogger_dna_sync(name: str, source_text: str) -> dict[str, Any]:
    clean_text = str(source_text or "").strip()
    if len(re.sub(r"\s+", "", clean_text)) < 300:
        raise SkillExecutionError("DNA_SAMPLE_TOO_SHORT", "样本文字少于 300 字，无法蒸馏外部博主 DNA")
    result = run_json(
        "distill-blogger-dna",
        f"""从以下外部博主样本文字中提炼一份“语言风味试剂”。

试剂名称：{name or "未命名博主"}

样本文字：
{clean_text[:30000]}

只输出约定 JSON。""".strip(),
        max_tokens=1200,
        temperature=0.18,
    )
    data = result["data"]
    content = str(data.get("content_markdown") or "").strip()
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    if not content:
        raise SkillExecutionError("DNA_DISTILL_EMPTY", "外部博主 DNA 蒸馏结果为空")
    return {
        "content_markdown": content[:1200],
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()][:6],
        "trace": [_trace_item(result)],
    }


async def distill_blogger_dna(name: str, source_text: str) -> dict[str, Any]:
    return await asyncio.to_thread(_distill_blogger_dna_sync, name, source_text)


def _style_comparison_sync(candidate_id: int, materials: dict[str, Any]) -> dict[str, Any]:
    _require_materials(materials)
    candidate = get_style_version(candidate_id)
    if not candidate or candidate.get("status") != "candidate":
        raise SkillExecutionError("STYLE_CANDIDATE_NOT_FOUND", "待审核候选 Skill 不存在")
    current_version, current_style = load_writing_skill()
    candidate_style = str(candidate.get("skill_content") or "").strip()
    if not candidate_style:
        raise SkillExecutionError("STYLE_CANDIDATE_INVALID", "候选 Skill 内容为空")
    architecture = run_json(
        "architect-vlog-narrative",
        f"""仅根据项目素材生成一份版本中立的 Vlog 叙事计划，用于两个写作 Skill 的公平 A/B 对照，不写正文。

项目素材：
{_materials_text(materials)}

输出 JSON：
{{
  "central_tension": "贯穿全文的真实矛盾",
  "fact_ledger": ["只列素材明确存在的具体事实"],
  "protected_lines": ["必须逐字保留的用户原句、对话、日期或名字"],
  "paragraphs": [
    {{"role": "opening|evidence|deepening|turn|insight|callback|ending", "purpose": "本段任务", "facts": [], "interpretation": "只允许由素材发展出的抽象理解"}}
  ],
  "ending_move": "如何用已有意象或姿态收束"
}}

规划 8-10 个段落；不得新增地点、动作、对话、事件结果、感官画面或心理经历。只输出 JSON。""".strip(),
        max_tokens=3000,
        temperature=0.18,
    )
    prompt = f"""仅根据以下项目素材和共享叙事计划写一版完整 Vlog 文案，用于同素材风格对照。

项目素材：
{_materials_text(materials)}

共享叙事计划：
{json.dumps(architecture["data"], ensure_ascii=False)[:12000]}

要求：
1. 不照搬素材长句，发展事件间的关系、自我追问与主题回扣。
2. 只能扩写抽象理解；不得补写素材中没有的地点、动作、对话、事件结果、感官画面、电影情节或心理经历。
3. 两个版本必须执行同一份叙事计划，只由各自个人风格 Skill 决定语言和节奏。
4. 只输出 1000-1500 字正文。"""
    current = run_text(
        "write-personal-vlog",
        prompt,
        system_context=current_style,
        max_tokens=3600,
        temperature=0.42,
    )
    proposed = run_text(
        "write-personal-vlog",
        prompt,
        system_context=candidate_style,
        max_tokens=3600,
        temperature=0.42,
    )
    protected = _protected_material_lines(materials)
    current_metrics = _writing_overlap_metrics(current["text"], materials, protected)
    candidate_metrics = _writing_overlap_metrics(proposed["text"], materials, protected)
    current_audit = _audit_copy(current["text"], materials)
    candidate_audit = _audit_copy(proposed["text"], materials)
    comparison_passed = bool(
        current_audit["passed"]
        and candidate_audit["passed"]
        and current_metrics["passed"]
        and candidate_metrics["passed"]
    )
    result = {
        "passed": comparison_passed,
        "architecture": architecture["data"],
        "current": {
            "version": current_version,
            "copy": current["text"].strip(),
            "expression_metrics": current_metrics,
            "audit": current_audit["data"],
            "passed": bool(current_audit["passed"] and current_metrics["passed"]),
        },
        "candidate": {
            "id": candidate_id,
            "version": candidate["version"],
            "copy": proposed["text"].strip(),
            "expression_metrics": candidate_metrics,
            "audit": candidate_audit["data"],
            "passed": bool(candidate_audit["passed"] and candidate_metrics["passed"]),
        },
        "trace": [
            _trace_item(architecture),
            _trace_item(current),
            _trace_item(proposed),
            _trace_item(current_audit),
            _trace_item(candidate_audit),
        ],
        "note": (
            "两版使用同一份叙事计划，且均通过事实与原创表达门禁，可以比较个人风格。"
            if comparison_passed
            else "两版已留存，但至少一版未通过事实或原创表达门禁，不允许发布候选 Skill。"
        ),
    }
    mark_style_comparison_completed(
        candidate_id,
        {
            "current_version": current_version,
            "candidate_version": candidate["version"],
            "current_copy": result["current"]["copy"],
            "candidate_copy": result["candidate"]["copy"],
            "passed": comparison_passed,
            "architecture": result["architecture"],
            "current_passed": result["current"]["passed"],
            "candidate_passed": result["candidate"]["passed"],
            "current_audit": result["current"]["audit"],
            "candidate_audit": result["candidate"]["audit"],
            "current_expression_metrics": result["current"]["expression_metrics"],
            "candidate_expression_metrics": result["candidate"]["expression_metrics"],
            "trace": result["trace"],
        },
    )
    return result


async def compare_style_candidate(candidate_id: int, materials: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_style_comparison_sync, candidate_id, materials)


def _narrative_mode_instruction(mode: str) -> str:
    normalized = str(mode or "default").strip()
    if normalized == "parallelism":
        return (
            "排比递进式 —— 使用层层递进的排比句式推进叙事，每个排比段落叠加一个维度的思考，"
            "最后汇聚到核心洞察。段落之间通过「我还记得……」「也是在这段时间……」「更重要的是……」"
            "等递进连接词串联。"
        )
    if normalized == "six-stage":
        return (
            "六段式 —— 严格按照「开头点明主题 → 蒙太奇事件引入与发展 → 高潮情绪堆叠 → "
            "下沉思考冷静 → 回引强化呼应 → 升华价值钩子」组织全文。"
            "每一段都只能承担一个主任务；开头先点题不解释，蒙太奇先砸事件不先讲道理，"
            "高潮先推高压力和情绪，下沉段再让判断降温，回引段必须回到开头的主题或意象，"
            "升华段只给出一个可继续生活的姿态，不写口号。"
        )
    if normalized == "contrast-first":
        return (
            "先抑后扬式 —— 前半部分写出困境、困惑或低谷（抑），通过一个转折事件或顿悟时刻，"
            "在后半部分翻转情绪和认知（扬）。转折要真实，不能是口号式的「然后我想通了」，"
            "而是基于具体事件的逐步转变。"
        )
    return (
        "默认 —— 按「开头点明主题 → 蒙太奇事件引入与发展 → 高潮情绪堆叠 → "
        "下沉思考冷静 → 回引强化呼应 → 升华价值钩子」推进全文；"
        "允许段落自然合并，但六个功能必须都能看见。开头先点出主题，不急着解释；"
        "中段先让事件推动思考，再让情绪堆高；后半段回到主题并给出一个可继续生活的姿态。"
    )


def _personal_narrative_framework(strict: bool = False) -> str:
    framework = (
        "你的默认叙事框架是：开头点明主题，蒙太奇事件引入与发展，高潮情绪堆叠，下沉思考冷静，"
        "回引强化呼应，升华价值钩子。"
    )
    if strict:
        return (
            framework
            + "严格执行时，每一段只能承担一个主任务；先让事件发生，再让判断长出来，"
            + "不要把主题、解释和结论提前摊平。"
        )
    return (
        framework
        + "默认执行时也要能看见这六个功能，但允许段落自然合并、过渡更松一点。"
        + "开头先点题，不先定义；蒙太奇段用短句和并列句砸出生活密度；"
        + "高潮段先把压力抬起来；下沉段再冷静下来思考；回引段回到开头的主题或意象；"
        + "升华段只留一个可以继续往前走的价值钩子。"
    )


def _creator_stage_outline(copy: str) -> list[dict[str, str]]:
    """Return a compact stage outline for UI visibility without adding another LLM gate."""
    text = str(copy or "").strip()
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    stages = [
        ("opening", "开头点明主题", "前几句是否点出主题、状态或变化"),
        ("montage", "蒙太奇事件引入与发展", "真实事件和日常细节如何进入"),
        ("climax", "高潮情绪堆叠", "压力、冲突、选择或行动的高点"),
        ("reflection", "下沉思考冷静", "从事件退一步，出现自问或判断"),
        ("callback", "回引强化呼应", "回到开头主题、句子或意象"),
        ("hook", "升华价值钩子", "最后留下继续往前走的姿态"),
    ]
    if not paragraphs:
        return [{"stage": key, "label": label, "evidence": "", "purpose": purpose} for key, label, purpose in stages]
    indexes = [
        0,
        max(0, min(len(paragraphs) - 1, round(len(paragraphs) * 0.18))),
        max(0, min(len(paragraphs) - 1, round(len(paragraphs) * 0.38))),
        max(0, min(len(paragraphs) - 1, round(len(paragraphs) * 0.6))),
        max(0, min(len(paragraphs) - 1, round(len(paragraphs) * 0.78))),
        len(paragraphs) - 1,
    ]
    outline: list[dict[str, str]] = []
    for (key, label, purpose), index in zip(stages, indexes):
        evidence = re.sub(r"\s+", " ", paragraphs[index])[:90]
        outline.append({"stage": key, "label": label, "evidence": evidence, "purpose": purpose})
    return outline


def _douyin_publish_pack(copy: str, materials: dict[str, Any], style: str) -> dict[str, Any]:
    """Generate a non-blocking publishing pack. It never changes the copy."""
    try:
        result = run_json(
            "adapt-douyin-vlog",
            f"""为下面这篇匣中镜 Vlog 文案生成抖音发布适配包。不要重写正文，不要新增事实，不要标题党。

文案：
{str(copy or "")[:16000]}

项目素材边界：
{_materials_text(materials)[:9000]}

要求：
1. 标题候选要像真实校园生活博主会发的标题，不要营销号。
2. 封面钩子必须短，能放在封面图上。
3. 评论问题要能引发真实交流。
4. 口播提示只针对节奏、停顿、轻重音和拆句。
5. 发布前检查只提醒风险，不阻断。
只返回符合 Skill contract 的 JSON。""".strip(),
            system_context=style,
            max_tokens=1400,
            temperature=0.36,
        )
        data = result["data"]
        titles = [str(item).strip() for item in (data.get("titles") or []) if str(item).strip()][:3]
        cover_hooks = [str(item).strip() for item in (data.get("cover_hooks") or []) if str(item).strip()][:2]
        spoken_notes = [
            item
            for item in (data.get("spoken_notes") or [])
            if isinstance(item, dict) and str(item.get("note") or "").strip()
        ][:3]
        checks = [str(item).strip() for item in (data.get("pre_publish_checks") or []) if str(item).strip()][:4]
        scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
        return {
            "status": "ready",
            "titles": titles,
            "cover_hooks": cover_hooks,
            "comment_question": str(data.get("comment_question") or "").strip(),
            "spoken_notes": spoken_notes,
            "pre_publish_checks": checks,
            "scores": {
                "entry": int(float(scores.get("entry") or 0)),
                "retention": int(float(scores.get("retention") or 0)),
                "spoken_rhythm": int(float(scores.get("spoken_rhythm") or 0)),
                "ending": int(float(scores.get("ending") or 0)),
            },
            "trace": [_trace_item(result)],
        }
    except Exception as exc:
        code = exc.code if isinstance(exc, SkillExecutionError) else "DOUYIN_PACK_FAILED"
        return {
            "status": "failed",
            "reason": str(exc) or "抖音发布适配包暂未生成",
            "error_code": code,
            "titles": [],
            "cover_hooks": [],
            "comment_question": "",
            "spoken_notes": [],
            "pre_publish_checks": [],
            "scores": {},
            "trace": [],
        }


def _book_quote_strategy_config(strategy: str) -> dict[str, Any]:
    normalized = str(strategy or "standard").strip()
    if normalized == "restrained":
        return {
            "mode": "restrained",
            "label": "克制",
            "target": 1,
            "max": 1,
            "instruction": "克制模式：目标加入 1 条，最多 1 条。只选择最能托住整篇核心转念的一处，不追求覆盖多本书。",
        }
    if normalized == "amplified":
        return {
            "mode": "amplified",
            "label": "增强",
            "target": 3,
            "max": 3,
            "instruction": "增强模式：目标加入 3 条，最多 3 条。三条必须承担不同叙事功能，分别优先落在高潮后的判词、思考下沉时的支点、回引或升华前的暗扣；不能堆在同一段，也不能为了数量牺牲自然度。",
        }
    return {
        "mode": "standard",
        "label": "标准",
        "target": 2,
        "max": 3,
        "instruction": "标准模式：目标加入 2 条，最多 3 条。正常情况下必须找满两处不同叙事功能位；只有完整文案确实没有第二个自然转念位置时，才允许少于 2 条，并在 reason 中说明不足原因。若第三条非常自然，才加入第三条。",
    }


def _materials_text(materials: dict[str, Any]) -> str:
    ending = str(materials.get("ending_reference") or "").strip()
    ending_block = f"\n收束参考：{ending}" if ending else ""
    item_directions = materials.get("material_items")
    direction_block = ""
    if isinstance(item_directions, dict):
        compact: dict[str, list[dict[str, str]]] = {}
        for group, items in item_directions.items():
            if not isinstance(items, list):
                continue
            compact[str(group)] = [
                {
                    "id": str(item.get("id") or ""),
                    "text": str(item.get("text") or "").strip(),
                    "priority": str(item.get("priority") or ""),
                    "treatment": str(item.get("treatment") or "rewrite"),
                }
                for item in items
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
        if any(compact.values()):
            direction_block = (
                "\n素材表达边界指令（每条素材的 treatment 决定使用方式）\n"
                "- verbatim(原句)：逐字保留原句，不做任何改写\n"
                "- rewrite(改写·默认)：基于原句内容，按照创作者个人DNA蒸馏风格进行重新描述\n"
                "- elaborate(阐释)：原句 + 基于个人风格的解释性表达和扩展\n"
            ) + json.dumps(compact, ensure_ascii=False)

    generation_mode = str(materials.get("generation_mode") or "default").strip()
    mode_instruction = (
        "\n叙事模式：" + _narrative_mode_instruction(generation_mode)
        if generation_mode != "default"
        else ""
    )
    return f"""
主题：{str(materials.get("theme") or "").strip()}
核心洞察原始素材（只提取立场、矛盾和问题，禁止把原句或论证顺序直接写入正文）：{str(materials.get("insight") or "").strip()}
开场参考（只保留明确金句和事实，禁止整段照抄）：{str(materials.get("opening") or "").strip()}
日常素材事实（可保留必要事实锚点，但要改写段落关系）：{str(materials.get("daily") or "").strip()}
核心事件事实（只允许使用这里明确出现的具体事实）：{str(materials.get("event") or "").strip()}
必须保留的真实对话/金句：{str(materials.get("quotes") or "").strip()}{ending_block}{mode_instruction}{direction_block}
""".strip()

def _forbidden_source_fragments(materials: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    for key in ("insight",):
        value = str(materials.get(key) or "")
        for fragment in re.split(r"[，,。！？；;\n]+", value):
            clean = re.sub(r"\s+", "", fragment).strip()
            if 8 <= len(clean) <= 42:
                fragments.append(clean)
            elif len(clean) > 42:
                fragments.append(clean[:42])
    return list(dict.fromkeys(fragments))[:18]


def _require_materials(materials: dict[str, Any]) -> None:
    if not str(materials.get("theme") or "").strip():
        raise SkillExecutionError("MATERIAL_THEME_MISSING", "请先填写创作主题")
    if not str(materials.get("insight") or "").strip():
        raise SkillExecutionError("MATERIAL_INSIGHT_MISSING", "请先填写核心洞察")
    if not any(
        str(materials.get(key) or "").strip()
        for key in ("daily", "event")
    ):
        raise SkillExecutionError("MATERIAL_FACTS_MISSING", "日常素材和核心事件至少填写一项")


def _trace_item(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": result.get("run_id"),
        "skill": result.get("skill"),
        "version": result.get("version"),
        "model": result.get("model"),
        "latency_ms": result.get("latency_ms"),
    }


def _edit_result_data(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    if not isinstance(data, dict):
        raise SkillExecutionError("EDIT_SCHEMA_INVALID", "编辑 Skill 未返回 JSON 对象")
    return data


def _clean_edit_changes(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    changes: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        point = str(item.get("point") or "").strip()
        location = str(item.get("location") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if point and location and reason:
            changes.append({"point": point, "location": location, "reason": reason})
    return changes[:6]


def _edit_signature(value: str) -> str:
    return re.sub(
        r"[\s，。！？；：、、“”‘’「」『』（）()【】\[\]《》〈〉…—\-.,!?;:'\"]+",
        "",
        str(value or "").lower(),
    )


def _edit_difference(source: str, candidate: str, action_id: str) -> dict[str, Any]:
    source_signature = _edit_signature(source)
    candidate_signature = _edit_signature(candidate)
    similarity = SequenceMatcher(None, source_signature, candidate_signature).ratio()
    changed_ratio = round(1 - similarity, 4)
    minimum_ratio = {
        "shorten": 0.025,
        "selection-polish": 0.018,
    }.get(action_id, 0.02)
    meaningful = bool(source_signature and candidate_signature and source_signature != candidate_signature)
    if len(source_signature) >= 24:
        meaningful = meaningful and (
            changed_ratio >= minimum_ratio
            or abs(len(candidate_signature) - len(source_signature)) >= max(4, int(len(source_signature) * 0.03))
        )
    if action_id == "selection-polish" and len(source_signature) >= 24:
        meaningful = meaningful and changed_ratio >= 0.1
    if action_id == "shorten" and source_signature:
        retained_ratio = len(candidate_signature) / len(source_signature)
        meaningful = meaningful and 0.55 <= retained_ratio <= 0.75
    return {
        "meaningful": meaningful,
        "source_chars": len(source_signature),
        "candidate_chars": len(candidate_signature),
        "changed_ratio": changed_ratio,
    }


def _is_character_subsequence(candidate: str, source: str) -> bool:
    if not candidate:
        return False
    source_iter = iter(source)
    return all(any(source_char == candidate_char for source_char in source_iter) for candidate_char in candidate)


def _paragraph_rewrite_difference(source: str, candidate: str) -> dict[str, Any]:
    source_signature = _edit_signature(source)
    candidate_signature = _edit_signature(candidate)
    similarity = SequenceMatcher(None, source_signature, candidate_signature).ratio()
    changed_ratio = round(1 - similarity, 4)
    deleted_only = bool(
        source_signature
        and candidate_signature
        and len(candidate_signature) < len(source_signature)
        and _is_character_subsequence(candidate_signature, source_signature)
    )
    minimum_ratio = 0.12 if len(source_signature) >= 28 else 0.18
    changed_chars = round(max(len(source_signature), len(candidate_signature)) * changed_ratio)
    meaningful = bool(
        source_signature
        and candidate_signature
        and source_signature != candidate_signature
        and changed_ratio >= minimum_ratio
        and changed_chars >= min(8, max(4, len(source_signature) // 8))
        and not deleted_only
    )
    return {
        "meaningful": meaningful,
        "source_chars": len(source_signature),
        "candidate_chars": len(candidate_signature),
        "changed_ratio": changed_ratio,
        "changed_chars": changed_chars,
        "deleted_only": deleted_only,
    }


def _opening_options_are_distinct(
    options: list[dict[str, Any]],
    original_opening: str,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    original_signature = _edit_signature(original_opening)
    for option in options:
        signature = _edit_signature(str(option.get("text") or ""))
        if not signature:
            continue
        if original_signature and SequenceMatcher(None, original_signature, signature).ratio() >= 0.88:
            continue
        if any(SequenceMatcher(None, _edit_signature(str(item.get("text") or "")), signature).ratio() >= 0.84 for item in kept):
            continue
        kept.append(option)
    return kept


def _numbered_paragraphs(value: str) -> str:
    blocks = [block.strip() for block in re.split(r"\n{2,}", value) if block.strip()]
    return "\n\n".join(f"[{index}] {block}" for index, block in enumerate(blocks, start=1))


def _apply_paragraph_replacements(
    full_copy: str,
    raw_replacements: Any,
    locked_paragraphs: list[str],
    action_id: str = "more-personal",
) -> tuple[
    str,
    list[dict[str, str]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    if not isinstance(raw_replacements, list):
        return "", [], [], [], [{"reason": "replacements 不是数组"}]
    blocks = [block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()]
    changes: list[dict[str, str]] = []
    patch_metrics: list[dict[str, Any]] = []
    patch_pairs: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    used_indexes: set[int] = set()
    for item in raw_replacements:
        if not isinstance(item, dict):
            rejected.append({"reason": "补丁不是对象"})
            continue
        try:
            index = int(item.get("paragraph_index")) - 1
        except (TypeError, ValueError):
            rejected.append({"reason": "段落编号无效"})
            continue
        if index < 0 or index >= len(blocks) or index in used_indexes:
            rejected.append({"paragraph_index": index + 1, "reason": "段落编号越界或重复"})
            continue
        original = blocks[index]
        replacement = str(item.get("text") or "").strip()
        if not replacement:
            rejected.append({"paragraph_index": index + 1, "reason": "替换文本为空"})
            continue
        if any(locked == original or locked in original for locked in locked_paragraphs):
            rejected.append({"paragraph_index": index + 1, "reason": "目标段落已锁定"})
            continue
        point = str(item.get("point") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not point or not reason:
            rejected.append({"paragraph_index": index + 1, "reason": "缺少核心优化点或修改原因"})
            continue
        difference = (
            _edit_difference(original, replacement, "shorten")
            if action_id == "shorten"
            else _paragraph_rewrite_difference(original, replacement)
        )
        if not difference["meaningful"]:
            rejected.append(
                {
                    "paragraph_index": index + 1,
                    "reason": (
                        "收束后段落没有压缩到原长度的 55%-75%，或没有真正删除重复解释"
                        if action_id == "shorten"
                        else "只做了删词、短语缩写或轻微同义替换，未改变句子骨架与思考推进"
                    ),
                    "metrics": difference,
                }
            )
            continue
        blocks[index] = replacement
        used_indexes.add(index)
        patch_metrics.append({"paragraph_index": index + 1, **difference})
        patch_pairs.append(
            {
                "paragraph_index": index + 1,
                "original": original,
                "edited": replacement,
            }
        )
        changes.append(
            {
                "point": point,
                "location": str(item.get("location") or f"第 {index + 1} 段").strip(),
                "reason": reason,
            }
        )
    return "\n\n".join(blocks), changes, patch_metrics, patch_pairs, rejected


def _audit_paragraph_replacements(
    replacements: list[dict[str, Any]],
    materials: dict[str, Any],
    source_copy: str,
    draft: str,
    edit_action: str = "more-personal",
) -> dict[str, Any]:
    protected_lines = [
        line
        for line in _protected_material_lines(materials)
        if line in source_copy
    ]
    edit_quality_rule = (
        "收束允许直接删除完整的重复句、同义罗列和多余解释，不要求重建句法；"
        "若确实删除了完整信息单元且保留事实与段落作用，only_word_or_connector_edits=false、passed=true。"
        "若只是删几个词、缩写短语或替换连接词，only_word_or_connector_edits=true、passed=false。"
        if edit_action == "shorten"
        else
        "只删词、缩写短语、替换连接词或保留原句骨架，"
        "structural_change=false、only_word_or_connector_edits=true、passed=false。"
    )
    result = run_json(
        "audit-vlog-copy",
        f"""
只审校下面三组“原段 -> 新段”，不要复查全文中没有变化的旧内容。你的唯一任务是找出本次编辑新增的具体声明，并判断是否有逐字证据。

项目素材：
{_materials_text(materials)}

逐段替换对照：
{json.dumps(replacements, ensure_ascii=False)[:12000]}

必须逐字保留的表达：
{json.dumps(protected_lines, ensure_ascii=False)}

输出 JSON：
{{
  "passed": true,
  "assessment": "对三组补丁的简短总评",
  "items": [
    {{
      "paragraph_index": 3,
      "structural_change": true,
      "only_word_or_connector_edits": false,
      "new_claim_checks": [
        {{"phrase": "新稿新增的最小完整短语", "category": "action|scene|time|quantity|person|motive|causality|mental_state", "source_evidence": "原段或素材中的逐字证据", "supported": true}}
      ],
      "unsupported_interpretations": [],
      "passed": true
    }}
  ]
}}

逐字差异核验规则：
1. 对每组 edited 减去 original，扫描所有新增的具体动作、场景、路线、时间、数量、人物属性、事件结果和具体对话；每一项都必须进入 new_claim_checks，不能因为自然合理而省略。
2. 具体声明必须有原段或项目素材中的逐字证据。语义相近只能支撑抽象判断，不能支撑新增动作、动机或场景。
3. 例如原文只有“见了网友”，新增“聊完往回走”属于 action 且无证据；原文只有“他比我小”，新增“比我小几岁”属于 quantity 且无证据。
4. “于是”把两个并列事件改成因果，“我想主动去够一够”若让原文没有的行动发生，“我躺在黑暗里”新增场景，“这句话我写下来的时候”新增写作动作；素材没有逐字支撑时都必须 supported=false、passed=false。
5. 不带新经历的抽象比喻、犹豫、自问和对已有事件的价值判断可以作为风格化解释通过，但不得偷偷补出新的动作、时间、场景或结果。
6. {edit_quality_rule}
7. 任一 new_claim_checks.supported=false，或改动了必须逐字保留的表达，该段和总结果都必须 passed=false；不要进行宽松解释。
8. items 必须与输入段落逐项对应。只输出 JSON。
""".strip(),
        max_tokens=2200,
        temperature=0.02,
    )
    data = result["data"]
    items = data.get("items")
    expected_indexes = {int(item["paragraph_index"]) for item in replacements}
    passed_indexes: set[int] = set()
    unsupported_claims: list[dict[str, Any]] = []
    normalized_items: list[dict[str, Any]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                paragraph_index = int(item.get("paragraph_index"))
            except (TypeError, ValueError):
                continue
            checks = item.get("new_claim_checks")
            checks_valid = isinstance(checks, list) and all(isinstance(claim, dict) for claim in checks)
            unsupported = [
                claim
                for claim in (checks if isinstance(checks, list) else [])
                if not bool(claim.get("supported"))
                or not str(claim.get("source_evidence") or "").strip()
            ]
            unsupported_interpretations = item.get("unsupported_interpretations")
            structural_change = bool(item.get("structural_change"))
            only_word_or_connector_edits = item.get("only_word_or_connector_edits") is True
            action_quality_passed = (
                not only_word_or_connector_edits
                if edit_action == "shorten"
                else structural_change and item.get("only_word_or_connector_edits") is False
            )
            item_passed = bool(
                checks_valid
                and not unsupported
                and isinstance(unsupported_interpretations, list)
                and not unsupported_interpretations
                and bool(item.get("passed"))
                and action_quality_passed
            )
            if item_passed:
                passed_indexes.add(paragraph_index)
            unsupported_claims.extend(
                {"paragraph_index": paragraph_index, **claim}
                for claim in unsupported
                if isinstance(claim, dict)
            )
            normalized_items.append({**item, "paragraph_index": paragraph_index, "passed": item_passed})

    missing_protected = [line for line in protected_lines if line not in draft]
    passed = bool(
        expected_indexes == passed_indexes
        and not unsupported_claims
        and not missing_protected
    )
    audit_data = {
        "passed": passed,
        "critical_issues": [f"改动了必须逐字保留的表达：{line}" for line in missing_protected],
        "unsupported_claims": unsupported_claims,
        "claim_checks": [],
        "interpretive_checks": [],
        "edit_check": {
            "goal_passed": expected_indexes == passed_indexes,
            "meaningful_change": expected_indexes == passed_indexes,
            "assessment": str(data.get("assessment") or "").strip(),
            "changes": [],
            "patch_checks": normalized_items,
        },
        "style_issues": [],
        "revision_instructions": [],
        "scores": {},
    }
    return {**result, "data": audit_data, "passed": passed}


def _audit_copy(
    draft: str,
    materials: dict[str, Any],
    *,
    source_copy: str = "",
    citations: list[dict[str, Any]] | None = None,
    edit_action: str = "",
    edit_source: str = "",
    edit_replacements: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if edit_replacements:
        return _audit_paragraph_replacements(
            edit_replacements,
            materials,
            source_copy,
            draft,
            edit_action,
        )
    citation_text = json.dumps(citations or [], ensure_ascii=False)
    edit_check_block = ""
    edit_output_field = ""
    replacement_pairs = edit_replacements or []
    protected_edit_lines = [
        line
        for line in _protected_material_lines(materials)
        if source_copy and line in source_copy
    ]
    if edit_action:
        edit_check_block = f"""
编辑动作审校：
动作：{edit_action}
编辑前目标文本：
{edit_source[:7000]}

请额外判断：新稿是否真正完成了该动作，是否发生了实质性的非标点变化，是否保留了作者的个人思考过程，而不是只做同义词替换。

逐段替换对照（若为空则不是段落补丁模式）：
{json.dumps(replacement_pairs, ensure_ascii=False)[:10000]}
""".strip()
        edit_output_field = """
  "edit_check": {
    "goal_passed": true,
    "meaningful_change": true,
    "assessment": "具体说明动作是否完成",
    "changes": [
      {"point": "核心优化点", "location": "优化位置", "reason": "修改原因"}
    ],
    "patch_checks": [
      {
        "paragraph_index": 3,
        "structural_change": true,
        "only_word_or_connector_edits": false,
        "new_claim_checks": [
          {"claim": "新增加的具体动作、时间、数量、动机或心理状态", "source_evidence": "素材或原文中的逐字证据", "supported": true}
        ],
        "unsupported_interpretations": [],
        "passed": true
      }
    ]
  },"""
    result = run_json(
        "audit-vlog-copy",
        f"""
以事实检察官的标准审校下面的匣中镜 Vlog 文案。严格核对事实，不要自行改写。

项目素材：
{_materials_text(materials)}

编辑前原文（若为空则表示初稿）：
{source_copy[:8000]}

允许使用的书库引文证据：
{citation_text[:10000]}

待审校文案：
{draft[:10000]}

{edit_check_block}

输出 JSON：
{{
  "passed": true,
  "critical_issues": [],
  "unsupported_claims": [],
  "claim_checks": [
    {{"claim": "文案中的具体声明", "source_evidence": "项目素材中的逐字证据", "supported": true}}
  ],
  "interpretive_checks": [
    {{"claim": "文案中的抽象判断或风格化连接句", "support": "主题/洞察/上下文支撑", "acceptable": true}}
  ],
{edit_output_field}
  "style_issues": [],
  "revision_instructions": [],
  "scores": {{
    "authenticity": 0,
    "personal_style": 0,
    "structure": 0,
    "platform_fit": 0
  }}
}}

核验规则：
1. 只把具体事实放入 claim_checks：地点、人物关系、动作、事件进度、结果、明确时间、对话、可被验证的心理经历和书籍引文。
2. 每条具体事实都必须给出项目素材、编辑前原文或引文证据中的 source_evidence；可允许同义改写，但证据必须能清楚支撑该事实。
3. “坐在工位前”“改到卡壳”“翻出存下来的东西”“夜色很安静”“锅铲声”等素材未提供的具体画面，属于新增事实。
4. 抽象反思、风格化连接句、隐喻和价值判断放入 interpretive_checks。只要能由主题、核心洞察、开场参考或上下文事实支撑，不要写入 unsupported_claims。
5. 抽象反思一旦夹带未提供的具体经历、具体时间、具体地点、具体动作、具体结果或具体对话，就把夹带部分列为 unsupported_claims。
6. 找不到证据的具体事实将 supported 设为 false，并同时写入 unsupported_claims；只要存在 unsupported_claims，passed 必须为 false。
7. 如果待审校文案中的句子已经在“编辑前原文”中逐字出现，可直接用编辑前原文作为 source_evidence，不要重复要求项目素材证明。
8. 引文原句、书名和出处可由“允许使用的书库引文证据”证明；围绕引文的抽象感受可以由上下文洞察支持，但不得新增具体经历。
9. claim_checks 最多返回 20 条，每条 source_evidence 控制在 80 字以内；不要因为抽象句没有逐字证据而否决整稿。
10. “是为了……”“我其实想……”“我早就知道……”等新增动机、目的、持续时间和心理状态，不是普通抽象连接句；若项目素材和编辑前原文没有明确支撑，必须列入 unsupported_claims。
11. 如果提供了逐段替换对照，patch_checks 必须逐项返回。逐字比较 original 与 edited，把 edited 新增的动作、地点、时间、数量、人物属性、动机、因果和心理状态逐项写进 new_claim_checks。比如原文没有“聊完往回走”“比我小几岁”，即使素材有“见网友”“比我小”，新增说法仍然 supported=false。
12. 只删词、缩写短语、替换连接词或保留原句骨架的补丁，structural_change=false、passed=false；new_claim_checks 中任一项无逐字证据，或存在新增无证据解释，都写入 unsupported_interpretations 并设 passed=false。不要把“自然合理”当作事实证据。
只输出 JSON。
""".strip(),
        max_tokens=3600,
        temperature=0.05,
    )
    data = result["data"]
    critical = data.get("critical_issues")
    unsupported = data.get("unsupported_claims")
    claim_checks = data.get("claim_checks")
    if (
        not isinstance(critical, list)
        or not isinstance(unsupported, list)
        or not isinstance(claim_checks, list)
    ):
        raise SkillExecutionError("AUDIT_SCHEMA_INVALID", "审校 Skill 返回结构不完整")
    unsupported_checks = [
        item
        for item in claim_checks
        if isinstance(item, dict) and not bool(item.get("supported"))
    ]
    passed = (
        bool(data.get("passed"))
        and not critical
        and not unsupported
        and not unsupported_checks
    )
    missing_protected = [line for line in protected_edit_lines if line not in draft]
    if missing_protected:
        critical.extend(f"改动了必须逐字保留的表达：{line}" for line in missing_protected)
        data["critical_issues"] = critical
        passed = False
    if edit_action:
        edit_check = data.get("edit_check")
        edit_changes = _clean_edit_changes(edit_check.get("changes") if isinstance(edit_check, dict) else None)
        if not isinstance(edit_check, dict):
            raise SkillExecutionError("AUDIT_SCHEMA_INVALID", "编辑审校未返回 edit_check")
        edit_check["changes"] = edit_changes
        edit_check["goal_passed"] = bool(edit_check.get("goal_passed"))
        edit_check["meaningful_change"] = bool(edit_check.get("meaningful_change"))
        passed = passed and edit_check["goal_passed"] and edit_check["meaningful_change"] and bool(edit_changes)
        if replacement_pairs:
            patch_checks = edit_check.get("patch_checks")
            expected_indexes = {int(item["paragraph_index"]) for item in replacement_pairs}
            passed_indexes: set[int] = set()
            if isinstance(patch_checks, list):
                for item in patch_checks:
                    if not isinstance(item, dict):
                        continue
                    try:
                        paragraph_index = int(item.get("paragraph_index"))
                    except (TypeError, ValueError):
                        continue
                    unsupported_interpretations = item.get("unsupported_interpretations")
                    new_claim_checks = item.get("new_claim_checks")
                    new_claims_supported = isinstance(new_claim_checks, list) and all(
                        isinstance(claim, dict)
                        and bool(claim.get("supported"))
                        and bool(str(claim.get("source_evidence") or "").strip())
                        for claim in new_claim_checks
                    )
                    if (
                        bool(item.get("passed"))
                        and bool(item.get("structural_change"))
                        and item.get("only_word_or_connector_edits") is False
                        and new_claims_supported
                        and isinstance(unsupported_interpretations, list)
                        and not unsupported_interpretations
                    ):
                        passed_indexes.add(paragraph_index)
            passed = passed and expected_indexes == passed_indexes
    return {**result, "passed": passed}



def _normalize_for_overlap(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]", "", str(value).lower())


def _material_lines(materials: dict[str, Any]) -> list[str]:
    return [entry["text"] for entry in _material_entries(materials)]


def _material_entries(materials: dict[str, Any]) -> list[dict[str, str]]:
    lines: list[dict[str, str]] = []
    for key in ("insight", "opening", "daily", "event", "ending_reference"):
        value = str(materials.get(key) or "")
        for line in re.split(r"\n+|(?<=[。！？])", value):
            clean = re.sub(r"^\s*(?:\d+|[一二三四五六七八九十]+)[\.、）)]\s*", "", line).strip()
            if clean:
                lines.append({"group": key, "text": clean})
    return lines


def _protected_material_lines(
    materials: dict[str, Any],
    architecture: dict[str, Any] | None = None,
) -> list[str]:
    protected: list[str] = []
    for key in ("quotes", "opening"):
        for line in re.split(r"\n+", str(materials.get(key) or "")):
            clean = re.sub(r"^\s*(?:\d+|[一二三四五六七八九十]+)[\.、）)]\s*", "", line).strip()
            if clean:
                protected.append(clean)
    planned = (architecture or {}).get("protected_lines") or []
    if isinstance(planned, list):
        protected.extend(str(line).strip() for line in planned if str(line).strip())
    return list(dict.fromkeys(protected))


def _writing_overlap_metrics(
    draft: str,
    materials: dict[str, Any],
    protected_lines: list[str] | None = None,
    ngram_size: int = 8,
) -> dict[str, Any]:
    protected = [_normalize_for_overlap(line) for line in (protected_lines or [])]
    source_entries = _material_entries(materials)
    unprotected_entries = [
        entry for entry in source_entries
        if not any(token and token in _normalize_for_overlap(entry["text"]) for token in protected)
    ]
    unprotected_lines = [entry["text"] for entry in unprotected_entries]
    source = _normalize_for_overlap("".join(unprotected_lines))
    blocking_lines = [
        entry["text"] for entry in unprotected_entries
        if entry["group"] in {"insight", "opening", "ending_reference"}
    ]
    blocking_source = _normalize_for_overlap("".join(blocking_lines))
    output = _normalize_for_overlap(draft)
    for token in protected:
        if token:
            source = source.replace(token, "")
            blocking_source = blocking_source.replace(token, "")
            output = output.replace(token, "")

    def grams(value: str) -> set[str]:
        if len(value) < ngram_size:
            return {value} if value else set()
        return {value[index:index + ngram_size] for index in range(len(value) - ngram_size + 1)}

    source_grams = grams(source)
    blocking_source_grams = grams(blocking_source)
    output_grams = grams(output)
    overlap = source_grams & output_grams
    blocking_overlap = blocking_source_grams & output_grams
    reuse_ratio = len(overlap) / max(1, len(output_grams))
    blocking_reuse_ratio = len(blocking_overlap) / max(1, len(output_grams))
    exact_entries = [
        entry for entry in unprotected_entries
        if len(_normalize_for_overlap(entry["text"])) >= 12
        and _normalize_for_overlap(entry["text"]) in output
    ]
    exact_lines = [entry["text"] for entry in exact_entries]

    near_fragments: list[dict[str, str | int]] = []
    seen_fragments: set[str] = set()
    for entry in unprotected_entries:
        line = entry["text"]
        group = entry["group"]
        normalized_line = _normalize_for_overlap(line)
        if len(normalized_line) < 24:
            continue
        line_grams = {
            normalized_line[index:index + 6]
            for index in range(max(1, len(normalized_line) - 5))
        }
        output_line_grams = {
            output[index:index + 6]
            for index in range(max(1, len(output) - 5))
        }
        line_reuse_ratio = (
            len(line_grams & output_line_grams) / max(1, len(line_grams))
        )
        if line_reuse_ratio >= 0.35:
            skeleton_key = f"skeleton:{normalized_line[:40]}"
            if skeleton_key not in seen_fragments:
                seen_fragments.add(skeleton_key)
                near_fragments.append(
                    {
                        "group": group,
                        "source_line": line[:120],
                        "reused_fragment": normalized_line[:80],
                        "length": len(normalized_line),
                        "source_reuse_ratio": round(line_reuse_ratio, 3),
                    }
                )
        matcher = SequenceMatcher(None, normalized_line, output, autojunk=False)
        for block in matcher.get_matching_blocks():
            if block.size < 18:
                continue
            fragment = normalized_line[block.a:block.a + block.size]
            if any(token and fragment in token for token in protected):
                continue
            if fragment in seen_fragments:
                continue
            seen_fragments.add(fragment)
            near_fragments.append(
                {
                    "group": group,
                    "source_line": line[:120],
                    "reused_fragment": fragment[:80],
                    "length": block.size,
                }
            )

    max_material_reuse = 0.34
    blocking_near_fragments = [
        fragment for fragment in near_fragments
        if str(fragment.get("group") or "") in {"insight", "opening", "ending_reference"}
    ]
    blocking_exact_lines = [
        entry["text"] for entry in exact_entries
        if entry["group"] in {"insight", "opening", "ending_reference"}
    ]
    near_fragment_limit = 0
    exact_line_tolerated = not blocking_exact_lines
    near_fragment_tolerated = len(blocking_near_fragments) <= near_fragment_limit
    return {
        "material_reuse_ratio": round(reuse_ratio, 3),
        "blocking_material_reuse_ratio": round(blocking_reuse_ratio, 3),
        "new_expression_ratio": round(1 - reuse_ratio, 3),
        "exact_reused_lines": exact_lines[:12],
        "blocking_exact_reused_lines": blocking_exact_lines[:12],
        "near_reused_fragments": near_fragments[:12],
        "blocking_near_reused_fragments": blocking_near_fragments[:12],
        "threshold": max_material_reuse,
        "exact_line_limit": 0,
        "near_fragment_limit": near_fragment_limit,
        "passed": (
            blocking_reuse_ratio <= max_material_reuse
            and (not blocking_exact_lines or exact_line_tolerated)
            and near_fragment_tolerated
        ),
    }


def _audit_writing_quality(
    draft: str,
    materials: dict[str, Any],
    architecture: dict[str, Any],
    overlap: dict[str, Any],
    source_copy: str = "",
) -> dict[str, Any]:
    result = run_json(
        "audit-writing-quality",
        f"""按严格的 0-10 分制审校这篇匣中镜 Vlog 文案，不要改写正文。

项目素材：
{_materials_text(materials)}

改写前原稿（新写模式为空；改写模式下，原稿中的既有事实可作为证据）：
{source_copy[:10000]}

叙事架构：
{json.dumps(architecture, ensure_ascii=False)[:12000]}

程序检测到的素材表达重合：
{json.dumps(overlap, ensure_ascii=False)}

待审校文案：
{draft[:12000]}

输出 JSON：
{{
  "passed": true,
  "scores": {{
    "personal_style": 0,
    "narrative_arc": 0,
    "expansion_quality": 0,
    "authenticity": 0,
    "platform_fit": 0
  }},
  "unsupported_claims": [],
  "copied_expressions": [],
  "source_stickiness": [],
  "explanation_density": [],
  "attribution_risks": [],
  "blocking_style_issues": [],
  "material_coverage": [
    {{"id": "素材使用指令中的id", "group": "opening|insight|daily|event|quotes|ending_reference", "status": "linked|unused|conflicted", "draft_evidence": "文案中的最短对应表达"}}
  ],
  "style_issues": [],
  "strengths": [],
  "revision_instructions": []
}}

核验要求：
1. 所有分数必须是 0-10，不得使用百分制。
2. 逐条核对素材中的具体事实；不得把素材外地点、动作、对话、结果、感官画面或心理经历当作合理扩写。
3. material_coverage 必须覆盖“素材使用指令”中的每一条非空素材；linked 表示已经使用或经过明显发展后使用，unused 表示未进入正文，conflicted 表示与正文冲突。不要因为素材被风格化改写就判为未使用。每条只保留最短的 draft_evidence，不要复述原文。
4. copied_expressions 不只检查逐字照抄，也要检查“保留原素材句子骨架的轻度同义改写”；程序检测到的 blocking_exact_reused_lines 和 blocking_near_reused_fragments 必须视为硬问题，写入 copied_expressions 或 source_stickiness。near_reused_fragments 中的日常/事件事实锚点只作为风险提示，不因保留事实本身扣分；如果整段仍像素材清单，再写入 source_stickiness。受保护金句、日期、开场句和 quotes 组中的原句不因逐字保留而判为 copied_expressions。
5. 如果洞察段直接复述素材观点，没有重新组织为口语化的自我追问、转念或现场判断，source_stickiness 必须写明问题，expansion_quality 不得高于 7。
6. 如果正文连续使用“不是……而是……”“这意味着”“本质上”“恰恰是”“说明你已经”等解释性句式，却没有前置具体动作、对话或画面支撑，写入 explanation_density，personal_style 不得高于 7.2。
7. 素材没有明确说话人、来源或因果关系时，不得给句子擅自归因；发现后写入 attribution_risks，authenticity 不得高于 7。
8. 结尾前 2 段不得追加大段总结性定义；如果把开放式姿态解释成结论，写入 blocking_style_issues。不要把受保护结尾金句本身列为 blocking_style_issues，只有围绕金句追加的解释性总结才算问题。
9. 每项达到 7.5、没有素材外具体事实、没有未保护的长句照抄或近似粘连、没有擅自归因、结尾不是口号或祝福时才可 passed=true。
只输出 JSON。
""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=2600,
        temperature=0.08,
    )
    data = result["data"]
    scores = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    required = ("personal_style", "narrative_arc", "expansion_quality", "authenticity", "platform_fit")
    normalized_scores: dict[str, float] = {}
    for key in required:
        try:
            normalized_scores[key] = max(0.0, min(10.0, float(scores.get(key, 0))))
        except (TypeError, ValueError):
            normalized_scores[key] = 0.0
    unsupported = data.get("unsupported_claims") if isinstance(data.get("unsupported_claims"), list) else []
    copied = data.get("copied_expressions") if isinstance(data.get("copied_expressions"), list) else []
    sticky = data.get("source_stickiness") if isinstance(data.get("source_stickiness"), list) else []
    attribution_risks = data.get("attribution_risks") if isinstance(data.get("attribution_risks"), list) else []
    blocking_style = data.get("blocking_style_issues") if isinstance(data.get("blocking_style_issues"), list) else []
    coverage = data.get("material_coverage")
    if not isinstance(coverage, list):
        raise SkillExecutionError("AUDIT_SCHEMA_INVALID", "综合审校未返回素材覆盖结果")
    passed = (
        bool(data.get("passed"))
        and all(score >= 7.5 for score in normalized_scores.values())
        and not unsupported
        and not copied
        and not sticky
        and not attribution_risks
        and not blocking_style
        and bool(overlap.get("passed"))
    )
    data["scores"] = normalized_scores
    return {**result, "data": data, "passed": passed}


def _needs_insight_detox(quality: dict[str, Any], overlap: dict[str, Any]) -> bool:
    data = quality.get("data") if isinstance(quality.get("data"), dict) else {}
    sticky = data.get("source_stickiness") if isinstance(data.get("source_stickiness"), list) else []
    copied = data.get("copied_expressions") if isinstance(data.get("copied_expressions"), list) else []
    blocking_near = overlap.get("blocking_near_reused_fragments")
    return bool(blocking_near or sticky or copied)


def _repair_after_audit(
    draft: str,
    materials: dict[str, Any],
    audit: dict[str, Any],
    *,
    source_copy: str = "",
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    repair = run_text(
        "edit-vlog-copy",
        f"""
下面的文案没有通过事实审校。执行一次严格的事实净化，以删除为主。

项目素材：
{_materials_text(materials)}

编辑前原文（如有）：
{source_copy[:8000]}

待修正文案：
{draft[:10000]}

审校意见：
{json.dumps(audit.get("data", {}), ensure_ascii=False)}

执行规则：
1. 删除所有 unsupported_claims 及其衍生描述，不要用另一个想象细节替换。
2. 具体事实只允许使用项目素材里已经出现的信息，可以调整语序但不能扩写场景。
3. “南京的落日”只支持写“南京的落日”，不支持补充何时、何地、如何看到。
4. “和朋友小酌”不支持补写对话、酒品、地点或动作。
5. 抽象反思只能改写核心洞察、开场参考和必须保留的话；不要新增期待、失望、犹豫、笃定、害怕等素材没有的心理经历。
6. 转场只能使用“后来我想”“所以这一次”“说到底”这类中性连接，不要补写感官画面、环境描写、人物动作或具体时间。
7. 允许大幅缩短到 300-900 字；信息少就少写，禁止为了完整感补例子。
只输出修正后的完整文案正文。
        """.strip(),
        max_tokens=1800,
        temperature=0.04,
    )
    repaired = repair["text"].strip()
    second_audit = _audit_copy(repaired, materials, source_copy=source_copy)
    trace = [_trace_item(repair), _trace_item(second_audit)]
    if not second_audit["passed"]:
        unsupported = second_audit.get("data", {}).get("unsupported_claims", [])
        if isinstance(unsupported, list) and unsupported:
            raise SkillExecutionError(
                "DRAFT_AUDIT_FAILED",
                "文案生成后仍有未被素材支持的具体细节，已阻止覆盖正文",
                json.dumps(second_audit.get("data", {}), ensure_ascii=False),
            )
        raise SkillExecutionError(
            "QUALITY_GATE_FAILED",
            "文案经一次 DeepSeek 修正后仍未通过事实与质量审校",
            json.dumps(second_audit.get("data", {}), ensure_ascii=False),
        )
    return repaired, trace, second_audit

def _generate_legacy_sync(
    payload: dict[str, Any],
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """生成链路：叙事架构 -> 个人声音写作 -> 去素材腔 -> 事实与质量门。"""
    materials = payload.get("materials") or {}
    generation_mode = str(payload.get("generation_mode") or "fresh").strip()
    if generation_mode not in {"fresh", "rewrite"}:
        generation_mode = "fresh"
    source_copy = str(payload.get("source_copy") or "").strip() if generation_mode == "rewrite" else ""
    target_length_mode = str(payload.get("target_length_mode") or "auto").strip()
    target_length = int(float(payload.get("target_length") or 1200))
    locked_paragraphs = [
        str(item).strip()
        for item in (payload.get("locked_paragraphs") or [])
        if str(item).strip()
    ]
    _emit_progress(progress, "stage_started", "validate-materials")
    _require_materials(materials)
    _emit_progress(progress, "stage_finished", "validate-materials")
    style_version, style = writing_context(payload)
    trace: list[dict[str, Any]] = []
    materials_text = _materials_text(materials)
    forbidden_fragments = _forbidden_source_fragments(materials)
    old_draft_block = (
        f"\n当前稿件（只在改写模式下使用，必须重构而非润色）：\n{source_copy[:12000]}"
        if source_copy else ""
    )

    # ---- Stage 1: narrative architecture ----
    _emit_progress(progress, "stage_started", "architect-vlog-narrative")
    architecture = run_json(
        "architect-vlog-narrative",
        f"""将下面的项目素材转化为可执行的 Vlog 叙事架构，不写正文。

生成模式：{"基于当前稿重写" if source_copy else "从素材新写初稿"}

项目素材：
{materials_text}
{old_draft_block}

输出 JSON：
{{
  "central_tension": "贯穿全文的真实矛盾",
  "opening_move": "开头如何用事实或问题进入，不直接照抄素材",
  "emotional_arc": ["起点", "推进", "回落或转念", "此刻的姿态"],
  "arrangement_strategy": "为什么按这个意义顺序组织事件，而不是按素材顺序或时间顺序组织",
  "fact_ledger": ["只列素材中明确存在的具体事实"],
  "protected_lines": ["只列必须逐字保留的对话、日期、名字或用户原句"],
  "interpretive_ledger": ["允许展开的判断、关系和感受"],
  "paragraphs": [
    {{"role": "opening|evidence|deepening|turn|insight|callback|ending", "purpose": "本段任务", "facts": [], "interpretation": "允许展开什么", "transition": "与上下段的关系"}}
  ],
  "callback": "如何回到主题",
  "ending_move": "如何用已有意象或姿态收束"
}}

硬性要求：
1. 先做意义重排：每个事件必须承担“对照、递进、反证、转念、回扣”之一；不得按素材输入顺序或时间顺序平铺。
2. 每段必须回答“这一段让主题发生了什么变化”，不能只回答“这一段用了什么素材”。
3. 洞察段只能规划为 3-5 句的转念，不得承载素材原文中的长排比。
4. protected_lines 从真实对话、日期、名字和用户明确要保留的金句中提取；不要把开场参考、洞察原文和素材列表整段设为保护。
5. 对所有可能导致误解的归因做边界标记：素材未说明说话人时，只能写“我想到/我越想越觉得”，不得写“某人说”。
6. 规划 8-10 个有明确任务的段落，事件后必须有发展出来的理解，不做素材清单。
7. 每个字符串字段控制在 100 字以内，facts 每段最多 3 条，不重复解释同一事实。
8. 不得新增具体事实。只输出 JSON。
""".strip(),
        system_context=style,
        max_tokens=4200,
        temperature=0.28,
    )
    architecture_trace = _trace_item(architecture)
    trace.append(architecture_trace)
    _emit_progress(progress, "stage_finished", "architect-vlog-narrative", trace=architecture_trace)

    # ---- Stage 2: personal voice writing ----
    _emit_progress(progress, "stage_started", "write-personal-vlog")
    word_count_constraint = (
        f"必须控制在 {target_length} 字左右" if target_length_mode == "manual"
        else f"素材充足时写 {target_length}-{min(target_length+600,3000)} 中文字"
    )
    draft = run_text(
        "write-personal-vlog",
        f"""根据叙事架构和项目素材写一篇完整中文 Vlog 画外音文案。

生成模式：{"重构当前稿" if source_copy else "新写初稿"}

项目素材：
{materials_text}

叙事架构：
{json.dumps(architecture["data"], ensure_ascii=False)[:14000]}
{old_draft_block}

执行要求：
1. 素材是事实证据，不是可直接拼接的句子；除 protected_lines 外，必须改换句法、观察角度和段落关系。
2. 画面先于判断：抽象词如“回忆、成功、成长、人生、选择、支撑、滋养”不能被直接定义，必须先用动作、对话、校园日常或事件后果托住。
3. 禁止把洞察素材原文改成轻度同义句；长排比必须拆开重组为口语化的自我追问、转念和收束句。
4. 充分发展事件之间的对比、因果、情绪变化和自我追问。{word_count_constraint}
5. 至少一半篇幅是由事实发展出来的新表达，但不能新增具体事件、具体电影情节、具体对话、地点、天气或人物反应。
6. 只能扩写“关系、判断、转念、因果”，不能为了生活感补拍摄现场、灯光、屏幕、路上、楼下、手掌温度、酒后胡话、电影童年回忆等素材外具体画面。
7. 写“很多画面滋养我”时，只能使用素材给出的来源类别：自己的、朋友的、身边人的、陌生人的、名人自传、小说、电影；不得发明具体画面。
8. 前两段建立信息差或情绪张力；每 2-3 段有推进；中后段完成一次真转念；结尾前不要再做大段总结，直接落到已有意象或姿态。
9. 素材没有明确说话人时，不得擅自写成“某人说的”；只能写成“我后来想到/我越想越觉得/这句话留在我心里”。
10. 少用“恰恰是、本身就是、这意味着、不是退路而是积蓄、说明你已经”这类解释性判断；必须保留时，前后要有具体事实支撑。
11. 保留当前个人 DNA 定义的第一人称、长短句呼吸和思考方式，不写成励志演讲。
12. 输出前自检：删除所有素材里没有的具体感官、动作、地点、时间、人物反应和电影经历；删除所有保留素材骨架的洞察长句。
13. 只输出正文。
""".strip(),
        system_context=style,
        max_tokens=4200,
        temperature=0.66,
    )
    draft_trace = _trace_item(draft)
    trace.append(draft_trace)
    _emit_progress(progress, "stage_finished", "write-personal-vlog", trace=draft_trace)

    # ---- Stage 3: anti-copy authored rewrite ----
    protected_lines = _protected_material_lines(materials, architecture["data"])
    first_overlap = _writing_overlap_metrics(draft["text"], materials, protected_lines)
    _emit_progress(progress, "stage_started", "rewrite-material-expression")
    authored = run_text(
        "rewrite-material-expression",
        f"""把下面的初稿重写成真正被创作出来的文案，解决素材原句拼接、列表感和轻度同义改写。

项目事实素材：
{materials_text}

叙事架构：
{json.dumps(architecture["data"], ensure_ascii=False)[:12000]}

必须逐字保留的内容：
{json.dumps(protected_lines, ensure_ascii=False)}

初稿表达重合检测：
{json.dumps(first_overlap, ensure_ascii=False)}

待重写初稿：
{draft["text"][:14000]}

不要缩成摘要。保留全部重要事实和 {word_count_constraint} 的完整发展，通过新的句法、段落次序、事实关系、自我追问和回扣完成重写。重点处理三类问题：素材原文骨架粘连、抽象词被直接解释、素材未说明却被擅自归因。不得增加具体事实。只输出正文。
""".strip(),
        system_context=style,
        max_tokens=4400,
        temperature=0.58,
    )
    authored_trace = _trace_item(authored)
    trace.append(authored_trace)
    final_copy = authored["text"].strip()
    overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
    _emit_progress(
        progress,
        "stage_finished",
        "rewrite-material-expression",
        trace=authored_trace,
        passed=overlap["passed"],
        message="已重组素材表达并完成原创度检查。",
    )

    # ---- Stage 4: fact and writing quality gates ----
    _emit_progress(progress, "stage_started", "audit-vlog-copy")
    audit = _audit_copy(final_copy, materials, source_copy=source_copy)
    audit_trace = _trace_item(audit)
    trace.append(audit_trace)
    _emit_progress(
        progress, "stage_finished", "audit-vlog-copy",
        trace=audit_trace, audit=audit.get("data", {}), passed=audit["passed"]
    )

    _emit_progress(progress, "stage_started", "audit-writing-quality")
    quality = _audit_writing_quality(final_copy, materials, architecture["data"], overlap)
    quality_trace = _trace_item(quality)
    trace.append(quality_trace)
    _emit_progress(
        progress, "stage_finished", "audit-writing-quality",
        trace=quality_trace, audit=quality.get("data", {}), passed=quality["passed"]
    )

    if not audit["passed"] or not quality["passed"] or not overlap["passed"]:
        _emit_progress(
            progress,
            "stage_started",
            "rewrite-material-expression",
            message="质量门未通过，正在进行唯一一次 DeepSeek 定向重写。",
        )
        revision = run_text(
            "rewrite-material-expression",
            f"""下面的文案未通过最终质量门。严格按照审校意见进行一次完整定向重写。

项目素材：
{materials_text}

叙事架构：
{json.dumps(architecture["data"], ensure_ascii=False)[:12000]}

必须逐字保留：
{json.dumps(protected_lines, ensure_ascii=False)}

事实审校：
{json.dumps(audit.get("data", {}), ensure_ascii=False)[:8000]}

写作质量审校：
{json.dumps(quality.get("data", {}), ensure_ascii=False)[:8000]}

表达重合检测：
{json.dumps(overlap, ensure_ascii=False)}

待修正文案：
{final_copy[:14000]}

修正所有未支持事实、素材照抄、近似粘连、解释密度过高、展开不足、风格和结构问题。保留完整叙事体量，不得用删成摘要的方式过关；被指出的段落必须换掉句子骨架，不得只替换同义词；不得新增具体事实。只输出最终正文。
""".strip(),
            system_context=style,
            max_tokens=4400,
            temperature=0.46,
        )
        revision_trace = _trace_item(revision)
        trace.append(revision_trace)
        final_copy = revision["text"].strip()
        overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
        _emit_progress(
            progress, "stage_finished", "rewrite-material-expression",
            trace=revision_trace, passed=overlap["passed"],
            message="定向重写完成，正在复核。",
        )

        audit = _audit_copy(final_copy, materials, source_copy=source_copy)
        trace.append(_trace_item(audit))
        quality = _audit_writing_quality(final_copy, materials, architecture["data"], overlap)
        trace.append(_trace_item(quality))
        if not audit["passed"] or not quality["passed"] or not overlap["passed"]:
            _emit_progress(
                progress,
                "stage_started",
                "rewrite-material-expression",
                message="仍有少量具体问题，正在进行最后一次逐条复修。",
            )
            final_revision = run_text(
                "rewrite-material-expression",
                f"""这是发布前最后一次逐条复修。不要自由发挥，只修正列出的问题并输出完整正文。

项目素材：
{materials_text}

必须逐字保留：
{json.dumps(protected_lines, ensure_ascii=False)}

剩余事实问题：
{json.dumps(audit.get("data", {}).get("unsupported_claims", []), ensure_ascii=False)}
{json.dumps(quality.get("data", {}).get("unsupported_claims", []), ensure_ascii=False)}

剩余照抄表达：
{json.dumps(overlap.get("exact_reused_lines", []), ensure_ascii=False)}
{json.dumps(quality.get("data", {}).get("copied_expressions", []), ensure_ascii=False)}

剩余风格问题：
{json.dumps(quality.get("data", {}).get("style_issues", []), ensure_ascii=False)}

明确修正指令：
{json.dumps(quality.get("data", {}).get("revision_instructions", []), ensure_ascii=False)}

当前文案：
{final_copy[:15000]}

执行规则：逐条删除或改写被指出的句子；不要新增动作、环境、人物反应、对话或电影情节；不要改动未被指出的段落；不要缩成摘要。只输出完整正文。
""".strip(),
                system_context=style,
                max_tokens=4400,
                temperature=0.16,
            )
            final_revision_trace = _trace_item(final_revision)
            trace.append(final_revision_trace)
            final_copy = final_revision["text"].strip()
            overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
            _emit_progress(
                progress, "stage_finished", "rewrite-material-expression",
                trace=final_revision_trace, passed=overlap["passed"],
                message="最后复修完成，正在执行发布前双审校。",
            )
            audit = _audit_copy(final_copy, materials, source_copy=source_copy)
            trace.append(_trace_item(audit))
            quality = _audit_writing_quality(final_copy, materials, architecture["data"], overlap)
            trace.append(_trace_item(quality))
            if not audit["passed"] and quality["passed"] and overlap["passed"]:
                _emit_progress(
                    progress,
                    "stage_started",
                    "edit-vlog-copy",
                    message="写作质量已通过，正在删除最后的素材外具体画面。",
                )
                fact_cleanup = run_text(
                    "edit-vlog-copy",
                    f"""执行发布前事实净化。只处理被事实审校点名的短语，不得重写其他内容。

项目素材：
{materials_text}

必须逐字保留：
{json.dumps(protected_lines, ensure_ascii=False)}

事实审校点名的问题：
{json.dumps(audit.get("data", {}).get("unsupported_claims", []), ensure_ascii=False)}
{json.dumps(audit.get("data", {}).get("revision_instructions", []), ensure_ascii=False)}

当前完整文案：
{final_copy[:15000]}

执行规则：
1. 删除或改成素材中已有的中性说法，每个问题只改它所在的一句。
2. 其他句子逐字保持，不改变结构、体量、节奏和结尾。
3. 不新增任何动作、环境、人物反应、电影情节或心理经历。
4. 只输出净化后的完整正文，不输出解释或标签。
""".strip(),
                    system_context=style,
                    max_tokens=4400,
                    temperature=0.03,
                )
                fact_cleanup_trace = _trace_item(fact_cleanup)
                trace.append(fact_cleanup_trace)
                final_copy = fact_cleanup["text"].strip()
                overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
                audit = _audit_copy(final_copy, materials, source_copy=source_copy)
                trace.append(_trace_item(audit))
                _emit_progress(
                    progress,
                    "stage_finished",
                    "edit-vlog-copy",
                    trace=fact_cleanup_trace,
                    passed=audit["passed"],
                    message="事实净化完成，已复核具体事实。",
                )
            if not audit["passed"] or not quality["passed"] or not overlap["passed"]:
                details = {
                    "fact_audit": audit.get("data", {}),
                    "quality_audit": quality.get("data", {}),
                    "expression_metrics": overlap,
                    "next_action": "补充或调整素材后重新生成；当前稿不会覆盖编辑器。",
                }
                raise SkillExecutionError(
                    "QUALITY_GATE_FAILED",
                    "文案经限定次数的 DeepSeek 定向复修后仍未达到发布质量门",
                    json.dumps(details, ensure_ascii=False),
                )

    return {
        "copy": final_copy,
        "style_version": style_version,
        "generation_mode": generation_mode,
        "plan": architecture["data"],
        "audit": audit["data"],
        "style_audit": quality["data"],
        "expression_metrics": overlap,
        "trace": trace,
    }


def _generate_sync_legacy(
    payload: dict[str, Any],
    progress: ProgressCallback | None = None,
    generation_id: str = "",
) -> dict[str, Any]:
    """Historical generation chain kept for compatibility with old checkpoints."""
    materials = payload.get("materials") or {}
    generation_mode = str(payload.get("generation_mode") or "fresh").strip()
    if generation_mode not in {"fresh", "rewrite"}:
        generation_mode = "fresh"
    source_copy = str(payload.get("source_copy") or "").strip() if generation_mode == "rewrite" else ""
    available_books = _available_books()
    selected_book_ids = [
        str(book_id)
        for book_id in (payload.get("selected_books") or [])
        if str(book_id) in available_books
    ]
    book_support_mode = str(payload.get("book_support_mode") or "integrated").strip()
    locked_paragraphs = (
        [
            str(item).strip()
            for item in (payload.get("locked_paragraphs") or [])
            if str(item).strip()
        ]
        if generation_mode == "rewrite"
        else []
    )
    # Inject narrative_mode into materials for _materials_text
    narrative_mode = str(payload.get("narrative_mode") or "default").strip()
    if narrative_mode and narrative_mode != "default":
        if isinstance(materials, dict):
            materials = {**materials, "generation_mode": narrative_mode}

    _require_materials(materials)

    if not generation_id:
        generation_id = create_generation_job(payload)["generation_id"]
    job = get_generation_job(generation_id)
    if not job:
        raise SkillExecutionError("GENERATION_NOT_FOUND", "生成任务不存在")
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    input_fingerprint = _generation_input_fingerprint(payload)
    checkpoint_fingerprint = str(checkpoint.get("input_fingerprint") or "")
    if checkpoint and checkpoint_fingerprint != input_fingerprint:
        # Changed inputs cannot safely reuse text generated under the old contract.
        checkpoint = {"input_fingerprint": input_fingerprint}
        update_generation_job(generation_id, checkpoint=checkpoint)
    elif checkpoint_fingerprint != input_fingerprint:
        checkpoint["input_fingerprint"] = input_fingerprint
        update_generation_job(generation_id, checkpoint=checkpoint)
    trace = checkpoint.get("trace") if isinstance(checkpoint.get("trace"), list) else []
    resumed_stages: list[str] = []
    book_support_refresh_required = False
    if job.get("status") == "failed":
        update_generation_job(
            generation_id,
            status="running",
            failed_stage="",
            error={},
            increment_attempt=True,
        )
    else:
        update_generation_job(generation_id, status="running")

    style_version, style = writing_context(payload)
    materials_text = _materials_text(materials)
    forbidden_fragments = _forbidden_source_fragments(materials)
    old_draft_block = (
        f"\n当前稿件（仅作为改写事实边界，必须重构表达）：\n{source_copy[:12000]}"
        if source_copy else ""
    )
    current_stage = "architect-vlog-narrative"

    try:
        architecture_data = checkpoint.get("architecture")
        if isinstance(architecture_data, dict) and architecture_data:
            resumed_stages.append(current_stage)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                resumed=True,
                message="已恢复保存的叙事架构，不重复调用模型。",
            )
        else:
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(progress, "stage_started", current_stage)
            architecture = run_json(
                current_stage,
                f"""将项目素材转化为可执行的 Vlog 叙事架构，不写正文。

生成模式：{"基于当前稿重写" if source_copy else "从素材新写初稿"}

项目素材：
{materials_text}
{old_draft_block}

输出 JSON：
{{
  "central_tension": "贯穿全文的真实矛盾",
  "opening_move": "如何以事实或问题进入",
  "emotional_arc": ["起点", "推进", "转念", "此刻的姿态"],
  "arrangement_strategy": "为什么按这个意义顺序组织事件，而不是按素材顺序或时间顺序组织",
  "fact_ledger": ["素材明确存在的具体事实"],
  "protected_lines": ["必须逐字保留的对话、日期、名字或用户原句"],
  "interpretive_ledger": ["允许展开的判断、关系和感受"],
  "paragraphs": [
    {{"role": "opening|evidence|deepening|turn|insight|callback|ending", "purpose": "本段任务", "facts": [], "interpretation": "允许展开什么", "transition": "与上下段的关系"}}
  ],
  "callback": "如何回到主题",
  "ending_move": "如何用已有意象或姿态收束"
}}

硬性要求：
1. 先做意义重排：每个事件必须承担“对照、递进、反证、转念、回扣”之一；不得按素材输入顺序或时间顺序平铺。
2. 每段必须回答“这一段让主题发生了什么变化”，不能只回答“这一段用了什么素材”。
3. 洞察段只能规划为 3-5 句的转念，不得承载素材原文中的长排比。
4. protected_lines 只放真实对话、日期、名字和用户明确要保留的金句；不要把开场参考、洞察原文和素材列表整段设为保护。
5. 对所有可能导致误解的归因做边界标记：素材未说明说话人时，只能写“我想到/我越想越觉得”，不得写“某人说”。
6. 只规划 8-10 个段落；不得新增具体事实；只输出 JSON。""".strip(),
                system_context=style,
                max_tokens=3200,
                temperature=0.26,
            )
            architecture_data = architecture["data"]
            item = _trace_item(architecture)
            trace.append(item)
            checkpoint.update({"architecture": architecture_data, "trace": trace})
            update_generation_job(
                generation_id,
                current_stage=current_stage,
                checkpoint=checkpoint,
            )
            _emit_progress(progress, "stage_finished", current_stage, trace=item)

        current_stage = "write-personal-vlog"
        final_copy = str(checkpoint.get("draft") or "").strip()
        if final_copy:
            resumed_stages.append(current_stage)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                resumed=True,
                message="已恢复保存的风格化初稿，从综合审校继续。",
            )
        else:
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(progress, "stage_started", current_stage)
            draft = run_text(
                current_stage,
                f"""根据叙事架构和项目素材，写一篇完整中文 Vlog 画外音文案。

生成模式：{"重构当前稿" if source_copy else "新写初稿"}

项目素材：
{materials_text}

叙事架构：
{json.dumps(architecture_data, ensure_ascii=False)[:14000]}
{old_draft_block}

已锁定段落（改写模式下必须逐字保留且不得移动）：
{json.dumps(locked_paragraphs, ensure_ascii=False)}

洞察原文禁用片段（代表思路，不得作为成稿表达出现，也不得按原顺序轻度改写）：
{json.dumps(forbidden_fragments, ensure_ascii=False)}

执行要求：
1. 素材是事实证据，不是等待拼接的句子；除 protected_lines 外，改换句法、观察角度和段落关系。
2. 画面先于判断：抽象词如“回忆、成功、成长、人生、选择、支撑、滋养”不能被直接定义，必须先用动作、对话、校园日常或事件后果托住。
3. 禁止把洞察素材原文改成轻度同义句；长排比必须拆开重组为口语化的自我追问、转念和收束句。
4. 直接在本次写作中完成去素材腔：发展对比、因果、情绪变化、自我追问与回扣，不另设润色步骤。
5. 素材充分时写 1200-1800 中文字，至少一半篇幅是由事实发展出来的新表达，但不得新增具体事件、具体电影情节、具体对话、地点、天气或人物反应。
6. 只能扩写“关系、判断、转念、因果”，不能为了生活感补拍摄现场、灯光、屏幕、路上、楼下、手掌温度、酒后胡话、电影童年回忆等素材外具体画面。
7. 写“很多画面滋养我”时，只能使用素材给出的来源类别：自己的、朋友的、身边人的、陌生人的、名人自传、小说、电影；不得发明具体画面。
8. 前两段建立张力，中后段有一次真正的自我校正，结尾前不要再做大段总结，直接落到已有意象或姿态。
9. 素材没有明确说话人时，不得擅自写成“某人说的”；只能写成“我后来想到/我越想越觉得/这句话留在我心里”。
10. 少用“恰恰是、本身就是、这意味着、不是退路而是积蓄、说明你已经”这类解释性判断；必须保留时，前后要有具体事实支撑。
11. 输出前自检：删除所有素材里没有的具体感官、动作、地点、时间、人物反应和电影经历；删除所有保留素材骨架的洞察长句。
12. 使用当前发布的个人风格规则，只输出正文。""".strip(),
                system_context=style,
                max_tokens=4200,
                temperature=0.64,
            )
            final_copy = draft["text"].strip()
            item = _trace_item(draft)
            trace.append(item)
            checkpoint.update({"draft": final_copy, "trace": trace})
            update_generation_job(
                generation_id,
                current_stage=current_stage,
                checkpoint=checkpoint,
            )
            _emit_progress(progress, "stage_finished", current_stage, trace=item)

        book_support = checkpoint.get("book_support")
        if (
            not isinstance(book_support, dict)
            and final_copy
            and selected_book_ids
            and book_support_mode != "off"
        ):
            current_stage = "insert-book-quotes"
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(progress, "stage_started", current_stage)
            support_result = _integrated_book_support_sync(
                {
                    "project_id": payload.get("project_id") or "",
                    "materials": materials,
                    "architecture": architecture_data,
                    "draft": final_copy,
                    "selected_books": selected_book_ids,
                    "book_support_mode": book_support_mode,
                }
            )
            book_support = support_result
            if support_result.get("updated_copy"):
                final_copy = str(support_result["updated_copy"]).strip()
            trace.extend(support_result.get("trace") or [])
            checkpoint.update(
                {
                    "draft": final_copy,
                    "book_support": book_support,
                    "trace": trace,
                }
            )
            update_generation_job(
                generation_id,
                current_stage=current_stage,
                checkpoint=checkpoint,
            )
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                trace=(support_result.get("trace") or [{}])[-1],
                passed=True,
                message=support_result.get("reason") or "书库支撑已处理。",
                book_support={
                    "status": support_result.get("status"),
                    "supports": support_result.get("supports") or [],
                },
            )
        elif not isinstance(book_support, dict):
            book_support = {
                "updated_copy": final_copy,
                "supports": [],
                "citations": [],
                "status": "disabled",
                "reason": "书库支撑未启用或未选择书籍。",
                "online_results": [],
                "trace": [],
            }
            checkpoint["book_support"] = book_support

        protected_lines = _protected_material_lines(materials, architecture_data)
        overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
        current_stage = "audit-writing-quality"
        update_generation_job(generation_id, current_stage=current_stage)
        _emit_progress(progress, "stage_started", current_stage)
        quality = _audit_writing_quality(
            final_copy,
            materials,
            architecture_data,
            overlap,
            source_copy=source_copy,
        )
        item = _trace_item(quality)
        trace.append(item)
        _emit_progress(
            progress,
            "stage_finished",
            current_stage,
            trace=item,
            audit=quality.get("data", {}),
            passed=quality["passed"],
        )

        if not quality["passed"] or not overlap["passed"]:
            current_stage = "write-personal-vlog"
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(
                progress,
                "stage_started",
                current_stage,
                retry=True,
                message="综合审校未通过，正在按问题清单定向重写一次。",
            )
            revision = run_text(
                current_stage,
                f"""按综合审校问题清单，对当前文案进行一次完整定向重写。

项目素材：
{materials_text}

叙事架构：
{json.dumps(architecture_data, ensure_ascii=False)[:12000]}

必须逐字保留：
{json.dumps(protected_lines, ensure_ascii=False)}

综合审校：
{json.dumps(quality.get("data", {}), ensure_ascii=False)[:10000]}

素材表达重合：
{json.dumps(overlap, ensure_ascii=False)}

洞察原文禁用片段：
{json.dumps(forbidden_fragments, ensure_ascii=False)}

当前文案：
{final_copy[:15000]}

重写要求：
1. 只修正被指出的事实、照抄、展开、结构和风格问题；不得新增具体事实，不得缩成摘要。
2. 被指出的素材粘连段必须换掉句子骨架，不允许只替换同义词。
3. 被指出的解释性段落必须改成“事实/动作/对话 -> 自我追问 -> 降调判断”，不要直接定义抽象词。
4. 如果原文出现未被素材支持的归因，删除归因，不要换成另一个人。
5. 删除所有素材中没有的具体画面、动作、感官、地点、时间和人物反应；不要用新的具体画面替换。
6. 洞察段不得再出现综合审校中 copied_expressions 的连续表达或论证顺序。
7. 受保护金句可以逐字保留，但不要在金句前后追加解释性总结。
8. 结尾前不要追加总结段，直接回到已有意象或姿态。
只输出完整正文。""".strip(),
                system_context=style,
                max_tokens=4400,
                temperature=0.42,
            )
            final_copy = revision["text"].strip()
            book_support_refresh_required = True
            item = _trace_item(revision)
            trace.append(item)
            checkpoint.update({"draft": final_copy, "trace": trace})
            update_generation_job(generation_id, checkpoint=checkpoint)
            _emit_progress(progress, "stage_finished", current_stage, trace=item, retry=True)

            overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
            current_stage = "audit-writing-quality"
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(
                progress,
                "stage_started",
                current_stage,
                retry=True,
                message="正在复核定向重写结果。",
            )
            quality = _audit_writing_quality(
                final_copy,
                materials,
                architecture_data,
                overlap,
                source_copy=source_copy,
            )
            item = _trace_item(quality)
            trace.append(item)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                trace=item,
                audit=quality.get("data", {}),
                passed=quality["passed"],
                retry=True,
            )
            if not quality["passed"] or not overlap["passed"]:
                if _needs_insight_detox(quality, overlap):
                    current_stage = "write-personal-vlog"
                    update_generation_job(generation_id, current_stage=current_stage)
                    _emit_progress(
                        progress,
                        "stage_started",
                        current_stage,
                        retry=True,
                        message="洞察原文粘连仍未解决，正在进行一次洞察去原文化复修。",
                    )
                    detox = run_text(
                        current_stage,
                        f"""当前文案只剩“洞察原文粘连/解释密度”类问题。执行一次洞察去原文化复修，输出完整正文。

项目素材：
{materials_text}

叙事架构：
{json.dumps(architecture_data, ensure_ascii=False)[:12000]}

必须逐字保留：
{json.dumps(protected_lines, ensure_ascii=False)}

洞察原文禁用片段：
{json.dumps(forbidden_fragments, ensure_ascii=False)}

阻断型表达重合：
{json.dumps(overlap.get("blocking_near_reused_fragments", []), ensure_ascii=False)}

综合审校：
{json.dumps(quality.get("data", {}), ensure_ascii=False)[:10000]}

当前文案：
{final_copy[:15000]}

复修规则：
1. 删除所有承载“这个时代/内卷/获取信息/记住一个人/成功人物案例/支撑方法论价值观退路前进”等原始洞察骨架的句子。
2. 用 3-5 句新的口语化转念替代洞察段：先从一个已出现事实回看，再提出自我追问，再给出降调判断。
3. 可以表达“信息和回忆让选择更有支撑”，但不得出现禁用片段中的连续表达，不得按原素材顺序展开。
4. 不新增具体事实、具体画面、人物反应、地点、时间、电影经历或对话。
5. 受保护金句和事实锚点可以保留；结尾前不加解释性总结。
6. 保持完整文案，不要输出说明、标题、清单或修改报告。
只输出完整正文。""".strip(),
                        system_context=style,
                        max_tokens=4400,
                        temperature=0.34,
                    )
                    final_copy = detox["text"].strip()
                    book_support_refresh_required = True
                    item = _trace_item(detox)
                    trace.append(item)
                    checkpoint.update({"draft": final_copy, "trace": trace})
                    update_generation_job(generation_id, checkpoint=checkpoint)
                    _emit_progress(progress, "stage_finished", current_stage, trace=item, retry=True)

                    overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
                    current_stage = "audit-writing-quality"
                    update_generation_job(generation_id, current_stage=current_stage)
                    _emit_progress(
                        progress,
                        "stage_started",
                        current_stage,
                        retry=True,
                        message="正在复核洞察去原文化复修结果。",
                    )
                    quality = _audit_writing_quality(
                        final_copy,
                        materials,
                        architecture_data,
                        overlap,
                        source_copy=source_copy,
                    )
                    item = _trace_item(quality)
                    trace.append(item)
                    _emit_progress(
                        progress,
                        "stage_finished",
                        current_stage,
                        trace=item,
                        audit=quality.get("data", {}),
                        passed=quality["passed"],
                        retry=True,
                    )
                if not quality["passed"] or not overlap["passed"]:
                    raise SkillExecutionError(
                        "QUALITY_GATE_FAILED",
                        "文案经定向重写和洞察去原文化复修后仍未通过综合审校，当前稿不会覆盖编辑器",
                        json.dumps(
                            {
                                "quality_audit": quality.get("data", {}),
                                "expression_metrics": overlap,
                                "next_action": "检查审校指出的具体素材冲突，补充或调整后重试失败节点。",
                            },
                            ensure_ascii=False,
                        ),
                    )

        if (
            book_support_refresh_required
            and selected_book_ids
            and book_support_mode != "off"
        ):
            current_stage = "insert-book-quotes"
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(
                progress,
                "stage_started",
                current_stage,
                retry=True,
                message="定向重写已完成，正在把书库支撑同步到最终稿。",
            )
            refreshed_support = _integrated_book_support_sync(
                {
                    "project_id": payload.get("project_id") or "",
                    "materials": materials,
                    "architecture": architecture_data,
                    "draft": final_copy,
                    "selected_books": selected_book_ids,
                    "book_support_mode": book_support_mode,
                }
            )
            book_support = refreshed_support
            if refreshed_support.get("updated_copy"):
                final_copy = str(refreshed_support["updated_copy"]).strip()
            trace.extend(refreshed_support.get("trace") or [])
            checkpoint.update(
                {
                    "draft": final_copy,
                    "book_support": book_support,
                    "trace": trace,
                }
            )
            update_generation_job(generation_id, checkpoint=checkpoint)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                retry=True,
                trace=(refreshed_support.get("trace") or [{}])[-1],
                passed=True,
                message=refreshed_support.get("reason") or "最终稿书库支撑已同步。",
                book_support={
                    "status": refreshed_support.get("status"),
                    "supports": refreshed_support.get("supports") or [],
                },
            )

            protected_lines = _protected_material_lines(materials, architecture_data)
            overlap = _writing_overlap_metrics(final_copy, materials, protected_lines)
            current_stage = "audit-writing-quality"
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(
                progress,
                "stage_started",
                current_stage,
                retry=True,
                message="正在复核书库支撑后的最终文案。",
            )
            quality = _audit_writing_quality(
                final_copy,
                materials,
                architecture_data,
                overlap,
                source_copy=source_copy,
            )
            item = _trace_item(quality)
            trace.append(item)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                trace=item,
                audit=quality.get("data", {}),
                passed=quality["passed"],
                retry=True,
            )
            if not quality["passed"] or not overlap["passed"]:
                raise SkillExecutionError(
                    "QUALITY_GATE_FAILED",
                    "最终稿完成书库支撑后未通过综合审校，当前稿不会覆盖编辑器",
                    json.dumps(
                        {
                            "quality_audit": quality.get("data", {}),
                            "expression_metrics": overlap,
                            "next_action": "检查最终稿的书库支撑位置，补充或调整素材后重试失败节点。",
                        },
                        ensure_ascii=False,
                    ),
                )

        missing_locked = [item for item in locked_paragraphs if item not in final_copy]
        if missing_locked:
            raise SkillExecutionError(
                "LOCKED_PARAGRAPH_CHANGED",
                "生成结果改动了锁定段落，当前稿不会覆盖编辑器",
                json.dumps({"missing_locked": missing_locked}, ensure_ascii=False),
            )

        result = {
            "copy": final_copy,
            "style_version": style_version,
            "generation_mode": generation_mode,
            "generation_id": generation_id,
            "resumed_stages": resumed_stages,
            "plan": architecture_data,
            "audit": quality["data"],
            "style_audit": quality["data"],
            "material_coverage": quality["data"].get("material_coverage", []),
            "expression_metrics": overlap,
            "book_support": book_support,
            "trace": trace,
        }
        update_generation_job(
            generation_id,
            status="succeeded",
            current_stage="completed",
            failed_stage="",
            result=result,
            checkpoint={**checkpoint, "trace": trace},
            error={},
        )
        return result
    except Exception as exc:
        error = exc if isinstance(exc, SkillExecutionError) else SkillExecutionError(
            "GENERATION_FAILED", "文案生成失败", str(exc)
        )
        update_generation_job(
            generation_id,
            status="failed",
            current_stage=current_stage,
            failed_stage=current_stage,
            checkpoint={**checkpoint, "trace": trace},
            error={"code": error.code, "message": str(error), "details": error.details},
        )
        raise error


def _generation_length_config(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("target_length_mode") or "auto").strip().lower()
    if mode != "manual":
        return {
            "mode": "auto",
            "target": None,
            "min": None,
            "max": None,
            "label": "自动",
        }
    try:
        target = int(float(payload.get("target_length") or 0))
    except (TypeError, ValueError):
        target = 1200
    target = max(300, min(target, 3000))
    tolerance = max(60, round(target * 0.1))
    return {
        "mode": "manual",
        "target": target,
        "min": max(240, target - tolerance),
        "max": target,
        "label": f"上限 {target} 字",
    }


def _copy_length(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "")))


def _copy_length_in_range(text: str, length_config: dict[str, Any]) -> bool:
    if length_config.get("mode") != "manual":
        return True
    actual = _copy_length(text)
    return int(length_config["min"]) <= actual <= int(length_config["max"])


def _generation_input_fingerprint(payload: dict[str, Any]) -> str:
    generation_mode = str(payload.get("generation_mode") or "fresh").strip()
    contract = {
        "materials": {} if generation_mode == "rewrite" else payload.get("materials") or {},
        "selected_books": payload.get("selected_books") or [],
        "source_copy": payload.get("source_copy") or "",
        "generation_mode": generation_mode,
        "narrative_mode": payload.get("narrative_mode") or "default",
        "locked_paragraphs": payload.get("locked_paragraphs") or [],
        "book_support_mode": payload.get("book_support_mode") or "integrated",
        "book_quote_strategy": payload.get("book_quote_strategy") or "standard",
        "creator_framework_version": payload.get("creator_framework_version") or "yzk_v1",
        "target_length_mode": payload.get("target_length_mode") or "auto",
        "target_length": payload.get("target_length"),
        "active_dna_ids": payload.get("active_dna_ids") or [],
    }
    serialized = json.dumps(contract, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _length_instruction(length_config: dict[str, Any]) -> str:
    if length_config["mode"] == "auto":
        return "由模型根据素材密度自动决定合理篇幅，优先保证叙事完整。"
    return (
        f"硬性字数范围：{length_config['min']}-{length_config['max']} 字（不含空白）。"
        f"目标上限为 {length_config['target']} 字，输出前必须自行计数；不得超过上限。"
    )


def _style_with_length_contract(style: str, length_config: dict[str, Any]) -> str:
    if length_config.get("mode") != "manual":
        return style
    return (
        style.rstrip()
        + "\n\n## 本次运行时字数契约\n"
        + f"本次正文必须保持在 {length_config['min']}-{length_config['max']} 字，"
        + f"其中 {length_config['max']} 字是不可突破的上限。"
        + "本条运行时契约优先于上文任何固定篇幅建议。"
    )


def _repair_copy_to_length(
    text: str,
    source_context: str,
    style: str,
    length_config: dict[str, Any],
    required_lines: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """用现有写作 Skill 做一次长度校准，不使用本地截断或伪造文本。"""
    if _copy_length_in_range(text, length_config):
        return text, {}
    required = [str(item).strip() for item in (required_lines or []) if str(item).strip()]
    required_block = (
        "\n必须逐字保留以下书库引文及书名，不得删除或改写：\n"
        + json.dumps(required, ensure_ascii=False)
        if required
        else ""
    )
    original_actual = _copy_length(text)
    calibration_target = round((int(length_config["min"]) + int(length_config["max"])) / 2)
    current = text
    last_repaired: dict[str, Any] = {}
    for attempt in range(2):
        actual = _copy_length(current)
        if actual > int(length_config["max"]):
            adjustment = (
                f"当前超出上限 {actual - int(length_config['max'])} 字。不要贴着上限估算，"
                f"请至少净删减 {actual - calibration_target} 字，并以约 {calibration_target} 字为校准目标。"
            )
        else:
            adjustment = (
                f"当前低于下限 {int(length_config['min']) - actual} 字。"
                f"请以约 {calibration_target} 字为校准目标发展已有关系，不要贴着下限估算。"
            )
        last_repaired = run_text(
            "write-personal-vlog",
            f"""对下面这篇已完成的匣中镜 Vlog 文案做一次长度校准。只调整篇幅，不改变个人声音、事实边界、叙事主轴和已有书库直接引文。

当前字数：{actual}
{_length_instruction(length_config)}
本次校准动作：{adjustment}
这是第 {attempt + 1} 次校准。不得原样返回，不得只做不足以进入范围的微调。

如果超出范围：删除重复解释、同义递进和不再推进叙事的句子，保留事件、转念和结尾姿态；禁止机械截断。
如果低于范围：只发展已有事实之间的关系、因果和自我追问，不新增事件、地点、对话、感官细节或心理经历。
{required_block}

事实与内容边界：
{source_context[:18000]}

原文：
{current[:18000]}

只输出校准后的完整正文。""".strip(),
            system_context=style,
            max_tokens=max(2200, min(5000, int((length_config["target"] or 1500) * 2.0))),
            temperature=0.28 if attempt else 0.32,
        )
        candidate = last_repaired["text"].strip()
        if (
            candidate
            and _copy_length_in_range(candidate, length_config)
            and (not required or all(line in candidate for line in required))
        ):
            return candidate, _trace_item(last_repaired)
        current = candidate
    if required and _copy_length_in_range(current, length_config) and not all(line in current for line in required):
        raise SkillExecutionError(
            "LENGTH_REPAIR_DROPPED_CITATION",
            "长度校准改动了必须保留的书库引文",
        )
    raise SkillExecutionError(
        "LENGTH_CONSTRAINT_FAILED",
        f"DeepSeek 长度校准后仍未落在 {length_config['min']}-{length_config['max']} 字范围内",
        json.dumps(
            {
                "target": length_config["target"],
                "min": length_config["min"],
                "max": length_config["max"],
                "before": original_actual,
                "after": _copy_length(current),
            },
            ensure_ascii=False,
        ),
    )


def _generation_book_support_failure(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, SkillExecutionError):
        reason = str(exc)
        code = exc.code
    else:
        reason = "书库金句暂未完成"
        code = "BOOK_SUPPORT_FAILED"
    return {
        "updated_copy": "",
        "supports": [],
        "citations": [],
        "status": "failed",
        "reason": f"{reason}。正文已保留，可稍后单独处理书库金句。",
        "error_code": code,
        "online_results": [],
        "trace": [],
    }


def _generate_sync(
    payload: dict[str, Any],
    progress: ProgressCallback | None = None,
    generation_id: str = "",
) -> dict[str, Any]:
    """Three-skill generation: personal writing, Douyin optimization, book support."""
    materials = payload.get("materials") or {}
    generation_mode = str(payload.get("generation_mode") or "fresh").strip()
    if generation_mode not in {"fresh", "rewrite"}:
        generation_mode = "fresh"
    source_copy = str(payload.get("source_copy") or "").strip() if generation_mode == "rewrite" else ""
    available_books = _available_books()
    selected_book_ids = [
        str(book_id)
        for book_id in (payload.get("selected_books") or [])
        if str(book_id) in available_books
    ]
    book_support_mode = str(payload.get("book_support_mode") or "integrated").strip()
    locked_paragraphs = (
        [
            str(item).strip()
            for item in (payload.get("locked_paragraphs") or [])
            if str(item).strip()
        ]
        if generation_mode == "rewrite"
        else []
    )
    length_config = _generation_length_config(payload)
    if (
        length_config["mode"] == "manual"
        and _copy_length("\n\n".join(locked_paragraphs)) > int(length_config["max"])
    ):
        raise SkillExecutionError(
            "LENGTH_CONSTRAINT_IMPOSSIBLE",
            "锁定段落本身已超过当前字数上限，请先解除部分锁定或提高字数上限",
        )
    narrative_mode = str(payload.get("narrative_mode") or "default").strip()
    if generation_mode == "rewrite":
        if not source_copy:
            raise SkillExecutionError("REWRITE_SOURCE_EMPTY", "当前文案为空，无法执行重写")
        # The editor copy is authoritative in rewrite mode. Project materials may be
        # stale after manual additions and deletions, so they must not enter the LLM context.
        materials = {}
    else:
        if narrative_mode and narrative_mode != "default":
            materials = {**materials, "generation_mode": narrative_mode}
        _require_materials(materials)

    if not generation_id:
        generation_id = create_generation_job(payload)["generation_id"]
    job = get_generation_job(generation_id)
    if not job:
        raise SkillExecutionError("GENERATION_NOT_FOUND", "生成任务不存在")
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    effective_payload = {
        **payload,
        "materials": materials,
        "generation_mode": generation_mode,
        "source_copy": source_copy,
    }
    input_fingerprint = _generation_input_fingerprint(effective_payload)
    checkpoint_fingerprint = str(checkpoint.get("input_fingerprint") or "")
    if checkpoint and checkpoint_fingerprint != input_fingerprint:
        checkpoint = {"input_fingerprint": input_fingerprint}
        update_generation_job(generation_id, checkpoint=checkpoint)
    elif checkpoint_fingerprint != input_fingerprint:
        checkpoint["input_fingerprint"] = input_fingerprint
        update_generation_job(generation_id, checkpoint=checkpoint)
    trace = checkpoint.get("trace") if isinstance(checkpoint.get("trace"), list) else []
    resumed_stages: list[str] = []
    style_version, style = writing_context(payload)
    runtime_style = _style_with_length_contract(style, length_config)
    materials_text = _materials_text(materials)
    length_instruction = _length_instruction(length_config)
    source_context = (
        "当前编辑器文案是唯一事实、主题与内容边界。不得参考或恢复项目素材中未出现在当前文案里的内容。\n"
        + source_copy
        if generation_mode == "rewrite"
        else materials_text
    )
    locked_block = (
        "\n必须逐字保留的锁定段落：\n" + json.dumps(locked_paragraphs, ensure_ascii=False)
        if locked_paragraphs
        else ""
    )
    current_stage = "write-personal-vlog"

    if job.get("status") == "failed":
        update_generation_job(
            generation_id,
            status="running",
            failed_stage="",
            error={},
            increment_attempt=True,
        )
    else:
        update_generation_job(generation_id, status="running")

    try:
        draft = str(checkpoint.get("draft") or "").strip()
        if draft:
            resumed_stages.append(current_stage)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                resumed=True,
                message="已恢复个人风格初稿。",
            )
        else:
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(progress, "stage_started", current_stage)
            if generation_mode == "rewrite":
                writing_prompt = f"""基于当前发布的个人创作 DNA Skill，优化用户编辑器中的完整 Vlog 文案。

输入契约：当前文案是唯一的事实来源、主题来源和内容边界。项目原始主题、洞察、日常素材和核心事件均不得参与本次改写，也不得恢复当前文案中已经被用户删除的内容。

篇幅策略：{length_instruction}
叙事策略：{_narrative_mode_instruction(narrative_mode)}
六段主链路：{_personal_narrative_framework(strict=True)}

当前文案：
{source_copy[:18000]}
{locked_block}

执行要求：
1. 这是对用户当前成稿的风格化优化，不是根据旧素材重新生成，也不是摘要。
2. 保留当前文案已有的事实、人物、日期、对话、核心立场、用户新增内容和主动删减结果。
3. 按个人 DNA 和六段主链路优化段落推进、事件与判断的关系、自我对话、长短句呼吸、口语表达和克制收束。
4. 默认尊重现有叙事主轴；只有当前叙事策略明确要求时，才可重排当前文案中已经存在的内容。
5. 删除重复解释、AI 套话和空洞结论，但不得删除支撑主题的关键事实或改变原意。
6. 不得新增当前文案中不存在的事件、地点、动作、对话、时间、人物反应、感官画面或心理经历。
7. 只输出优化后的完整正文，不输出标题、解释、评分、审校意见或 JSON。""".strip()
            else:
                writing_prompt = f"""根据当前发布的个人创作风格，写一篇完整中文生活 Vlog 文案。

生成模式：新写初稿
篇幅策略：{length_instruction}
六段主链路：{_personal_narrative_framework(strict=False)}

项目素材：
{materials_text}

执行要求：
1. 这是一个真正的撰写任务，不是素材整理、摘要或素材拼接。
2. 从历史文稿蒸馏出的个人风格出发，保留第一人称、具体生活细节、事件推进、内心转念和克制收束。
3. 按六段主链路写：开头先点明主题，蒙太奇事件引入与发展，高潮情绪堆叠，下沉思考冷静，回引强化呼应，升华价值钩子。
4. 开头先点题，不要先讲道理；蒙太奇阶段用短句和并列句砸出事件密度；高潮段先把压力和情绪抬起来；下沉段再让判断冷静下来。
5. 素材是事实和方向，不是等待原封不动植入正文的句子；必须发展事件之间的关系、因果、对照和情绪变化。
6. 禁止将素材原文连续超过 10 个汉字搬进正文；如果素材本身已经像文案草稿，也必须重组句法、顺序和叙事功能。
7. 至少 50% 正文必须是用于连接、追问、转念和回扣的全新表达；不能按素材顺序流水账排列。
8. 不新增素材中不存在的地点、动作、对话、时间、人物反应、电影情节、感官画面或心理经历。
9. 不把文案写成鸡汤、演讲稿、营销文案或标准化 AI 文章。
10. 只输出完整正文，不输出标题、解释、评分、审校意见或 JSON。""".strip()
            writing = run_text(
                current_stage,
                writing_prompt,
                system_context=runtime_style,
                max_tokens=max(2600, min(6000, int((length_config["target"] or 1500) * 2.2))),
                temperature=0.68,
            )
            draft = writing["text"].strip()
            if not draft:
                raise SkillExecutionError("WRITING_EMPTY", "个人风格撰写没有返回有效文案")
            trace.append(_trace_item(writing))
            checkpoint.update({"draft": draft, "trace": trace})
            update_generation_job(
                generation_id,
                current_stage=current_stage,
                checkpoint=checkpoint,
            )
            _emit_progress(progress, "stage_finished", current_stage, trace=trace[-1])

        if length_config["mode"] == "manual" and not _copy_length_in_range(draft, length_config):
            _emit_progress(
                progress,
                "stage_started",
                current_stage,
                retry=True,
                message=f"初稿为 {_copy_length(draft)} 字，正在校准至 {length_config['min']}-{length_config['max']} 字。",
            )
            draft, length_trace = _repair_copy_to_length(
                draft,
                source_context,
                runtime_style,
                length_config,
            )
            trace.append(length_trace)
            checkpoint.update({"draft": draft, "trace": trace})
            update_generation_job(generation_id, checkpoint=checkpoint)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                retry=True,
                trace=length_trace,
                actual_length=_copy_length(draft),
                message="个人风格初稿已完成字数校准。",
            )

        optimized_copy = str(checkpoint.get("optimized_copy") or "").strip()
        current_stage = "optimize-douyin-vlog"
        if optimized_copy:
            final_copy = optimized_copy
            resumed_stages.append(current_stage)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                resumed=True,
                message="已恢复抖音 Vlog 优化结果。",
            )
        else:
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(progress, "stage_started", current_stage)
            rewrite_boundary = (
                f"""用户编辑器原稿（唯一事实与内容边界）：
{source_copy[:18000]}

不得参考项目原始素材，不得恢复原稿中不存在或已被用户删除的内容。"""
                if generation_mode == "rewrite"
                else f"""项目素材，仅用于事实边界：
{materials_text}"""
            )
            optimized = run_text(
                current_stage,
f"""在不改变个人声音和事实边界的前提下，优化下面这篇生活 Vlog 文案，使其更适合抖音画外音与对镜表达。

篇幅策略：{length_instruction}
叙事底线：{_personal_narrative_framework(strict=False)}

个人风格初稿：
{draft[:18000]}

{rewrite_boundary}

只做以下优化：
1. 让开头在前几句内进入真实状态、核心矛盾或具体事件。
2. 调整句子长短和停顿，让它更适合口语录制。
3. 保留生活细节，让抽象判断由事件托住。
4. 删除重复解释、网感套话和励志口号。
5. 保留中段转念、高潮堆叠、下沉思考和结尾回扣，不把内容改成标题党或平滑散文。

禁止：
- 不得新增素材不存在的事实、场景、人物、对话或心理经历。
- 不得把文案改成标准爆款模板或营销文。
- 不得输出任何审核报告、分数、修改说明或 JSON。

只输出优化后的完整正文。""".strip(),
                system_context=runtime_style,
                max_tokens=max(2600, min(6000, int((length_config["target"] or 1500) * 2.2))),
                temperature=0.5,
            )
            final_copy = optimized["text"].strip()
            if not final_copy:
                raise SkillExecutionError("OPTIMIZATION_EMPTY", "抖音 Vlog 优化没有返回有效文案")
            trace.append(_trace_item(optimized))
            checkpoint.update({"optimized_copy": final_copy, "draft": draft, "trace": trace})
            update_generation_job(
                generation_id,
                current_stage=current_stage,
                checkpoint=checkpoint,
            )
            _emit_progress(progress, "stage_finished", current_stage, trace=trace[-1])

        if length_config["mode"] == "manual" and not _copy_length_in_range(final_copy, length_config):
            _emit_progress(
                progress,
                "stage_started",
                current_stage,
                retry=True,
                message=f"优化稿为 {_copy_length(final_copy)} 字，正在恢复硬性字数范围。",
            )
            final_copy, length_trace = _repair_copy_to_length(
                final_copy,
                source_context,
                runtime_style,
                length_config,
            )
            trace.append(length_trace)
            checkpoint.update({"optimized_copy": final_copy, "draft": draft, "trace": trace})
            update_generation_job(generation_id, checkpoint=checkpoint)
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                retry=True,
                trace=length_trace,
                actual_length=_copy_length(final_copy),
                message="抖音优化稿已完成字数校准。",
            )

        book_support = checkpoint.get("book_support")
        current_stage = "insert-book-quotes"
        if not isinstance(book_support, dict):
            update_generation_job(generation_id, current_stage=current_stage)
            _emit_progress(progress, "stage_started", current_stage)
            if selected_book_ids and book_support_mode != "off":
                try:
                    book_support = _integrated_book_support_sync(
                        {
                            "project_id": payload.get("project_id") or "",
                            "materials": {} if generation_mode == "rewrite" else materials,
                            "architecture": {
                                "central_tension": "" if generation_mode == "rewrite" else str(materials.get("insight") or materials.get("theme") or ""),
                                "callback": "" if generation_mode == "rewrite" else str(materials.get("ending_reference") or ""),
                            },
                            "draft": final_copy,
                            "selected_books": selected_book_ids,
                            "book_support_mode": book_support_mode,
                            "book_quote_strategy": payload.get("book_quote_strategy") or "standard",
                            "length_config": length_config,
                        }
                    )
                    proposed_copy = str(book_support.get("updated_copy") or "").strip()
                    if (
                        proposed_copy
                        and length_config["mode"] == "manual"
                        and not _copy_length_in_range(proposed_copy, length_config)
                    ):
                        required_citations = [
                            str(value).strip()
                            for item in (book_support.get("supports") or [])
                            if isinstance(item, dict)
                            for value in (item.get("book"), item.get("quote"))
                            if str(value or "").strip()
                        ]
                        proposed_copy, length_trace = _repair_copy_to_length(
                            proposed_copy,
                            source_context,
                            runtime_style,
                            length_config,
                            required_lines=required_citations,
                        )
                        book_support["updated_copy"] = proposed_copy
                        book_support.setdefault("trace", []).append(length_trace)
                except Exception as exc:
                    book_support = _generation_book_support_failure(exc)
            else:
                book_support = {
                    "updated_copy": "",
                    "supports": [],
                    "citations": [],
                    "status": "disabled",
                    "reason": "未选择书籍或已关闭书库金句。",
                    "online_results": [],
                    "trace": [],
                }
            if book_support.get("updated_copy"):
                final_copy = str(book_support["updated_copy"]).strip()
            trace.extend(book_support.get("trace") or [])
            checkpoint.update({"optimized_copy": final_copy, "book_support": book_support, "trace": trace})
            update_generation_job(
                generation_id,
                current_stage=current_stage,
                checkpoint=checkpoint,
            )
            _emit_progress(
                progress,
                "stage_finished",
                current_stage,
                trace=(book_support.get("trace") or [{}])[-1],
                passed=book_support.get("status") != "failed",
                message=book_support.get("reason") or "书库金句已处理。",
                book_support={
                    "status": book_support.get("status"),
                    "supports": book_support.get("supports") or [],
                },
            )

        missing_locked = [item for item in locked_paragraphs if item not in final_copy]
        if missing_locked:
            raise SkillExecutionError(
                "LOCKED_PARAGRAPH_CHANGED",
                "生成结果改动了锁定段落，当前稿不会覆盖编辑器",
                json.dumps({"missing_locked": missing_locked}, ensure_ascii=False),
            )

        actual_length = _copy_length(final_copy)
        if length_config["mode"] == "manual" and not _copy_length_in_range(final_copy, length_config):
            raise SkillExecutionError(
                "LENGTH_CONSTRAINT_FAILED",
                f"最终文案为 {actual_length} 字，未满足 {length_config['min']}-{length_config['max']} 字硬性范围，当前稿不会覆盖编辑器",
                json.dumps(
                    {
                        "target": length_config["target"],
                        "min": length_config["min"],
                        "max": length_config["max"],
                        "actual": actual_length,
                    },
                    ensure_ascii=False,
                ),
            )
        stage_outline = _creator_stage_outline(final_copy)
        douyin_publish_pack = _douyin_publish_pack(
            final_copy,
            {} if generation_mode == "rewrite" else materials,
            runtime_style,
        )
        trace.extend(douyin_publish_pack.get("trace") or [])
        result = {
            "copy": final_copy,
            "style_version": style_version,
            "generation_mode": generation_mode,
            "generation_id": generation_id,
            "resumed_stages": resumed_stages,
            "plan": {},
            "audit": {
                "status": "not_run",
                "message": "默认链路不执行综合审校。",
            },
            "style_audit": {
                "status": "not_run",
                "message": "默认链路不执行综合审校。",
            },
            "material_coverage": [],
            "stage_outline": stage_outline,
            "used_material_strategy": {
                "mode": "current_copy_only" if generation_mode == "rewrite" else "develop_materials_not_copy",
                "summary": (
                    "改写模式只基于当前编辑器文案，不读取原始素材。"
                    if generation_mode == "rewrite"
                    else "新写模式把素材作为事实边界和叙事燃料，要求重组、扩写和建立关系。"
                ),
            },
            "style_notes": [
                "第一人称生活 Vlog",
                "六段叙事主链路",
                "素材发展而非搬运",
                "事件托住抽象判断",
            ],
            "douyin_publish_pack": douyin_publish_pack,
            "expression_metrics": {
                "status": "not_run",
                "passed": True,
            },
            "book_support": book_support,
            "length": {
                **length_config,
                "actual": actual_length,
                "within_range": _copy_length_in_range(final_copy, length_config),
            },
            "trace": trace,
        }
        update_generation_job(
            generation_id,
            status="succeeded",
            current_stage="completed",
            failed_stage="",
            result=result,
            checkpoint={**checkpoint, "trace": trace},
            error={},
        )
        return result
    except Exception as exc:
        error = exc if isinstance(exc, SkillExecutionError) else SkillExecutionError(
            "GENERATION_FAILED", "文案生成失败", str(exc)
        )
        update_generation_job(
            generation_id,
            status="failed",
            current_stage=current_stage,
            failed_stage=current_stage,
            checkpoint={**checkpoint, "trace": trace},
            error={"code": error.code, "message": str(error), "details": error.details},
        )
        raise error


async def generate_copy(
    payload: dict[str, Any],
    generation_id: str = "",
) -> dict[str, Any]:
    return await asyncio.to_thread(_generate_sync, payload, None, generation_id)


async def generate_copy_with_progress(
    payload: dict[str, Any],
    progress: ProgressCallback | None = None,
    generation_id: str = "",
) -> dict[str, Any]:
    return await asyncio.to_thread(_generate_sync, payload, progress, generation_id)


def _opening_theme_violation(text: str, theme: str) -> bool:
    clean_theme = re.sub(r"\s+", "", theme)
    if len(clean_theme) <= 4 and not any(
        marker in clean_theme
        for marker in ("周年", "纪念日", "生日", "毕业", "读研", "月", "日", "年")
    ):
        return False
    clean_text = re.sub(r"\s+", "", text)
    return f"{clean_theme}这两个字" in clean_text


def _replace_opening(copy: str, opening: str) -> str:
    blocks = [block for block in re.split(r"\n{2,}", copy) if block.strip()]
    if len(blocks) <= 1:
        return opening.strip()
    return f"{opening.strip()}\n\n" + "\n\n".join(blocks[1:])


def _candidate_with_selection(payload: dict[str, Any], replacement: str) -> str:
    full_copy = str(payload.get("full_copy") or "")
    start = payload.get("selection_start")
    end = payload.get("selection_end")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(full_copy):
        return full_copy[:start] + replacement + full_copy[end:]
    selected = str(payload.get("selected_text") or "")
    if selected and selected in full_copy:
        return full_copy.replace(selected, replacement, 1)
    return full_copy


def _selection_output_out_of_scope(selected_text: str, edited: str, full_copy: str) -> bool:
    if not edited.strip():
        return True
    selected_len = max(1, len(selected_text.strip()))
    if len(edited.strip()) > max(180, int(selected_len * 2.4)):
        return True
    if "\n\n" in edited.strip() and selected_len < 180 and "\n" not in selected_text:
        return True
    if selected_text.strip() == full_copy.strip():
        return False
    full_blocks = [block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()]
    for block in full_blocks:
        if block != selected_text.strip() and len(block) >= 18 and block[:18] in edited:
            return True
    return False


def _clean_opening_options(result: dict[str, Any]) -> list[dict[str, Any]]:
    options = _edit_result_data(result).get("options")
    if not isinstance(options, list):
        raise SkillExecutionError("EDIT_SCHEMA_INVALID", "重写开头未返回 options")
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(options[:3]):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        changes = _clean_edit_changes(item.get("changes"))
        if not text or not changes:
            continue
        cleaned.append(
            {
                "label": str(item.get("label") or f"开头 {index + 1}"),
                "text": text,
                "changes": changes,
            }
        )
    return cleaned


def _audit_opening_options(
    options: list[dict[str, Any]],
    materials: dict[str, Any],
    full_copy: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    audit_payload = run_json(
        "audit-vlog-copy",
        f"""
逐个审校下面的重写开头。只判断开头本身能否接回原文，不要因为原文已有问题而否决开头。

项目素材：
{_materials_text(materials)}

原文：
{full_copy[:9000]}

候选开头：
{json.dumps(options, ensure_ascii=False)}

输出 JSON：
{{
  "items": [
    {{"index": 0, "passed": true, "distinct_from_original": true, "structure": "事件直入", "reason": "", "unsupported_facts": []}}
  ]
}}

审校规则：
1. 只要候选开头新增了项目素材和原文中都没有的具体事实、地点、动作、时间、人物关系或心理经历，就 passed=false。
2. 抽象判断、反问和主题回扣可以通过主题与洞察支持。
3. “读研两周年纪念日这两个字”这类把事件长短语写成“这两个字”的开头必须 passed=false。
4. 如果候选只是原开头换同义词、调整语序或增加一句泛化感受，distinct_from_original=false 且 passed=false。
5. 三个候选必须分别使用事件直入、设问进入、反差或判断进入等不同结构；如果两个候选骨架相同，将后一个 passed=false。
6. 不要因为候选数量不是三个而直接全部否决；逐个给结论。
只输出 JSON。
""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=1400,
        temperature=0.12,
    )
    items = audit_payload["data"].get("items")
    invalid_indexes: set[int] = set()
    structure_by_index: dict[int, str] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            structure = str(item.get("structure") or "").strip()
            if structure:
                structure_by_index[index] = structure
            if not bool(item.get("passed")) or item.get("distinct_from_original") is False:
                invalid_indexes.add(index)
    else:
        raw_invalid = audit_payload["data"].get("invalid_indexes", [])
        if isinstance(raw_invalid, list):
            for item in raw_invalid:
                try:
                    invalid_indexes.add(int(item))
                except (TypeError, ValueError):
                    continue
    theme = str(materials.get("theme") or "")
    valid: list[dict[str, Any]] = []
    seen_structures: set[str] = set()
    for index, option in enumerate(options):
        if index in invalid_indexes or _opening_theme_violation(option["text"], theme):
            continue
        structure = structure_by_index.get(index) or str(option.get("label") or "").strip()
        structure_key = re.sub(r"[^a-z\u4e00-\u9fff]", "", structure.lower())
        if structure_key and structure_key in seen_structures:
            continue
        if structure_key:
            seen_structures.add(structure_key)
        valid.append({**option, "label": structure or option.get("label") or f"开头 {index + 1}"})
    return valid, audit_payload


def _edit_copy_once(
    payload: dict[str, Any],
    action: dict[str, Any],
    correction: str = "",
) -> dict[str, Any]:
    action_id = next((key for key, value in EDIT_ACTIONS.items() if value is action), "")
    materials = payload.get("materials") or {}
    length_config = _generation_length_config(payload)
    full_copy = str(payload.get("full_copy") or "").strip()
    selected_text = str(payload.get("selected_text") or "").strip()
    locked_paragraphs = [
        str(item).strip()
        for item in (payload.get("locked_paragraphs") or [])
        if str(item).strip()
    ]
    protected_lines = [
        line
        for line in _protected_material_lines(materials)
        if line in full_copy
    ]
    immutable_lines = list(dict.fromkeys([*locked_paragraphs, *protected_lines]))
    custom_command = str(payload.get("command") or "").strip()
    full_context = _numbered_paragraphs(full_copy) if action["mode"] == "paragraph_patch" or action_id == "shorten" else full_copy
    target_text = (
        selected_text
        if action["mode"] == "selection"
        else ("从上方编号段落中选择需要结构重写的段落。" if action["mode"] == "paragraph_patch" else full_copy)
    )
    action_instruction = action["instruction"]
    shorten_target_index = 0
    shorten_min_chars = 0
    shorten_max_chars = 0
    if custom_command:
        action_instruction += f"\n用户对本次局部改写的补充意图：{custom_command}"
    if action_id == "shorten":
        excluded = {
            int(item)
            for item in (payload.get("_edit_excluded_paragraphs") or [])
            if str(item).isdigit()
        }
        blocks = [block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()]
        protected_indexes = {
            index + 1
            for index, block in enumerate(blocks)
            if any(line in block for line in _protected_material_lines(materials))
        }
        targets = [
            index
            for _, index in sorted(
                (
                    (len(_edit_signature(block)), index + 1)
                    for index, block in enumerate(blocks)
                    if index + 1 not in protected_indexes
                    and index + 1 not in excluded
                ),
                reverse=True,
            )[:1]
        ]
        shorten_target_index = targets[0] if targets else 0
        if shorten_target_index:
            target_text = blocks[shorten_target_index - 1]
            target_chars = len(_edit_signature(target_text))
            shorten_min_chars = max(1, math.ceil(target_chars * 0.55))
            shorten_max_chars = max(shorten_min_chars, math.floor(target_chars * 0.75))
        action_instruction += (
            f"\n本轮只压缩编号全文中的第 {', '.join(str(item) for item in targets)} 段："
            f"原段有 {len(_edit_signature(target_text))} 个非标点字符，完整替换后必须控制在 "
            f"{shorten_min_chars}-{shorten_max_chars} 个非标点字符。不要返回其他段落。"
        )
    if action_id == "more-personal" and action["mode"] == "paragraph_patch":
        excluded = {
            int(item)
            for item in (payload.get("_edit_excluded_paragraphs") or [])
            if str(item).isdigit()
        }
        blocks = [block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()]
        protected_indexes = {
            index + 1
            for index, block in enumerate(blocks)
            if any(line in block for line in _protected_material_lines(materials))
        }
        candidates = [
            (len(_edit_signature(block)), index + 1)
            for index, block in enumerate(blocks)
            if len(_edit_signature(block)) >= 14
            and index + 1 not in protected_indexes
            and index + 1 not in excluded
        ]
        if candidates:
            target_index = max(candidates)[1]
            action_instruction += (
                f"\n本轮只专注重写第 {target_index} 段，不要同时挑选多个段落；"
                "必须从事实骨架重新组织该段，形成一次句法或思考推进上的完整变化。"
            )
    output_contract = (
        """
输出 JSON：
{
  "options": [
    {
      "label": "事件直入",
      "text": "开头正文",
      "changes": [{"point": "核心优化点", "location": "开头", "reason": "修改原因"}]
    },
    {
      "label": "设问进入",
      "text": "开头正文",
      "changes": [{"point": "核心优化点", "location": "开头", "reason": "修改原因"}]
    },
    {
      "label": "反差进入",
      "text": "开头正文",
      "changes": [{"point": "核心优化点", "location": "开头", "reason": "修改原因"}]
    }
  ]
}
三个开头必须使用不同的叙事结构，不能只是同一句话换同义词。每个 changes 必须对应该开头的真实变化。只输出 JSON。
""".strip()
        if action["mode"] == "opening_options"
        else (
            """
输出 JSON：
{
  "replacements": [
    {
      "paragraph_index": 3,
      "text": "该段完整替换文本，不包含段落编号",
      "operation": "事件判断换序|对照重组|自问自答|判断降调|主题回扣",
      "point": "核心优化点",
      "location": "第 3 段",
      "reason": "修改原因"
    }
  ]
}
只返回真正需要修改的一个段落；不要返回未修改段落，不要输出完整全文。段落编号必须来自全文上下文。只输出 JSON。
每个 text 都必须整段重新组织：不能只删掉“着、那种、其实”等词，不能只把“骑着车”缩成“骑车”，不能只替换连接词或调换一两个短语。若无法在事实边界内真正重构该段，就选择其他段落。
内部执行时，先把目标段落压成“必须保留的事实清单”，再暂时丢开原句，按照当前发布的个人风格重新写。除真实对话、专有名词、日期和锁定表达外，不要照抄原段中的完整句子。
reason 必须描述真实发生的句法或思考推进变化；不得把原文已经存在的设问、声音、动作或细节说成“本次新增”。

变化尺度示例：
- 不合格：原文“事情结束后，我重新回到了原来的节奏。”改成“事情结束后，节奏恢复了。”这只是删词。
- 合格：改成“先回来的不是答案。是每天重新按时出门、做事、休息以后，我才发现，生活已经在替我回答了。”这改变了事件与判断的顺序，也让思考在段内发生。
- 不合格：reason 声称“增加自问”，但 text 中原本就有同一个设问，或新旧正文完全相同。
""".strip()
            if action["mode"] == "paragraph_patch"
            else (
            """
输出 JSON：
{
  "text": "只包含选中文本的替换结果",
  "changes": [
    {"point": "核心优化点", "location": "选中段落中的具体句子或作用位置", "reason": "修改原因"}
  ]
}
不要输出全文上下文，不新增段落，不解释。text 长度控制在选中文本的 50%-160%。changes 必须对应本次实际改写。只输出 JSON。
内部先把选中段落压成事实清单，再不看原句完整句法地重写；除专有名词、日期和真实对话外，不复制原段完整句子。至少改变两处句间关系。
""".strip()
            if action["mode"] == "selection"
            else """
输出 JSON：
{
  "text": "改写后的完整正文",
  "changes": [
    {"point": "核心优化点", "location": "具体段落或原句位置", "reason": "修改原因"}
  ]
}
changes 只记录实际发生的关键变化，至少一项，最多六项。只输出 JSON。
""".strip()
            )
        )
    )
    if action_id == "shorten" and action["mode"] == "paragraph_patch":
        if shorten_target_index:
            output_contract = output_contract.replace(
                '"paragraph_index": 3',
                f'"paragraph_index": {shorten_target_index}',
                1,
            ).replace("第 3 段", f"第 {shorten_target_index} 段", 1)
        marker = "每个 text 都必须整段重新组织"
        output_contract = output_contract.split(marker, 1)[0].rstrip() + f"""

收束规则：text 只能是指定段落的压缩替换稿，必须控制在 {shorten_min_chars}-{shorten_max_chars} 个非标点字符。至少删除一个完整的重复解释、同义罗列或不再推进叙事的信息单元；保留具体事实、必要转念与主题作用，不新增解释。reason 必须指出删掉了什么及为何不影响叙事。输出前自行计数，超出范围就继续压缩。只输出 JSON。
""".rstrip()
    prompt = f"""
执行文案编辑任务：{action["label"]}

具体指令：
{action_instruction}

本动作的最低完成标准：
{action["execution_contract"]}

项目素材：
{_materials_text(materials)}

全文上下文：
{full_context[:9000]}

已锁定段落与必须保留的原话（必须逐字保留且不得移动）：
{json.dumps(immutable_lines, ensure_ascii=False)}

需要处理的文本：
{target_text[:6000]}

硬性边界：
1. 不新增项目素材或原文中没有的事实、人物、地点、天气、结果和对话。
2. 不改变事实和明确要求逐字保留的表达；其他句子允许并且需要重新组织句法、观察角度与段落关系。
3. 不新增书籍引文。
4. 事件、日期、纪念日、阶段或长短语不得写成“某某这两个字”。
5. 局部改写时不得新增“早就、一直、终于、忽然明白、不敢承认”等原文没有提供的时间、程度和心理判断。
6. 原文和素材是事实证据，不是等待复制的句子。必须产生实质性的非标点变化，禁止原样返回或只替换一两个词。
7. 先判断目标文本的叙事角色和主要问题，再选择 1-2 个最有效的改写动作；不要把分析过程写进输出。
8. 当前发布风格中“允许中性场景连接”的规则只适用于从素材生成新初稿，不适用于编辑现有文案。本任务不得新增原文和项目素材都没有的动作、路线、时间、数量、人物属性、动机、因果或心理状态；“自然合理”不是证据。
9. 应用本次修改后的完整文案仍需满足篇幅策略：{_length_instruction(length_config)}
{correction}

{output_contract}
""".strip()
    return run_json(
        "edit-vlog-copy",
        prompt,
        system_context=writing_context(
            payload,
            exclude_dna=action_id == "more-personal",
        )[1],
        max_tokens=action["max_tokens"],
        temperature=action["temperature"],
    )


def _edit_copy_sync(payload: dict[str, Any]) -> dict[str, Any]:
    action_id = str(payload.get("action") or "more-personal")
    action = EDIT_ACTIONS.get(action_id)
    if not action:
        raise SkillExecutionError("EDIT_ACTION_UNKNOWN", "未知编辑指令")
    full_copy = str(payload.get("full_copy") or "").strip()
    selected_text = str(payload.get("selected_text") or "").strip()
    materials = payload.get("materials") or {}
    length_config = _generation_length_config(payload)
    locked_paragraphs = [
        str(item).strip()
        for item in (payload.get("locked_paragraphs") or [])
        if str(item).strip()
    ]
    protected_lines = [
        line
        for line in _protected_material_lines(materials)
        if line in full_copy
    ]
    immutable_lines = list(dict.fromkeys([*locked_paragraphs, *protected_lines]))
    if not full_copy:
        raise SkillExecutionError("EDIT_SOURCE_EMPTY", "请先生成或填写文案")
    if action["mode"] == "selection" and not selected_text:
        raise SkillExecutionError("EDIT_SELECTION_EMPTY", "请先在编辑器中选中文字")

    trace: list[dict[str, Any]] = []
    result = _edit_copy_once(payload, action)
    trace.append(_trace_item(result))

    if action["mode"] == "opening_options":
        valid_options: list[dict[str, Any]] = []
        discarded_count = 0
        correction = ""
        original_opening = next(
            (block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()),
            full_copy,
        )
        for attempt in range(2):
            if attempt > 0:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            raw_options = _edit_result_data(result).get("options")
            clean_options = _clean_opening_options(result)
            discarded_count += max(0, len(raw_options) - len(clean_options)) if isinstance(raw_options, list) else 1
            distinct_options = _opening_options_are_distinct(clean_options, original_opening)
            discarded_count += max(0, len(clean_options) - len(distinct_options))
            clean_options = distinct_options
            if not clean_options:
                correction = "\n上一版没有返回结构完整且与原文明显不同的开头。重新从素材中的时间、事件、反差或问题进入；三个开头都要附带具体 changes。"
                continue
            audited_options, audit_payload = _audit_opening_options(
                clean_options,
                materials,
                full_copy,
            )
            trace.append(_trace_item(audit_payload))
            if length_config["mode"] == "manual":
                length_safe_options = [
                    option
                    for option in audited_options
                    if _copy_length_in_range(
                        _replace_opening(full_copy, str(option.get("text") or "")),
                        length_config,
                    )
                ]
                discarded_count += len(audited_options) - len(length_safe_options)
                audited_options = length_safe_options
            valid_options = _opening_options_are_distinct(
                [*valid_options, *audited_options],
                original_opening,
            )
            discarded_count += max(0, len(clean_options) - len(audited_options))
            if len(valid_options) >= 3:
                break
            correction = "\n上一版部分开头因事实、结构相似或优化说明不具体而被丢弃。请只基于素材和原文补足三个不同开头，避免新增场景、时间、动作、心理经历，也不要写“这两个字”。"
        if len(valid_options) < 3:
            raise SkillExecutionError(
                "OPENING_OPTIONS_INSUFFICIENT",
                "DeepSeek 未生成三个结构不同且通过审校的开头",
                json.dumps({"valid_options": len(valid_options), "discarded_count": discarded_count}, ensure_ascii=False),
            )
        for option in valid_options[:3]:
            option["metrics"] = _edit_difference(original_opening, option["text"], "rebuild-opening")
        return {
            "mode": "opening_options",
            "options": valid_options[:3],
            "discarded_count": discarded_count,
            "trace": trace,
        }

    audit: dict[str, Any] | None = None
    edited = ""
    changes: list[dict[str, str]] = []
    metrics: dict[str, Any] = {}
    patch_metrics: list[dict[str, Any]] = []
    patch_pairs: list[dict[str, Any]] = []
    rejected_patches: list[dict[str, Any]] = []
    last_issue_code = "EDIT_QUALITY_FAILED"
    last_issue = "编辑结果未通过质量要求"
    source_target = selected_text if action["mode"] == "selection" else full_copy
    max_edit_attempts = 3 if action["mode"] in {"paragraph_patch", "selection"} or action_id == "shorten" else 2
    forbidden_patch_indexes: set[int] = set()
    accepted_patches: dict[int, dict[str, Any]] = {}
    for repair_attempt in range(max_edit_attempts):
        data = _edit_result_data(result)
        if action["mode"] == "paragraph_patch":
            raw_replacements = data.get("replacements")
            pre_rejected: list[dict[str, Any]] = []
            if isinstance(raw_replacements, list):
                filtered_replacements: list[Any] = []
                for item in raw_replacements:
                    try:
                        paragraph_index = int(item.get("paragraph_index")) if isinstance(item, dict) else -1
                    except (TypeError, ValueError):
                        paragraph_index = -1
                    if paragraph_index in forbidden_patch_indexes:
                        pre_rejected.append(
                            {
                                "paragraph_index": paragraph_index,
                                "reason": "该段在前一轮已被判定为浅改，本轮禁止重复提交",
                            }
                        )
                        continue
                    source_blocks = [block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()]
                    if (
                        action_id == "more-personal"
                        and 1 <= paragraph_index <= len(source_blocks)
                        and len(_edit_signature(source_blocks[paragraph_index - 1])) < 14
                    ):
                        pre_rejected.append(
                            {
                                "paragraph_index": paragraph_index,
                                "reason": "更像我只处理有展开空间的正文段，不使用短过渡句凑修改",
                                "metrics": {"meaningful": False, "too_short": True},
                            }
                        )
                        continue
                    filtered_replacements.append(item)
                raw_replacements = filtered_replacements
            edited, changes, patch_metrics, patch_pairs, rejected_patches = _apply_paragraph_replacements(
                full_copy,
                raw_replacements,
                immutable_lines,
                action_id,
            )
            rejected_patches = [*pre_rejected, *rejected_patches]
            round_audit: dict[str, Any] | None = None
            if patch_pairs:
                round_audit = _audit_copy(
                    edited,
                    materials,
                    source_copy=full_copy,
                    edit_action=action_id,
                    edit_source=source_target,
                    edit_replacements=patch_pairs,
                )
                audit = round_audit
                trace.append(_trace_item(round_audit))
                raw_checks = round_audit.get("data", {}).get("edit_check", {}).get("patch_checks", [])
                checks = {
                    int(item.get("paragraph_index")): item
                    for item in (raw_checks if isinstance(raw_checks, list) else [])
                    if isinstance(item, dict) and str(item.get("paragraph_index") or "").isdigit()
                }
                for pair, change, metric in zip(patch_pairs, changes, patch_metrics):
                    index = int(pair["paragraph_index"])
                    check = checks.get(index)
                    if check and bool(check.get("passed")):
                        accepted_patches[index] = {
                            "pair": pair,
                            "change": change,
                            "metric": metric,
                            "check": check,
                        }
                    else:
                        rejected_patches.append(
                            {
                                "paragraph_index": index,
                                "reason": "该段未通过本轮事实与风格审校",
                                "audit": check or {},
                            }
                        )
            if len(accepted_patches) >= int(action.get("min_changes") or 1):
                accepted_blocks = [block.strip() for block in re.split(r"\n{2,}", full_copy) if block.strip()]
                for index, item in accepted_patches.items():
                    accepted_blocks[index - 1] = str(item["pair"]["edited"])
                edited = "\n\n".join(accepted_blocks)
                changes = [accepted_patches[index]["change"] for index in sorted(accepted_patches)]
                patch_metrics = [accepted_patches[index]["metric"] for index in sorted(accepted_patches)]
                metrics = {
                    **_edit_difference(source_target, edited, action_id),
                    "meaningful": True,
                    "valid_patch_count": len(accepted_patches),
                    "rejected_patch_count": len(rejected_patches),
                    "patches": patch_metrics,
                }
                if length_config["mode"] == "manual" and not _copy_length_in_range(edited, length_config):
                    raise SkillExecutionError(
                        "EDIT_LENGTH_CONSTRAINT_FAILED",
                        f"AI 编辑后为 {_copy_length(edited)} 字，未满足 {length_config['min']}-{length_config['max']} 字硬性范围",
                    )
                audit_data = {
                    "passed": True,
                    "critical_issues": [],
                    "unsupported_claims": [],
                    "claim_checks": [],
                    "interpretive_checks": [],
                    "edit_check": {
                        "goal_passed": True,
                        "meaningful_change": True,
                        "assessment": "仅合并逐段事实与风格审校均通过的结构改写。",
                        "changes": changes,
                        "patch_checks": [accepted_patches[index]["check"] for index in sorted(accepted_patches)],
                    },
                    "style_issues": [],
                    "revision_instructions": [],
                    "scores": {},
                }
                return {
                    "mode": action["mode"],
                    "text": edited,
                    "changes": changes,
                    "metrics": metrics,
                    "audit": audit_data,
                    "trace": trace,
                }
            last_issue_code = "EDIT_QUALITY_FAILED" if audit and not audit["passed"] else "EDIT_NO_MEANINGFUL_CHANGE"
            last_issue = (
                "部分段落虽完成重写，但未达到事实与风格审校要求"
                if audit and not audit["passed"]
                else (
                    "DeepSeek 返回的收束结果没有压缩到原段长度的 55%-75%"
                    if action_id == "shorten"
                    else "DeepSeek 返回的段落没有发生句子骨架或思考推进上的实质变化"
                )
            )
            metrics = {
                "meaningful": bool(accepted_patches),
                "valid_patch_count": len(accepted_patches),
                "rejected_patch_count": len(rejected_patches),
                "patches": [accepted_patches[index]["metric"] for index in sorted(accepted_patches)],
                "rejected_patches": rejected_patches,
            }
            shallow_indexes = {
                int(item["paragraph_index"])
                for item in rejected_patches
                if isinstance(item, dict)
                and isinstance(item.get("paragraph_index"), int)
                and isinstance(item.get("metrics"), dict)
            }
            forbidden_patch_indexes.update(shallow_indexes)
            correction = (
                f"\n上一轮累计只有 {len(accepted_patches)} 段通过审校，还需要至少 "
                f"{max(0, int(action.get('min_changes') or 1) - len(accepted_patches))} 段真正结构重写。"
                "只输出新的未锁定段落，不要重交已通过或被判定为浅改的段落。"
            )
            if action_id == "shorten":
                correction += (
                    "\n上一版没有达到明确的字符区间。新一轮必须删除完整信息单元，"
                    "不能只删修饰词或缩写短语；严格按本轮目标段旁标出的非标点字符区间输出。"
                )
            if forbidden_patch_indexes:
                correction += f"\n禁止选择第 {', '.join(str(item) for item in sorted(forbidden_patch_indexes))} 段。"
            if rejected_patches:
                correction += "\n本轮被拒绝的原因：" + json.dumps(rejected_patches, ensure_ascii=False)
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(
                    {**payload, "_edit_excluded_paragraphs": sorted(forbidden_patch_indexes)},
                    action,
                    correction,
                )
                trace.append(_trace_item(result))
            continue
        else:
            edited = str(data.get("text") or "").strip()
            changes = _clean_edit_changes(data.get("changes"))
        if not edited:
            last_issue_code = "EDIT_SCHEMA_INVALID"
            last_issue = "编辑 Skill 没有返回有效正文"
            correction = "\n上一版没有返回可应用的改写正文。请严格按当前模式的输出契约重新生成。"
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            continue
        if len(changes) < int(action.get("min_changes") or 1):
            rejected_as_shallow = any(
                isinstance(item, dict) and isinstance(item.get("metrics"), dict)
                for item in rejected_patches
            ) or bool(forbidden_patch_indexes)
            last_issue_code = (
                "EDIT_NO_MEANINGFUL_CHANGE"
                if action["mode"] == "paragraph_patch" and rejected_as_shallow
                else "EDIT_CHANGE_SUMMARY_MISSING"
            )
            last_issue = (
                "DeepSeek 返回的段落没有发生句子骨架或思考推进上的实质变化"
                if last_issue_code == "EDIT_NO_MEANINGFUL_CHANGE"
                else "编辑 Skill 没有完成足够的关键改写或说明"
            )
            metrics = {
                "meaningful": False,
                "valid_patch_count": len(patch_metrics),
                "rejected_patch_count": len(rejected_patches),
                "patches": patch_metrics,
                "rejected_patches": rejected_patches,
            }
            shallow_indexes = {
                int(item["paragraph_index"])
                for item in rejected_patches
                if isinstance(item, dict)
                and isinstance(item.get("paragraph_index"), int)
                and isinstance(item.get("metrics"), dict)
            }
            forbidden_patch_indexes.update(shallow_indexes)
            correction = f"\n上一版只返回了 {len(changes)} 项有效变化，未达到本动作至少 {action.get('min_changes', 1)} 项的要求。请重新改写，并为每个真实变化给出 point、location、reason，禁止写空泛说明。"
            if action["mode"] == "paragraph_patch" and forbidden_patch_indexes:
                correction += (
                    f"\n本次重试禁止再次选择第 {', '.join(str(item) for item in sorted(forbidden_patch_indexes))} 段。"
                    "请从其他未锁定段落中选择至少三段：先只提取事实，再完全重写句子骨架与思考推进；"
                    "不要复制原段完整句子，也不要声称新增了原文已有内容。"
                )
            if rejected_patches:
                correction += "\n以下补丁已被逐段质量门拒绝，请不要重复同类问题：" + json.dumps(
                    rejected_patches,
                    ensure_ascii=False,
                )
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            continue
        metrics = _edit_difference(source_target, edited, action_id)
        if action["mode"] == "paragraph_patch":
            metrics = {
                **metrics,
                "meaningful": len(patch_metrics) >= int(action.get("min_changes") or 1),
                "valid_patch_count": len(patch_metrics),
                "rejected_patch_count": len(rejected_patches),
                "patches": patch_metrics,
            }
        if not metrics["meaningful"]:
            last_issue_code = "EDIT_NO_MEANINGFUL_CHANGE"
            last_issue = "DeepSeek 返回的内容与原文没有实质区别"
            correction = (
                "\n上一版与原文相同、只改了标点或改动幅度不足，没有完成编辑任务。"
                "请保留事实，但必须重构句法、观察角度或思考推进。"
            )
            if action_id == "shorten":
                correction += (
                    "收束目标段必须保留原段非标点字符的 55%-75%。请删除至少一个完整的重复解释、"
                    "同义罗列或不再推进叙事的信息单元，再用剩余事实重新组织段落；不能只删几个词。"
                )
            if action_id == "more-personal":
                correction += "必须整段重写至少一处，优先处理两处；每一处都要改变句子骨架或思考推进，不能用删词和缩写短语凑变化。"
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            continue
        if action["mode"] == "selection" and _selection_output_out_of_scope(
            selected_text,
            edited,
            full_copy,
        ):
            last_issue_code = "EDIT_SELECTION_OUT_OF_SCOPE"
            last_issue = "局部改写输出了过长文本或全文上下文"
            correction = "\n上一版没有遵守局部改写范围。你只能改写“需要处理的文本”本身，不得输出全文，不得新增段落，不得补写任何经历。"
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            continue
        candidate = (
            _candidate_with_selection(payload, edited)
            if action["mode"] == "selection"
            else edited
        )
        if length_config["mode"] == "manual" and not _copy_length_in_range(candidate, length_config):
            last_issue_code = "EDIT_LENGTH_CONSTRAINT_FAILED"
            last_issue = f"AI 编辑后未满足 {length_config['min']}-{length_config['max']} 字硬性范围"
            correction = (
                f"\n上一版应用到全文后为 {_copy_length(candidate)} 字。"
                f"请在不改变编辑目标的前提下，将应用后的全文严格保持在 "
                f"{length_config['min']}-{length_config['max']} 字。"
            )
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            continue
        missing_locked = [item for item in immutable_lines if item not in candidate]
        if missing_locked:
            last_issue_code = "LOCKED_PARAGRAPH_CHANGED"
            last_issue = "编辑结果改动了锁定段落"
            correction = "\n上一版改动了锁定段落。必须逐字保留以下段落且不得移动：" + json.dumps(
                missing_locked,
                ensure_ascii=False,
            )
            if repair_attempt < max_edit_attempts - 1:
                result = _edit_copy_once(payload, action, correction)
                trace.append(_trace_item(result))
            continue
        if action["mode"] == "selection":
            audit = _audit_paragraph_replacements(
                [
                    {
                        "paragraph_index": 1,
                        "original": selected_text,
                        "edited": edited,
                    }
                ],
                materials,
                full_copy,
                candidate,
                "selection-polish",
            )
        else:
            audit = _audit_copy(
                candidate,
                materials,
                source_copy=full_copy,
                edit_action=action_id,
                edit_source=source_target,
                edit_replacements=patch_pairs,
            )
        trace.append(_trace_item(audit))
        if audit["passed"]:
            break
        last_issue_code = "EDIT_QUALITY_FAILED"
        last_issue = "DeepSeek 编辑结果未完成目标或未通过事实审校"
        correction = "\n上一版未通过审校，请严格按以下意见重新编辑：" + json.dumps(
            audit["data"], ensure_ascii=False
        )
        if action["mode"] == "selection":
            correction += "\n这次仍然只输出选中文本的替换结果，允许更小幅度修改，禁止新增时间、程度、心理状态或因果判断。"
        if repair_attempt < max_edit_attempts - 1:
            result = _edit_copy_once(payload, action, correction)
            trace.append(_trace_item(result))
    else:
        raise SkillExecutionError(
            last_issue_code,
            last_issue,
            json.dumps({"metrics": metrics, "audit": audit.get("data", {}) if audit else {}}, ensure_ascii=False),
        )
    if not audit or not audit["passed"]:
        raise SkillExecutionError(
            "EDIT_QUALITY_FAILED",
            "DeepSeek 编辑结果未通过事实审校",
            json.dumps(audit.get("data", {}) if audit else {}, ensure_ascii=False),
        )
    return {
        "mode": action["mode"],
        "text": edited,
        "changes": changes,
        "metrics": metrics,
        "audit": audit["data"],
        "trace": trace,
    }


async def edit_copy(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_edit_copy_sync, payload)


def _rewrite_selection_sync(payload: dict[str, Any]) -> str:
    result = _edit_copy_sync(
        {
            **payload,
            "action": "selection-polish",
            "command": payload.get("command") or "更像我的口吻，减少 AI 味",
        }
    )
    return str(result.get("text") or "").strip()


async def rewrite_selection(payload: dict[str, Any]) -> str:
    return await asyncio.to_thread(_rewrite_selection_sync, payload)


def _strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^~~~(?:markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*~~~$", "", cleaned)
    return cleaned.strip()


def _analyze_style_update_sync(filename: str, text: str) -> dict[str, Any]:
    if len(text.strip()) < 300:
        raise SkillExecutionError("REFERENCE_TOO_SHORT", "历史文稿正文过短，无法可靠蒸馏")
    style_version, current_style = load_writing_skill()
    analysis = run_json(
        "distill-personal-style",
        f"""
独立分析下面这篇历史 Vlog 文稿。区分稳定风格证据与仅属于本篇的题材事实。

文件名：{filename}

历史文稿：
{text[:16000]}

输出 JSON：
{{
  "narrative_patterns": [{{"pattern": "", "evidence": "", "confidence": 0}}],
  "sentence_rhythm": [],
  "emotional_logic": [],
  "opening_patterns": [],
  "ending_patterns": [],
  "recurring_language": [],
  "anti_patterns": [],
  "one_off_facts": []
}}
只输出 JSON。
""".strip(),
        max_tokens=2600,
        temperature=0.24,
    )
    document_id, created = save_reference_document(filename, text, analysis["data"])
    if not created:
        raise SkillExecutionError("REFERENCE_DUPLICATE", "这篇历史文稿已经蒸馏过")

    synthesis = run_text(
        "distill-personal-style",
        f"""
基于当前已发布风格和新证据，生成一份完整的候选个人创作 Skill。
不要追加日志，不要包含历史稿件中的具体事件，不要降低事实边界。

当前发布版本：{style_version}

当前风格：
{current_style[:14000]}

新证据：
{json.dumps(analysis["data"], ensure_ascii=False)}

候选 Skill 必须包含：创作者定位、输入协议、事实边界、叙事结构、语言节奏、开头规范、结尾规范、书库使用原则、禁止事项和输出形态。
只输出完整 Markdown 正文，不使用代码围栏。
""".strip(),
        max_tokens=3600,
        temperature=0.38,
    )
    candidate_content = _strip_markdown_fence(synthesis["text"])
    if len(candidate_content) < 800:
        raise SkillExecutionError("STYLE_CANDIDATE_INVALID", "候选创作 Skill 内容不完整")

    evaluation = run_json(
        "distill-personal-style",
        f"""
评估候选个人创作 Skill 是否值得发布。重点检查证据支持、是否过拟合单篇题材、是否保留事实边界，以及规则是否互相冲突。

新文稿证据：
{json.dumps(analysis["data"], ensure_ascii=False)}

候选 Skill：
{candidate_content[:16000]}

输出 JSON：
{{
  "passed": true,
  "evidence_coverage": 0,
  "overfit_risk": 0,
  "conflicts": [],
  "improvements": [],
  "summary": ""
}}
只输出 JSON。
""".strip(),
        max_tokens=1400,
        temperature=0.15,
    )
    if not bool(evaluation["data"].get("passed")):
        raise SkillExecutionError(
            "STYLE_CANDIDATE_REJECTED",
            "候选创作 Skill 未通过蒸馏评测",
            json.dumps(evaluation["data"], ensure_ascii=False),
        )
    candidate = create_style_candidate(
        document_id,
        candidate_content,
        analysis["data"],
        evaluation["data"],
    )
    return {
        "filename": filename,
        "analysis": analysis["data"],
        "evaluation": evaluation["data"],
        "candidate": candidate,
        "mode": "style_candidate_created",
        "trace": [
            _trace_item(analysis),
            _trace_item(synthesis),
            _trace_item(evaluation),
        ],
    }


async def analyze_style_update(filename: str, text: str) -> dict[str, Any]:
    return await asyncio.to_thread(_analyze_style_update_sync, filename, text)


def _analyze_style_batch_legacy_sync(documents: list[dict[str, str]]) -> dict[str, Any]:
    clean_documents = [
        {
            "filename": str(item.get("filename") or "").strip(),
            "text": str(item.get("text") or "").strip(),
        }
        for item in documents
        if str(item.get("filename") or "").strip() and str(item.get("text") or "").strip()
    ]
    if not clean_documents:
        raise SkillExecutionError("REFERENCE_BATCH_EMPTY", "没有可蒸馏的历史文稿")
    for item in clean_documents:
        if len(item["text"]) < 300:
            raise SkillExecutionError(
                "REFERENCE_TOO_SHORT",
                f"{item['filename']} 正文过短，无法可靠蒸馏",
            )

    style_version, current_style = load_writing_skill()
    feedback_evidence = recent_style_feedback(30)
    trace: list[dict[str, Any]] = []
    document_evidence: list[dict[str, Any]] = []
    source_document_ids: list[int] = []

    for item in clean_documents:
        analysis = run_json(
            "distill-personal-style",
            f"""
独立分析下面这篇历史 Vlog 文稿。区分稳定风格证据与仅属于本篇的题材事实。

文件名：{item["filename"]}

历史文稿：
{item["text"][:16000]}

输出 JSON：
{{
  "narrative_patterns": [{{"pattern": "", "evidence": "", "confidence": 0}}],
  "sentence_rhythm": [],
  "emotional_logic": [],
  "opening_patterns": [],
  "ending_patterns": [],
  "recurring_language": [],
  "anti_patterns": [],
  "one_off_facts": []
}}
只输出 JSON。
""".strip(),
            max_tokens=2600,
            temperature=0.24,
        )
        trace.append(_trace_item(analysis))
        document_id, created = save_reference_document(
            item["filename"],
            item["text"],
            analysis["data"],
        )
        source_document_ids.append(document_id)
        document_evidence.append(
            {
                "document_id": document_id,
                "filename": item["filename"],
                "created": created,
                "chars": len(item["text"]),
                "analysis": analysis["data"],
            }
        )

    synthesis = run_text(
        "distill-personal-style",
        f"""
基于当前已发布风格和五篇历史文稿证据，生成一份完整的候选个人创作 Skill。
这是一轮批量蒸馏，不要按单篇追加日志，要综合提炼稳定风格。

当前发布版本：{style_version}

当前风格：
{current_style[:14000]}

批量证据：
{json.dumps(document_evidence, ensure_ascii=False)[:26000]}

候选 Skill 必须包含：创作者定位、输入协议、事实边界、叙事结构、语言节奏、开头规范、结尾规范、书库使用原则、禁止事项和输出形态。
必须明确哪些是稳定风格，哪些只是单篇题材，不得把历史文稿的具体事件迁移到未来创作。
只输出完整 Markdown 正文，不使用代码围栏。
""".strip(),
        max_tokens=4200,
        temperature=0.34,
    )
    trace.append(_trace_item(synthesis))
    candidate_content = _strip_markdown_fence(synthesis["text"])
    if len(candidate_content) < 900:
        raise SkillExecutionError("STYLE_CANDIDATE_INVALID", "批量候选创作 Skill 内容不完整")

    evaluation = run_json(
        "distill-personal-style",
        f"""
评估这份批量候选个人创作 Skill 是否值得进入待发布。重点检查五篇证据覆盖、是否过拟合单篇题材、是否保留事实边界，以及规则是否互相冲突。

批量证据摘要：
{json.dumps(document_evidence, ensure_ascii=False)[:22000]}

候选 Skill：
{candidate_content[:18000]}

输出 JSON：
{{
  "passed": true,
  "evidence_coverage": 0,
  "overfit_risk": 0,
  "conflicts": [],
  "improvements": [],
  "summary": ""
}}
只输出 JSON。
""".strip(),
        max_tokens=1600,
        temperature=0.12,
    )
    trace.append(_trace_item(evaluation))
    if not bool(evaluation["data"].get("passed")):
        raise SkillExecutionError(
            "STYLE_CANDIDATE_REJECTED",
            "批量候选创作 Skill 未通过蒸馏评测",
            json.dumps(evaluation["data"], ensure_ascii=False),
        )

    candidate = create_style_candidate(
        source_document_ids[0],
        candidate_content,
        {
            "mode": "batch_style_distillation",
            "current_style_version": style_version,
            "source_document_ids": source_document_ids,
            "documents": document_evidence,
        },
        evaluation["data"],
    )
    return {
        "documents": document_evidence,
        "evaluation": evaluation["data"],
        "candidate": candidate,
        "mode": "batch_style_candidate_created",
        "trace": trace,
    }


def _analyze_style_batch_sync(documents: list[dict[str, str]]) -> dict[str, Any]:
    """Classify a batch once, then synthesize one candidate Skill."""
    clean_documents = [
        {
            "filename": str(item.get("filename") or "").strip(),
            "text": str(item.get("text") or "").strip(),
        }
        for item in documents
        if str(item.get("filename") or "").strip() and str(item.get("text") or "").strip()
    ]
    if not clean_documents:
        raise SkillExecutionError("REFERENCE_BATCH_EMPTY", "没有可蒸馏的历史文稿")
    short_files = [item["filename"] for item in clean_documents if len(item["text"]) < 300]
    if short_files:
        raise SkillExecutionError(
            "REFERENCE_TOO_SHORT",
            "以下文稿正文过短，无法可靠蒸馏：" + "、".join(short_files),
        )

    style_version, current_style = load_writing_skill()
    feedback_evidence = recent_style_feedback(30)
    corpus = "\n\n".join(
        f"===== {item['filename']} =====\n{item['text'][:9000]}"
        for item in clean_documents
    )
    analysis = run_json(
        "distill-personal-style",
        f"""一次性分析这一批历史 Vlog 文稿，提取可进入个人创作 Skill 的跨文稿证据。

本产品的历史视频文案批次默认由已完成并拍摄的视频正文组成。除非用户明确标记某篇未完成，否则每篇都必须按成熟正文处理：maturity=final_script，weight=1.0。文稿以何种手写格式保存、是否混有 BGM、镜头、动作、占位符或制作批注，不改变正文成熟度；只分析其中的文字性文案，制作标记放入 excluded_noise，不参与成熟度判断，也不能成为写作规则。

历史文稿：
{corpus[:52000]}

输出 JSON：
{{
  "documents": [
    {{
      "filename": "",
      "maturity": "final_script",
      "weight": 1.0,
      "strengths": [],
      "stable_evidence": [{{"dimension": "opening|narrative|rhythm|turn|audience|ending", "pattern": "", "evidence": "不超过60字的原文证据"}}],
      "excluded_noise": []
    }}
  ],
  "stable_personal_dna": [],
  "new_repeated_patterns": [],
  "one_off_expressions": [],
  "production_only_patterns": [],
  "excluded_placeholders": []
}}

必须覆盖每个文件。只有跨两篇以上重复出现、或在成熟成稿中非常明确的模式才能进入 stable_personal_dna；不得把具体事件迁移成通用风格。只输出 JSON。""".strip(),
        max_tokens=4400,
        temperature=0.2,
    )
    evidence = analysis["data"]
    classified = evidence.get("documents")
    if not isinstance(classified, list) or len(classified) != len(clean_documents):
        raise SkillExecutionError("STYLE_CLASSIFICATION_INVALID", "批量蒸馏未完整返回文稿分级")

    by_filename = {
        str(item.get("filename") or ""): item
        for item in classified
        if isinstance(item, dict)
    }
    # This product batch is explicitly a corpus of published video copy. Keep
    # production annotations out of the style evidence without down-weighting
    # the completed writing itself.
    for item in classified:
        if isinstance(item, dict):
            item["maturity"] = "final_script"
            item["weight"] = 1.0
            item["content_scope"] = "正文文字；忽略 BGM、镜头、动作、占位符和制作批注"
    source_document_ids: list[int] = []
    document_evidence: list[dict[str, Any]] = []
    for document in clean_documents:
        item_analysis = by_filename.get(document["filename"], {})
        document_id, created = save_reference_document(
            document["filename"],
            document["text"],
            item_analysis,
        )
        source_document_ids.append(document_id)
        document_evidence.append(
            {
                "document_id": document_id,
                "filename": document["filename"],
                "created": created,
                "chars": len(document["text"]),
                **item_analysis,
            }
        )

    synthesis = run_text(
        "distill-personal-style",
        f"""基于当前已发布 Skill 与本批分级证据，生成完整候选个人创作 Skill。

当前发布版本：{style_version}

当前 Skill：
{current_style[:18000]}

终稿反馈证据（keep 表示保留，revise 表示需要修正；仅吸收明确、重复或带具体意见的反馈）：
{json.dumps(feedback_evidence, ensure_ascii=False)[:14000]}

本批分级证据：
{json.dumps(evidence, ensure_ascii=False)[:30000]}

要求：
1. 保留已有稳定规则，只吸收有跨文稿证据的新模式。
2. 本批每篇都是成熟正文，统一按 final_script / 1.0 处理；占位符、xxx、未完成书本金句、BGM 和镜头批注只作为 excluded_noise，不得变成写作规则。
3. 新增连续设问、自我对话、重复推进、辩证反转、直接观众交流与自我暴露时，都写成可执行规则并标明使用边界。
4. 不召回历史原段落，不把历史文稿的具体事件迁移到未来创作。
5. 输出包含：创作者定位、输入协议、事实边界、稳定风格 DNA、叙事引擎、语言节奏、开头与结尾、书库原则、禁止事项、输出形态。

只输出完整 Markdown 正文，不使用代码围栏。""".strip(),
        max_tokens=4600,
        temperature=0.3,
    )
    candidate_content = _strip_markdown_fence(synthesis["text"])
    if len(candidate_content) < 1200:
        raise SkillExecutionError("STYLE_CANDIDATE_INVALID", "批量候选创作 Skill 内容不完整")

    evaluation = {
        "passed": True,
        "review_required": True,
        "ab_test_required": True,
        "source_count": len(clean_documents),
        "classification": {
            item["filename"]: {
                "maturity": item.get("maturity", "final_script"),
                "weight": item.get("weight", 1.0),
            }
            for item in document_evidence
        },
        "summary": "已完成分级蒸馏；候选版本需通过同素材 A/B 对照后再发布。",
    }
    candidate = create_style_candidate(
        source_document_ids[0],
        candidate_content,
        {
            "mode": "weighted_batch_distillation",
            "current_style_version": style_version,
            "source_document_ids": source_document_ids,
            "documents": document_evidence,
            "stable_personal_dna": evidence.get("stable_personal_dna", []),
            "new_repeated_patterns": evidence.get("new_repeated_patterns", []),
            "excluded_placeholders": evidence.get("excluded_placeholders", []),
            "feedback_count": len(feedback_evidence),
        },
        evaluation,
    )
    return {
        "documents": document_evidence,
        "evaluation": evaluation,
        "candidate": candidate,
        "mode": "weighted_batch_style_candidate_created",
        "trace": [_trace_item(analysis), _trace_item(synthesis)],
    }


async def analyze_style_batch(documents: list[dict[str, str]]) -> dict[str, Any]:
    return await asyncio.to_thread(_analyze_style_batch_sync, documents)


def _item_lines(items: Any) -> str:
    if not isinstance(items, list):
        return ""
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("label") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            lines.append(f"{index}. {text}")
    return "\n".join(lines)


def _string_lines(items: Any) -> str:
    if isinstance(items, list):
        return "\n".join(str(item).strip() for item in items if str(item).strip())
    return str(items or "").strip()


def _parse_creation_materials_sync(raw_text: str) -> dict[str, Any]:
    raw_text = str(raw_text or "").strip()
    if len(raw_text) < 20:
        raise SkillExecutionError("CLIPBOARD_TEXT_EMPTY", "请先粘贴或读取一段创作素材")
    result = run_json(
        "parse-creation-materials",
        f"""
识别下面的创作者原始素材，并整理为匣中镜创作项目输入。只整理，不写成文案。

原始素材：
{raw_text[:18000]}

输出 JSON：
{{
  "theme": "",
  "opening_items": [],
  "insight_items": [],
  "daily_items": [
    {{"label": "短标签", "text": "保留原意的日常素材"}}
  ],
  "event_items": [
    {{"label": "短标签", "text": "保留原意的核心事件"}}
  ],
  "quotes": [],
  "ending_reference": [],
  "import_summary": ""
}}

规则：
1. 不新增事实，不补全地点、人物、动作、日期、结果或心理状态。
2. 原文中已有编号的日常素材和核心事件要逐条保留，不要合并成一坨。
3. “Hi，我是……”这类开场口播放入 opening_items。
4. 大段世界观、方法论、价值判断拆成 insight_items，不再单独创建“额外思考”。
5. 可以把“回忆”识别为 theme；如果有更具体主题，以更具体主题为准。
6. quotes 只放需要逐字保留的原话、短句或显著金句。
只输出 JSON。
""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=3000,
        temperature=0.12,
    )
    data = result["data"]
    daily_items = data.get("daily_items")
    event_items = data.get("event_items")
    if not isinstance(daily_items, list) or not isinstance(event_items, list):
        raise SkillExecutionError("CLIPBOARD_PARSE_SCHEMA_INVALID", "剪贴板识别结果缺少素材列表")
    opening_items = data.get("opening_items", data.get("opening_reference", []))
    insight_items = data.get("insight_items", data.get("insight", ""))
    legacy_thoughts = data.get("extra_thoughts", [])
    if legacy_thoughts:
        insight_items = (insight_items if isinstance(insight_items, list) else [insight_items])
        insight_items += legacy_thoughts if isinstance(legacy_thoughts, list) else [legacy_thoughts]
    materials = {
        "theme": str(data.get("theme") or "").strip(),
        "opening": _string_lines(opening_items),
        "insight": _string_lines(insight_items),
        "daily": _item_lines(daily_items),
        "event": _item_lines(event_items),
        "quotes": _string_lines(data.get("quotes")),
        "ending_reference": _string_lines(data.get("ending_reference")),
        }
    return {
        "materials": materials,
        "structured": {
            "opening_items": opening_items if isinstance(opening_items, list) else [],
            "insight_items": insight_items if isinstance(insight_items, list) else [insight_items] if str(insight_items).strip() else [],
            "daily_items": daily_items,
            "event_items": event_items,
            "quotes": data.get("quotes") if isinstance(data.get("quotes"), list) else [],
            "ending_reference": data.get("ending_reference") if isinstance(data.get("ending_reference"), list) else [],
        },
        "import_summary": str(data.get("import_summary") or "").strip(),
        "trace": [_trace_item(result)],
    }


async def parse_creation_materials(raw_text: str) -> dict[str, Any]:
    return await asyncio.to_thread(_parse_creation_materials_sync, raw_text)


def _source_text(results: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, result in enumerate(results[:18]):
        evidence = (result.get("raw_content") or result.get("content") or "")[:2400]
        blocks.append(
            f"""
[SOURCE {index}]
书名：{result.get("book", "")}
作者：{result.get("author", "")}
标题：{result.get("title", "")}
URL：{result.get("url", "")}
检索摘要与页面内容：
{evidence}
""".strip()
        )
    return "\n\n".join(blocks)


TRADITIONAL_QUOTE_CHARS = str.maketrans(
    {
        "來": "来",
        "劍": "剑",
        "傳": "传",
        "經": "经",
        "長": "长",
        "為": "为",
        "無": "无",
        "萬": "万",
        "與": "与",
        "於": "于",
        "後": "后",
        "裡": "里",
        "裏": "里",
        "說": "说",
        "時": "时",
        "過": "过",
        "個": "个",
        "這": "这",
        "選": "选",
        "擇": "择",
        "實": "实",
        "體": "体",
        "風": "风",
        "險": "险",
        "動": "动",
        "馬": "马",
        "爾": "尔",
        "薩": "萨",
        "諸": "诸",
    }
)


def _normalize_quote_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").translate(TRADITIONAL_QUOTE_CHARS)
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]", "", normalized).lower()


def _source_contains_quote(source: dict[str, Any], quote: str) -> bool:
    body = str(source.get("raw_content") or "") + "\n" + str(source.get("content") or "")
    normalized_quote = _normalize_quote_text(quote)
    return len(normalized_quote) >= 4 and normalized_quote in _normalize_quote_text(body)


def _book_matches(expected: str, value: str) -> bool:
    def clean(text: str) -> str:
        return re.sub(r"[\s《》<>\"'“”‘’·]", "", text or "").lower()

    expected_clean = clean(expected)
    value_clean = clean(value)
    return bool(expected_clean and value_clean and (
        expected_clean == value_clean
        or expected_clean in value_clean
        or value_clean in expected_clean
    ))


def _candidate_meta(raw_candidates: list[Any], quote: str, source_index: int) -> dict[str, Any]:
    normalized = _normalize_quote_text(quote)
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        item_quote = _normalize_quote_text(str(item.get("quote") or ""))
        if item_quote != normalized:
            continue
        try:
            item_source_index = int(item.get("source_index"))
        except (TypeError, ValueError):
            item_source_index = source_index
        if item_source_index == source_index:
            return item
    return {}


BOOK_QUERY_SEEDS: dict[str, list[str]] = {
    "jianlai": [
        "《剑来》 读过的书 看过的山水 见到的人事 脚下的路 原文",
        "《剑来》 人生往往如此 老天爷 按着脑袋 往前走 原文",
        "《剑来》 人生 往前走 岔路 原文 语录",
    ],
    "musk": [
        "《埃隆·马斯克传》 沃尔特·艾萨克森 风险 容忍度 原文",
        "《埃隆·马斯克传》 至暗时期 原文 片段",
        "《埃隆·马斯克传》 五步工作法 删除 简化 自动化 原文",
    ],
    "daode": [
        "《道德经》 知足不辱 知止不殆 可以长久 原文",
        "《道德经》 自知者明 自胜者强 原文",
        "《道德经》 千里之行 始于足下 原文",
    ],
}


def _expand_book_queries(
    selected_book_ids: list[str],
    query_items: list[dict[str, str]],
) -> list[dict[str, str]]:
    by_book: dict[str, list[str]] = {book_id: [] for book_id in selected_book_ids}
    for item in query_items:
        book_id = str(item.get("book_id") or "")
        query = re.sub(r"\s+", " ", str(item.get("query") or "")).strip()
        if book_id in by_book and query:
            by_book[book_id].append(query[:120])

    for book_id in selected_book_ids:
        by_book[book_id].extend(BOOK_QUERY_SEEDS.get(book_id, []))

    deduped: dict[str, list[str]] = {}
    for book_id, queries in by_book.items():
        seen: set[str] = set()
        deduped[book_id] = []
        for query in queries:
            key = _normalize_quote_text(query)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped[book_id].append(query)
            if len(deduped[book_id]) >= 3:
                break

    # Interleave books so the source window cannot be filled by one book only.
    expanded: list[dict[str, str]] = []
    for index in range(3):
        for book_id in selected_book_ids:
            queries = deduped.get(book_id) or []
            if index < len(queries):
                expanded.append({"book_id": book_id, "query": queries[index]})
    return expanded


def _select_verified_quotes_for_book(
    book_id: str,
    draft: str,
    tensions: Any,
    book_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not book_results:
        return [], []
    book = _available_books()[book_id]
    sources = _source_text(book_results)
    trace: list[dict[str, Any]] = []
    selection = run_json(
        "research-book-quotes",
        f"""
只处理这一本书：{book["title"]}，作者：{book["author"]}。
只能从提供的 SOURCE 页面内容中选择契合文案的短原句。原句必须逐字出现在对应 SOURCE 中。

当前文案：
{draft[:10000]}

文案张力：
{json.dumps(tensions, ensure_ascii=False)}

联网来源：
{sources}

输出 JSON：
{{
  "candidates": [
    {{
      "book": "{book["title"]}",
      "quote": "逐字原句",
      "attribution": "可以被来源支持的作者、书中人物或作品本身",
      "source_index": 0,
      "fit": "为什么契合当前文案",
      "insert_after": "建议植入位置"
    }}
  ]
}}

选择标准：
1. 宁可少选，也不要输出无法逐字定位的句子。
2. 引文必须能以“某某在《XXX》中写道：”“《XXX》里有提到：”或“XXXXX”（《XXX》）进入文案。
3. 不要使用模型记忆、常识或未出现在 SOURCE 的名句。
找不到逐字证据就返回空 candidates。最多三条。只输出 JSON。
""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=1800,
        temperature=0.12,
    )
    trace.append(_trace_item(selection))
    raw_candidates = selection["data"].get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        return [], trace

    verification = run_json(
        "verify-book-quotes",
        f"""
核验候选引文。只能依据 SOURCE 内容，不能使用模型记忆。

候选：
{json.dumps(raw_candidates, ensure_ascii=False)}

来源：
{sources}

输出 JSON：
{{
  "candidates": [
    {{
      "verified": true,
      "book": "{book["title"]}",
      "quote": "",
      "attribution": "",
      "source_index": 0,
      "evidence_text": "包含原句的来源证据",
      "reason": "",
      "confidence": 0
    }}
  ]
}}
无法逐字核验就将 verified 设为 false。只输出 JSON。
""".strip(),
        max_tokens=2200,
        temperature=0.06,
    )
    trace.append(_trace_item(verification))
    verified_raw = verification["data"].get("candidates")
    if not isinstance(verified_raw, list):
        raise SkillExecutionError("QUOTE_VERIFY_SCHEMA_INVALID", "金句核验结果结构错误")

    verified: list[dict[str, Any]] = []
    for item in verified_raw:
        if not isinstance(item, dict) or not bool(item.get("verified")):
            continue
        try:
            source_index = int(item.get("source_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= source_index < len(book_results):
            continue
        source = book_results[source_index]
        quote = str(item.get("quote") or "").strip().strip("“”\"")
        if len(_normalize_quote_text(quote)) > 140 or not _source_contains_quote(source, quote):
            continue
        if not _book_matches(source["book"], str(item.get("book") or "")):
            continue
        attribution = str(item.get("attribution") or "").strip()
        if not attribution:
            attribution = source["book"]
        meta = _candidate_meta(raw_candidates, quote, source_index)
        verified.append(
            {
                "book": source["book"],
                "book_id": source["book_id"],
                "quote": quote,
                "attribution": attribution,
                "url": source["url"],
                "source_title": source["title"],
                "source_index": source_index,
                "source_type": "tavily_live",
                "evidence_text": str(item.get("evidence_text") or quote),
                "fit": str(meta.get("fit") or item.get("reason") or ""),
                "insert_after": str(meta.get("insert_after") or ""),
                "verified": True,
                "confidence": item.get("confidence"),
            }
        )
        if len(verified) >= 2:
            break
    return verified, trace


def _select_verified_quotes_batch(
    selected_book_ids: list[str],
    draft: str,
    tensions: Any,
    online_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not online_results:
        return [], {}
    books = _available_books()
    verification = run_json(
        "verify-book-quotes",
        f"""从联网来源中直接选择并核验与当前文案最契合的短引文。选择和核验在一次完成，只能依据 SOURCE，不能使用模型记忆。

当前文案：
{draft[:10000]}

真实思想张力：
{json.dumps(tensions, ensure_ascii=False)}

允许书籍：
{json.dumps([books[book_id] for book_id in selected_book_ids if book_id in books], ensure_ascii=False)}

联网来源：
{_source_text(online_results)}

输出 JSON：
{{
  "candidates": [
    {{
      "verified": true,
      "book": "书名",
      "quote": "逐字出现在对应 SOURCE 的短原句",
      "attribution": "作者、书中人物或作品本身",
      "source_index": 0,
      "evidence_text": "包含原句的来源证据",
      "fit": "与当前文案思想张力的关系",
      "insert_after": "建议植入的原文位置",
      "confidence": 0
    }}
  ]
}}

规则：
1. 每本书最多一条，总计最多三条；宁可少选。
2. quote 必须逐字出现在对应 SOURCE 中，无法逐字定位就不要返回。
3. 引文必须适合以“某某在《XXX》中写道：”“《XXX》里有提到：”或“XXXXX”（《XXX》）进入文案。
4. 不得输出模型记忆中的名句，不得改写原句。只输出 JSON。""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=2600,
        temperature=0.06,
    )
    raw = verification["data"].get("candidates")
    if not isinstance(raw, list):
        raise SkillExecutionError("QUOTE_VERIFY_SCHEMA_INVALID", "批量金句核验结果结构错误")
    verified: list[dict[str, Any]] = []
    seen_books: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or not bool(item.get("verified")):
            continue
        try:
            source_index = int(item.get("source_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= source_index < len(online_results):
            continue
        source = online_results[source_index]
        book_id = str(source.get("book_id") or "")
        if book_id not in selected_book_ids or book_id in seen_books:
            continue
        quote = str(item.get("quote") or "").strip().strip("“”\"")
        if not quote or len(_normalize_quote_text(quote)) > 140:
            continue
        if not _source_contains_quote(source, quote):
            continue
        if not _book_matches(str(source.get("book") or ""), str(item.get("book") or "")):
            continue
        seen_books.add(book_id)
        verified.append(
            {
                "book": source["book"],
                "book_id": book_id,
                "quote": quote,
                "attribution": str(item.get("attribution") or books[book_id]["author"]).strip(),
                "url": source["url"],
                "source_title": source["title"],
                "source_index": source_index,
                "source_type": "tavily_live",
                "evidence_text": str(item.get("evidence_text") or quote),
                "fit": str(item.get("fit") or ""),
                "insert_after": str(item.get("insert_after") or ""),
                "verified": True,
                "confidence": item.get("confidence"),
            }
        )
        if len(verified) >= 3:
            break
    return verified, _trace_item(verification)


BOOK_SUPPORT_PROFILES: dict[str, str] = {
    "jianlai": "道路、问心、长期行走、在选择中成为自己",
    "musk": "行动、不确定性、风险、执行与代价",
    "daode": "自知、知足、取舍、顺势与克制",
}


def _generation_book_query_items(
    selected_book_ids: list[str],
    materials: dict[str, Any],
    architecture: dict[str, Any],
) -> list[dict[str, str]]:
    anchors = [
        str(materials.get("theme") or "").strip(),
        str(materials.get("insight") or "").strip(),
        str(architecture.get("central_tension") or "").strip(),
        str(architecture.get("callback") or "").strip(),
    ]
    anchor_text = re.sub(r"\s+", " ", " ".join(item for item in anchors if item)).strip()
    anchor_text = anchor_text[:90] or "人生 选择 前行"
    books = _available_books()
    return [
        {
            "book_id": book_id,
            "query": (
                f'{books[book_id]["title"]} {books[book_id]["author"]} '
                f"{anchor_text} 原文 语录 书摘"
            )[:180],
        }
        for book_id in selected_book_ids
        if book_id in books
    ]


def _book_id_from_title(title: str) -> str:
    for book_id, book in _available_books().items():
        if _book_matches(book["title"], title):
            return book_id
    return ""


def _saved_book_support_candidates(
    project_id: str,
    selected_book_ids: list[str],
) -> list[dict[str, Any]]:
    books = _available_books()
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in list_book_citations(project_id, limit=2000):
        book_id = str(item.get("book_id") or "").strip() or _book_id_from_title(str(item.get("book") or ""))
        if book_id not in selected_book_ids:
            continue
        if not is_generation_ready_citation(item):
            continue
        quote = str(item.get("quote") or "").strip().strip("“”\"「」『』")
        source_url = str(item.get("source_url") or "").strip()
        key = (book_id, _normalize_quote_text(quote))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "book": str(item.get("book") or books[book_id]["title"]),
                "book_id": book_id,
                "quote": quote,
                "attribution": str(item.get("attribution") or ""),
                "url": source_url,
                "source_title": str(item.get("source_title") or ""),
                "source_index": -1,
                "source_type": "local_note" if source_url.startswith("local-note://") else "chapter_source",
                "evidence_text": str(item.get("evidence_text") or quote),
                "fit": "已通过书库质量校验的逐字引文。",
                "verified": True,
            }
        )
    # Keep every selected book represented without making the model prompt huge.
    grouped = {book_id: [] for book_id in selected_book_ids}
    for candidate in candidates:
        grouped.setdefault(candidate["book_id"], []).append(candidate)
    balanced: list[dict[str, Any]] = []
    for index in range(max((len(items) for items in grouped.values()), default=0)):
        for book_id in selected_book_ids:
            items = grouped.get(book_id) or []
            if index < len(items):
                balanced.append(items[index])
                if len(balanced) >= 180:
                    return balanced
    return balanced


def _compact_book_search_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "book": item.get("book", ""),
            "author": item.get("author", ""),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": str(item.get("content") or "")[:900],
            "raw_content": str(item.get("raw_content") or "")[:1400],
        }
        for item in results[:12]
    ]


def _run_integrated_book_support(
    draft: str,
    materials: dict[str, Any],
    architecture: dict[str, Any],
    selected_book_ids: list[str],
    exact_candidates: list[dict[str, Any]],
    online_results: list[dict[str, Any]],
    length_config: dict[str, Any] | None = None,
    quote_strategy: str = "standard",
) -> dict[str, Any]:
    books = _available_books()
    if not selected_book_ids:
        return {
            "updated_copy": draft,
            "supports": [],
            "citations": [],
            "status": "disabled",
            "reason": "未选择精神书库。",
            "online_results": [],
            "trace": [],
        }

    if not exact_candidates:
        return {
            "updated_copy": draft,
            "supports": [],
            "citations": [],
            "status": "none",
            "reason": "本地书库暂时没有可用于直接引用的候选原句，已保留原稿。",
            "online_results": [],
            "trace": [],
        }

    local_candidates = [
        {
            "candidate_index": index,
            "book": item.get("book", ""),
            "book_id": item.get("book_id", ""),
            "quote": item.get("quote", ""),
            "attribution": item.get("attribution", ""),
            "source_title": item.get("source_title", ""),
            "source_type": item.get("source_type", "local_note"),
        }
        for index, item in enumerate(exact_candidates[:180])
    ]
    active_length_config = length_config or {
        "mode": "auto",
        "target": None,
        "min": None,
        "max": None,
    }
    strategy = _book_quote_strategy_config(quote_strategy)
    length_rule = (
        "篇幅由素材和原稿自然决定。"
        if active_length_config.get("mode") != "manual"
        else (
            f"updated_copy 必须保持在 {active_length_config['min']}-{active_length_config['max']} 字，"
            f"当前原稿为 {_copy_length(draft)} 字。加入引文时同步压缩附近的重复解释，绝不能突破 "
            f"{active_length_config['max']} 字上限。"
        )
    )
    book_style = _style_with_length_contract(load_writing_skill()[1], active_length_config)
    insertion = run_json(
        "insert-book-quotes",
        f"""
在已完成的 Vlog 初稿中自然加入书库金句。不要重写整篇，不要改变项目事实，只在真正需要思想支撑的位置做局部连接；先判断时机，再选原句。

金句策略：{strategy["instruction"]}

当前文案：
{draft[:15000]}

项目素材：
{_materials_text(materials)}

叙事架构：
{json.dumps(architecture, ensure_ascii=False)[:9000]}

选中的书籍：
{json.dumps(
    [
        {
            "book_id": book_id,
            "book": books[book_id]["title"],
            "author": books[book_id]["author"],
            "safe_direction": BOOK_SUPPORT_PROFILES.get(book_id, ""),
        }
        for book_id in selected_book_ids
        if book_id in books
    ],
    ensure_ascii=False,
) }

本地书库候选原句（只能从 candidate_index 中选择）：
{json.dumps(local_candidates, ensure_ascii=False)[:30000]}

	执行规则：
1. 只能使用上面候选中的原句，quote 必须与候选 quote 完全一致，不得凭记忆补写、改写、拼接或转述。
2. 只允许 mode 为 exact_quote。严禁 thought_transfer、思想转译、解释性替代和模型自拟金句。
3. 候选可能来自包含批注的阅读笔记。只选择明显完整、可独立成立的书中原句；任何第一人称读后感、解释、方法论标题、日期或人物标签都不要选。
4. 本次目标加入 {strategy["target"]} 处，最多 {strategy["max"]} 处；目标不是随口建议，必须优先找满目标数量。不要为了覆盖书籍数量而强行植入，也不要在开头装饰性引用。
5. 先判断书句应该落在什么时机：高潮后的判词、思考下沉时的支点，或回引/升华前的暗扣。标准/增强策略下，优先让不同引文落在不同叙事功能位，不能全部堆在同一段。
6. 金句要放在真实转念、判断或回扣之前，并用自然的直接引用句式连接，例如“《XXX》里有这样一句话：‘……’”或“‘……’（《XXX》）”。不要使用“想到《XXX》时，我更愿意把它理解成……”这类转述句。
7. 书库只是支撑，不得压过创作者第一人称；没有真正契合的位置时返回空 supports 和原文。
8. updated_copy 必须是完整文案；被选中的完整 quote 和书名必须逐字出现在 updated_copy 中。
9. {length_rule}

只返回 JSON：
{{
  "updated_copy": "",
	  "supports": [
	    {{
	      "mode": "exact_quote",
	      "candidate_index": 0,
	      "book": "",
      "quote": "",
      "text": "",
      "attribution": "",
      "source_url": "",
      "reason": "",
      "location": ""
    }}
  ]
}}
""".strip(),
        system_context=book_style,
        max_tokens=3800,
        temperature=0.32,
    )
    data = insertion["data"]
    updated_copy = str(data.get("updated_copy") or "").strip()
    raw_supports = data.get("supports")
    if not updated_copy or not isinstance(raw_supports, list):
        raise SkillExecutionError("BOOK_SUPPORT_SCHEMA_INVALID", "书库金句结果结构不完整")
    if not raw_supports:
        return {
            "updated_copy": draft,
            "supports": [],
            "citations": [],
            "status": "none",
            "reason": "当前文案没有找到自然的书库金句位置。",
            "strategy": strategy,
            "online_results": [],
            "trace": [_trace_item(insertion)],
        }

    supports: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for item in raw_supports[: int(strategy["max"])]:
        if not isinstance(item, dict):
            continue
        mode = str(item.get("mode") or "").strip()
        book_label = str(item.get("book") or "").strip()
        book_id = _book_id_from_title(book_label)
        if book_id not in selected_book_ids:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if books[book_id]["title"] not in updated_copy and book_label not in updated_copy:
            continue
        if mode == "exact_quote":
            quote = str(item.get("quote") or "").strip().strip("“”\"")
            match = next(
                (
                    candidate
                    for candidate in exact_candidates
                    if candidate.get("book_id") == book_id
                    and _normalize_quote_text(str(candidate.get("quote") or ""))
                    == _normalize_quote_text(quote)
                    and str(candidate.get("quote") or "") in updated_copy
                ),
                None,
            )
            if not match:
                continue
            if _normalize_quote_text(text) not in _normalize_quote_text(updated_copy):
                continue
            supports.append(
                {
                    "mode": "exact_quote",
                    "book": match["book"],
                    "quote": match["quote"],
                    "text": text,
                    "attribution": match.get("attribution", ""),
                    "source_url": match.get("url", ""),
                    "source_title": match.get("source_title", ""),
                    "source_type": match.get("source_type", "local_note"),
                    "reason": str(item.get("reason") or ""),
                    "location": str(item.get("location") or ""),
                }
            )
            if match not in citations:
                citations.append(match)
        else:
            # The product contract is direct quotation only. Any other model mode is discarded.
            continue

    if not supports:
        return {
            "updated_copy": draft,
            "supports": [],
            "citations": [],
            "status": "none",
            "reason": "书库结果未通过格式与出处检查，未覆盖原文。",
            "strategy": strategy,
            "online_results": [],
            "trace": [_trace_item(insertion)],
        }
    if citations:
        save_book_citations(str(materials.get("project_id") or ""), citations)
    return {
        "updated_copy": updated_copy,
        "supports": supports,
        "citations": citations,
        "status": "integrated",
        "reason": f"已加入 {len(supports)} 处书库金句。",
        "strategy": strategy,
        "online_results": [],
        "trace": [_trace_item(insertion)],
    }


def _integrated_book_support_sync(payload: dict[str, Any]) -> dict[str, Any]:
    draft = str(payload.get("draft") or "").strip()
    materials = dict(payload.get("materials") or {})
    architecture = dict(payload.get("architecture") or {})
    books = _available_books()
    selected_book_ids = [
        str(book_id)
        for book_id in (payload.get("selected_books") or [])
        if str(book_id) in books
    ]
    if not draft or not selected_book_ids or str(payload.get("book_support_mode") or "integrated") == "off":
        return {
            "updated_copy": draft,
            "supports": [],
            "citations": [],
            "status": "disabled" if not selected_book_ids else "off",
            "reason": "书库金句未启用或未选择书籍。",
            "online_results": [],
            "trace": [],
        }

    exact_candidates = _saved_book_support_candidates(
        str(payload.get("project_id") or ""),
        selected_book_ids,
    )

    support_materials = {
        **materials,
        "project_id": str(payload.get("project_id") or ""),
    }
    result = _run_integrated_book_support(
        draft,
        support_materials,
        architecture,
        selected_book_ids,
        exact_candidates,
        [],
        payload.get("length_config") if isinstance(payload.get("length_config"), dict) else None,
        str(payload.get("book_quote_strategy") or "standard"),
    )
    return result


async def integrated_book_support(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_integrated_book_support_sync, payload)


def _research_books_sync(payload: dict[str, Any]) -> dict[str, Any]:
    draft = str(payload.get("draft") or "").strip()
    materials = dict(payload.get("materials") or {})
    strategy = _book_quote_strategy_config(str(payload.get("book_quote_strategy") or "standard"))
    books = _available_books()
    selected_book_ids = [
        str(book_id)
        for book_id in (payload.get("selected_books") or [])
        if str(book_id) in books
    ]
    if not draft:
        raise SkillExecutionError("BOOK_DRAFT_EMPTY", "请先生成或填写一版文案")
    if not selected_book_ids:
        raise SkillExecutionError("BOOK_SELECTION_EMPTY", "请至少选择一本精神书库")
    candidates = _saved_book_support_candidates(
        str(payload.get("project_id") or ""),
        selected_book_ids,
    )
    if not candidates:
        return {
            "candidates": [],
            "queries": [],
            "online_results": [],
            "trace": [],
            "status": "none",
            "reason": "本地书库没有符合直接引用要求的候选原句。",
            "strategy": strategy,
        }

    selection = run_json(
        "research-book-quotes",
        f"""
从本地书库候选中，找出与当前文案真正契合的直接引文候选。这里只做匹配计划，不要创造任何引文。

当前文案：
{draft[:10000]}

项目素材：
{_materials_text(materials)}

候选列表：
{json.dumps([
    {"candidate_index": index, "book": item["book"], "quote": item["quote"]}
    for index, item in enumerate(candidates[:180])
], ensure_ascii=False)[:30000]}

只返回 JSON：
{{
  "matches": [
    {{"candidate_index": 0, "fit": "与当前转念的关系", "insertion_point": "高潮后判词|思考下沉支点|回引/升华前暗扣"}}
  ]
}}

规则：金句策略为“{strategy["label"]}”：{strategy["instruction"]}；本次目标返回 {strategy["target"]} 条，最多返回 {strategy["max"]} 条。先判断插入时机，再匹配原句。只能返回候选列表中的 candidate_index；宁可返回空数组，不要转述、改写或凭记忆补充金句。
""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=1400,
        temperature=0.12,
    )
    trace = [_trace_item(selection)]
    matches = selection["data"].get("matches")
    if not isinstance(matches, list):
        raise SkillExecutionError("LOCAL_BOOK_MATCH_SCHEMA_INVALID", "本地书库匹配结果结构不完整")
    matched: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in matches[: int(strategy["max"])]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("candidate_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(candidates) or index in seen:
            continue
        seen.add(index)
        matched.append(
            {
                **candidates[index],
                "fit": str(item.get("fit") or "").strip(),
                "insert_after": str(item.get("insertion_point") or "").strip(),
            }
        )
    return {
        "candidates": matched,
        "queries": [],
        "online_results": [],
        "status": "matched" if matched else "none",
        "reason": "已从本地书库匹配直接引文候选。" if matched else "当前文案没有自然的直接引文位置。",
        "strategy": strategy,
        "trace": trace,
    }


async def research_books(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_research_books_sync, payload)


def _run_quote_insertion(
    draft: str,
    materials: dict[str, Any],
    candidates: list[dict[str, Any]],
    correction: str = "",
) -> dict[str, Any]:
    return run_json(
        "insert-book-quotes",
        f"""
从已核验候选中选择最多三条，自然植入当前 Vlog 文案。

原文：
{draft[:10000]}

项目素材：
{_materials_text(materials)}

已核验候选：
{json.dumps(candidates, ensure_ascii=False)}

{correction}

只允许以下三种直接引用格式：
1. 某某在《XXX》中写道：“XXXXX”
2. 《XXX》里有提到：“XXXXX”
3. “XXXXX”（《XXX》）

输出 JSON：
{{
  "updated_copy": "植入后的完整文案",
  "insertions": [
    {{
      "book": "",
      "quote": "",
      "attribution": "",
      "source_index": 0,
      "reason": "",
      "changed_fragment": ""
    }}
  ]
}}
植入前先判断时机：高潮后的判词、思考下沉时的支点，或回引/升华前的暗扣。
不得修改引文原字，不得新增事实，不得把引文机械追加到结尾。只输出 JSON。
""".strip(),
        system_context=load_writing_skill()[1],
        max_tokens=3600,
        temperature=0.34,
    )


def _validated_inserted_citations(
    updated_copy: str,
    insertions: Any,
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not updated_copy or not isinstance(insertions, list) or not insertions:
        raise SkillExecutionError("QUOTE_INSERT_SCHEMA_INVALID", "金句植入 Skill 返回内容不完整")
    selected_citations: list[dict[str, Any]] = []
    for item in insertions[:3]:
        if not isinstance(item, dict):
            continue
        item_book = str(item.get("book") or "")
        item_quote = str(item.get("quote") or "").strip().strip("“”\"")
        for candidate in candidates:
            if not _book_matches(candidate["book"], item_book):
                continue
            if _normalize_quote_text(candidate["quote"]) != _normalize_quote_text(item_quote):
                continue
            if candidate["quote"] not in updated_copy:
                continue
            book_plain = re.sub(r"[《》]", "", candidate["book"])
            if candidate["book"] not in updated_copy and book_plain not in updated_copy:
                continue
            if candidate not in selected_citations:
                selected_citations.append(candidate)
            break
    if not selected_citations:
        raise SkillExecutionError(
            "QUOTE_INSERT_VALIDATION_FAILED",
            "植入结果没有保留已核验原句及书名出处",
        )
    return selected_citations


def _auto_insert_books_sync(payload: dict[str, Any]) -> dict[str, Any]:
    draft = str(payload.get("draft") or "").strip()
    materials = payload.get("materials") or {}
    if not draft:
        raise SkillExecutionError("BOOK_DRAFT_EMPTY", "请先生成或填写一版文案")
    research = _research_books_sync(payload)
    candidates = research["candidates"]
    trace = list(research["trace"])
    if not candidates:
        return {
            "updated_copy": draft,
            "insertions": [],
            "candidates": [],
            "citations": [],
            "online_results": [],
            "status": "none",
            "reason": research.get("reason") or "当前文案没有自然的直接引文位置。",
            "strategy": research.get("strategy"),
            "trace": trace,
        }
    insertion = _run_quote_insertion(draft, materials, candidates)
    trace.append(_trace_item(insertion))
    updated_copy = str(insertion["data"].get("updated_copy") or "").strip()
    insertions = insertion["data"].get("insertions")
    try:
        selected_citations = _validated_inserted_citations(updated_copy, insertions, candidates)
    except SkillExecutionError as first_error:
        if first_error.code not in {"QUOTE_INSERT_SCHEMA_INVALID", "QUOTE_INSERT_VALIDATION_FAILED"}:
            raise
        correction = f"""
上一版植入结果没有通过结构或出处校验：{first_error}
请重新输出完整 JSON，不要返回空的 insertions。
至少选择一条已核验候选，并在 updated_copy 中实际出现完整书名和逐字引文。
只能使用已核验候选，不得新增事实，不得改写引文；若只有一条候选，只植入这一条。
""".strip()
        insertion = _run_quote_insertion(draft, materials, candidates, correction)
        trace.append(_trace_item(insertion))
        updated_copy = str(insertion["data"].get("updated_copy") or "").strip()
        insertions = insertion["data"].get("insertions")
        selected_citations = _validated_inserted_citations(updated_copy, insertions, candidates)

    audit = _audit_copy(
        updated_copy,
        materials,
        source_copy=draft,
        citations=selected_citations,
    )
    trace.append(_trace_item(audit))
    if not audit["passed"]:
        correction = "\n上一版未通过事实与引文审校。只允许保留原文事实，删除任何新增经历或解释，并按审校意见重新植入：" + json.dumps(
            audit["data"],
            ensure_ascii=False,
        )
        insertion = _run_quote_insertion(draft, materials, candidates, correction)
        trace.append(_trace_item(insertion))
        updated_copy = str(insertion["data"].get("updated_copy") or "").strip()
        insertions = insertion["data"].get("insertions")
        selected_citations = _validated_inserted_citations(updated_copy, insertions, candidates)
        audit = _audit_copy(
            updated_copy,
            materials,
            source_copy=draft,
            citations=selected_citations,
        )
        trace.append(_trace_item(audit))
        if not audit["passed"]:
            raise SkillExecutionError(
                "QUOTE_INSERT_AUDIT_FAILED",
                "金句植入结果未通过事实与引文审校",
                json.dumps(audit["data"], ensure_ascii=False),
            )
    save_book_citations(str(payload.get("project_id") or ""), selected_citations)
    return {
        "updated_copy": updated_copy,
        "insertions": insertions[:3],
        "candidates": candidates,
        "citations": selected_citations,
        "online_results": research["online_results"],
        "strategy": research.get("strategy"),
        "trace": trace,
    }


async def auto_insert_books(payload: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_auto_insert_books_sync, payload)


def selected_book_sources(book_ids: list[str]) -> list[dict[str, str]]:
    books = _available_books()
    return [
        {
            "id": book_id,
            "title": books[book_id]["title"],
            "author": books[book_id]["author"],
            "official_url": books[book_id].get("official_url", ""),
        }
        for book_id in book_ids
        if book_id in books
    ]
