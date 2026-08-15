from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from api.contracts import GenerateCopyRequest
from tests.frontend_assets import demo_markup, demo_source
from services import cover_service, xiangzhongjing_store


BASE_DIR = Path(__file__).resolve().parents[1]


class ModularArchitectureContractTests(unittest.TestCase):
    def test_main_is_only_application_composition(self) -> None:
        main = (BASE_DIR / "main.py").read_text(encoding="utf-8")
        self.assertLess(len(main.splitlines()), 80)
        for module in ("generation", "library", "dialogue", "style", "state", "pages"):
            self.assertIn(f"from api.{module} import router", main)
        self.assertNotIn("@app.post", main)

    def test_frontend_has_domain_assets_and_no_inline_application_script(self) -> None:
        markup = demo_markup()
        self.assertNotIn("<script>\n", markup)
        for module in (
            "api",
            "core",
            "materials",
            "workspace",
            "style",
            "generation",
            "dialogue",
            "events",
        ):
            self.assertIn(f"/static/js/{module}.js", markup)
        self.assertIn('class="mobile-bottom-nav"', markup)

    def test_core_generation_contract_rejects_invalid_length(self) -> None:
        with self.assertRaises(ValidationError):
            GenerateCopyRequest(target_length_mode="manual", target_length=3500)

    def test_state_revision_prevents_silent_cross_window_overwrite(self) -> None:
        with TemporaryDirectory() as temp_dir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(temp_dir) / "state.db",
        ):
            first = xiangzhongjing_store.save_state(
                {"_revision": 0, "projects": {"one": {"title": "第一版"}}}
            )
            self.assertEqual(first["revision"], 1)
            with self.assertRaises(xiangzhongjing_store.StateConflictError):
                xiangzhongjing_store.save_state(
                    {"_revision": 0, "projects": {"one": {"title": "旧窗口覆盖"}}}
                )
            state = xiangzhongjing_store.load_state()

        self.assertEqual(state["_revision"], 1)
        self.assertEqual(state["projects"]["one"]["title"], "第一版")

    def test_local_mode_is_private_by_default(self) -> None:
        config = (BASE_DIR / "config.py").read_text(encoding="utf-8")
        self.assertIn('def host(self) -> str:', config)
        self.assertIn('os.getenv("HOST", "127.0.0.1")', config)

    def test_sqlite_contexts_close_connections_after_exit(self) -> None:
        for module, filename in (
            (xiangzhongjing_store, "state.db"),
            (cover_service, "covers.db"),
        ):
            with TemporaryDirectory() as temp_dir, patch.object(
                module,
                "DB_PATH",
                Path(temp_dir) / filename,
            ):
                with module._connect() as connection:
                    connection.execute("CREATE TABLE close_check (id INTEGER PRIMARY KEY)")
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute("SELECT 1")

    def test_frontend_uses_shared_api_gateway(self) -> None:
        source = demo_source()
        self.assertIn("const XZJApi = Object.freeze", source)
        self.assertNotIn("await fetch(", source)
        self.assertIn("STATE_REVISION_CONFLICT", (BASE_DIR / "api" / "state.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
