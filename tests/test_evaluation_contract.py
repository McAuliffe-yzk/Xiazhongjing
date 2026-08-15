from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path
from tests.frontend_assets import backend_source


BASE_DIR = Path(__file__).resolve().parents[1]


class EvaluationHTMLParser(HTMLParser):
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


class EvaluationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (BASE_DIR / "templates" / "xiangzhongjing_evaluation.html").read_text(
            encoding="utf-8"
        )
        cls.css = (BASE_DIR / "static" / "evaluation.css").read_text(encoding="utf-8")
        cls.js = (BASE_DIR / "static" / "evaluation.js").read_text(encoding="utf-8")
        cls.main = backend_source()
        cls.parser = EvaluationHTMLParser()
        cls.parser.feed(cls.html)

    def test_evaluation_route_and_navigation_are_available(self) -> None:
        self.assertIn('@router.get("/xiangzhongjing-evaluation"', self.main)
        self.assertIn("/xiangzhongjing-demo", self.parser.links)
        self.assertIn("/xiangzhongjing-prd", self.parser.links)

    def test_required_product_sections_are_present(self) -> None:
        self.assertTrue(
            {
                "positioning",
                "dimensions",
                "strategy",
                "roadmap",
                "architecture",
                "strategy-detail",
                "architecture-panel",
            }.issubset(self.parser.ids)
        )
        for title in ("用户体验与交互", "UI 视觉与设计美学", "功能价值与信息呈现", "代码架构与技术框架"):
            self.assertIn(title, self.html)

    def test_strategy_and_architecture_views_have_all_options(self) -> None:
        for value in ('data-strategy="a"', 'data-strategy="b"', 'data-strategy="c"'):
            self.assertIn(value, self.html)
        self.assertIn('data-architecture="current"', self.html)
        self.assertIn('data-architecture="target"', self.html)
        self.assertIn("renderStrategy", self.js)
        self.assertIn("renderArchitecture", self.js)

    def test_responsive_and_accessibility_contracts_are_present(self) -> None:
        self.assertIn('@media (max-width: 640px)', self.css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', self.css)
        self.assertNotIn("transition: all", self.css)
        self.assertIn('class="skip-link"', self.html)
        self.assertIn('aria-live="polite"', self.html)


if __name__ == "__main__":
    unittest.main()
