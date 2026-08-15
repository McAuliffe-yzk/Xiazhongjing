"""封面图生成与用户形象资产服务。"""

from __future__ import annotations

import base64
import json
import mimetypes
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import requests

from config import DATA_DIR, app_config


MEDIA_DIR = DATA_DIR / "media"
COVER_MEDIA_DIR = MEDIA_DIR / "covers"
MEDIA_KINDS = {"avatars", "references", "generated"}
DB_PATH = DATA_DIR / "xiangzhongjing.db"
IMAGE_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
IMAGE_REQUEST_ATTEMPTS = 3


DEFAULT_PRESETS: tuple[dict[str, str], ...] = (
    {
        "id": "ink-cover",
        "name": "墨染人物",
        "prompt": "国风水墨与现代创作者海报融合，人物正面半身，宣纸肌理，克制红蓝点缀，标题留白清晰，适合抖音封面。",
    },
    {
        "id": "film-diary",
        "name": "电影日记",
        "prompt": "电影感日记封面，真实人物主视觉，暖色胶片颗粒，生活化场景，强情绪标题区，画面高级但不夸张。",
    },
    {
        "id": "creator-dna",
        "name": "创作者 DNA",
        "prompt": "创作者 DNA 主题封面，人物与记忆碎片、手写稿、光线纹理结合，红蓝双色作为结构线索，现代 SaaS 视觉质感。",
    },
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except json.JSONDecodeError:
        return fallback


def _media_url(relative_path: str) -> str:
    if not relative_path:
        return ""
    kind, _, filename = relative_path.partition("/")
    if kind not in MEDIA_KINDS or not filename:
        return ""
    return f"/api/xiangzhongjing/covers/media/{kind}/{filename}"


def _row_to_profile(row: sqlite3.Row | None) -> dict[str, Any]:
    if not row:
        return {
            "display_name": "创作者",
            "handle": "creator",
            "bio": "个人创作者",
            "location": "",
            "creator_positioning": "",
            "platforms": "",
            "content_columns": "",
            "style_keywords": "",
            "visual_preferences": "",
            "cover_negative_prompt": "",
            "avatar_url": "",
            "avatar_path": "",
        }
    item = dict(row)
    item["avatar_url"] = _media_url(str(item.get("avatar_path") or ""))
    return item


def _row_to_preset(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _row_to_cover(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["reference_url"] = _media_url(str(item.get("reference_path") or ""))
    item["image_url"] = _media_url(str(item.get("image_path") or ""))
    item["metadata"] = _json_load(str(item.pop("metadata_json", "{}")), {})
    return item


def initialize_cover_store() -> None:
    COVER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    for kind in MEDIA_KINDS:
        (COVER_MEDIA_DIR / kind).mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS creator_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                display_name TEXT NOT NULL DEFAULT '创作者',
                handle TEXT NOT NULL DEFAULT 'creator',
                bio TEXT NOT NULL DEFAULT '个人创作者',
                location TEXT NOT NULL DEFAULT '',
                creator_positioning TEXT NOT NULL DEFAULT '',
                platforms TEXT NOT NULL DEFAULT '',
                content_columns TEXT NOT NULL DEFAULT '',
                style_keywords TEXT NOT NULL DEFAULT '',
                visual_preferences TEXT NOT NULL DEFAULT '',
                cover_negative_prompt TEXT NOT NULL DEFAULT '',
                avatar_path TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cover_presets (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                builtin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cover_images (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL DEFAULT '',
                project_title TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                preset_id TEXT NOT NULL DEFAULT '',
                prompt TEXT NOT NULL DEFAULT '',
                reference_path TEXT NOT NULL DEFAULT '',
                image_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'blank',
                error_message TEXT NOT NULL DEFAULT '',
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                generated_at TEXT
            );
            """
        )
        now = _now()
        connection.execute(
            """
            INSERT OR IGNORE INTO creator_profile (id, created_at, updated_at)
            VALUES (1, ?, ?)
            """,
            (now, now),
        )
        for preset in DEFAULT_PRESETS:
            connection.execute(
                """
                INSERT OR IGNORE INTO cover_presets (
                    id, name, prompt, builtin, created_at, updated_at
                ) VALUES (?, ?, ?, 1, ?, ?)
                """,
                (preset["id"], preset["name"], preset["prompt"], now, now),
            )
        profile_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(creator_profile)").fetchall()
        }
        for column in (
            "location",
            "creator_positioning",
            "platforms",
            "content_columns",
            "style_keywords",
            "visual_preferences",
            "cover_negative_prompt",
        ):
            if column not in profile_columns:
                connection.execute(
                    f"ALTER TABLE creator_profile ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
        connection.commit()


def media_path(kind: str, filename: str) -> Path:
    initialize_cover_store()
    if kind not in MEDIA_KINDS or "/" in filename or ".." in filename:
        raise ValueError("非法媒体路径")
    path = (COVER_MEDIA_DIR / kind / filename).resolve()
    root = (COVER_MEDIA_DIR / kind).resolve()
    if root not in path.parents:
        raise ValueError("非法媒体路径")
    return path


def _save_upload(kind: str, filename: str, content: bytes) -> str:
    initialize_cover_store()
    if kind not in MEDIA_KINDS:
        raise ValueError("非法媒体类型")
    if not content:
        raise ValueError("文件为空")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        guessed = mimetypes.guess_extension(mimetypes.guess_type(filename or "")[0] or "")
        suffix = guessed if guessed in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    target = media_path(kind, stored_name)
    target.write_bytes(content)
    return f"{kind}/{stored_name}"


def profile() -> dict[str, Any]:
    initialize_cover_store()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM creator_profile WHERE id = 1").fetchone()
    return _row_to_profile(row)


def update_profile(payload: dict[str, Any]) -> dict[str, Any]:
    initialize_cover_store()
    display_name = str(payload.get("display_name") or "创作者").strip()[:40]
    handle = str(payload.get("handle") or "creator").strip()[:60]
    bio = str(payload.get("bio") or "个人创作者").strip()[:120]
    location = str(payload.get("location") or "").strip()[:80]
    creator_positioning = str(payload.get("creator_positioning") or "").strip()[:240]
    platforms = str(payload.get("platforms") or "").strip()[:160]
    content_columns = str(payload.get("content_columns") or "").strip()[:400]
    style_keywords = str(payload.get("style_keywords") or "").strip()[:240]
    visual_preferences = str(payload.get("visual_preferences") or "").strip()[:360]
    cover_negative_prompt = str(payload.get("cover_negative_prompt") or "").strip()[:360]
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            UPDATE creator_profile
            SET display_name = ?, handle = ?, bio = ?, location = ?,
                creator_positioning = ?, platforms = ?, content_columns = ?,
                style_keywords = ?, visual_preferences = ?,
                cover_negative_prompt = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                display_name,
                handle,
                bio,
                location,
                creator_positioning,
                platforms,
                content_columns,
                style_keywords,
                visual_preferences,
                cover_negative_prompt,
                now,
            ),
        )
        connection.commit()
    return profile()


def update_avatar(filename: str, content: bytes) -> dict[str, Any]:
    relative_path = _save_upload("avatars", filename, content)
    now = _now()
    with _connect() as connection:
        connection.execute(
            "UPDATE creator_profile SET avatar_path = ?, updated_at = ? WHERE id = 1",
            (relative_path, now),
        )
        connection.commit()
    return profile()


def list_presets() -> list[dict[str, Any]]:
    initialize_cover_store()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM cover_presets ORDER BY builtin DESC, created_at ASC"
        ).fetchall()
    return [_row_to_preset(row) for row in rows]


def create_preset(payload: dict[str, Any]) -> dict[str, Any]:
    initialize_cover_store()
    name = str(payload.get("name") or "").strip()[:40]
    prompt = str(payload.get("prompt") or "").strip()[:1000]
    if not name or not prompt:
        raise ValueError("请填写预设名称和风格 Prompt")
    preset_id = f"preset_{uuid.uuid4().hex[:12]}"
    now = _now()
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO cover_presets (id, name, prompt, builtin, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (preset_id, name, prompt, now, now),
        )
        connection.commit()
        row = connection.execute(
            "SELECT * FROM cover_presets WHERE id = ?",
            (preset_id,),
        ).fetchone()
    return _row_to_preset(row)


def list_covers() -> list[dict[str, Any]]:
    initialize_cover_store()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT * FROM cover_images ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_cover(row) for row in rows]


def create_cover(payload: dict[str, Any]) -> dict[str, Any]:
    initialize_cover_store()
    cover_id = f"cover_{uuid.uuid4().hex[:14]}"
    project_id = str(payload.get("project_id") or "").strip()
    project_title = str(payload.get("project_title") or "").strip()
    title = str(payload.get("title") or project_title or "未命名封面").strip()[:80]
    preset_id = str(payload.get("preset_id") or "ink-cover").strip()
    prompt = str(payload.get("prompt") or "").strip()[:1200]
    now = _now()
    with _connect() as connection:
        preset = connection.execute(
            "SELECT prompt FROM cover_presets WHERE id = ?",
            (preset_id,),
        ).fetchone()
        if not prompt and preset:
            prompt = str(preset["prompt"] or "")
        connection.execute(
            """
            INSERT INTO cover_images (
                id, project_id, project_title, title, preset_id, prompt,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'blank', ?, ?)
            """,
            (cover_id, project_id, project_title, title, preset_id, prompt, now, now),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
    return _row_to_cover(row)


def update_cover(cover_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    initialize_cover_store()
    project_id = str(payload.get("project_id") or "").strip()
    project_title = str(payload.get("project_title") or "").strip()
    title = str(payload.get("title") or project_title or "未命名封面").strip()[:80]
    preset_id = str(payload.get("preset_id") or "ink-cover").strip()
    prompt = str(payload.get("prompt") or "").strip()[:1200]
    now = _now()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
        if not row:
            raise KeyError("封面卡不存在")
        if not prompt:
            preset = connection.execute(
                "SELECT prompt FROM cover_presets WHERE id = ?",
                (preset_id,),
            ).fetchone()
            prompt = str(preset["prompt"] or "") if preset else str(row["prompt"] or "")
        connection.execute(
            """
            UPDATE cover_images
            SET project_id = ?, project_title = ?, title = ?, preset_id = ?,
                prompt = ?, updated_at = ?
            WHERE id = ?
            """,
            (project_id, project_title, title, preset_id, prompt, now, cover_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
    return _row_to_cover(updated)


def update_cover_reference(cover_id: str, filename: str, content: bytes) -> dict[str, Any]:
    relative_path = _save_upload("references", filename, content)
    now = _now()
    with _connect() as connection:
        row = connection.execute("SELECT id FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
        if not row:
            raise KeyError("封面卡不存在")
        connection.execute(
            "UPDATE cover_images SET reference_path = ?, updated_at = ? WHERE id = ?",
            (relative_path, now, cover_id),
        )
        connection.commit()
        updated = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
    return _row_to_cover(updated)


def _image_prompt(cover: dict[str, Any], user_profile: dict[str, Any], reference_label: str) -> str:
    title = str(cover.get("title") or cover.get("project_title") or "个人创作封面")
    style_prompt = str(cover.get("prompt") or "")
    display_name = str(user_profile.get("display_name") or "创作者")
    positioning = str(user_profile.get("creator_positioning") or "")
    columns = str(user_profile.get("content_columns") or "")
    visual_preferences = str(user_profile.get("visual_preferences") or "")
    negative_prompt = str(user_profile.get("cover_negative_prompt") or "")
    return (
        f"为短视频博主 {display_name} 生成一张竖版封面图。"
        f"封面标题：{title}。"
        f"{f'创作者定位：{positioning}。' if positioning else ''}"
        f"{f'栏目方向：{columns}。' if columns else ''}"
        f"视觉风格：{style_prompt}。"
        f"{f'用户长期视觉偏好：{visual_preferences}。' if visual_preferences else ''}"
        f"{reference_label}"
        "画面必须高级、清晰、适合抖音封面，人物自然可信，留出可读标题区域；"
        "不要出现乱码文字、水印、低清像素、畸形五官或多余肢体。"
        f"{f'额外避免：{negative_prompt}。' if negative_prompt else ''}"
    )


def _extract_image_bytes(data: dict[str, Any]) -> bytes:
    items = data.get("data")
    if not isinstance(items, list) or not items:
        raise ValueError("图片服务未返回图片数据")
    first = items[0] if isinstance(items[0], dict) else {}
    encoded = str(first.get("b64_json") or "").strip()
    if encoded:
        return base64.b64decode(encoded)
    image_url = str(first.get("url") or "").strip()
    if image_url:
        response = requests.get(image_url, timeout=60)
        response.raise_for_status()
        return response.content
    raise ValueError("图片服务返回格式无法识别")


class ImageServiceError(requests.RequestException):
    """A user-readable image provider error that keeps request fallback semantics."""


def _image_error_message(response: requests.Response, attempts: int) -> str:
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                detail = str(error.get("message") or error.get("code") or "").strip()
            elif error:
                detail = str(error).strip()
            if not detail:
                detail = str(body.get("message") or body.get("detail") or "").strip()
    except (ValueError, TypeError):
        detail = ""
    if response.status_code == 503:
        prefix = f"图片服务暂时不可用（HTTP 503，已自动尝试 {attempts} 次）"
    elif response.status_code == 429:
        prefix = f"图片服务当前请求过多（HTTP 429，已自动尝试 {attempts} 次）"
    else:
        prefix = f"图片服务请求失败（HTTP {response.status_code}）"
    return f"{prefix}：{detail[:240]}" if detail else prefix


def _post_image_request(*, url: str, headers: dict[str, str], timeout: int, **kwargs) -> requests.Response:
    last_error: requests.RequestException | None = None
    for attempt in range(1, IMAGE_REQUEST_ATTEMPTS + 1):
        for file_spec in (kwargs.get("files") or {}).values():
            file_object = file_spec[1] if isinstance(file_spec, tuple) and len(file_spec) > 1 else None
            if hasattr(file_object, "seek"):
                file_object.seek(0)
        try:
            response = requests.post(url, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= IMAGE_REQUEST_ATTEMPTS:
                raise ImageServiceError(
                    f"无法连接图片服务，已自动尝试 {IMAGE_REQUEST_ATTEMPTS} 次：{str(exc)[:240]}"
                ) from exc
            time.sleep(attempt)
            continue
        if response.status_code < 400:
            return response
        if response.status_code not in IMAGE_RETRYABLE_STATUS_CODES or attempt >= IMAGE_REQUEST_ATTEMPTS:
            raise ImageServiceError(_image_error_message(response, attempt))
        time.sleep(attempt)
    raise ImageServiceError(str(last_error or "图片服务请求失败"))


def probe_image_service() -> dict[str, Any]:
    """Verify provider reachability and whether the configured image model exists."""
    configured_model = app_config.image_model
    if not app_config.image_api_key:
        return {
            "configured": False,
            "reachable": False,
            "model": configured_model,
            "model_available": False,
            "available_models": [],
            "message": "Image 2.0 API Key 未配置",
        }
    base_url = app_config.image_api_base.rstrip("/")
    try:
        response = requests.get(
            f"{base_url}/v1/models",
            headers={"Authorization": f"Bearer {app_config.image_api_key}"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        model_ids = sorted(
            str(item.get("id") or "")
            for item in data.get("data", [])
            if isinstance(item, dict) and item.get("id")
        )
        image_models = [
            model for model in model_ids
            if "image" in model.lower() or "dall" in model.lower()
        ]
        model_available = configured_model in model_ids
        return {
            "configured": True,
            "reachable": True,
            "model": configured_model,
            "model_available": model_available,
            "available_models": image_models,
            "message": (
                f"图片服务连接正常，当前模型 {configured_model} 可用"
                if model_available
                else f"图片服务可连接，但当前模型 {configured_model} 不在服务模型列表中"
            ),
        }
    except requests.RequestException as exc:
        return {
            "configured": True,
            "reachable": False,
            "model": configured_model,
            "model_available": False,
            "available_models": [],
            "message": f"图片服务连接失败：{str(exc)[:240]}",
        }


def _post_generation(prompt: str) -> bytes:
    base_url = app_config.image_api_base.rstrip("/")
    response = _post_image_request(
        url=f"{base_url}/v1/images/generations",
        headers={"Authorization": f"Bearer {app_config.image_api_key}"},
        json={
            "model": app_config.image_model,
            "prompt": prompt,
            "size": "1024x1536",
            "n": 1,
        },
        timeout=180,
    )
    return _extract_image_bytes(response.json())


def _post_edit(prompt: str, reference_path: Path) -> bytes:
    base_url = app_config.image_api_base.rstrip("/")
    mime_type = mimetypes.guess_type(reference_path.name)[0] or "image/png"
    with reference_path.open("rb") as image_file:
        response = _post_image_request(
            url=f"{base_url}/v1/images/edits",
            headers={"Authorization": f"Bearer {app_config.image_api_key}"},
            data={
                "model": app_config.image_model,
                "prompt": prompt,
                "size": "1024x1536",
                "n": "1",
            },
            files={"image": (reference_path.name, image_file, mime_type)},
            timeout=180,
        )
    return _extract_image_bytes(response.json())


def _reference_file(cover: dict[str, Any], use_default_avatar: bool) -> Path | None:
    relative_path = str(cover.get("reference_path") or "")
    if not relative_path and use_default_avatar:
        relative_path = str(profile().get("avatar_path") or "")
    if not relative_path:
        return None
    kind, _, filename = relative_path.partition("/")
    try:
        path = media_path(kind, filename)
    except ValueError:
        return None
    return path if path.exists() else None


def generate_cover(cover_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    initialize_cover_store()
    if not app_config.image_api_key:
        raise RuntimeError("请先在设置页配置 Image 2.0 API Key")
    use_default_avatar = bool(payload.get("use_default_avatar", True))
    now = _now()
    with _connect() as connection:
        row = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
        if not row:
            raise KeyError("封面卡不存在")
        cover = _row_to_cover(row)
        if payload.get("prompt"):
            cover["prompt"] = str(payload.get("prompt") or "").strip()[:1200]
        if payload.get("preset_id"):
            cover["preset_id"] = str(payload.get("preset_id") or "").strip()
        connection.execute(
            """
            UPDATE cover_images
            SET status = 'generating', error_message = '', prompt = ?, preset_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (cover["prompt"], cover["preset_id"], now, cover_id),
        )
        connection.commit()

    user_profile = profile()
    reference = _reference_file(cover, use_default_avatar)
    prompt = _image_prompt(
        cover,
        user_profile,
        "请以用户上传的标准正面形象作为人物一致性参考。" if reference else "暂无可用人物参考图，请生成自然可信的创作者形象。",
    )
    started = time.monotonic()
    try:
        try:
            image_bytes = _post_edit(prompt, reference) if reference else _post_generation(prompt)
        except requests.RequestException:
            if not reference:
                raise
            image_bytes = _post_generation(prompt)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        image_path = _save_upload("generated", f"{cover_id}.png", image_bytes)
        metadata = {
            "model": app_config.image_model,
            "used_reference": bool(reference),
            "api_base": app_config.image_api_base,
            "prompt_chars": len(prompt),
        }
        with _connect() as connection:
            connection.execute(
                """
                UPDATE cover_images
                SET image_path = ?, status = 'completed', error_message = '',
                    elapsed_ms = ?, metadata_json = ?, updated_at = ?, generated_at = ?
                WHERE id = ?
                """,
                (image_path, elapsed_ms, json.dumps(metadata, ensure_ascii=False), _now(), _now(), cover_id),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
        return _row_to_cover(row)
    except Exception as exc:
        with _connect() as connection:
            connection.execute(
                """
                UPDATE cover_images
                SET status = 'failed', error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (str(exc)[:500], _now(), cover_id),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM cover_images WHERE id = ?", (cover_id,)).fetchone()
        return _row_to_cover(row)
