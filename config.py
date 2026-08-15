"""匣中镜 AI Vlogger Studio 配置。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

def _default_data_dir() -> Path:
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA", "").strip()
        return Path(local_app_data) / "Xiangzhongjing" if local_app_data else Path.home() / "AppData" / "Local" / "Xiangzhongjing"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "xiangzhongjing"
    xdg_data_home = os.getenv("XDG_DATA_HOME", "").strip()
    return Path(xdg_data_home) / "xiangzhongjing" if xdg_data_home else Path.home() / ".local" / "share" / "xiangzhongjing"


_data_dir_value = os.getenv("XIANGZHONGJING_DATA_DIR", "").strip()
DATA_DIR = Path(_data_dir_value).expanduser() if _data_dir_value else _default_data_dir()


_DEFAULTS: dict[str, str] = {
    "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
    "DEEPSEEK_API_BASE": os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"),
    "DEEPSEEK_MODEL": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    "DEEPSEEK_REASONER_MODEL": os.getenv("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner"),
    "DEEPSEEK_TIMEOUT_SECONDS": os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "75"),
    "TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", ""),
    "TAVILY_API_BASE": os.getenv("TAVILY_API_BASE", "https://api.tavily.com"),
    "IMAGE_API_KEY": os.getenv("IMAGE_API_KEY", ""),
    "IMAGE_API_BASE": os.getenv("IMAGE_API_BASE", "https://api.openai.com"),
    "IMAGE_MODEL": os.getenv("IMAGE_MODEL", "gpt-image-2"),
    "SKILL_MAX_ATTEMPTS": os.getenv("SKILL_MAX_ATTEMPTS", "1"),
    "HOST": os.getenv("HOST", "127.0.0.1"),
    "PORT": os.getenv("PORT", "8860"),
}

_overrides: dict[str, str] = {}


def _resolve(key: str, default: str) -> str:
    if key in _overrides:
        return _overrides[key]
    return _DEFAULTS.get(key, default)


def reload_settings() -> None:
    """Load DB-backed local settings. Missing DB simply falls back to .env."""
    global _overrides
    try:
        from services.settings_store import get_all_settings

        _overrides = get_all_settings()
    except Exception:
        _overrides = _overrides or {}


def _write_env(key: str, value: str) -> None:
    try:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    except OSError:
        lines = []
    replaced = False
    for index, line in enumerate(lines):
        if line.strip().split("=", 1)[0].strip() == key:
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def persist_setting(key: str, value: str) -> None:
    from services.settings_store import set_setting

    set_setting(key, value)
    _overrides[key] = value
    _write_env(key, value)


def persist_settings(items: dict[str, str]) -> None:
    for key, value in items.items():
        persist_setting(key, value)


class AppConfig:
    @property
    def deepseek_api_key(self) -> str:
        return _resolve("DEEPSEEK_API_KEY", "")

    @property
    def deepseek_api_base(self) -> str:
        return _resolve("DEEPSEEK_API_BASE", "https://api.deepseek.com")

    @property
    def deepseek_model(self) -> str:
        return _resolve("DEEPSEEK_MODEL", "deepseek-chat")

    @property
    def deepseek_reasoner_model(self) -> str:
        return _resolve("DEEPSEEK_REASONER_MODEL", "deepseek-reasoner")

    @property
    def deepseek_timeout_seconds(self) -> float:
        return max(10.0, float(_resolve("DEEPSEEK_TIMEOUT_SECONDS", "75")))

    @property
    def tavily_api_key(self) -> str:
        return _resolve("TAVILY_API_KEY", "")

    @property
    def tavily_api_base(self) -> str:
        return _resolve("TAVILY_API_BASE", "https://api.tavily.com")

    @property
    def image_api_key(self) -> str:
        return _resolve("IMAGE_API_KEY", "")

    @property
    def image_api_base(self) -> str:
        return _resolve("IMAGE_API_BASE", "https://api.openai.com")

    @property
    def image_model(self) -> str:
        return _resolve("IMAGE_MODEL", "gpt-image-2")

    @property
    def skill_max_attempts(self) -> int:
        return max(1, int(_resolve("SKILL_MAX_ATTEMPTS", "1")))

    @property
    def host(self) -> str:
        return _resolve("HOST", "127.0.0.1")

    @property
    def port(self) -> int:
        return int(_resolve("PORT", "8860"))


app_config = AppConfig()

DATA_DIR.mkdir(parents=True, exist_ok=True)
