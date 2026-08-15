from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

from config import BASE_DIR
from services import cover_service, dna_store, settings_store, xiangzhongjing_store
from services.deepseek_service import load_writing_skill


class CommunityBetaContractTests(unittest.TestCase):
    def test_required_open_source_files_exist(self):
        for relative in (
            "LICENSE",
            "CHANGELOG.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "CODE_OF_CONDUCT.md",
            "TRADEMARKS.md",
            "docker-compose.yml",
            ".dockerignore",
            ".github/workflows/ci.yml",
            "docs/COMMUNITY_BETA.md",
            "docs/COMMUNITY_PRD.md",
            "docs/ARCHITECTURE.md",
            "scripts/bootstrap.py",
            "scripts/backup_xiangzhongjing.py",
            "scripts/restore_xiangzhongjing.py",
            "scripts/sanitize_community_package.py",
        ):
            self.assertTrue((BASE_DIR / relative).exists(), relative)

    def test_page_rendering_and_container_dependencies_are_version_stable(self):
        pages = (BASE_DIR / "api/pages.py").read_text(encoding="utf-8")
        dockerfile = (BASE_DIR / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("request=request", pages)
        self.assertIn('name="xiangzhongjing_demo.html"', pages)
        self.assertIn("-r requirements-lock.txt", dockerfile)

    def test_blank_frontend_has_no_private_sample_projects(self):
        core = (BASE_DIR / "static/js/core.js").read_text(encoding="utf-8")
        workspace = (BASE_DIR / "static/js/workspace.js").read_text(encoding="utf-8")
        self.assertIn("let projects = {};", core)
        self.assertNotIn('id: "heart"', core)
        self.assertNotIn("抖音搜创作者本人", core)
        self.assertIn("createStarterProject", workspace)
        self.assertIn("projects = state.projects;", workspace)

    def test_blank_database_uses_generic_profile_and_style(self):
        with TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "community.db"
            with patch.object(xiangzhongjing_store, "DB_PATH", database), patch.object(
                cover_service, "DB_PATH", database
            ), patch.object(settings_store, "DB_PATH", database), patch.object(
                dna_store, "DB_PATH", database
            ):
                profile = cover_service.profile()
                version, style = load_writing_skill()

        self.assertEqual(profile["display_name"], "创作者")
        self.assertEqual(profile["handle"], "creator")
        self.assertEqual(version, "v2.2")
        self.assertIn("通用创作者基线", style)
        self.assertNotIn("创作者本人", style)

    def test_explicit_data_directory_never_imports_legacy_private_database(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            legacy_database = root / "legacy.db"
            isolated_database = root / "isolated" / "xiangzhongjing.db"
            legacy_database.write_bytes(b"private legacy database")

            with patch.object(xiangzhongjing_store, "LEGACY_DB_PATH", legacy_database), patch.object(
                xiangzhongjing_store, "DB_PATH", isolated_database
            ), patch.dict(os.environ, {"XIANGZHONGJING_DATA_DIR": str(isolated_database.parent)}):
                xiangzhongjing_store._migrate_legacy_database()

            self.assertFalse(isolated_database.exists())

    def test_private_published_style_still_overrides_generic_baseline(self):
        with TemporaryDirectory() as tmpdir:
            database = Path(tmpdir) / "private.db"
            with patch.object(xiangzhongjing_store, "DB_PATH", database), patch.object(
                cover_service, "DB_PATH", database
            ), patch.object(settings_store, "DB_PATH", database), patch.object(
                dna_store, "DB_PATH", database
            ):
                load_writing_skill()
                with xiangzhongjing_store._connect() as connection:
                    connection.execute(
                        """
                        UPDATE style_skill_versions
                        SET skill_content = ?
                        WHERE version = 'v2.2' AND status = 'published'
                        """,
                        ("PRIVATE V2.2 DNA",),
                    )
                    connection.commit()
                version, style = load_writing_skill()

        self.assertEqual(version, "v2.2")
        self.assertEqual(style, "PRIVATE V2.2 DNA")

    def test_community_pack_excludes_private_profile_files(self):
        script = (BASE_DIR / "scripts/package_community_beta.sh").read_text(encoding="utf-8")
        for private_path in (
            "knowledge/personal_style_profile.md",
            "knowledge/xiangzhongjing_writing_skill_published_v2_2.md",
            "docs/private-delivery/",
            "product_skills/.defaults/",
            "scripts/private_delivery/",
            "scripts/package_private_full_copy.sh",
            "scripts/seed_v22_candidate.py",
            "backups/",
            "*.zip",
            ".DS_Store",
        ):
            self.assertIn(private_path, script)
        self.assertIn("检测到疑似真实密钥", script)
        self.assertIn("检测到运行时创作者身份硬编码", script)
        self.assertIn("检测到超过 10MB 的异常单文件", script)
        self.assertIn('sanitize_community_package.py" "${STAGE}"', script)
        self.assertIn('VERSION="${1:-v0.3.0-beta}"', script)
        self.assertIn('"${VERSION#v}" > "${STAGE}/VERSION"', script)


if __name__ == "__main__":
    unittest.main()
