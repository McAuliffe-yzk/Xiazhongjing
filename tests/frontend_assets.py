"""测试中组合模块化前端与后端源码的辅助函数。"""

from pathlib import Path
import re


BASE_DIR = Path(__file__).resolve().parents[1]
DEMO_PATH = BASE_DIR / "templates" / "xiangzhongjing_demo.html"


def demo_markup() -> str:
    return DEMO_PATH.read_text(encoding="utf-8")


def demo_javascript() -> str:
    markup = demo_markup()
    paths = re.findall(r'<script src="(/static/js/[^"?]+)', markup)
    return "\n".join(
        (BASE_DIR / path.lstrip("/")).read_text(encoding="utf-8")
        for path in paths
    )


def demo_source() -> str:
    return f"{demo_markup()}\n{demo_javascript()}"


def demo_styles() -> str:
    markup = demo_markup()
    paths = re.findall(r'<link rel="stylesheet" href="(/static/styles/[^"?]+)', markup)
    return "\n".join(
        (BASE_DIR / path.lstrip("/")).read_text(encoding="utf-8")
        for path in paths
    )


def backend_source() -> str:
    paths = [BASE_DIR / "main.py", *sorted((BASE_DIR / "api").glob("*.py"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)

