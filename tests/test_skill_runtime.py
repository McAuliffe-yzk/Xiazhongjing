import unittest
from unittest.mock import patch

from services.skill_runtime import _parse_json, run_json


class SkillRuntimeTests(unittest.TestCase):
    def test_parse_json_handles_fences_and_trailing_text(self) -> None:
        payload = """```json
        {"passed": true, "scores": {"personal_style": 8}}
        ```
        """
        data = _parse_json(payload)
        self.assertTrue(data["passed"])
        self.assertEqual(data["scores"]["personal_style"], 8)

    def test_run_json_repairs_invalid_output_with_second_skill_call(self) -> None:
        first_run = {
            "text": "这次输出坏了：{passed: true, scores: {personal_style: 8}}",
            "run_id": "run-1",
            "skill": "audit-writing-quality",
            "version": "1.0.0",
            "model": "mock",
            "latency_ms": 12,
        }
        repaired_run = {
            "text": "{\"passed\": true, \"scores\": {\"personal_style\": 8}, \"unsupported_claims\": [], \"copied_expressions\": [], \"material_coverage\": [], \"style_issues\": [], \"strengths\": [], \"revision_instructions\": []}",
            "run_id": "run-2",
            "skill": "audit-writing-quality",
            "version": "1.0.0",
            "model": "mock",
            "latency_ms": 9,
        }
        with patch("services.skill_runtime.run_text", side_effect=[first_run, repaired_run]) as run_text_mock:
            result = run_json("audit-writing-quality", "请输出 JSON。", model="mock-model")

        self.assertEqual(run_text_mock.call_count, 2)
        self.assertEqual(result["run_id"], "run-2")
        self.assertTrue(result["data"]["passed"])
        self.assertTrue(run_text_mock.call_args_list[0].kwargs.get("json_output"))


if __name__ == "__main__":
    unittest.main()
