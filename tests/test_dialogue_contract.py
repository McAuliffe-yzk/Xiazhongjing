import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from services import xiangzhongjing_store
from services.dialogue_service import (
    _bulk_delete_sessions_sync,
    _clear_session_sync,
    _create_session_sync,
    _delete_session_sync,
    _has_unverified_book_quote,
    _list_sessions_sync,
    _update_asset_sync,
    _patch_session_sync,
    _restore_session_sync,
    _send_message_sync,
    dialogue_personas,
    stream_message_events,
)
from tests.frontend_assets import demo_source, demo_styles


BASE_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = BASE_DIR / "product_skills"


class DialogueContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = demo_source()
        cls.css = demo_styles()
        dialogue_source = (BASE_DIR / "static" / "js" / "dialogue.js").read_text(encoding="utf-8")
        start = dialogue_source.index("async function extractDialogueItem")
        cls.dialogue_extract_source = dialogue_source[start:]

    def test_dialogue_navigation_and_page_exist(self):
        self.assertIn('data-page="mirror"', self.html)
        self.assertIn('data-page="book-person"', self.html)
        self.assertIn('data-page="assets"', self.html)
        self.assertIn('id="page-dialogue"', self.html)
        self.assertIn('id="page-assets"', self.html)
        self.assertIn('data-page-panel="assets"', self.html)
        self.assertIn('data-page-panel="mirror"', self.html)
        self.assertIn('id="dialogue-composer"', self.html)
        self.assertIn('id="dialogue-thread"', self.html)

    def test_dialogue_controls_are_wired(self):
        self.assertIn('$$("[data-dialogue-mode]")', self.html)
        self.assertIn('id="dialogue-persona-picker"', self.html)
        self.assertIn('id="new-dialogue-session"', self.html)
        self.assertIn('function sendDialogueMessage', self.html)
        self.assertIn('function extractDialogueItem', self.html)
        self.assertIn('data-dialogue-extract', self.html)
        self.assertIn('id="dialogue-session-search"', self.html)
        self.assertIn('id="dialogue-session-menu"', self.html)
        self.assertIn('function loadOlderDialogueMessages', self.html)
        self.assertIn('data-dialogue-retry', self.html)
        self.assertIn('id="asset-category-board"', self.html)
        self.assertIn('data-asset-scope="mirror"', self.html)
        self.assertIn('data-asset-scope="book"', self.html)
        self.assertIn('id="dialogue-persona-dock"', self.html)
        self.assertIn('id="dialogue-flow"', self.html)
        self.assertIn('id="clear-asset-filters"', self.html)

    def test_dialogue_api_lifecycle_is_present(self):
        self.assertIn('/api/xiangzhongjing/dialogue/personas', self.html)
        self.assertIn('/api/xiangzhongjing/dialogue/sessions', self.html)
        self.assertIn('/api/xiangzhongjing/dialogue/extract', self.html)
        self.assertIn('loadDialogueSessions();', self.html)
        self.assertIn('safePage === "mirror" || safePage === "book-person"', self.html)
        self.assertIn('/messages/${encodeURIComponent(messageId)}/retry', self.html)
        self.assertIn('method: "PATCH"', self.html)
        self.assertIn('method: "DELETE"', self.html)

    def test_dialogue_does_not_auto_open_history_when_switching_persona(self):
        self.assertIn('function sessionMatchesDialogue(session)', self.html)
        self.assertIn('session.persona_id === activeDialoguePersona', self.html)
        self.assertNotIn('await loadDialogueSessions({ selectFirst: true })', self.html)

    def test_dialogue_extractables_are_global_assets_not_project_mutations(self):
        self.assertIn('async function extractDialogueItem', self.dialogue_extract_source)
        self.assertIn('target: "persona_asset"', self.dialogue_extract_source)
        self.assertIn('project_id: ""', self.dialogue_extract_source)
        self.assertIn('已沉淀为全局资产，不会自动写入当前项目', self.html)
        self.assertIn('沉淀为观点洞察', self.html)
        self.assertIn('id="dialogue-asset-list"', self.html)
        self.assertIn('id="refresh-dialogue-assets"', self.html)
        self.assertIn('let dialogueContextOpen = false;', self.html)
        self.assertIn('aria-label="查看沉淀资产库"', self.html)
        self.assertIn('title="查看沉淀资产库"', self.html)
        self.assertIn('id="dialogue-context-toggle"', self.html)
        self.assertIn('>资产库</button>', self.html)
        self.assertIn('id="dialogue-asset-search"', self.html)
        self.assertIn('id="dialogue-asset-type-filter"', self.html)
        self.assertIn('id="asset-page-search"', self.html)
        self.assertIn('id="asset-page-type-filter"', self.html)
        self.assertIn('data-asset-type-update', self.html)
        self.assertIn('/api/xiangzhongjing/dialogue/assets/${encodeURIComponent(assetId)}', self.html)
        self.assertIn('更改沉淀素材所属类别', self.html)
        self.assertIn('GLOBAL MEMORY', self.html)
        self.assertIn('switchPage("assets");', self.html)
        self.assertIn('dialogueAssetScope = dialogueMode === "book" ? "book" : "mirror";', self.html)
        self.assertIn('workspace?.classList.toggle("has-context-panel", dialogueContextOpen);', self.html)
        self.assertIn('dialogueContextOpen = false;', self.html)
        self.assertNotIn('id="dialogue-context-toggle" type="button" aria-label="查看沉淀资产与会话记忆" title="查看沉淀资产与会话记忆">◌</button>', self.html)
        self.assertIn('/api/xiangzhongjing/dialogue/assets?limit=300', self.html)
        self.assertIn('function renderDialogueAssets', self.html)
        self.assertIn('function renderDialogueAssetPage', self.html)
        self.assertIn('function renderDialogueFlow', self.html)
        self.assertIn('function switchDialoguePersona', self.html)
        self.assertIn('dialogueSessionsLoading', self.html)
        self.assertIn('dialogueAssetsLoading', self.html)
        self.assertIn('正在思考', self.html)
        self.assertIn('主题念头', self.html)
        self.assertNotIn('已更新当前项目主题', self.dialogue_extract_source)
        self.assertNotIn('item.type === "theme" ? "项目主题"', self.html)
        self.assertNotIn('captureMaterialUndo', self.dialogue_extract_source)
        self.assertNotIn('activeProject', self.dialogue_extract_source)
        self.assertNotIn('ensureMaterialItems(project)[group].push', self.dialogue_extract_source)

    def test_dialogue_is_open_ended_not_project_bound(self):
        self.assertIn('独立交流', self.html)
        self.assertIn('placeholder="随便说点什么…"', self.html)
        self.assertIn('? "和这个人物聊聊"', self.html)
        self.assertNotIn('function dialogueProjectContext', self.html)
        self.assertNotIn('project_context:', self.html)
        self.assertNotIn('dialogue/sessions?project_id=', self.html)
        self.assertNotIn('绑定当前项目', self.html)

    def test_dialogue_layout_has_desktop_and_mobile_rules(self):
        self.assertIn('.dialogue-workspace', self.css)
        self.assertIn('grid-template-columns: minmax(230px, 0.68fr) minmax(420px, 1.55fr) minmax(230px, 0.74fr);', self.css)
        self.assertIn('@media (max-width: 980px)', self.css)
        self.assertIn('@media (max-width: 720px)', self.css)
        self.assertIn('grid-template-columns: minmax(0, 1fr);', self.css)
        self.assertIn('align-content: start;', self.css)
        self.assertIn('grid-auto-rows: max-content;', self.css)
        self.assertIn('height: 68px;', self.css)
        self.assertIn('border-left: 3px solid var(--accent);', self.css)
        self.assertIn('.dialogue-session-list-head', self.css)
        self.assertIn('grid-template-columns: minmax(284px, 0.82fr) minmax(0, 1.78fr);', self.css)
        self.assertIn('grid-template-rows: auto auto auto minmax(260px, 1fr) auto;', self.css)
        self.assertIn('height: 30px;', self.css)
        self.assertIn('align-self: end;', self.css)
        self.assertIn('.dialogue-persona-card {\n  display: none;', self.css)
        self.assertIn('grid-template-columns: repeat(4, minmax(0, 1fr));', self.css)
        self.assertIn('.dialogue-session-list-head b', self.css)
        self.assertRegex(
            self.css,
            r"@media \(max-width: 720px\)\s*\{[\s\S]*?\.dialogue-workspace\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);",
        )
        self.assertIn('选好人物后，新建一段对话。', self.html)
        self.assertIn('.dialogue-workspace.has-context-panel', self.css)
        self.assertIn('minmax(320px, 0.95fr)', self.css)
        self.assertIn('.asset-dashboard', self.css)
        self.assertIn('.asset-scope-tabs', self.css)
        self.assertIn('.asset-category-board', self.css)
        self.assertIn('grid-template-columns: repeat(3, minmax(0, 1fr));', self.css)
        self.assertIn('.dialogue-persona-dock', self.css)
        self.assertIn('.dialogue-flow', self.css)
        self.assertIn('.dialogue-session-loading', self.css)

    def test_final_mobile_styles_keep_dialogue_in_one_column(self):
        polish = (BASE_DIR / "static" / "styles" / "10-modular-polish.css").read_text(encoding="utf-8")
        mobile = polish.split("@media (max-width: 720px)", 1)[1]
        self.assertRegex(
            mobile,
            r"\.dialogue-workspace\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);",
        )
        self.assertRegex(
            mobile,
            r"\.dialogue-chat-panel\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;",
        )

    def test_dialogue_product_skills_exist(self):
        for skill_name in (
            "mirror-self-dialogue",
            "book-person-dialogue",
            "summarize-dialogue-memory",
        ):
            skill_path = SKILLS_DIR / skill_name / "SKILL.md"
            self.assertTrue(skill_path.exists(), skill_name)
            content = skill_path.read_text(encoding="utf-8")
            self.assertIn(f"name: {skill_name}", content)
            self.assertIn("Output Contract", content)

    def test_dialogue_product_skills_do_not_require_project_context(self):
        mirror = (SKILLS_DIR / "mirror-self-dialogue" / "SKILL.md").read_text(encoding="utf-8")
        book = (SKILLS_DIR / "book-person-dialogue" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("No project context is required", mirror)
        self.assertIn("No project context is required", book)
        self.assertNotIn("- project context", mirror)
        self.assertNotIn("- project context", book)
        self.assertIn("历史文稿记忆包", mirror)
        self.assertIn("不是待复制语料，而是你的过往", mirror)

    def test_private_legacy_personas_are_preserved_when_their_books_exist(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            for book_id, book in xiangzhongjing_store.LEGACY_LIBRARY_BOOKS.items():
                xiangzhongjing_store.create_library_book(
                    book["title"], author=book["author"], book_id=book_id, source_type="legacy"
                )
            for persona in xiangzhongjing_store.LEGACY_BOOK_PERSONAS:
                xiangzhongjing_store.create_book_persona(
                    persona["name"],
                    persona["book_ids"],
                    description=persona["description"],
                    voice=persona["voice"],
                    boundaries=persona["boundaries"],
                    persona_id=persona["id"],
                )
            payload = dialogue_personas()
            people = [item for item in payload["personas"] if item["type"] == "book"]
        self.assertEqual({item["name"] for item in people}, {"马斯克", "陈平安", "齐静春", "老子"})
        self.assertEqual(len(people), 4)
        self.assertNotIn("艾萨克森观察者", [item["name"] for item in people])
        self.assertNotIn("剑来世界观人格", [item["name"] for item in people])

    def test_new_dialogue_session_is_global_by_default(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            session = _create_session_sync({"mode": "mirror", "title": "contract mirror"})

        self.assertEqual(session["project_id"], "")
        self.assertEqual(session["mode"], "mirror")
        self.assertEqual(session["persona_id"], "mirror-self")

    def test_dialogue_asset_type_can_be_reclassified(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            asset = xiangzhongjing_store.create_persona_asset(
                "dialogue_insight",
                "一个值得保留的判断",
                title="旧分类",
                source="dialogue:missing",
            )
            updated = _update_asset_sync(asset["id"], {"asset_type": "dialogue_event"})["asset"]
            stored = xiangzhongjing_store.get_persona_asset(asset["id"])

        self.assertEqual(updated["asset_type"], "dialogue_event")
        self.assertEqual(stored["asset_type"], "dialogue_event")
        self.assertIn("source_label", updated)

    def test_dialogue_asset_type_rejects_unknown_category(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            asset = xiangzhongjing_store.create_persona_asset(
                "dialogue_insight",
                "一个值得保留的判断",
                title="旧分类",
            )
            with self.assertRaises(Exception):
                _update_asset_sync(asset["id"], {"asset_type": "unknown"})
    def test_dialogue_session_management_and_message_pagination(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            session = _create_session_sync({"mode": "mirror", "title": "新会话"})
            for index in range(65):
                xiangzhongjing_store.add_dialogue_message(
                    session["id"],
                    "user" if index % 2 == 0 else "assistant",
                    f"第 {index} 条消息",
                    turn_id=f"turn-{index // 2}",
                )
            page = xiangzhongjing_store.list_dialogue_messages_page(session["id"], limit=30)
            self.assertEqual(len(page["messages"]), 30)
            self.assertTrue(page["has_more"])
            older = xiangzhongjing_store.list_dialogue_messages_page(
                session["id"], limit=30, before=page["next_before"]
            )
            self.assertEqual(len(older["messages"]), 30)
            self.assertNotEqual(page["messages"][-1]["content"], older["messages"][-1]["content"])

            renamed = _patch_session_sync(session["id"], {"title": "新的会话标题", "pinned": True})
            self.assertEqual(renamed["title"], "新的会话标题")
            self.assertTrue(renamed["pinned_at"])
            self.assertEqual(len(_list_sessions_sync(query="会话标题")["sessions"]), 1)

            _clear_session_sync(session["id"])
            cleared = xiangzhongjing_store.get_dialogue_session(session["id"])
            self.assertEqual(cleared["message_count"], 0)
            self.assertEqual(cleared["last_message_preview"], "")

            _delete_session_sync(session["id"])
            self.assertEqual(_list_sessions_sync()["sessions"], [])
            self.assertEqual(len(_list_sessions_sync(include_deleted=True)["sessions"]), 1)
            restored = _restore_session_sync(session["id"])
            self.assertIsNone(restored["deleted_at"])

    def test_dialogue_session_bulk_clear_current_and_trash_lists(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ):
            xiangzhongjing_store.create_library_book(
                "《剑来》", author="烽火戏诸侯", book_id="jianlai", source_type="legacy"
            )
            xiangzhongjing_store.create_library_book(
                "《埃隆·马斯克传》", author="沃尔特·艾萨克森", book_id="musk", source_type="legacy"
            )
            xiangzhongjing_store.create_book_persona(
                "陈平安", ["jianlai"], persona_id="chen-ping-an"
            )
            xiangzhongjing_store.create_book_persona(
                "马斯克", ["musk"], persona_id="musk-action"
            )
            first = _create_session_sync({"mode": "book", "persona_id": "chen-ping-an", "title": "第一段"})
            second = _create_session_sync({"mode": "book", "persona_id": "chen-ping-an", "title": "第二段"})
            other = _create_session_sync({"mode": "book", "persona_id": "musk-action", "title": "不应清空"})
            result = _bulk_delete_sessions_sync({
                "session_ids": [first["id"], second["id"]],
                "permanent": False,
            })
            self.assertEqual(result["count"], 2)
            self.assertEqual(len(_list_sessions_sync(mode="book", persona_id="chen-ping-an")["sessions"]), 0)
            self.assertEqual(len(_list_sessions_sync(mode="book", persona_id="chen-ping-an", include_deleted=True)["sessions"]), 2)
            self.assertEqual(len(_list_sessions_sync(mode="book", persona_id="musk-action")["sessions"]), 1)

            permanent = _bulk_delete_sessions_sync({
                "session_ids": [first["id"], second["id"], other["id"]],
                "permanent": True,
            })
            self.assertEqual(permanent["count"], 2)
            self.assertEqual(len(_list_sessions_sync(mode="book", persona_id="chen-ping-an", include_deleted=True)["sessions"]), 0)
            self.assertIsNotNone(xiangzhongjing_store.get_dialogue_session(other["id"]))

    def test_dialogue_session_bulk_clear_has_confirmed_frontend_entry(self):
        self.assertIn("data-dialogue-bulk-clear", self.html + (BASE_DIR / "static" / "js" / "dialogue.js").read_text(encoding="utf-8"))
        self.assertIn("bulkClearDialogueSessions", (BASE_DIR / "static" / "js" / "dialogue.js").read_text(encoding="utf-8"))
        self.assertIn("/api/xiangzhongjing/dialogue/sessions/bulk-delete", (BASE_DIR / "static" / "js" / "dialogue.js").read_text(encoding="utf-8"))
        self.assertIn("永久清空最近删除？", (BASE_DIR / "static" / "js" / "dialogue.js").read_text(encoding="utf-8"))

    def test_mirror_dialogue_ignores_project_context_payload(self):
        prompts = []

        def fake_run_json(skill_name, user_prompt, **kwargs):
            prompts.append(user_prompt)
            return {
                "data": {
                    "reply": "这件事先别急着包装成主题，先看你到底被哪一刻拽住了。",
                    "extractable": [],
                    "questions": [],
                    "style_diagnosis": {"is_like_creator": True, "reason": "克制"},
                },
                "run_id": "dialogue-run",
                "skill": skill_name,
                "version": "1.0.0",
                "model": "mock",
                "latency_ms": 3,
            }

        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store,
            "DB_PATH",
            Path(tmpdir) / "test.db",
        ), patch("services.dialogue_service.load_writing_skill", return_value=("v2.1", "STYLE")), patch(
            "services.dialogue_service.run_json", side_effect=fake_run_json
        ):
            session = _create_session_sync({"mode": "mirror", "title": "contract prompt"})
            result = _send_message_sync(
                session["id"],
                {
                    "message": "我最近有点不知道该往哪里用力。",
                    "project_context": {"title": "不应进入 prompt"},
                },
            )

        self.assertIn("先别急着包装成主题", result["reply"])
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("project_context", prompts[0])
        self.assertNotIn("不应进入 prompt", prompts[0])
        self.assertIn("个人历史文稿与长期记忆", prompts[0])

    def test_book_dialogue_rejects_unverified_quote_language(self):
        self.assertTrue(
            _has_unverified_book_quote(
                {
                    "reply": "老子讲‘知足者富’，所以你应该停下来。",
                    "book_support": [
                        {"type": "paraphrase", "source_status": "paraphrase"}
                    ],
                }
            )
        )
        self.assertTrue(
            _has_unverified_book_quote(
                {
                    "reply": "可以用《道德经》的思想来理解。",
                    "book_support": [
                        {"type": "quote", "source_status": "paraphrase"}
                    ],
                }
            )
        )
        self.assertFalse(
            _has_unverified_book_quote(
                {
                    "reply": "用《道德经》的思想来说，回忆可以是一种自知。",
                    "book_support": [
                        {"type": "paraphrase", "source_status": "paraphrase"}
                    ],
                }
            )
        )
        self.assertTrue(
            _has_unverified_book_quote(
                {
                    "reply": "用《道德经》的思想来说，回忆可以是一种自知。",
                    "book_support": [
                        {
                            "type": "quote",
                            "source_status": "verified",
                            "source_url": "https://example.com/fake",
                            "text": "知足者富",
                        }
                    ],
                },
                {},
            )
        )
        self.assertFalse(
            _has_unverified_book_quote(
                {
                    "reply": "老子讲“知足者富”。",
                    "book_support": [
                        {
                            "type": "quote",
                            "source_status": "verified",
                            "source_url": "https://source.example/daode",
                            "text": "知足者富",
                        }
                    ],
                },
                {"https://source.example/daode": "知足者富"},
            )
        )


class DialogueStreamContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_forwards_progress_before_final_result(self):
        def fake_send(session_id, payload, progress):
            self.assertEqual(session_id, "session-stream")
            self.assertEqual(payload["message"], "我是谁")
            progress("accepted", "问题已进入当前会话", {"mode": "mirror"})
            progress("retrieving_memory", "正在检索相关个人记忆", None)
            progress("memory_ready", "已找到 2 条相关个人依据", {"source_count": 2})
            progress("generating", "镜中人正在组织回答", None)
            return {"reply": "我就是你。"}

        with patch("services.dialogue_service._send_message_sync", side_effect=fake_send):
            events = [
                event
                async for event in stream_message_events(
                    "session-stream", {"message": "我是谁"}
                )
            ]

        self.assertEqual(
            [event["stage"] for event in events if event["type"] == "stage"],
            ["accepted", "retrieving_memory", "memory_ready", "generating"],
        )
        self.assertEqual(events[-1], {"type": "result", "data": {"reply": "我就是你。"}})


if __name__ == "__main__":
    unittest.main()
