import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from docx import Document

from api.style import _extract_reference_text
from services import settings_store, xiangzhongjing_store
from services.book_notes_service import ingest_book_note_bytes
from services.deepseek_service import load_writing_skill
from services.dialogue_service import dialogue_personas
from services.onboarding_service import onboarding_status


class CreatorOnboardingContractTests(unittest.TestCase):
    def test_blank_install_has_no_private_books_or_book_personas(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "blank.db"
        ):
            payload = dialogue_personas()

        self.assertEqual(payload["books"], {})
        self.assertEqual(
            [(item["id"], item["type"]) for item in payload["personas"]],
            [("mirror-self", "mirror")],
        )

    def test_legacy_citations_backfill_three_books_and_four_personas(self):
        citations = [
            ("《剑来》", "走在正确的道路上，每天终究是在进步。"),
            ("《埃隆·马斯克传》", "把要求变得不那么愚蠢。"),
            ("《道德经》", "知人者智，自知者明。"),
        ]
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "legacy.db"
        ):
            xiangzhongjing_store.save_book_citations(
                "",
                [
                    {
                        "book": book,
                        "quote": quote,
                        "source_title": "legacy-note.txt",
                        "material_type": "direct_quote",
                        "quality_status": "valid",
                    }
                    for book, quote in citations
                ],
            )
            xiangzhongjing_store.initialize_store()
            books = xiangzhongjing_store.list_library_books()
            personas = xiangzhongjing_store.list_book_personas()
            stored = xiangzhongjing_store.list_book_citations("", limit=10)

        self.assertEqual({item["id"] for item in books}, {"jianlai", "musk", "daode"})
        self.assertEqual(
            {item["id"] for item in personas},
            {"musk-action", "chen-ping-an", "qi-jing-chun", "laozi-daodejing"},
        )
        self.assertEqual({item["book_id"] for item in stored}, {"jianlai", "musk", "daode"})

    def test_generic_txt_import_classifies_quotes_notes_and_review_candidates(self):
        text = "\n".join(
            (
                "“真正重要的不是看见答案，而是学会提出自己的问题。”",
                "没有引号的短句需要创作者确认后才能直接引用。",
                "我的思考：这句话让我重新理解了长期积累。",
            )
        )
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "generic.db"
        ):
            result = ingest_book_note_bytes(
                "思考练习.txt",
                text.encode("utf-8"),
                title="《思考练习》",
                author="示例作者",
            )
            books = xiangzhongjing_store.list_library_books()
            citations = xiangzhongjing_store.list_book_citations("", limit=20)

        self.assertEqual(result["count"], 3)
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["title"], "《思考练习》")
        self.assertIn(("direct_quote", "valid"), {(item["material_type"], item["quality_status"]) for item in citations})
        self.assertIn(("direct_quote", "pending_review"), {(item["material_type"], item["quality_status"]) for item in citations})
        self.assertIn("reading_note", {item["material_type"] for item in citations})

    def test_pending_quote_can_be_approved_and_updates_book_counts(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "approval.db"
        ):
            ingest_book_note_bytes(
                "边界.txt",
                "未经引号标记的候选句需要先经过人工确认。".encode("utf-8"),
                title="《边界》",
            )
            citation = xiangzhongjing_store.list_book_citations("", limit=1)[0]
            self.assertEqual(citation["quality_status"], "pending_review")
            updated = xiangzhongjing_store.update_book_citation_quality(
                citation["id"],
                material_type="direct_quote",
                quality_status="valid",
                quality_reason="创作者已对照自己的书籍或笔记确认原句",
            )
            book = xiangzhongjing_store.list_library_books()[0]

        self.assertTrue(updated)
        self.assertEqual(book["quotable_count"], 1)

    def test_dynamic_book_persona_lifecycle(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "persona.db"
        ):
            book = xiangzhongjing_store.create_library_book(
                "《思考练习》", author="示例作者"
            )
            persona = xiangzhongjing_store.create_book_persona(
                "提问者",
                [book["id"]],
                description="陪我把问题问清楚",
            )
            updated = xiangzhongjing_store.update_book_persona(
                persona["id"], {"voice": "克制、直接、先追问再回答"}
            )
            deleted = xiangzhongjing_store.delete_book_persona(persona["id"])
            active = xiangzhongjing_store.list_book_personas()
            archived = xiangzhongjing_store.list_book_personas(include_archived=True)

        self.assertEqual(updated["voice"], "克制、直接、先追问再回答")
        self.assertTrue(deleted)
        self.assertEqual(active, [])
        self.assertEqual(archived[0]["status"], "archived")

    def test_project_keeps_selected_dynamic_books_after_save_and_load(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "state.db"
        ):
            book = xiangzhongjing_store.create_library_book("《我的书》")
            saved = xiangzhongjing_store.save_state(
                {
                    "_revision": 0,
                    "activeProject": "project-one",
                    "projects": {
                        "project-one": {
                            "id": "project-one",
                            "title": "第一篇",
                            "selected_books": [book["id"]],
                            "copy": "",
                        }
                    },
                }
            )
            loaded = xiangzhongjing_store.load_state()

        self.assertEqual(saved["revision"], 1)
        self.assertEqual(loaded["projects"]["project-one"]["selected_books"], [book["id"]])

    def test_txt_and_docx_reference_extractors_preserve_creator_text(self):
        text = "这是第一段历史文案。" * 10
        document = Document()
        document.add_paragraph(text)
        buffer = BytesIO()
        document.save(buffer)

        self.assertEqual(_extract_reference_text("history.txt", text.encode("utf-8")), text)
        self.assertEqual(_extract_reference_text("history.docx", buffer.getvalue()), text)

    def test_onboarding_readiness_transitions_from_blank_to_complete(self):
        fake_config = SimpleNamespace(
            deepseek_api_key="configured-key",
            deepseek_api_base="https://example.invalid",
            deepseek_model="creator-model",
        )
        profile = {
            "display_name": "测试创作者",
            "creator_positioning": "记录真实生活与个人成长",
            "content_columns": "校园、工作、创作",
            "style_keywords": "真诚、克制",
            "avatar_path": "",
        }
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "onboarding.db"
        ), patch("services.onboarding_service.app_config", fake_config), patch(
            "services.onboarding_service.profile", return_value=profile
        ), patch(
            "services.onboarding_service.memory_engine_status",
            return_value={"documents": 1, "total_chunks": 2},
        ):
            load_writing_skill()
            blank = onboarding_status()
            settings_store.set_setting("DEEPSEEK_LAST_VERIFIED_AT", "2026-08-15T12:00:00")
            settings_store.set_setting(
                "DEEPSEEK_LAST_VERIFIED_SIGNATURE",
                "https://example.invalid|creator-model",
            )
            xiangzhongjing_store.save_reference_document(
                "第一篇.txt", "这是一篇用于建立个人创作 DNA 的真实历史文案。" * 12, {}
            )
            book = xiangzhongjing_store.create_library_book("《我的书》")
            xiangzhongjing_store.create_book_persona("书中朋友", [book["id"]])
            xiangzhongjing_store.save_state(
                {
                    "_revision": 0,
                    "projects": {
                        "first": {
                            "id": "first",
                            "title": "第一篇",
                            "copy": "这是一篇已经生成并准备继续修改的文案。",
                        }
                    },
                }
            )
            complete = onboarding_status()

        self.assertFalse(blank["ready"])
        self.assertTrue(complete["ready"])
        self.assertEqual(complete["progress"], {"ready": 7, "total": 7})
        self.assertIsNone(complete["next_stage"])


if __name__ == "__main__":
    unittest.main()
