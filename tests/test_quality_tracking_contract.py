from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services import xiangzhongjing_store
from tests.frontend_assets import backend_source, demo_source


BASE_DIR = Path(__file__).resolve().parents[1]


class QualityTrackingContractTests(unittest.TestCase):
    def test_quality_summary_is_exposed_without_an_extra_form(self) -> None:
        main = backend_source()
        html = demo_source()
        self.assertIn('@router.get("/quality-summary")', main)
        self.assertIn('id="quality-observation-progress"', html)
        self.assertIn('XZJApi.request("/api/xiangzhongjing/quality-summary")', html)
        self.assertNotIn("请为这次生成评分", html)

    def test_publication_automatically_records_generation_and_adoption(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(temp_dir) / "quality.db",
        ):
            xiangzhongjing_store.initialize_store()
            xiangzhongjing_store.save_state({"diaryEntries": []})

            failed = xiangzhongjing_store.create_generation_job({"project_id": "project-1"})
            xiangzhongjing_store.update_generation_job(
                failed["generation_id"],
                status="failed",
                current_stage="write-personal-vlog",
                failed_stage="write-personal-vlog",
                error={"code": "MODEL_REQUEST_FAILED"},
            )
            succeeded = xiangzhongjing_store.create_generation_job({"project_id": "project-1"})
            generated_copy = "\n\n".join(
                [
                    "事情结束以后，我重新听见了生活本身。",
                    "工位、出租屋和球场，让日子重新有了节奏。",
                    "后来我才明白，人先活回来，答案才会慢慢出现。",
                ]
            )
            xiangzhongjing_store.update_generation_job(
                succeeded["generation_id"],
                status="succeeded",
                current_stage="completed",
                result={
                    "copy": generated_copy,
                    "style_version": "v2.1",
                },
            )

            xiangzhongjing_store.save_state(
                {
                    "diaryEntries": [
                        {
                            "id": "diary-1",
                            "project_id": "project-1",
                            "project_title": "回来",
                            "copy": generated_copy,
                            "published_at": "2026-08-08T10:00:00.000Z",
                        }
                    ]
                }
            )
            summary = xiangzhongjing_store.creation_quality_summary()

        self.assertEqual(summary["sample_count"], 1)
        self.assertEqual(summary["target_samples"], 5)
        self.assertEqual(summary["adoption_counts"], {"direct": 1})
        outcome = summary["outcomes"][0]
        self.assertEqual(outcome["generation_attempts"], 2)
        self.assertEqual(outcome["regeneration_count"], 1)
        self.assertEqual(outcome["failed_generations"], 1)
        self.assertEqual(outcome["style_version"], "v2.1")
        self.assertEqual(outcome["edit_distance_ratio"], 0.0)

    def test_same_diary_entry_is_never_counted_twice(self) -> None:
        state = {
            "diaryEntries": [
                {
                    "id": "diary-1",
                    "project_id": "project-1",
                    "project_title": "回来",
                    "copy": "这是一篇已经正式发布的完整文案稿。",
                    "published_at": "2026-08-08T10:00:00.000Z",
                }
            ]
        }
        with TemporaryDirectory() as temp_dir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(temp_dir) / "quality.db",
        ):
            xiangzhongjing_store.save_state({"diaryEntries": []})
            xiangzhongjing_store.save_state(state)
            xiangzhongjing_store.save_state(state)
            summary = xiangzhongjing_store.creation_quality_summary()

        self.assertEqual(summary["sample_count"], 1)

    def test_same_project_is_only_counted_once(self) -> None:
        entries = [
            {
                "id": "diary-1",
                "project_id": "project-1",
                "project_title": "回来",
                "copy": "这是同一个项目第一次正式发布的完整文案稿。",
                "published_at": "2026-08-08T10:00:00.000Z",
            },
            {
                "id": "diary-2",
                "project_id": "project-1",
                "project_title": "回来",
                "copy": "这是同一个项目第二次正式发布的完整文案稿。",
                "published_at": "2026-08-08T11:00:00.000Z",
            },
        ]
        with TemporaryDirectory() as temp_dir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(temp_dir) / "quality.db",
        ):
            xiangzhongjing_store.save_state({"diaryEntries": []})
            xiangzhongjing_store.save_state({"diaryEntries": entries})
            summary = xiangzhongjing_store.creation_quality_summary()

        self.assertEqual(summary["sample_count"], 1)

    def test_quality_cohort_freezes_after_five_projects(self) -> None:
        entries = [
            {
                "id": f"diary-{index}",
                "project_id": f"project-{index}",
                "project_title": f"项目 {index}",
                "copy": f"这是第 {index} 个真实项目正式发布的完整文案稿。",
                "published_at": f"2026-08-08T1{index}:00:00.000Z",
            }
            for index in range(6)
        ]
        with TemporaryDirectory() as temp_dir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(temp_dir) / "quality.db",
        ):
            xiangzhongjing_store.save_state({"diaryEntries": []})
            xiangzhongjing_store.save_state({"diaryEntries": entries})
            summary = xiangzhongjing_store.creation_quality_summary(limit=20)

        self.assertEqual(summary["sample_count"], 5)
        self.assertEqual(summary["target_samples"], 5)

    def test_edit_distance_is_exact_and_ignores_whitespace(self) -> None:
        self.assertEqual(
            xiangzhongjing_store._normalized_edit_distance("子 坤", "子期"),
            2 / 3,
        )
        self.assertEqual(
            xiangzhongjing_store._normalized_edit_distance(
                xiangzhongjing_store._copy_signature("我就是 创作者本人"),
                xiangzhongjing_store._copy_signature("我就是创作者本人"),
            ),
            0.0,
        )

    def test_v22_baseline_preserves_layered_non_regression_contract(self) -> None:
        baseline = (BASE_DIR / "knowledge" / "generic_creator_writing_skill.md").read_text(encoding="utf-8")
        self.assertIn("规则优先级", baseline)
        self.assertIn("叙事模式", baseline)
        self.assertIn("原句", baseline)
        self.assertIn("改写（默认）", baseline)
        self.assertIn("阐释", baseline)
        self.assertIn("只使用请求中提供且已核验的直接引文", baseline)

        private_candidate_path = BASE_DIR / "knowledge" / "xiangzhongjing_writing_skill_v2_2_candidate.md"
        if private_candidate_path.exists():
            candidate = private_candidate_path.read_text(encoding="utf-8")
            self.assertIn("核心创作 DNA（始终激活）", candidate)
            self.assertIn("叙事策略（只激活一种）", candidate)
            self.assertNotIn("六篇历史文稿", candidate)


if __name__ == "__main__":
    unittest.main()
