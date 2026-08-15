import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services import xiangzhongjing_store
from services.book_notes_service import _join_pdf_lines, _material_records, ingest_book_note_bytes
from services.deepseek_service import (
    GENERATION_STAGE_META,
    _book_quote_strategy_config,
    _integrated_book_support_sync,
    _normalize_quote_text,
    _research_books_sync,
    _run_integrated_book_support,
    _saved_book_support_candidates,
    _source_contains_quote,
)
from services.skill_runtime import SKILL_META
from tests.frontend_assets import demo_source


TEST_BOOKS = {
    "jianlai": {"id": "jianlai", "title": "《剑来》", "author": "烽火戏诸侯"},
    "musk": {"id": "musk", "title": "《埃隆·马斯克传》", "author": "沃尔特·艾萨克森"},
    "daode": {"id": "daode", "title": "《道德经》", "author": "老子"},
}


def skill_result(data, run_id="run-book-support", skill="insert-book-quotes"):
    return {
        "data": data,
        "run_id": run_id,
        "skill": skill,
        "version": "1.0.0",
        "model": "mock",
        "latency_ms": 12,
    }


class BookResearchContractTests(unittest.TestCase):
    def test_quote_normalization_ignores_punctuation_and_common_traditional_chars(self) -> None:
        self.assertEqual(
            _normalize_quote_text("知足不辱，知止不殆，可以長久。"),
            _normalize_quote_text("知足不辱 知止不殆 可以长久"),
        )

    def test_source_contains_quote_with_punctuation_difference(self) -> None:
        source = {"content": "故知足不辱，知止不殆，可以长久。", "raw_content": ""}
        self.assertTrue(_source_contains_quote(source, "知足不辱，知止不殆，可以长久"))

    def test_generation_chain_uses_the_real_book_support_skill_name(self) -> None:
        self.assertIn("insert-book-quotes", GENERATION_STAGE_META)
        self.assertNotIn("book-support", GENERATION_STAGE_META)
        self.assertEqual(SKILL_META["insert-book-quotes"]["display_name"], "书库金句")
        self.assertIn("本地书库原文", GENERATION_STAGE_META["insert-book-quotes"]["message"])

    def test_book_quote_strategy_contract(self) -> None:
        self.assertEqual(_book_quote_strategy_config("restrained")["target"], 1)
        self.assertEqual(_book_quote_strategy_config("standard")["target"], 2)
        self.assertEqual(_book_quote_strategy_config("standard")["max"], 3)
        self.assertEqual(_book_quote_strategy_config("amplified")["target"], 3)

    def test_frontend_exposes_local_library_without_online_search(self) -> None:
        html = demo_source()
        self.assertIn('id="book-note-upload"', html)
        self.assertIn('/api/xiangzhongjing/book-notes/upload', html)
        self.assertIn('/api/xiangzhongjing/book-notes/seed', html)
        self.assertIn("生成链路里自动判断", html)
        self.assertIn("本地书库", html)
        self.assertNotIn("online_search: true", html)
        self.assertNotIn("思想转译", html)
        self.assertNotIn("Tavily", html)

    def test_ingest_book_note_bytes_saves_global_citations(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            result = ingest_book_note_bytes(
                "剑来摘录.txt",
                "好句\n走在正确的道路上，悟性再差，只要够勤奋坚韧，每天终究是在进步。".encode("utf-8"),
                "jianlai",
            )
            saved = xiangzhongjing_store.list_book_citations("", limit=5)

        self.assertEqual(result["book_id"], "jianlai")
        self.assertTrue(saved)
        self.assertEqual(saved[0]["project_id"], "")
        self.assertIn("走在正确的道路上", saved[0]["quote"])
        self.assertEqual(saved[0]["material_type"], "direct_quote")
        self.assertEqual(saved[0]["quality_status"], "valid")

    def test_store_migrates_book_quality_columns(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            xiangzhongjing_store.initialize_store()
            with xiangzhongjing_store._connect() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(book_citations)").fetchall()
                }
        self.assertTrue({"material_type", "quality_status", "quality_reason", "source_locator"} <= columns)

    def test_musk_pdf_line_join_and_chapter_rejection(self) -> None:
        lines = _join_pdf_lines([
            "《埃隆·马斯克传》",
            "-方法论-",
            "5.每当有问题需要解决时，不要只与你直接管理的相关负责人聊。深入调研就要跨层级沟",
            "通，去跟你属下的属下直接交流吧。",
            "01冒险家",
            "“我知道只要我做好了准备，我就可以去冒险。”",
        ])
        records = _material_records("musk", lines)
        communication = next(item for item in records if "跨层级沟" in item["quote"])
        chapter = next(item for item in records if item["quote"] == "01冒险家")
        self.assertIn("沟通，去跟", communication["quote"])
        self.assertEqual(communication["material_type"], "reading_note")
        self.assertEqual(chapter["material_type"], "metadata")

    def test_daode_negated_quote_is_not_extracted_as_direct_quote(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            ingest_book_note_bytes(
                "道德经再读.txt",
                "绝非“千里之行，始于足下”，这里是在讨论另一种理解。".encode("utf-8"),
                "daode",
            )
            saved = xiangzhongjing_store.list_book_citations("", limit=10)
        self.assertEqual(saved[0]["material_type"], "reading_note")
        self.assertFalse(any(item["quote"] == "千里之行，始于足下" for item in saved))

    @patch("services.deepseek_service.list_book_citations")
    def test_local_candidate_loader_filters_metadata_and_balances_books(self, list_mock) -> None:
        rows = []
        for book, book_id, quote, material_type in (
            ("《剑来》", "jianlai", "老秀才（文圣·荀子）", "metadata"),
            ("《剑来》", "jianlai", "走在正确的道路上，每天终究是在进步。", "direct_quote"),
            ("《埃隆·马斯克传》", "musk", "把要求变得不那么愚蠢。", "direct_quote"),
            ("《道德经》", "daode", "我们会通过观察别人来了解别人，但不会这样观察自己。", "reading_note"),
            ("《道德经》", "daode", "知人者智，自知者明。", "direct_quote"),
        ):
            rows.append({
                "book": book,
                "book_id": book_id,
                "quote": quote,
                "attribution": "作者",
                "source_title": f"{book_id}.docx",
                "source_url": f"local-note://{book_id}/1",
                "evidence_text": quote,
                "material_type": material_type,
                "quality_status": "valid",
            })
        list_mock.return_value = rows

        candidates = _saved_book_support_candidates("project", ["jianlai", "musk", "daode"])

        self.assertEqual({item["book_id"] for item in candidates}, {"jianlai", "musk", "daode"})
        self.assertFalse(any("老秀才" in item["quote"] for item in candidates))
        self.assertFalse(any("我们会通过观察" in item["quote"] for item in candidates))
        list_mock.assert_called_once_with("project", limit=2000)

    @patch("services.deepseek_service.list_book_citations")
    def test_candidate_loader_excludes_pending_and_quarantined_material(self, list_mock) -> None:
        list_mock.return_value = [
            {
                "book": "《剑来》",
                "book_id": "jianlai",
                "quote": "这条原句已经通过书库校验。",
                "source_title": "剑来摘录.docx",
                "source_url": "local-note://jianlai/1",
                "evidence_text": "这条原句已经通过书库校验。",
                "material_type": "direct_quote",
                "quality_status": "valid",
            },
            {
                "book": "《剑来》",
                "book_id": "jianlai",
                "quote": "这条内容仍然等待人工复核。",
                "source_title": "剑来摘录.docx",
                "source_url": "local-note://jianlai/2",
                "evidence_text": "这条内容仍然等待人工复核。",
                "material_type": "direct_quote",
                "quality_status": "pending_review",
            },
            {
                "book": "《剑来》",
                "book_id": "jianlai",
                "quote": "这是章节标题一类的无效内容。",
                "source_title": "剑来摘录.docx",
                "source_url": "local-note://jianlai/3",
                "evidence_text": "这是章节标题一类的无效内容。",
                "material_type": "metadata",
                "quality_status": "quarantined",
            },
        ]
        candidates = _saved_book_support_candidates("project", ["jianlai"])
        self.assertEqual([item["quote"] for item in candidates], ["这条原句已经通过书库校验。"])

    @patch("services.deepseek_service.list_book_citations")
    def test_trusted_ctext_chapter_quote_is_generation_ready(self, list_mock) -> None:
        quote = "知人者智，自知者明。"
        list_mock.return_value = [{
            "book": "《道德经》",
            "book_id": "daode",
            "quote": quote,
            "attribution": "老子",
            "source_title": "联网检索·Chinese Text Project《道德经》·第33章",
            "source_url": "https://ctext.org/dao-de-jing/ens",
            "evidence_text": f"第33章：{quote}",
            "material_type": "direct_quote",
            "quality_status": "valid",
        }]
        candidates = _saved_book_support_candidates("project", ["daode"])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "chapter_source")

    def test_book_library_can_return_more_than_one_hundred_assets(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            xiangzhongjing_store.save_book_citations(
                "",
                [
                    {
                        "book": "《剑来》",
                        "quote": f"这是第 {index} 条可查看的本地书库素材。",
                        "source_title": "test.txt",
                        "url": f"local-note://jianlai/test/{index}",
                        "material_type": "direct_quote",
                        "quality_status": "valid",
                    }
                    for index in range(130)
                ],
            )
            loaded = xiangzhongjing_store.list_book_citations("", limit=500)
            recent = xiangzhongjing_store.book_citation_summary(limit=240)["recent"]

        self.assertEqual(len(loaded), 130)
        self.assertEqual(len(recent), 130)

    def test_global_library_listing_does_not_include_project_citations(self) -> None:
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            xiangzhongjing_store.save_book_citations("", [{
                "book": "《剑来》", "quote": "全局素材应当显示。", "source_title": "global.txt"
            }])
            xiangzhongjing_store.save_book_citations("project-a", [{
                "book": "《剑来》", "quote": "项目引文不应混进全局页。", "source_title": "project.txt"
            }])
            loaded = xiangzhongjing_store.list_book_citations("", limit=50)
        self.assertEqual([item["quote"] for item in loaded], ["全局素材应当显示。"])

    @patch("services.deepseek_service.save_book_citations")
    @patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "个人风格"))
    @patch("services.deepseek_service.run_json")
    def test_integrated_support_keeps_only_a_local_exact_quote(
        self,
        run_json_mock,
        _load_style_mock,
        save_citations_mock,
    ) -> None:
        quote = "知足不辱，知止不殆，可以长久。"
        context = f"忙完以后，我重新理解了取舍。《道德经》里有这样一句话：“{quote}”"
        run_json_mock.return_value = skill_result({
            "updated_copy": context,
            "supports": [{
                "mode": "exact_quote",
                "candidate_index": 0,
                "book": "《道德经》",
                "quote": quote,
                "text": f"《道德经》里有这样一句话：“{quote}”",
                "attribution": "老子",
                "reason": "与结尾的取舍判断相连",
                "location": "结尾回扣",
            }],
        })
        candidate = {
            "book": "《道德经》",
            "book_id": "daode",
            "quote": quote,
            "attribution": "老子",
            "url": "local-note://daode/test/1",
            "source_title": "道德经再读.docx",
            "source_type": "local_note",
            "evidence_text": quote,
            "verified": True,
        }

        with patch("services.deepseek_service._available_books", return_value=TEST_BOOKS):
            result = _run_integrated_book_support(
                "忙完以后，我重新理解了取舍。",
                {"project_id": "project-test", "theme": "取舍"},
                {"central_tension": "向前走与懂得取舍"},
                ["daode"],
                [candidate],
                [],
            )

        self.assertEqual(result["status"], "integrated")
        self.assertEqual(result["supports"][0]["mode"], "exact_quote")
        self.assertEqual(result["supports"][0]["source_title"], "道德经再读.docx")
        self.assertIn(quote, result["updated_copy"])
        self.assertEqual(result["online_results"], [])
        save_citations_mock.assert_called_once()

    @patch("services.deepseek_service.save_book_citations")
    @patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "个人风格"))
    @patch("services.deepseek_service.run_json")
    def test_thought_transfer_is_rejected_and_original_draft_is_kept(
        self,
        run_json_mock,
        _load_style_mock,
        save_citations_mock,
    ) -> None:
        draft = "我没有急着证明什么。"
        transfer = "想到《道德经》时，我更愿意把取舍理解成给生活留下余地。"
        run_json_mock.return_value = skill_result({
            "updated_copy": f"{draft}{transfer}",
            "supports": [{
                "mode": "thought_transfer",
                "book": "《道德经》",
                "quote": "",
                "text": transfer,
            }],
        })
        candidate = {
            "book": "《道德经》",
            "book_id": "daode",
            "quote": "知人者智，自知者明。",
            "attribution": "老子",
            "url": "local-note://daode/test/1",
            "source_title": "道德经再读.docx",
            "source_type": "local_note",
        }

        with patch("services.deepseek_service._available_books", return_value=TEST_BOOKS):
            result = _run_integrated_book_support(
                draft,
                {"project_id": "project-test"},
                {},
                ["daode"],
                [candidate],
                [],
            )

        self.assertEqual(result["status"], "none")
        self.assertEqual(result["updated_copy"], draft)
        self.assertEqual(result["supports"], [])
        save_citations_mock.assert_not_called()

    @patch("services.deepseek_service.run_json")
    def test_no_local_candidate_keeps_original_without_model_call(self, run_json_mock) -> None:
        draft = "这是原稿。"
        result = _run_integrated_book_support(draft, {}, {}, ["daode"], [], [])
        self.assertEqual(result["status"], "none")
        self.assertEqual(result["updated_copy"], draft)
        run_json_mock.assert_not_called()

    def test_generation_book_support_never_calls_online_search(self) -> None:
        source = inspect.getsource(_integrated_book_support_sync)
        self.assertNotIn("search_book_queries", source)
        self.assertNotIn("online_search", source)

    @patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "个人风格"))
    @patch("services.deepseek_service.run_json")
    @patch("services.deepseek_service._saved_book_support_candidates")
    def test_manual_research_endpoint_matches_local_candidate_only(
        self,
        candidates_mock,
        run_json_mock,
        _load_style_mock,
    ) -> None:
        candidate = {
            "book": "《道德经》",
            "book_id": "daode",
            "quote": "知人者智，自知者明。",
            "attribution": "老子",
            "url": "local-note://daode/test/1",
            "source_title": "道德经再读.docx",
            "source_type": "local_note",
        }
        candidates_mock.return_value = [candidate]
        run_json_mock.return_value = skill_result(
            {"matches": [{"candidate_index": 0, "fit": "对应自我认识", "insertion_point": "中段转念"}]},
            skill="research-book-quotes",
        )

        with patch("services.deepseek_service._available_books", return_value=TEST_BOOKS):
            result = _research_books_sync(
                {"draft": "我开始重新认识自己。", "selected_books": ["daode"]}
            )

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["candidates"][0]["quote"], candidate["quote"])
        self.assertEqual(result["online_results"], [])
        self.assertEqual(result["queries"], [])


if __name__ == "__main__":
    unittest.main()
