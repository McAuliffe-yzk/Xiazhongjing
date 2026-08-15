import unittest
from unittest.mock import patch

from services.deepseek_service import (
    _audit_paragraph_replacements,
    _audit_opening_options,
    _clean_edit_changes,
    _edit_copy_sync,
    _edit_difference,
    _opening_options_are_distinct,
    _paragraph_rewrite_difference,
    _protected_material_lines,
)
from services.skill_runtime import SkillExecutionError


def paragraph_patch_result(
    paragraphs: list[str],
    changes: list[dict[str, str]],
    *,
    start_index: int = 1,
) -> dict:
    replacements = []
    for index, paragraph in enumerate(paragraphs):
        change = changes[index] if index < len(changes) else {}
        replacements.append(
            {
                "paragraph_index": start_index + index,
                "text": paragraph,
                "point": change.get("point", ""),
                "location": change.get("location", ""),
                "reason": change.get("reason", ""),
            }
        )
    return {
        "data": {"replacements": replacements},
        "run_id": "edit-run",
        "skill": "edit-vlog-copy",
        "version": "1.0.0",
        "model": "mock",
        "latency_ms": 10,
    }


def passing_audit(indexes: tuple[int, ...] = (1, 2, 3)) -> dict:
    return {
        "passed": True,
        "data": {
            "edit_check": {
                "goal_passed": True,
                "meaningful_change": True,
                "changes": [
                    {
                        "point": "重构观点进入方式",
                        "location": "第 1 段",
                        "reason": "让判断从事件中自然出现",
                    }
                ],
                "patch_checks": [
                    {
                        "paragraph_index": index,
                        "structural_change": True,
                        "only_word_or_connector_edits": False,
                        "new_claim_checks": [],
                        "unsupported_interpretations": [],
                        "passed": True,
                    }
                    for index in indexes
                ],
            }
        },
        "run_id": "audit-run",
        "skill": "audit-vlog-copy",
        "version": "1.0.0",
        "model": "mock",
        "latency_ms": 8,
    }


class EditContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_paragraphs = [
            "事情结束以后，我的生活重新恢复了原来的节奏。",
            "我每天在工位、出租屋和球场之间来回。",
            "我也开始重新思考自己正在做的事情。",
        ]
        self.rewrite_paragraphs = [
            "事情结束以后，先回来的其实不是某种宏大的答案，而是生活本身。",
            "书桌、客厅、街道，我又开始在这三个地方之间来回。",
            "后来我才发现，人重新有了节奏的时候，也会重新听见自己到底在想什么。",
        ]
        self.source = "\n\n".join(self.source_paragraphs)
        self.rewrite = "\n\n".join(self.rewrite_paragraphs)
        self.changes = [
            {
                "point": "把概括判断改为从校园日常中进入",
                "location": "第 1 段",
                "reason": "原文直接总结状态，缺少个人经历推动",
            },
            {
                "point": "增加一次自我追问",
                "location": "第 2 段",
                "reason": "让思考过程发生在观众面前",
            },
            {
                "point": "压低结论的确定感",
                "location": "第 3 段",
                "reason": "保留作者此刻仍在辨认答案的状态",
            },
        ]
        self.payload = {
            "action": "more-personal",
            "full_copy": self.source,
            "materials": {
                "theme": "回来",
                "insight": "重新找到生活节奏",
                "daily": "书桌、客厅、街道三点一线",
                "event": "回到日常",
            },
            "locked_paragraphs": [],
        }

    def test_punctuation_only_change_is_not_meaningful(self) -> None:
        metrics = _edit_difference("我回到日常。", "我回到日常！", "selection-polish")
        self.assertFalse(metrics["meaningful"])

    def test_selection_requires_structural_change_not_connector_edits(self) -> None:
        source = "说来也巧，我见了一个网友。我们聊了各自的人生，也聊了不同的打算。"
        shallow = "说来也是巧，我见了一个网友。我们聊了各自的人生，也聊了不同的打算。"
        rewritten = "见网友这件事，起初只是聊天。聊到各自的人生和打算时，我才发现，两条轨迹也可以短暂交在一起。"
        self.assertFalse(_edit_difference(source, shallow, "selection-polish")["meaningful"])
        self.assertTrue(_edit_difference(source, rewritten, "selection-polish")["meaningful"])

    def test_shorten_requires_actual_reduction(self) -> None:
        source = "这是一段重复解释。" * 20
        almost_same = "这是一段重复解释。" * 19
        shortened = "保留真正重要的部分。" * 10
        self.assertFalse(_edit_difference(source, almost_same, "shorten")["meaningful"])
        self.assertTrue(_edit_difference(source, shortened, "shorten")["meaningful"])

    def test_shorten_rejects_shallow_ten_percent_reduction(self) -> None:
        source = "这是一段重复解释。" * 20
        shallow = "这是一段重复解释。" * 17
        metrics = _edit_difference(source, shallow, "shorten")
        self.assertFalse(metrics["meaningful"])

    def test_focused_audit_rejects_model_reported_shallow_patch(self) -> None:
        model_result = {
            "data": {
                "passed": True,
                "assessment": "只删除了几个词",
                "items": [
                    {
                        "paragraph_index": 1,
                        "structural_change": False,
                        "only_word_or_connector_edits": True,
                        "new_claim_checks": [],
                        "unsupported_interpretations": [],
                        "passed": True,
                    }
                ],
            },
            "run_id": "audit-run",
            "skill": "audit-vlog-copy",
            "version": "1.0.0",
            "model": "mock",
            "latency_ms": 8,
        }
        with patch("services.deepseek_service.run_json", return_value=model_result):
            audit = _audit_paragraph_replacements(
                [{"paragraph_index": 1, "original": "原段落。", "edited": "原段。"}],
                {},
                "原段落。",
                "原段。",
            )

        self.assertFalse(audit["passed"])
        self.assertFalse(audit["data"]["edit_check"]["meaningful_change"])

    def test_paragraph_patch_rejects_deletion_only_word_edits(self) -> None:
        metrics = _paragraph_rewrite_difference(
            "我骑着车回到日常，不是那种放假式的放松。",
            "我骑车回到日常，不是放假式的松。",
        )
        self.assertTrue(metrics["deleted_only"])
        self.assertFalse(metrics["meaningful"])

    def test_change_summary_requires_all_three_fields(self) -> None:
        changes = _clean_edit_changes(
            [
                self.changes[0],
                {"point": "缺少原因", "location": "第 2 段"},
            ]
        )
        self.assertEqual(changes, [self.changes[0]])

    def test_numbered_quotes_become_protected_lines(self) -> None:
        protected = _protected_material_lines(
            {"quotes": "1. 成长，在时间跨度的加持下，真的像彩虹一般浪漫\n2. 我在，新的起点"}
        )
        self.assertEqual(
            protected,
            ["成长，在时间跨度的加持下，真的像彩虹一般浪漫", "我在，新的起点"],
        )

    def test_focused_patch_audit_rejects_unsupported_new_action(self) -> None:
        model_result = {
            "data": {
                "passed": False,
                "assessment": "新增了原段没有的动作",
                "items": [
                    {
                        "paragraph_index": 1,
                        "structural_change": True,
                        "only_word_or_connector_edits": False,
                        "new_claim_checks": [
                            {
                                "phrase": "聊完往回走",
                                "category": "action",
                                "source_evidence": "",
                                "supported": False,
                            }
                        ],
                        "unsupported_interpretations": [],
                        "passed": False,
                    }
                ],
            },
            "run_id": "audit-run",
            "skill": "audit-vlog-copy",
            "version": "1.0.0",
            "model": "mock",
            "latency_ms": 8,
        }
        with patch("services.deepseek_service.run_json", return_value=model_result):
            audit = _audit_paragraph_replacements(
                [{"paragraph_index": 1, "original": "我见了一个网友。", "edited": "聊完往回走，我想了很多。"}],
                {"theme": "社交", "daily": "见了一个网友"},
                "我见了一个网友。",
                "聊完往回走，我想了很多。",
            )

        self.assertFalse(audit["passed"])
        self.assertEqual(audit["data"]["unsupported_claims"][0]["phrase"], "聊完往回走")

    def test_same_output_retries_then_accepts_real_rewrite(self) -> None:
        later_source = [
            "我重新开始和身边的人认真聊天。",
            "几件正在发生的事让我重新看见了生活。",
            "我还没有答案，但愿意继续往前走。",
        ]
        later_rewrite = [
            "重新和身边的人认真聊天以后，我才发现，生活并没有把门关上。",
            "事情一件件发生，我也在里面重新看见了生活，而不是等一个答案落下来。",
            "答案还是没有，但这次我不急着替自己回答。先继续往前走。",
        ]
        payload = {**self.payload, "full_copy": "\n\n".join([*self.source_paragraphs, *later_source])}
        with patch(
            "services.deepseek_service._edit_copy_once",
            side_effect=[
                paragraph_patch_result(self.source_paragraphs, self.changes),
                paragraph_patch_result(later_rewrite, self.changes, start_index=4),
            ],
        ) as edit_mock, patch(
            "services.deepseek_service._audit_copy",
            return_value=passing_audit((4, 5, 6)),
        ):
            result = _edit_copy_sync(payload)

        self.assertEqual(edit_mock.call_count, 2)
        self.assertEqual(result["text"], "\n\n".join([*self.source_paragraphs, *later_rewrite]))
        self.assertEqual(result["changes"], self.changes)
        self.assertTrue(result["metrics"]["meaningful"])

    def test_missing_change_summary_retries(self) -> None:
        with patch(
            "services.deepseek_service._edit_copy_once",
            side_effect=[
                paragraph_patch_result(self.rewrite_paragraphs, []),
                paragraph_patch_result(self.rewrite_paragraphs, self.changes),
            ],
        ) as edit_mock, patch(
            "services.deepseek_service._audit_copy",
            return_value=passing_audit(),
        ):
            result = _edit_copy_sync(self.payload)

        self.assertEqual(edit_mock.call_count, 2)
        self.assertEqual(result["changes"], self.changes)

    def test_paragraph_patches_are_not_rejected_by_full_copy_ratio(self) -> None:
        filler = [
            f"这是第 {index} 段没有被编辑的生活记录，它会保留在当前完整文案里。"
            for index in range(4, 54)
        ]
        full_source = "\n\n".join([*self.source_paragraphs, *filler])
        payload = {**self.payload, "full_copy": full_source}
        with patch(
            "services.deepseek_service._edit_copy_once",
            return_value=paragraph_patch_result(self.rewrite_paragraphs, self.changes),
        ), patch(
            "services.deepseek_service._audit_copy",
            return_value=passing_audit(),
        ):
            result = _edit_copy_sync(payload)

        self.assertTrue(result["metrics"]["meaningful"])
        self.assertEqual(result["metrics"]["valid_patch_count"], 3)
        self.assertLess(result["metrics"]["changed_ratio"], 0.05)

    def test_ai_edit_rejects_result_above_manual_word_limit(self) -> None:
        filler = "这是为了保持手动字数上限测试而保留的背景段落，它不会被本次编辑动作修改。" * 26
        payload = {
            **self.payload,
            "full_copy": "\n\n".join([*self.source_paragraphs, filler]),
            "target_length_mode": "manual",
            "target_length": 1000,
        }
        with patch(
            "services.deepseek_service._edit_copy_once",
            return_value=paragraph_patch_result(self.rewrite_paragraphs, self.changes),
        ), patch(
            "services.deepseek_service._audit_copy",
            return_value=passing_audit(),
        ):
            with self.assertRaises(SkillExecutionError) as raised:
                _edit_copy_sync(payload)

        self.assertEqual(raised.exception.code, "EDIT_LENGTH_CONSTRAINT_FAILED")
        self.assertIn("AI 编辑后为", str(raised.exception))
        self.assertIn("900-1000", str(raised.exception))

    def test_repeated_noop_fails_without_original_fallback(self) -> None:
        same = paragraph_patch_result(self.source_paragraphs, self.changes)
        with patch(
            "services.deepseek_service._edit_copy_once",
            side_effect=[same, same, same],
        ) as edit_mock:
            with self.assertRaises(SkillExecutionError) as raised:
                _edit_copy_sync(self.payload)

        self.assertEqual(edit_mock.call_count, 3)
        self.assertEqual(raised.exception.code, "EDIT_NO_MEANINGFUL_CHANGE")

    def test_opening_duplicate_is_removed(self) -> None:
        original = "如今的我即将步入研三。"
        options = _opening_options_are_distinct(
            [
                {"text": original},
                {"text": original},
                {"text": "从上海回到杭州以后，我最先找回来的不是答案。"},
            ],
            original,
        )
        self.assertEqual(len(options), 1)

    def test_opening_duplicate_structures_are_removed(self) -> None:
        audit_result = {
            "data": {
                "items": [
                    {"index": 0, "passed": True, "distinct_from_original": True, "structure": "事件直入"},
                    {"index": 1, "passed": True, "distinct_from_original": True, "structure": "设问进入"},
                    {"index": 2, "passed": True, "distinct_from_original": True, "structure": "设问进入"},
                ]
            },
            "run_id": "audit-run",
            "skill": "audit-vlog-copy",
            "version": "1.0.0",
            "model": "mock",
            "latency_ms": 8,
        }
        options = [
            {"label": "事件直入", "text": "电影散场，我开始回想这十年。", "changes": self.changes[:1]},
            {"label": "设问进入", "text": "你会怎么理解自己的十年？", "changes": self.changes[:1]},
            {"label": "设问进入", "text": "如果是你，会把回忆当成什么？", "changes": self.changes[:1]},
        ]
        with patch("services.deepseek_service.run_json", return_value=audit_result):
            valid, _ = _audit_opening_options(options, {}, "原文")
        self.assertEqual(len(valid), 2)


if __name__ == "__main__":
    unittest.main()
