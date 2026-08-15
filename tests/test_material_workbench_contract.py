import re
import unittest
from pathlib import Path
from tests.frontend_assets import demo_markup, demo_source, demo_styles


BASE_DIR = Path(__file__).resolve().parents[1]
class MaterialWorkbenchContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.markup = demo_markup()
        cls.html = demo_source()
        cls.css = demo_styles()

    def test_ui_uses_ordered_domain_stylesheets(self):
        self.assertGreaterEqual(self.markup.count('/static/styles/'), 8)
        self.assertNotIn('/static/demo.css', self.markup)
        self.assertIn('/static/styles/01-shell-editor.css', self.markup)
        self.assertIn('/static/styles/10-modular-polish.css', self.markup)

    def test_navigation_and_tabs_are_accessible_and_deep_linked(self):
        self.assertIn('class="skip-link"', self.html)
        self.assertIn('href="?page=workspace"', self.html)
        self.assertIn('role="tab" aria-selected="true"', self.html)
        self.assertIn('function syncUrlState(mode = "push")', self.html)
        self.assertIn('materialQuery', self.html)
        self.assertIn('materialStatus', self.html)
        self.assertIn('showArchived', self.html)
        self.assertIn('url.searchParams.set("mode", generationMode)', self.html)
        self.assertIn('window.addEventListener("popstate"', self.html)

    def test_legacy_material_fields_are_not_focusable(self):
        self.assertEqual(self.html.count('class="material-legacy-field"'), 6)
        self.assertEqual(self.html.count('hidden aria-hidden="true" tabindex="-1"'), 6)

    def test_removed_manual_save_button_has_no_listener(self):
        self.assertNotIn('#save-materials', self.html)

    def test_material_page_has_no_duplicate_header_actions(self):
        self.assertNotIn('id="material-save-state"', self.html)
        self.assertNotIn('id="add-material-global"', self.html)
        self.assertNotIn('id="material-group-filter"', self.html)

    def test_book_library_state_cannot_leak_into_other_pages(self):
        self.assertIn('bookNotesState = await response.json();', self.html)
        self.assertIn('if (activePage !== "library") {\n      updateStrategy();\n      return;\n    }', self.html)
        load_state_start = self.html.index('async function loadBookNotesState()')
        catalog_index = self.html.index('replaceBookCatalog(bookNotesState.books || []);', load_state_start)
        guard_index = self.html.index('if (activePage !== "library")', load_state_start)
        detail_index = self.html.index('renderBookLibraryView();', guard_index)
        self.assertLess(catalog_index, guard_index)
        self.assertLess(guard_index, detail_index)
        page_switch = self.html[self.html.index('function switchPage('):]
        self.assertIn('if (safePage !== "library") {', page_switch)
        self.assertIn('renderBookDiagnostics("clear");', page_switch)
        self.assertIn('clearResearch();', page_switch)

    def test_book_quotes_are_hidden_until_library_viewer_is_opened(self):
        self.assertNotIn('id="research-list"', self.html)
        self.assertIn('id="view-book-library"', self.html)
        self.assertIn('id="book-library-viewer"', self.html)
        self.assertIn('id="book-library-research-list"', self.html)
        self.assertIn('function openBookLibraryViewer()', self.html)

    def test_published_copy_is_saved_to_global_journal(self):
        self.assertIn('data-page="diary"', self.html)
        self.assertIn('id="publish-diary"', self.html)
        self.assertIn('id="page-diary"', self.html)
        self.assertIn('class="diary-nav"', self.html)
        sidebar = self.html[self.html.index('<aside class="demo-sidebar">'):self.html.index('</aside>', self.html.index('<aside class="demo-sidebar">'))]
        self.assertIn('<nav class="diary-nav"', sidebar)
        self.assertLess(sidebar.index('<nav class="diary-nav"'), sidebar.index('class="profile-tile"'))
        self.assertIn('diaryEntries', self.html)
        self.assertIn('function publishCurrentProject()', self.html)
        self.assertIn('diaryEntries.push(diaryEntry)', self.html)
        self.assertIn('diaryEntries', self.html[self.html.index('function snapshotState'):self.html.index('function persistState')])
        self.assertIn('.mobile-bottom-nav [data-page]', self.html)
        self.assertIn('$$(sidebarNavSelector).forEach((link) => {', self.html)

    def test_diary_entry_delete_requires_product_confirmation(self):
        self.assertIn('id="delete-diary-entry"', self.html)
        self.assertIn('function deleteCurrentDiaryEntry()', self.html)
        delete_source = self.html[self.html.index('async function deleteCurrentDiaryEntry'):self.html.index('function snapshotState')]
        self.assertIn('await requestConfirm({', delete_source)
        self.assertIn('confirmText: "确认删除"', delete_source)
        self.assertIn('danger: true', delete_source)
        self.assertIn('diaryEntries = diaryEntries.filter', delete_source)

    def test_material_v2_uses_group_navigation_and_single_list(self):
        self.assertIn('id="material-group-navigation"', self.html)
        self.assertIn('id="material-active-list"', self.html)
        self.assertIn('data-material-group-tab="daily"', self.html)
        self.assertIn('id="add-material-current"', self.html)

    def test_project_meta_is_inline_and_ai_import_stays_in_drawer(self):
        self.assertIn('id="edit-project-meta"', self.html)
        self.assertIn('id="project-meta-editor"', self.html)
        self.assertIn('id="project-theme-input"', self.html)
        self.assertNotIn('project-content-type-input', self.html)
        self.assertNotIn('project-content-type-label', self.html)
        self.assertNotIn('{ key: "content_type"', self.html)
        self.assertNotIn('data-material-drawer-panel="context"', self.html)
        self.assertIn('id="material-drawer"', self.html)
        self.assertIn('data-material-drawer-panel="import"', self.html)
        self.assertIn('data-open-material-drawer="import"', self.html)

    def test_material_groups_follow_creator_input_model(self):
        for group in ("opening", "insight", "daily", "event", "quotes", "ending_reference"):
            self.assertIn(f'data-material-group-tab="{group}"', self.html)
        self.assertNotIn('data-material-group-tab="extra_thoughts"', self.html)
        self.assertNotIn('id="material-axis-title"', self.html)

    def test_material_expression_boundaries_are_three_standard_modes(self):
        self.assertIn('const materialTreatmentLabels = { verbatim: "原句", rewrite: "改写（默认）", elaborate: "阐释" };', self.html)
        self.assertIn('opening: { label: "开场构想"', self.html)
        self.assertIn('opening: { label: "开场构想", count: "#opening-count", kicker: "OPENING IDEAS", description: "进入这条视频的视角、问题或开场原句。", defaultPriority: "optional", defaultTreatment: "rewrite" }', self.html)
        self.assertIn('quotes: { label: "对话与原句"', self.html)
        self.assertIn('defaultTreatment: "verbatim"', self.html)
        self.assertNotIn('defaultTreatment: "direct"', self.html)
        self.assertNotIn('defaultTreatment: "original"', self.html)

    def test_materials_page_removes_redundant_readiness_and_keeps_draft_audit(self):
        self.assertNotIn('id="material-readiness-summary"', self.html)
        self.assertNotIn('class="material-readiness"', self.html)
        self.assertIn('id="material-draft-audit"', self.html)
        self.assertIn('material_coverage_state', self.html)
        self.assertIn('function invalidateMaterialCoverage', self.html)
        self.assertIn('待重新分析', self.html)

    def test_material_drawer_uses_body_portal_and_responsive_scroll_lock(self):
        self.assertIn('document.body.appendChild(materialDrawerBackdrop)', self.html)
        self.assertIn('document.body.appendChild(materialDrawer)', self.html)
        self.assertIn("lockMode: materialDrawerLockMode()", self.html)
        self.assertIn("return window.matchMedia('(max-width: 1040px)').matches ? 'modal' : 'none'", self.html)
        self.assertNotIn('material-drawer-open', self.html)
        self.assertNotIn('body.material-drawer-open', self.css)

    def test_overlays_share_scroll_focus_and_layer_management(self):
        self.assertIn('const overlayManager = (() => {', self.html)
        self.assertIn("id: 'style-audit'", self.html)
        self.assertIn("id: 'edit-preview'", self.html)
        self.assertIn('event.stopImmediatePropagation()', self.html)
        self.assertIn('class="edit-preview-body"', self.html)
        self.assertIn('aria-label="关闭创作风格审核"', self.html)
        self.assertIn('aria-label="关闭编辑预览"', self.html)
        self.assertNotIn('modal-open', self.html)
        self.assertIn('body.overlay-scroll-locked', self.css)
        compare_rule = re.search(r"\.edit-compare\s*\{(?P<body>.*?)\}", self.css, flags=re.DOTALL)
        self.assertIsNotNone(compare_rule)
        self.assertIn('height: max-content', compare_rule.group('body'))
        self.assertNotIn('min-height: 620px', self.css)

    def test_material_rows_support_drag_sort_and_progressive_controls(self):
        self.assertIn('data-material-drag-handle', self.html)
        self.assertIn('data-material-menu-trigger', self.html)
        self.assertIn('class="material-row-evidence', self.html)
        self.assertIn('addEventListener("drop"', self.html)

    def test_material_actions_use_one_compact_body_portal(self):
        self.assertNotIn('<details class="material-more-menu">', self.html)
        self.assertEqual(self.html.count('id="material-action-popover"'), 1)
        self.assertNotIn('popover="auto"', self.html)
        self.assertIn('role="group" aria-labelledby="material-action-title" aria-hidden="true"', self.html)
        self.assertIn('aria-haspopup="true" aria-controls="material-action-popover"', self.html)
        self.assertIn('function positionMaterialActionPopover()', self.html)
        self.assertIn('document.body.appendChild(materialActionPopover)', self.html)
        self.assertIn('.material-action-popover.open', self.css)

    def test_material_action_popover_supports_collision_and_dismissal(self):
        self.assertIn('availableBelow', self.html)
        self.assertIn('availableAbove', self.html)
        self.assertIn('closeMaterialActionPopover({ restoreFocus: false })', self.html)
        self.assertIn('addEventListener("pointerdown"', self.html)

    def test_ai_parse_waits_for_user_confirmation(self):
        start = self.html.index('$("#parse-clipboard").addEventListener')
        end = self.html.index('$("#clipboard-result").addEventListener', start)
        parse_handler = self.html[start:end]
        self.assertIn("renderClipboardResult(data, true)", parse_handler)
        self.assertNotIn("applyParsedMaterials(data", parse_handler)
        self.assertIn('data-import-action="merge"', self.html)
        self.assertIn('data-import-action="replace"', self.html)

    def test_cancel_restores_staged_clipboard_source(self):
        self.assertIn("previousSource: projects[activeProject].clipboard_source", self.html)
        self.assertIn('$("#clipboard-source").value = pendingMaterialImport.previousSource', self.html)

    def test_material_status_controls_are_not_absolute(self):
        rule = re.search(
            r"\.material-usage,\s*\.material-role-control select,\s*\.material-more-trigger\s*\{(?P<body>.*?)\}",
            self.css,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(rule)
        self.assertNotIn("position: absolute", rule.group("body"))

    def test_destructive_actions_use_product_confirm_dialog(self):
        self.assertNotIn("window.confirm", self.html)
        self.assertIn('id="confirm-dialog"', self.html)
        self.assertIn("function requestConfirm", self.html)
        self.assertIn('$("#confirm-accept").addEventListener("click"', self.html)
        self.assertIn(".confirm-panel", self.css)

    def test_versions_do_not_nest_interactive_controls(self):
        self.assertNotIn('<button class="version-item', self.html)
        self.assertIn('<article class="version-item', self.html)
        self.assertIn('<button data-version-action="diff"', self.html)
        self.assertIn(".version-actions button", self.css)

    def test_ai_edit_failure_has_dedicated_preview(self):
        start = self.html.index("async function requestAiEdit")
        end = self.html.index("async function consumeSseResponse", start)
        edit_handler = self.html[start:end]
        self.assertIn("openEditFailure", edit_handler)
        self.assertIn('data.metrics?.meaningful === false', edit_handler)
        self.assertIn("materialSignature(previewText) === materialSignature(comparisonSource)", edit_handler)
        self.assertNotIn('renderGenerationDiagnostics("failed"', edit_handler)


if __name__ == "__main__":
    unittest.main()
