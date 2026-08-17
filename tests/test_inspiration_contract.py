from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services import inspiration_service, xiangzhongjing_store
from services.skill_runtime import SkillExecutionError
from tests.frontend_assets import demo_source


BASE_DIR = Path(__file__).resolve().parents[1]


def generation_context() -> dict:
    return {
        "profile": {"display_name": "创作者本人"},
        "style_version": "v2.2",
        "style": "个人风格",
        "workspace": {"projects": [], "diary": []},
        "memories": [{"title": "历史文稿", "content": "回忆支撑今天的选择", "source_type": "history_document"}],
        "quotes": [
            {
                "id": "quote-1",
                "book": "《道德经》",
                "attribution": "老子",
                "quote": "知人者智，自知者明。",
                "source_locator": "第三十三章",
            }
        ],
        "recent_draws": [],
        "context_sources": ["已发布个人 DNA", "历史文稿"],
    }


def candidates(quote_id: str = "quote-1") -> list[dict]:
    return [
        {
            "title": f"今日命题{index}",
            "core_insight": f"这是第{index}条足够具体的个人洞察，它来自真实历史记忆，并且能够继续发展成为今天的创作。",
            "why_today": "因为近期创作重新触碰到了回忆与选择之间的关系，此刻适合把它说清楚。",
            "keywords": ["回忆", "选择", "今天"],
            "three_questions": ["哪段回忆还在影响选择？", "它为什么今天出现？", "它应该如何被拍下来？"],
            "shootable_scenes": ["翻看旧视频的桌面", "走回熟悉的校园路线"],
            "action": "用三个具体画面写一段二百字的蒙太奇。",
            "quote_id": quote_id,
        }
        for index in range(1, 4)
    ]


class InspirationContractTests(unittest.TestCase):
    def test_frontend_uses_server_engine_and_has_archive_filters(self):
        source = demo_source()
        self.assertIn("/api/xiangzhongjing/inspiration/today", source)
        self.assertIn("/api/xiangzhongjing/inspiration/draw", source)
        self.assertIn('id="inspiration-archive-type"', source)
        self.assertIn('id="inspiration-archive-status"', source)
        self.assertIn("为什么是今天", source)
        self.assertIn("可拍场景", source)
        self.assertIn("有启发", source)
        self.assertIn("不适合我", source)
        self.assertIn("/feedback", source)
        self.assertIn("/api/xiangzhongjing/inspiration/metrics", source)
        self.assertNotIn("const inspirationBanks", source)

    def test_daily_draw_is_idempotent_across_types(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "inspiration.db"
        ), patch.object(inspiration_service, "local_date", return_value="2026-08-15"), patch.object(
            inspiration_service, "_import_legacy_draws"
        ), patch.object(
            inspiration_service, "_build_generation_context", return_value=generation_context()
        ), patch.object(
            inspiration_service,
            "_generate_candidates",
            return_value=(candidates(), {"model": "test-model", "latency_ms": 80}),
        ) as generate:
            first = inspiration_service.draw_daily("theme")
            second = inspiration_service.draw_daily("book")

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["draw"]["id"], second["draw"]["id"])
        self.assertEqual(second["draw"]["type"], "theme")
        self.assertEqual(generate.call_count, 1)

    def test_failed_generation_does_not_consume_daily_chance(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "retry.db"
        ), patch.object(inspiration_service, "local_date", return_value="2026-08-15"), patch.object(
            inspiration_service, "_import_legacy_draws"
        ), patch.object(
            inspiration_service, "_build_generation_context", return_value=generation_context()
        ), patch.object(
            inspiration_service,
            "_generate_candidates",
            side_effect=SkillExecutionError("MODEL_REQUEST_FAILED", "模型暂时不可用"),
        ):
            with self.assertRaises(SkillExecutionError):
                inspiration_service.draw_daily("theme")
            self.assertIsNone(inspiration_service.today_draw()["draw"])

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "retry-success.db"
        ), patch.object(inspiration_service, "local_date", return_value="2026-08-15"), patch.object(
            inspiration_service, "_import_legacy_draws"
        ), patch.object(
            inspiration_service, "_build_generation_context", return_value=generation_context()
        ), patch.object(
            inspiration_service,
            "_generate_candidates",
            return_value=(candidates(), {"model": "test-model", "latency_ms": 60}),
        ):
            result = inspiration_service.draw_daily("theme")
        self.assertTrue(result["created"])

    def test_model_cannot_invent_a_direct_quote(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "quotes.db"
        ), patch.object(inspiration_service, "local_date", return_value="2026-08-15"), patch.object(
            inspiration_service, "_import_legacy_draws"
        ), patch.object(
            inspiration_service, "_build_generation_context", return_value=generation_context()
        ), patch.object(
            inspiration_service,
            "_generate_candidates",
            return_value=(candidates("invented-quote"), {"model": "test-model", "latency_ms": 60}),
        ):
            result = inspiration_service.draw_daily("book")

        self.assertEqual(result["draw"]["quote"], "")
        self.assertEqual(result["draw"]["quote_source"], "")

    def test_archive_tracks_favorite_conversion_delete_and_restore(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "archive.db"
        ), patch.object(inspiration_service, "local_date", return_value="2026-08-15"), patch.object(
            inspiration_service, "_import_legacy_draws"
        ), patch.object(
            inspiration_service, "_build_generation_context", return_value=generation_context()
        ), patch.object(
            inspiration_service,
            "_generate_candidates",
            return_value=(candidates(), {"model": "test-model", "latency_ms": 60}),
        ):
            draw = inspiration_service.draw_daily("theme")["draw"]
            updated = inspiration_service.update_draw(
                draw["id"], favorited=True, conversion="project:demo"
            )
            feedback = inspiration_service.save_feedback(
                draw["id"],
                verdict="not_useful",
                reasons=["too_vague", "unlike_me", "invalid"],
                note="还不够贴近近期状态",
            )
            metrics = inspiration_service.inspiration_metrics(days=14)
            inspiration_service.delete_draw(draw["id"])
            deleted = inspiration_service.list_draws(status="deleted", include_deleted=True)
            restored = inspiration_service.restore_draw(draw["id"])

        self.assertTrue(updated["favorited"])
        self.assertEqual(updated["conversion_status"], "converted")
        self.assertEqual(feedback["feedback"]["verdict"], "not_useful")
        self.assertEqual(feedback["feedback"]["reasons"], ["too_vague", "unlike_me"])
        self.assertEqual(metrics["draw_count"], 1)
        self.assertEqual(metrics["feedback_count"], 1)
        self.assertEqual(metrics["converted_count"], 1)
        self.assertEqual(metrics["reason_counts"]["too_vague"], 1)
        self.assertEqual(deleted["total"], 1)
        self.assertTrue(deleted["items"][0]["deleted_at"])
        self.assertEqual(restored["deleted_at"], "")

    def test_daily_inspiration_skill_is_registered(self):
        skill = (BASE_DIR / "product_skills" / "draw-daily-inspiration" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("name: draw-daily-inspiration", skill)
        self.assertIn("quote_id", skill)

    def test_application_imports_on_supported_python_runtime(self):
        from main import app

        paths = {route.path for route in app.routes}
        self.assertIn("/api/xiangzhongjing/inspiration/today", paths)
        self.assertIn("/api/xiangzhongjing/inspiration/draw", paths)
        self.assertIn("/api/xiangzhongjing/inspiration/metrics", paths)


if __name__ == "__main__":
    unittest.main()
