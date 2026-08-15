from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.frontend_assets import backend_source, demo_markup, demo_styles


BASE_DIR = Path(__file__).resolve().parents[1]


class PrdHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))


class PrdContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prd_markdown = (BASE_DIR / "PRD.md").read_text(encoding="utf-8")
        cls.html = (BASE_DIR / "templates" / "xiangzhongjing_prd.html").read_text(
            encoding="utf-8"
        )
        cls.css = (BASE_DIR / "static" / "prd.css").read_text(encoding="utf-8")
        cls.javascript = (BASE_DIR / "static" / "prd.js").read_text(encoding="utf-8")
        cls.demo = demo_markup()
        cls.demo_css = demo_styles()
        cls.backend = backend_source()
        cls.parser = PrdHTMLParser()
        cls.parser.feed(cls.html)

    def test_prd_v2_is_the_shared_product_baseline(self) -> None:
        self.assertIn("PRD v2.0", self.prd_markdown)
        self.assertIn("个人 DNA", self.prd_markdown)
        self.assertIn("模块化单体", self.prd_markdown)
        self.assertIn("PRD v2.0", self.html)
        self.assertNotIn("PRD v1.2", self.html)

    def test_visual_prd_covers_the_current_product_domains(self) -> None:
        required_sections = {
            "overview",
            "blueprint",
            "workflow",
            "contracts",
            "library",
            "architecture",
            "metrics",
            "roadmap",
            "boundaries",
            "module-detail",
            "contract-detail",
        }
        self.assertTrue(required_sections.issubset(self.parser.ids))
        for module in (
            "灵感匣签",
            "精神书库",
            "镜中人",
            "书中人",
            "资产库",
            "DNA 试剂",
            "个人信息",
            "封面图",
            "设置",
        ):
            self.assertIn(module, self.html)
        self.assertIn("个人创作 Skill", self.html)
        self.assertIn("书库", self.html)
        self.assertIn("模块化单体", self.html)

    def test_prd_entry_is_a_structured_product_destination(self) -> None:
        self.assertIn('class="product-blueprint-link"', self.demo)
        self.assertIn('href="/xiangzhongjing-prd"', self.demo)
        self.assertIn("产品PRD", self.demo)
        self.assertNotIn("PRD v2.0 · 当前基线", self.demo)
        self.assertNotIn("产品资料", self.demo)
        self.assertIn('class="mobile-prd-link"', self.demo)
        self.assertNotIn('class="back-link" href="/xiangzhongjing-prd"', self.demo)
        self.assertIn(".product-blueprint-link", self.demo_css)

    def test_route_interaction_and_accessibility_contracts_are_present(self) -> None:
        self.assertIn('@router.get("/xiangzhongjing-prd"', self.backend)
        self.assertIn("/xiangzhongjing-demo", self.parser.links)
        self.assertIn('class="skip-link"', self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn("renderModule", self.javascript)
        self.assertIn("renderContract", self.javascript)
        self.assertIn("IntersectionObserver", self.javascript)
        self.assertIn("@media (max-width: 720px)", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertNotIn("transition: all", self.css)


if __name__ == "__main__":
    unittest.main()
