from __future__ import annotations

import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from config import app_config
from services import cover_service
from tests.frontend_assets import backend_source, demo_source, demo_styles


class CoversContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = demo_source()
        cls.css = demo_styles()
        cls.backend = backend_source()

    def test_diary_slogan_is_updated(self) -> None:
        self.assertIn("行到水穷处，坐看云起时。", self.html)
        self.assertNotIn("不期待吗？100篇之后的你，会有多么的不同凡响？", self.html)

    def test_cover_page_is_routed_and_visible(self) -> None:
        self.assertIn('data-page="covers"', self.html)
        self.assertIn('id="page-covers"', self.html)
        self.assertIn('function loadCoversPage()', self.html)
        self.assertIn('if (safePage === "covers" && typeof loadCoversPage === "function") loadCoversPage();', self.html)
        self.assertIn('/static/styles/13-covers.css', self.html)
        self.assertIn('/static/js/covers.js', self.html)
        self.assertIn(".cover-wall", self.css)

    def test_cover_assets_and_studio_are_separate_views(self) -> None:
        self.assertIn('data-cover-tab="assets"', self.html)
        self.assertIn('data-cover-tab="studio"', self.html)
        self.assertIn('id="cover-assets-view"', self.html)
        self.assertIn('id="cover-studio-view"', self.html)
        self.assertIn('function setCoverTab(', self.html)
        self.assertIn('destination.searchParams.set("coverTab", activeCoverTab)', self.html)
        self.assertIn('download="${escapeHtml(title)}.png"', self.html)
        self.assertIn('data-cover-open-project=', self.html)
        self.assertNotIn('id="cover-create-card"', self.html)

    def test_cover_generation_keeps_saved_draft_state_before_render(self) -> None:
        self.assertIn("const saved = await XZJApi.json", self.html)
        self.assertIn('item.id === coverId ? { ...saved, status: "generating"', self.html)
        self.assertIn('showToast("封面生成完成，已保存到封面资产")', self.html)
        self.assertNotIn("data-cover-save", self.html)
        self.assertIn("queueCoverDraftSave", self.html)

    def test_cover_preset_uses_product_modal_instead_of_browser_prompt(self) -> None:
        self.assertIn('id="cover-preset-modal"', self.html)
        self.assertIn('id="cover-preset-form"', self.html)
        self.assertIn("function openCoverPresetModal", self.html)
        self.assertIn("function keepCoverPresetFocusInside", self.html)
        self.assertIn('aria-hidden="true" aria-labelledby="cover-preset-title"', self.html)
        covers_script = Path(__file__).resolve().parents[1].joinpath("static/js/covers.js").read_text(encoding="utf-8")
        self.assertNotIn("window.prompt", covers_script)
        self.assertIn(".cover-preset-dialog", self.css)
        self.assertIn("body.cover-preset-lock", self.css)

    def test_profile_page_is_separate_from_cover_wall(self) -> None:
        self.assertIn('class="profile-tile" data-page="profile"', self.html)
        self.assertIn('id="page-profile"', self.html)
        self.assertIn('function loadCreatorProfilePage()', self.html)
        self.assertIn('if (safePage === "profile" && typeof loadCreatorProfilePage === "function") loadCreatorProfilePage();', self.html)
        profile_source = self.html[
            self.html.index('id="page-profile"'):self.html.index('id="page-covers"')
        ]
        covers_source = self.html[
            self.html.index('id="page-covers"'):self.html.index('id="page-editor"')
        ]
        self.assertIn('id="cover-profile-form"', profile_source)
        self.assertNotIn('id="cover-profile-form"', covers_source)
        self.assertIn('id="sidebar-profile-avatar"', self.html)
        for field in (
            "creator_positioning",
            "platforms",
            "content_columns",
            "style_keywords",
            "visual_preferences",
            "cover_negative_prompt",
        ):
            self.assertIn(f'name="{field}"', profile_source)

    def test_image_config_fields_are_available_without_revealing_key(self) -> None:
        self.assertIn("IMAGE_API_KEY", self.backend)
        self.assertIn("IMAGE_API_BASE", self.backend)
        self.assertIn("IMAGE_MODEL", self.backend)
        self.assertEqual(app_config.image_model, "gpt-image-2")

    def test_cover_store_round_trip_and_media_path_guard(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            cover_service,
            "DB_PATH",
            Path(temp_dir) / "covers.db",
        ), patch.object(
            cover_service,
            "COVER_MEDIA_DIR",
            Path(temp_dir) / "media" / "covers",
        ):
            profile = cover_service.profile()
            self.assertEqual(profile["display_name"], "创作者")
            preset = cover_service.list_presets()[0]
            cover = cover_service.create_cover(
                {
                    "project_id": "project-1",
                    "project_title": "回忆",
                    "title": "回忆",
                    "preset_id": preset["id"],
                }
            )
            self.assertEqual(cover["status"], "blank")
            updated = cover_service.update_cover(cover["id"], {"title": "新的封面"})
            self.assertEqual(updated["title"], "新的封面")
            profile = cover_service.update_profile(
                {
                    "display_name": "创作者本人",
                    "creator_positioning": "校园生活与 AI 创业记录者",
                    "content_columns": "研二日记、创业记录",
                    "visual_preferences": "红蓝点缀、电影感",
                    "cover_negative_prompt": "不要廉价网感",
                }
            )
            self.assertEqual(profile["creator_positioning"], "校园生活与 AI 创业记录者")
            prompt = cover_service._image_prompt(updated, profile, "使用头像参考。")
            self.assertIn("校园生活与 AI 创业记录者", prompt)
            self.assertIn("研二日记、创业记录", prompt)
            self.assertIn("红蓝点缀、电影感", prompt)
            self.assertIn("不要廉价网感", prompt)
            with self.assertRaises(ValueError):
                cover_service.media_path("generated", "../secret.png")

    def test_image_response_parser_supports_b64_and_url(self) -> None:
        raw = b"fake-image"
        encoded = base64.b64encode(raw).decode("ascii")
        self.assertEqual(cover_service._extract_image_bytes({"data": [{"b64_json": encoded}]}), raw)
        response = Mock()
        response.content = raw
        response.raise_for_status.return_value = None
        with patch("services.cover_service.requests.get", return_value=response):
            self.assertEqual(cover_service._extract_image_bytes({"data": [{"url": "https://example.test/a.png"}]}), raw)

    def test_image_request_retries_transient_503(self) -> None:
        unavailable = Mock(status_code=503)
        unavailable.json.return_value = {"error": {"message": "upstream unavailable"}}
        success = Mock(status_code=200)
        with patch(
            "services.cover_service.requests.post",
            side_effect=[unavailable, success],
        ) as post, patch("services.cover_service.time.sleep"):
            result = cover_service._post_image_request(
                url="https://example.test/v1/images/generations",
                headers={},
                timeout=10,
                json={"model": "gpt-image-2"},
            )
        self.assertIs(result, success)
        self.assertEqual(post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
