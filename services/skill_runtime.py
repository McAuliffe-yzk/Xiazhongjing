"""产品 Skill 加载、DeepSeek 执行与可观测运行记录。"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import BASE_DIR, app_config
from services.xiangzhongjing_store import finish_skill_run, start_skill_run


PRODUCT_SKILLS_DIR = BASE_DIR / "product_skills"
CUSTOM_SKILLS_DIR = BASE_DIR / "custom_skills"
DEFAULTS_DIR = PRODUCT_SKILLS_DIR / ".defaults"
SKILL_VERSION = "1.0.0"

SKILL_META: dict[str, dict[str, str]] = {
    "distill-personal-style": {"display_name": "个人风格蒸馏", "phase": "蒸馏"},
    "distill-blogger-dna": {"display_name": "博主 DNA 蒸馏", "phase": "蒸馏"},
    "parse-creation-materials": {"display_name": "剪贴板素材识别", "phase": "输入"},
    "architect-vlog-narrative": {"display_name": "叙事架构", "phase": "创作"},
    "write-personal-vlog": {"display_name": "个人声音写作", "phase": "创作"},
    "optimize-douyin-vlog": {"display_name": "抖音 Vlog 优化", "phase": "提效"},
    "adapt-douyin-vlog": {"display_name": "发布适配包", "phase": "发布"},
    "audit-writing-quality": {"display_name": "写作质量门", "phase": "审校"},
    "research-book-quotes": {"display_name": "本地金句匹配", "phase": "书库"},
    "verify-book-quotes": {"display_name": "书本金句核验", "phase": "书库"},
    "insert-book-quotes": {"display_name": "书库金句", "phase": "书库"},
    "inspect-content-style": {"display_name": "内容检查员", "phase": "审查"},
    "mirror-self-dialogue": {"display_name": "镜中人", "phase": "交流"},
    "book-person-dialogue": {"display_name": "书中人", "phase": "交流"},
    "summarize-dialogue-memory": {"display_name": "对话记忆摘要", "phase": "记忆"},
    "edit-vlog-copy": {"display_name": "文案编辑", "phase": "编辑"},
    "audit-vlog-copy": {"display_name": "事实审校", "phase": "审校"},
}


class SkillExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, details: str = ""):
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    instructions: str
    version: str = SKILL_VERSION


def _parse_skill(path: Path) -> SkillDefinition:
    raw = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n([\s\S]*)$", raw)
    if not match:
        raise SkillExecutionError("SKILL_INVALID", f"Skill 文件格式错误：{path}")
    frontmatter, body = match.groups()
    name_match = re.search(r"^name:\s*(.+)$", frontmatter, flags=re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", frontmatter, flags=re.MULTILINE)
    if not name_match or not description_match:
        raise SkillExecutionError("SKILL_INVALID", f"Skill 缺少 name 或 description：{path}")
    return SkillDefinition(
        name=name_match.group(1).strip(),
        description=description_match.group(1).strip(),
        instructions=body.strip(),
    )


def load_skill(skill_name: str) -> SkillDefinition:
    from services.settings_store import get_skill_registry

    row = get_skill_registry(skill_name)
    if row is not None:
        if not int(row["enabled"]):
            raise SkillExecutionError("SKILL_DISABLED", f"Skill 已停用：{skill_name}")
        path = Path(row["dir_path"]) / "SKILL.md"
    else:
        if skill_name not in SKILL_META:
            raise SkillExecutionError("SKILL_NOT_FOUND", f"未知 Skill：{skill_name}")
        path = PRODUCT_SKILLS_DIR / skill_name / "SKILL.md"
    if not path.exists():
        raise SkillExecutionError("SKILL_NOT_FOUND", f"Skill 文件不存在：{skill_name}")
    skill = _parse_skill(path)
    if skill.name != skill_name:
        raise SkillExecutionError("SKILL_INVALID", f"Skill 名称不匹配：{skill_name}")
    return skill


def skill_catalog() -> list[dict[str, Any]]:
    from services.settings_store import list_skills_registry

    registered = list_skills_registry()
    if registered:
        return [
            {
                "name": row["name"],
                "display_name": row["display_name"],
                "phase": row["phase"],
                "version": SKILL_VERSION,
                "description": row["description"],
                "source": row["source"],
                "enabled": int(row["enabled"]),
                "core": int(row["core"]),
            }
            for row in registered
            if int(row["enabled"])
        ]
    catalog: list[dict[str, str]] = []
    for name, meta in SKILL_META.items():
        skill = load_skill(name)
        catalog.append(
            {
                "name": name,
                "display_name": meta["display_name"],
                "phase": meta["phase"],
                "version": skill.version,
                "description": skill.description,
            }
        )
    return catalog


def _read_skill_frontmatter(path: Path) -> tuple[str, str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n", raw)
    if not match:
        return "", ""
    frontmatter = match.group(1)
    name_match = re.search(r"^name:\s*(.+)$", frontmatter, flags=re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", frontmatter, flags=re.MULTILINE)
    return (
        name_match.group(1).strip() if name_match else "",
        description_match.group(1).strip() if description_match else "",
    )


def ensure_defaults_snapshot() -> None:
    if DEFAULTS_DIR.exists():
        return
    DEFAULTS_DIR.mkdir(parents=True, exist_ok=True)
    for skill_dir in PRODUCT_SKILLS_DIR.iterdir():
        if not skill_dir.is_dir() or skill_dir.name == ".defaults":
            continue
        source = skill_dir / "SKILL.md"
        if not source.exists():
            continue
        target = DEFAULTS_DIR / skill_dir.name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def sync_skill_registry() -> None:
    """Register built-in and custom Skills without changing existing enabled flags."""
    from services.settings_store import list_skills_registry, upsert_skill_registry

    ensure_defaults_snapshot()
    CUSTOM_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    existing = {row["name"]: row for row in list_skills_registry()}

    def seed(name: str, source: str, directory: Path) -> None:
        _, description = _read_skill_frontmatter(directory / "SKILL.md")
        meta = SKILL_META.get(name, {})
        previous = existing.get(name)
        upsert_skill_registry(
            {
                "name": name,
                "display_name": meta.get("display_name", name),
                "phase": meta.get("phase", "其它"),
                "description": description,
                "source": source,
                "core": 1 if name in SKILL_META else 0,
                "enabled": int(previous["enabled"]) if previous else (1 if name in SKILL_META or source == "custom" else 0),
                "dir_path": str(directory),
                "sort_order": int(previous["sort_order"]) if previous else 0,
            }
        )

    for directory in PRODUCT_SKILLS_DIR.iterdir():
        if directory.is_dir() and directory.name != ".defaults" and (directory / "SKILL.md").exists():
            seed(directory.name, "builtin", directory)
    for directory in CUSTOM_SKILLS_DIR.iterdir():
        if directory.is_dir() and (directory / "SKILL.md").exists():
            seed(directory.name, "custom", directory)


_CUSTOM_SKILL_NAME = re.compile(r"^[a-z0-9-]{1,64}$")


def get_skill_detail(skill_name: str) -> dict[str, Any]:
    from services.settings_store import get_skill_registry

    row = get_skill_registry(skill_name)
    if row is None:
        raise SkillExecutionError("SKILL_NOT_FOUND", f"未知 Skill：{skill_name}")
    path = Path(row["dir_path"]) / "SKILL.md"
    instructions = ""
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        match = re.match(r"^---\s*\n[\s\S]*?\n---\s*\n([\s\S]*)$", raw)
        instructions = match.group(1).strip() if match else raw
    return {
        "name": row["name"],
        "display_name": row["display_name"],
        "phase": row["phase"],
        "description": row["description"],
        "source": row["source"],
        "core": int(row["core"]),
        "enabled": int(row["enabled"]),
        "instructions": instructions,
    }


def create_skill(
    *,
    name: str,
    display_name: str,
    phase: str,
    description: str,
    instructions: str,
) -> dict[str, Any]:
    from services.settings_store import get_skill_registry, upsert_skill_registry

    if not _CUSTOM_SKILL_NAME.fullmatch(name):
        raise SkillExecutionError("SKILL_INVALID_NAME", "Skill 名称仅允许小写字母、数字和短横线")
    if get_skill_registry(name) is not None:
        raise SkillExecutionError("SKILL_DUPLICATE", f"Skill 已存在：{name}")
    directory = CUSTOM_SKILLS_DIR / name
    if directory.exists():
        raise SkillExecutionError("SKILL_DUPLICATE", f"Skill 目录已存在：{name}")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description.strip()}\n---\n\n{instructions.strip()}\n",
        encoding="utf-8",
    )
    upsert_skill_registry(
        {
            "name": name,
            "display_name": display_name.strip() or name,
            "phase": phase.strip() or "自定义",
            "description": description.strip(),
            "source": "custom",
            "core": 0,
            "enabled": 1,
            "dir_path": str(directory),
            "sort_order": 0,
        }
    )
    return get_skill_detail(name)


def update_skill(
    skill_name: str,
    *,
    display_name: str,
    phase: str,
    description: str,
    instructions: str,
) -> dict[str, Any]:
    from services.settings_store import get_skill_registry, upsert_skill_registry

    row = get_skill_registry(skill_name)
    if row is None:
        raise SkillExecutionError("SKILL_NOT_FOUND", f"未知 Skill：{skill_name}")
    path = Path(row["dir_path"]) / "SKILL.md"
    path.write_text(
        f"---\nname: {skill_name}\ndescription: {description.strip()}\n---\n\n{instructions.strip()}\n",
        encoding="utf-8",
    )
    _parse_skill(path)
    upsert_skill_registry(
        {
            "name": skill_name,
            "display_name": display_name.strip() or skill_name,
            "phase": phase.strip() or "其它",
            "description": description.strip(),
            "source": row["source"],
            "core": int(row["core"]),
            "enabled": int(row["enabled"]),
            "dir_path": row["dir_path"],
            "sort_order": int(row["sort_order"]),
        }
    )
    return get_skill_detail(skill_name)


def set_skill_enabled(skill_name: str, enabled: bool) -> None:
    from services.settings_store import get_skill_registry, set_skill_enabled as store_set

    row = get_skill_registry(skill_name)
    if row is None:
        raise SkillExecutionError("SKILL_NOT_FOUND", f"未知 Skill：{skill_name}")
    if int(row["core"]) and not enabled:
        raise SkillExecutionError("SKILL_CORE_LOCKED", f"核心 Skill 不可停用：{skill_name}")
    store_set(skill_name, 1 if enabled else 0)


def reset_skill(skill_name: str) -> dict[str, Any]:
    from services.settings_store import get_skill_registry, upsert_skill_registry

    row = get_skill_registry(skill_name)
    if row is None:
        raise SkillExecutionError("SKILL_NOT_FOUND", f"未知 Skill：{skill_name}")
    if row["source"] != "builtin":
        raise SkillExecutionError("SKILL_NOT_RESETTABLE", "仅内置 Skill 可重置")
    source = DEFAULTS_DIR / skill_name / "SKILL.md"
    if not source.exists():
        raise SkillExecutionError("SKILL_DEFAULT_MISSING", f"缺少默认快照：{skill_name}")
    target = Path(row["dir_path"]) / "SKILL.md"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    _, description = _read_skill_frontmatter(target)
    meta = SKILL_META.get(skill_name, {})
    upsert_skill_registry(
        {
            "name": skill_name,
            "display_name": meta.get("display_name", skill_name),
            "phase": meta.get("phase", "其它"),
            "description": description,
            "source": "builtin",
            "core": int(row["core"]),
            "enabled": 1,
            "dir_path": row["dir_path"],
            "sort_order": int(row["sort_order"]),
        }
    )
    return get_skill_detail(skill_name)


def delete_skill(skill_name: str) -> None:
    from services.settings_store import delete_skill_registry, get_skill_registry

    row = get_skill_registry(skill_name)
    if row is None:
        raise SkillExecutionError("SKILL_NOT_FOUND", f"未知 Skill：{skill_name}")
    if row["source"] != "custom":
        raise SkillExecutionError("SKILL_NOT_DELETABLE", f"内置 Skill 不可删除：{skill_name}")
    shutil.rmtree(Path(row["dir_path"]), ignore_errors=True)
    delete_skill_registry(skill_name)


def _client() -> OpenAI:
    if not app_config.deepseek_api_key:
        raise SkillExecutionError("DEEPSEEK_NOT_CONFIGURED", "未配置 DeepSeek API Key")
    return OpenAI(
        api_key=app_config.deepseek_api_key,
        base_url=app_config.deepseek_api_base.rstrip("/"),
        timeout=app_config.deepseek_timeout_seconds,
        max_retries=0,
    )


def _summary(value: str, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", value).strip()[:limit]


def run_text(
    skill_name: str,
    user_prompt: str,
    *,
    system_context: str = "",
    max_tokens: int = 2200,
    temperature: float = 0.6,
    model: str = "",
    json_output: bool = False,
) -> dict[str, Any]:
    skill = load_skill(skill_name)
    selected_model = model.strip() or app_config.deepseek_model
    run_id = uuid.uuid4().hex
    started = time.perf_counter()
    start_skill_run(
        run_id,
        skill.name,
        skill.version,
        selected_model,
        _summary(user_prompt),
    )
    system_parts = [
        f"你正在执行产品 Skill：{skill.name}，版本 {skill.version}。",
        skill.instructions,
    ]
    if json_output:
        system_parts.append("输出要求：只返回合法 JSON 对象，不要 Markdown、代码块、注释、解释或额外文本。")
    if system_context.strip():
        system_parts.append("当前发布的个人创作风格：\n" + system_context.strip())
    messages = [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {"role": "user", "content": user_prompt.strip()},
    ]
    last_error: Exception | None = None
    try:
        for _ in range(app_config.skill_max_attempts):
            try:
                request: dict[str, Any] = {
                    "model": selected_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                }
                if "reasoner" not in selected_model.lower():
                    request["temperature"] = temperature
                if json_output and "reasoner" not in selected_model.lower():
                    request["response_format"] = {"type": "json_object"}
                response = _client().chat.completions.create(**request)
                choice = response.choices[0]
                content = choice.message.content
                if not content or not content.strip():
                    raise SkillExecutionError(
                        "MODEL_EMPTY",
                        "DeepSeek 返回了空内容",
                        f"finish_reason={choice.finish_reason}",
                    )
                output = content.strip()
                elapsed = int((time.perf_counter() - started) * 1000)
                finish_skill_run(
                    run_id,
                    "succeeded",
                    elapsed,
                    output_summary=_summary(output),
                )
                return {
                    "text": output,
                    "run_id": run_id,
                    "skill": skill.name,
                    "version": skill.version,
                    "model": selected_model,
                    "latency_ms": elapsed,
                }
            except Exception as exc:
                last_error = exc
        if isinstance(last_error, SkillExecutionError):
            raise last_error
        raise SkillExecutionError(
            "MODEL_REQUEST_FAILED",
            f"{skill.name} 调用 DeepSeek 失败",
            str(last_error or ""),
        )
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        error = exc if isinstance(exc, SkillExecutionError) else SkillExecutionError(
            "SKILL_EXECUTION_FAILED", f"{skill.name} 执行失败", str(exc)
        )
        finish_skill_run(
            run_id,
            "failed",
            elapsed,
            error_code=error.code,
            error_message=f"{error}: {error.details}".strip(),
        )
        raise error


def _parse_json(raw: str) -> Any:
    cleaned = raw.strip()
    cleaned = re.sub(r"^\`\`\`(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\`\`\`$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "{[":
                continue
            try:
                candidate, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, (dict, list)):
                return candidate
        raise


def run_json(
    skill_name: str,
    user_prompt: str,
    *,
    system_context: str = "",
    max_tokens: int = 2200,
    temperature: float = 0.4,
    model: str = "",
) -> dict[str, Any]:
    first = run_text(
        skill_name,
        user_prompt,
        system_context=system_context,
        max_tokens=max_tokens,
        temperature=temperature,
        model=model,
        json_output=True,
    )
    try:
        data = _parse_json(first["text"])
    except (json.JSONDecodeError, TypeError) as exc:
        repaired = run_text(
            skill_name,
            f"""上一轮输出未返回有效 JSON。请严格修复为合法 JSON 对象，只输出 JSON，不要解释，不要 Markdown。

原始任务：
{user_prompt.strip()}

上一轮输出：
{first.get('text', '').strip()}
""".strip(),
            system_context=system_context,
            max_tokens=max_tokens,
            temperature=min(temperature, 0.2),
            model=model,
            json_output=True,
        )
        try:
            data = _parse_json(repaired["text"])
            first = repaired
        except (json.JSONDecodeError, TypeError) as repair_exc:
            raise SkillExecutionError(
                "MODEL_JSON_INVALID",
                f"{skill_name} 未返回有效 JSON，已按失败不兜底策略停止",
                str(repair_exc),
            ) from repair_exc
    if not isinstance(data, dict):
        raise SkillExecutionError("MODEL_SCHEMA_INVALID", f"{skill_name} 输出必须是 JSON 对象")
    return {**first, "data": data}
