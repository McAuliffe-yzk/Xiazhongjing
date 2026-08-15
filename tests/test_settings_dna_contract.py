from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from api.contracts import GenerateCopyRequest
from services import dna_store, settings_store
from services.deepseek_service import writing_context
from services.skill_runtime import SkillExecutionError, set_skill_enabled


class SettingsDnaContractTests(unittest.TestCase):
    def test_settings_store_round_trips_values(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            settings_store,
            "DB_PATH",
            Path(temp_dir) / "settings.db",
        ):
            settings_store.set_setting("DEEPSEEK_MODEL", "deepseek-chat")
            self.assertEqual(settings_store.get_setting("DEEPSEEK_MODEL"), "deepseek-chat")
            self.assertEqual(settings_store.get_all_settings()["DEEPSEEK_MODEL"], "deepseek-chat")

    def test_dna_store_lists_without_large_source_text(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            dna_store,
            "DB_PATH",
            Path(temp_dir) / "dna.db",
        ):
            created = dna_store.create_dna_reagent(
                "外部风味",
                "只做语言试剂",
                "句式更短，节奏更快。",
                ["快节奏"],
                "很长的样本文字" * 40,
                "paste",
            )
            listed = dna_store.list_dna_reagents()[0]
            self.assertEqual(created["name"], listed["name"])
            self.assertNotIn("source_text", listed)
            self.assertNotIn("content", listed)

    def test_generate_request_carries_optional_dna_ids(self) -> None:
        payload = GenerateCopyRequest(active_dna_ids=[1, 2]).service_payload()
        self.assertEqual(payload["active_dna_ids"], [1, 2])

    def test_empty_dna_ids_keep_personal_context_unchanged(self) -> None:
        with patch(
            "services.deepseek_service.load_writing_skill",
            return_value=("v2.1", "个人 DNA"),
        ), patch(
            "services.deepseek_service.get_dna_reagents_by_ids",
            return_value=[],
        ) as get_reagents:
            version, context = writing_context({"active_dna_ids": []})
        self.assertEqual(version, "v2.1")
        self.assertEqual(context, "个人 DNA")
        get_reagents.assert_not_called()

    def test_selected_dna_is_appended_as_optional_reagent(self) -> None:
        with patch(
            "services.deepseek_service.load_writing_skill",
            return_value=("v2.1", "个人 DNA"),
        ), patch(
            "services.deepseek_service.get_dna_reagents_by_ids",
            return_value=[
                {"id": 1, "name": "外部风味", "content": "短句推进。", "tags": ["节奏"]}
            ],
        ):
            _, context = writing_context({"active_dna_ids": [1]})
        self.assertIn("个人 DNA", context)
        self.assertIn("可选外部博主 DNA 试剂", context)
        self.assertIn("短句推进", context)
        self.assertIn("不得覆盖当前创作者的个人 DNA", context)

    def test_core_skill_cannot_be_disabled(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            settings_store,
            "DB_PATH",
            Path(temp_dir) / "skills.db",
        ):
            settings_store.upsert_skill_registry(
                {
                    "name": "write-personal-vlog",
                    "display_name": "个人声音写作",
                    "phase": "创作",
                    "description": "核心写作 Skill",
                    "source": "builtin",
                    "core": 1,
                    "enabled": 1,
                    "dir_path": "/tmp/write-personal-vlog",
                    "sort_order": 0,
                }
            )
            with self.assertRaises(SkillExecutionError):
                set_skill_enabled("write-personal-vlog", False)


if __name__ == "__main__":
    unittest.main()
