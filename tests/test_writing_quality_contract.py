import unittest

from services.deepseek_service import _writing_overlap_metrics


class WritingQualityContractTests(unittest.TestCase):
    def test_overlap_metrics_blocks_near_copy_of_insight_skeleton(self) -> None:
        materials = {
            "insight": "这个时代，获取信息是那么容易，记住一个人的成本变得很低，记住一件事的可能被放大。",
            "opening": "",
            "daily": "",
            "event": "",
            "ending_reference": "",
        }
        draft = "我后来想到，这个时代获取信息那么容易，记住一个人的成本很低，记住一件事情的可能也被放大。"

        metrics = _writing_overlap_metrics(draft, materials, [])

        self.assertFalse(metrics["passed"])
        self.assertGreater(len(metrics["near_reused_fragments"]), 0)

    def test_overlap_metrics_allows_protected_opening_line(self) -> None:
        line = "Hi，我是创作者本人，你不认识我，但我想告诉你一些事情"
        materials = {
            "insight": "",
            "opening": line,
            "daily": "",
            "event": "",
            "ending_reference": "",
        }

        metrics = _writing_overlap_metrics(line, materials, [line])

        self.assertTrue(metrics["passed"])
        self.assertEqual(metrics["exact_reused_lines"], [])

    def test_overlap_metrics_reports_daily_fact_reuse_without_blocking(self) -> None:
        materials = {
            "insight": "回忆正在改变我对成功的理解。",
            "opening": "",
            "daily": "每周一定会把朋友叫到家里来开灶做饭，家常饭菜与烟火气息是生活的一剂良药。",
            "event": "",
            "ending_reference": "",
        }
        draft = "每周一定会把朋友叫到家里来开灶做饭，家常饭菜与烟火气息是生活的一剂良药。"

        metrics = _writing_overlap_metrics(draft, materials, [])

        self.assertTrue(metrics["passed"])
        self.assertGreater(len(metrics["near_reused_fragments"]), 0)
        self.assertEqual(metrics["blocking_near_reused_fragments"], [])


if __name__ == "__main__":
    unittest.main()
