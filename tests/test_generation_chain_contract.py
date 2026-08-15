import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services import xiangzhongjing_store
from services.deepseek_service import _generate_sync, _generation_length_config
from services.skill_runtime import SkillExecutionError
from tests.frontend_assets import backend_source, demo_source, demo_styles


BASE_DIR = Path(__file__).resolve().parents[1]
class GenerationChainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = demo_source()
        cls.css = demo_styles()
        cls.main_source = backend_source()
        cls.service_source = (BASE_DIR / "services" / "deepseek_service.py").read_text(encoding="utf-8")

    def test_frontend_generation_chain_is_three_visible_skills(self):
        self.assertIn('skill: "write-personal-vlog"', self.html)
        self.assertIn('skill: "optimize-douyin-vlog"', self.html)
        self.assertIn('skill: "insert-book-quotes"', self.html)
        self.assertIn("个人风格撰写、抖音 Vlog 优化与书库金句支撑会依次执行", self.html)
        self.assertNotIn("个人声音写作与原创表达审校", self.html)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", self.css)

    def test_generation_prompts_include_creator_narrative_framework(self):
        for phrase in (
            "开头点明主题",
            "蒙太奇事件引入与发展",
            "高潮情绪堆叠",
            "下沉思考冷静",
            "回引强化呼应",
            "升华价值钩子",
        ):
            self.assertIn(phrase, self.service_source)

    def test_book_quote_support_is_timing_first_and_allows_three_quotes(self):
        self.assertIn("先判断时机，再选原句", self.service_source)
        self.assertIn('本次目标加入 {strategy["target"]} 处', self.service_source)
        self.assertIn('最多 {strategy["max"]} 处', self.service_source)
        self.assertIn("正常情况下必须找满两处不同叙事功能位", self.service_source)
        self.assertIn("目标不是随口建议，必须优先找满目标数量", self.service_source)
        self.assertIn("book_quote_strategy", self.service_source)
        self.assertIn('data-book-quote-strategy="restrained"', self.html)
        self.assertIn('data-book-quote-strategy="standard"', self.html)
        self.assertIn('data-book-quote-strategy="amplified"', self.html)

    def test_frontend_has_manual_length_control(self):
        self.assertIn('id="generation-length-control"', self.html)
        self.assertIn('id="generation-length-mode"', self.html)
        self.assertIn('id="generation-target-length"', self.html)
        self.assertIn("target_length_mode", self.html)
        self.assertIn(".generation-length-control", self.css)
        self.assertIn("diagnostic-runtime", self.html)
        self.assertIn("耗时", self.html)

    def test_generate_button_is_in_editor_workflow(self):
        self.assertIn('data-generate-copy type="button">生成文案稿</button>', self.html)
        self.assertIn("$$('[data-generate-copy]')", self.html)
        self.assertIn('.generate-copy-action', self.css)

    def test_manual_length_config_uses_hard_upper_limit(self):
        config = _generation_length_config(
            {"target_length_mode": "manual", "target_length": 900}
        )

        self.assertEqual(config["mode"], "manual")
        self.assertEqual(config["target"], 900)
        self.assertEqual(config["min"], 810)
        self.assertEqual(config["max"], 900)

    def test_stream_route_forwards_narrative_mode(self):
        self.assertIn('narrative_mode: Literal["default", "parallelism", "six-stage", "contrast-first"]', self.main_source)
        self.assertIn('book_quote_strategy: Literal["restrained", "standard", "amplified"]', self.main_source)
        self.assertIn("generation_payload = payload.service_payload()", self.main_source)
        self.assertIn('data-book-quote-strategy="standard"', self.html)

    def test_default_generation_chain_skips_quality_gate(self):
        events = []
        called_skills = []

        def fake_run_text(skill_name, user_prompt, **kwargs):
            called_skills.append(skill_name)
            text = "事情结束以后，我重新看见生活。" * 54
            if skill_name == "optimize-douyin-vlog":
                text = "事情结束以后，我重新看见生活。" * 54
            return {
                "text": text,
                "run_id": f"{skill_name}-run",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 5,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.deepseek_service.run_text",
            side_effect=fake_run_text,
        ):
            result = _generate_sync(
                {
                    "project_id": "contract_project",
                    "materials": {
                        "theme": "回到日常",
                        "insight": "重新回到生活，才知道自己还能往前走。",
                        "daily": "书桌、客厅、街道三点一线。",
                        "event": "从上海离职回到杭州，回到浙江大学。",
                    },
                    "selected_books": [],
                    "book_support_mode": "integrated",
                    "target_length_mode": "manual",
                    "target_length": 900,
                },
                progress=lambda event: events.append(event),
            )

        self.assertEqual(called_skills, ["write-personal-vlog", "optimize-douyin-vlog"])
        self.assertEqual(result["audit"]["status"], "not_run")
        self.assertEqual(result["style_audit"]["status"], "not_run")
        self.assertEqual(result["book_support"]["status"], "disabled")
        self.assertEqual(result["length"]["target"], 900)
        self.assertNotIn("audit-writing-quality", [event["skill"] for event in events])
        self.assertIn("optimize-douyin-vlog", [event["skill"] for event in events])
        self.assertIn("stage_outline", result)
        self.assertIn("douyin_publish_pack", result)
        self.assertEqual(result["used_material_strategy"]["mode"], "develop_materials_not_copy")

    def test_manual_length_repairs_overlong_stage_before_success(self):
        calls = []
        overlong = "这是一段需要压缩的个人生活表达。" * 80
        in_range = "事情结束以后，我重新看见生活。" * 54

        def fake_run_text(skill_name, user_prompt, **kwargs):
            calls.append(skill_name)
            text = overlong if len(calls) == 1 else in_range
            return {
                "text": text,
                "run_id": f"{skill_name}-{len(calls)}",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 5,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.deepseek_service.run_text", side_effect=fake_run_text
        ):
            result = _generate_sync(
                {
                    "project_id": "length_repair_project",
                    "materials": {
                        "theme": "回到日常",
                        "insight": "重新回到生活，才知道自己还能往前走。",
                        "daily": "书桌、客厅、街道三点一线。",
                        "event": "从上海离职回到杭州，回到浙江大学。",
                    },
                    "selected_books": [],
                    "target_length_mode": "manual",
                    "target_length": 900,
                }
            )

        self.assertEqual(calls, ["write-personal-vlog", "write-personal-vlog", "optimize-douyin-vlog"])
        self.assertTrue(result["length"]["within_range"])
        self.assertLessEqual(result["length"]["actual"], 900)

    def test_manual_length_never_returns_over_limit(self):
        overlong = "这是一段始终无法压缩到目标范围的个人生活表达。" * 80

        def fake_run_text(skill_name, user_prompt, **kwargs):
            return {
                "text": overlong,
                "run_id": f"{skill_name}-run",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 5,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.deepseek_service.run_text", side_effect=fake_run_text
        ):
            with self.assertRaises(SkillExecutionError) as context:
                _generate_sync(
                    {
                        "project_id": "length_failure_project",
                        "materials": {
                            "theme": "回到日常",
                            "insight": "重新回到生活，才知道自己还能往前走。",
                            "daily": "书桌、客厅、街道三点一线。",
                            "event": "从上海离职回到杭州，回到浙江大学。",
                        },
                        "selected_books": [],
                        "target_length_mode": "manual",
                        "target_length": 900,
                    }
                )

        self.assertEqual(context.exception.code, "LENGTH_CONSTRAINT_FAILED")

    def test_rewrite_uses_current_editor_copy_without_project_materials(self):
        prompts = []
        current_copy = "我把旧计划删掉了，只想把今天过得更具体一点。" * 40
        stale_material = "这是已经被用户从当前稿删除的旧素材，绝不能进入改写结果。"

        def fake_run_text(skill_name, user_prompt, **kwargs):
            prompts.append(user_prompt)
            return {
                "text": current_copy,
                "run_id": f"{skill_name}-run",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 5,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.deepseek_service.run_text", side_effect=fake_run_text
        ):
            result = _generate_sync(
                {
                    "project_id": "rewrite_project",
                    "generation_mode": "rewrite",
                    "source_copy": current_copy,
                    "materials": {
                        "theme": stale_material,
                        "insight": stale_material,
                        "daily": stale_material,
                        "event": stale_material,
                    },
                    "selected_books": [],
                }
            )

        joined_prompts = "\n".join(prompts)
        self.assertEqual(result["generation_mode"], "rewrite")
        self.assertIn(current_copy[:80], joined_prompts)
        self.assertNotIn(stale_material, joined_prompts)
        self.assertIn("唯一的事实来源、主题来源和内容边界", prompts[0])

    def test_rewrite_requires_editor_copy_but_not_materials(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            with self.assertRaises(SkillExecutionError) as context:
                _generate_sync(
                    {
                        "project_id": "empty_rewrite",
                        "generation_mode": "rewrite",
                        "source_copy": "",
                        "materials": {},
                        "selected_books": [],
                    }
                )

        self.assertEqual(context.exception.code, "REWRITE_SOURCE_EMPTY")

    def test_rewrite_resets_stale_checkpoint_when_editor_copy_changes(self):
        current_copy = "我把这一段重新写过了，留下来的内容才是这次要被优化的内容。" * 35
        calls = []

        def fake_run_text(skill_name, user_prompt, **kwargs):
            calls.append(skill_name)
            return {
                "text": current_copy,
                "run_id": f"{skill_name}-run",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 5,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.deepseek_service.run_text", side_effect=fake_run_text
        ):
            job = xiangzhongjing_store.create_generation_job({"project_id": "retry_rewrite"})
            xiangzhongjing_store.update_generation_job(
                job["generation_id"],
                status="failed",
                checkpoint={
                    "input_fingerprint": "previous-editor-copy",
                    "draft": "这是上次失败时留下的旧草稿。",
                    "optimized_copy": "这是上次失败时留下的旧优化稿。",
                },
            )
            result = _generate_sync(
                {
                    "project_id": "retry_rewrite",
                    "generation_mode": "rewrite",
                    "source_copy": current_copy,
                    "materials": {},
                    "selected_books": [],
                },
                generation_id=job["generation_id"],
            )

        self.assertEqual(calls, ["write-personal-vlog", "optimize-douyin-vlog"])
        self.assertEqual(result["copy"], current_copy)
        self.assertNotIn("旧优化稿", result["copy"])

    def test_frontend_sends_no_materials_for_rewrite(self):
        self.assertIn('materials: generationMode === "rewrite" ? {} : project.materials', self.html)
        self.assertIn("项目原始素材不会参与", self.html)

    def test_douyin_publish_pack_is_non_blocking_display_layer(self):
        self.assertIn("adapt-douyin-vlog", self.service_source)
        self.assertIn("Generate a non-blocking publishing pack. It never changes the copy.", self.service_source)
        self.assertIn("douyin_publish_pack", self.service_source)
        self.assertIn("generation-publish-pack", self.html)
        self.assertIn("DOUYIN PACK", self.html)
        self.assertIn("发布前适配包已生成", self.html)

    def test_book_support_failure_does_not_block_generated_copy(self):
        def fake_run_text(skill_name, user_prompt, **kwargs):
            return {
                "text": f"{skill_name} 完成后的文案正文。",
                "run_id": f"{skill_name}-run",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 5,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.deepseek_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.deepseek_service.run_text", side_effect=fake_run_text
        ), patch(
            "services.deepseek_service._integrated_book_support_sync",
            side_effect=SkillExecutionError("TAVILY_TIMEOUT", "联网检索超时"),
        ):
            xiangzhongjing_store.create_library_book(
                "《剑来》", author="烽火戏诸侯", book_id="jianlai", source_type="legacy"
            )
            result = _generate_sync(
                {
                    "project_id": "contract_project",
                    "materials": {
                        "theme": "回到日常",
                        "insight": "重新回到生活，才知道自己还能往前走。",
                        "daily": "书桌、客厅、街道三点一线。",
                        "event": "从上海离职回到杭州，回到浙江大学。",
                    },
                    "selected_books": ["jianlai"],
                    "book_support_mode": "integrated",
                }
            )

        self.assertIn("optimize-douyin-vlog", result["copy"])
        self.assertEqual(result["book_support"]["status"], "failed")
        self.assertEqual(result["audit"]["status"], "not_run")


if __name__ == "__main__":
    unittest.main()
