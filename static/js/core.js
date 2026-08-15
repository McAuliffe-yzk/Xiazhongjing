"use strict";

let projects = {};

let books = {};

let activeProject = "";
let activePage = "workspace";
let activeEditorTab = "copy";
let activeInspirationType = "";
let inspirationDraws = [];
let activeBooks = [];
let bookQuoteStrategy = "standard";
let dnaReagents = [];
let settingsState = null;
let bookNotesState = { summary: [], recent: [] };
let bookLibraryVisibleLimit = 80;
let versions = [];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);
const sidebarNavSelector = ".workspace-nav [data-page], .diary-nav [data-page], .profile-tile[data-page], .mobile-bottom-nav [data-page]";
let persistTimer = null;
let persistInFlight = Promise.resolve(true);
let stateRevision = 0;
let pendingEdit = null;
let pendingStyleCandidate = null;
let skillStatus = null;
let styleAuditData = null;
let styleAuditTab = "rules";
let styleAuditSection = "";
let generationTimeline = [];
let generationMode = "fresh";
let failedGenerationId = "";
let projectFilter = "";
let showArchived = false;
const expandedMaterialRows = new Set();
const selectedMaterialIds = new Set();
let activeMaterialGroup = "opening";
let materialSelectionMode = false;
let draggedMaterialId = "";
let activeMaterialMenu = null;
let materialFilters = { query: "", status: "all" };
let pendingMaterialImport = null;
let materialUndoState = null;
let materialPersistTimer = null;
let hasPendingChanges = false;
let persistFailed = false;
let dialogueMode = "mirror";
let dialoguePersonas = [];
let activeDialoguePersona = "mirror-self";
let dialogueSessions = [];
let activeDialogueSession = "";
let activeDialogueMessages = [];
let activeDialogueMemory = {};
const dialogueEvidenceOpen = new Set();
let dialogueAssets = [];
let dialogueReferenceMemoryCount = 0;
let dialogueMemoryEngineStatus = {};
let dialogueAssetQuery = "";
let dialogueAssetTypeFilter = "all";
let dialogueAssetScope = "all";
let dialogueSending = false;
let dialogueThinkingState = "idle";
window.dialogueThinkingState = dialogueThinkingState;
let dialogueRuntimeProgress = { stage: "", label: "", meta: {} };
window.dialogueRuntimeProgress = dialogueRuntimeProgress;
let dialogueSessionQuery = "";
let dialogueTrashMode = false;
let dialogueSessionsLoading = false;
let dialogueAssetsLoading = false;
let dialogueMenuSessionId = "";
let dialogueMessagesBefore = "";
let dialogueMessagesHasMore = false;
let dialogueLoadingHistory = false;
let dialogueContextOpen = false;
let dialogueRenameSessionId = "";
let dialogueDeleteUndo = null;
let diaryEntries = [];
let activeDiaryPage = 1;

function readUrlState() {
  const params = new URLSearchParams(window.location.search);
  const rawPage = params.get("page") === "dialogue" ? "mirror" : params.get("page");
  const page = ["onboarding", "workspace", "editor", "inspiration", "diary", "distill", "library", "mirror", "book-person", "assets", "covers", "profile", "dna", "settings"].includes(rawPage)
    ? rawPage
    : null;
  const project = params.get("project");
  const tab = ["copy", "materials", "versions"].includes(params.get("tab"))
    ? params.get("tab")
    : null;
  const group = ["opening", "insight", "daily", "event", "quotes", "ending_reference"].includes(params.get("group"))
    ? params.get("group")
    : null;
  const materialQuery = params.get("q") || "";
  const materialStatus = ["all", "stale", "linked", "unused", "conflicted"].includes(params.get("status"))
    ? params.get("status")
    : "all";
  const mode = ["fresh", "rewrite"].includes(params.get("mode"))
    ? params.get("mode")
    : null;
  const archived = ["1", "true"].includes(params.get("archived"));
  return { page, project, tab, group, materialQuery, materialStatus, mode, archived };
}

function syncUrlState(mode = "push") {
  if (mode === "none") return;
  const url = new URL(window.location.href);
  url.searchParams.set("page", activePage);
  if (activeProject) url.searchParams.set("project", activeProject);
  if (activePage === "editor") url.searchParams.set("tab", activeEditorTab);
  else url.searchParams.delete("tab");
  if (activePage === "editor" && activeEditorTab === "materials") {
    if (activeMaterialGroup) url.searchParams.set("group", activeMaterialGroup);
    else url.searchParams.delete("group");
    if (materialFilters.query) url.searchParams.set("q", materialFilters.query);
    else url.searchParams.delete("q");
    if (materialFilters.status !== "all") url.searchParams.set("status", materialFilters.status);
    else url.searchParams.delete("status");
  } else {
    url.searchParams.delete("group");
    url.searchParams.delete("q");
    url.searchParams.delete("status");
  }
  if (activePage === "editor") {
    url.searchParams.set("mode", generationMode);
  } else {
    url.searchParams.delete("mode");
  }
  if (activePage === "onboarding" || activePage === "inspiration" || activePage === "mirror" || activePage === "book-person" || activePage === "diary" || activePage === "assets" || activePage === "covers" || activePage === "profile" || activePage === "dna" || activePage === "settings") {
    url.searchParams.delete("project");
  }
  if (activePage === "workspace" && showArchived) {
    url.searchParams.set("archived", "1");
  } else {
    url.searchParams.delete("archived");
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  window.history[mode === "replace" ? "replaceState" : "pushState"]({
    page: activePage,
    project: activeProject,
    tab: activeEditorTab,
    group: activeMaterialGroup,
    materialQuery: materialFilters.query,
    materialStatus: materialFilters.status,
    generationMode,
    showArchived
  }, "", next);
}
function updateUrl() {
  syncUrlState("replace");
}


const overlayManager = (() => {
  const stack = [];
  const focusableSelector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[contenteditable="true"]',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');
  let scrollLock = null;

  function freezePage() {
    if (scrollLock) return;
    const body = document.body;
    const root = document.documentElement;
    const scrollY = window.scrollY;
    const scrollbarWidth = Math.max(0, window.innerWidth - root.clientWidth);
    scrollLock = {
      scrollY,
      rootScrollBehavior: root.style.scrollBehavior,
      bodyStyles: {
        position: body.style.position,
        top: body.style.top,
        left: body.style.left,
        right: body.style.right,
        width: body.style.width,
        paddingRight: body.style.paddingRight,
        overflow: body.style.overflow
      }
    };
    body.classList.add('overlay-scroll-locked');
    body.style.position = 'fixed';
    body.style.top = `-${scrollY}px`;
    body.style.left = '0';
    body.style.right = '0';
    body.style.width = '100%';
    if (scrollbarWidth) {
      body.style.paddingRight = `calc(${getComputedStyle(body).paddingRight} + ${scrollbarWidth}px)`;
    }
  }

  function restorePage() {
    if (!scrollLock) return;
    const body = document.body;
    const root = document.documentElement;
    const { scrollY, rootScrollBehavior, bodyStyles } = scrollLock;
    scrollLock = null;
    body.classList.remove('overlay-scroll-locked');
    Object.entries(bodyStyles).forEach(([property, value]) => {
      body.style[property] = value;
    });
    root.style.scrollBehavior = 'auto';
    window.scrollTo(0, scrollY);
    window.requestAnimationFrame(() => {
      root.style.scrollBehavior = rootScrollBehavior;
    });
  }

  function syncPageLock() {
    if (stack.some((entry) => entry.lockMode === 'modal')) freezePage();
    else restorePage();
  }

  function open({ id, element, backdrop = null, lockMode = 'none', trapFocus = true, onRequestClose }) {
    const existing = stack.find((entry) => entry.id === id);
    if (existing) {
      existing.onRequestClose = onRequestClose;
      return;
    }
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const layer = 80 + stack.length * 10;
    const entry = {
      id,
      element,
      backdrop,
      lockMode,
      trapFocus,
      trigger,
      onRequestClose,
      elementZIndex: element.style.zIndex,
      backdropZIndex: backdrop?.style.zIndex || ''
    };
    stack.push(entry);
    if (backdrop) backdrop.style.zIndex = String(layer);
    element.style.zIndex = String(layer + (backdrop ? 1 : 0));
    syncPageLock();
  }

  function close(id, { restoreFocus = true } = {}) {
    const index = stack.findIndex((entry) => entry.id === id);
    if (index < 0) return;
    const [entry] = stack.splice(index, 1);
    entry.element.style.zIndex = entry.elementZIndex;
    if (entry.backdrop) entry.backdrop.style.zIndex = entry.backdropZIndex;
    syncPageLock();
    if (restoreFocus && entry.trigger?.isConnected) {
      window.requestAnimationFrame(() => entry.trigger.focus({ preventScroll: true }));
    }
  }

  function updateLock(id, lockMode) {
    const entry = stack.find((candidate) => candidate.id === id);
    if (!entry || entry.lockMode === lockMode) return;
    entry.lockMode = lockMode;
    syncPageLock();
  }

  function top() {
    return stack[stack.length - 1] || null;
  }

  document.addEventListener('keydown', (event) => {
    const entry = top();
    if (!entry) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      entry.onRequestClose?.();
      return;
    }
    if (event.key !== 'Tab' || !entry.trapFocus) return;
    const focusable = [...entry.element.querySelectorAll(focusableSelector)].filter((node) => {
      return !node.hidden && node.getAttribute('aria-hidden') !== 'true' && node.getClientRects().length > 0;
    });
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!entry.element.contains(document.activeElement)) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus({ preventScroll: true });
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  });

  return { open, close, updateLock };
})();

let pendingConfirmResolve = null;

function closeConfirmDialog(confirmed = false) {
  const dialog = $("#confirm-dialog");
  if (!dialog) return;
  dialog.classList.add("hidden");
  dialog.setAttribute("aria-hidden", "true");
  overlayManager.close("confirm-dialog");
  const resolve = pendingConfirmResolve;
  pendingConfirmResolve = null;
  resolve?.(confirmed);
}

function requestConfirm({
  title = "确认操作",
  message = "这个操作需要确认。",
  confirmText = "确认",
  danger = false
} = {}) {
  const dialog = $("#confirm-dialog");
  if (!dialog) return Promise.resolve(false);
  if (pendingConfirmResolve) closeConfirmDialog(false);
  $("#confirm-title").textContent = title;
  $("#confirm-message").textContent = message;
  $("#confirm-accept").textContent = confirmText;
  $("#confirm-accept").classList.toggle("danger", danger);
  dialog.classList.remove("hidden");
  dialog.setAttribute("aria-hidden", "false");
  overlayManager.open({
    id: "confirm-dialog",
    element: dialog,
    lockMode: "modal",
    onRequestClose: () => closeConfirmDialog(false)
  });
  return new Promise((resolve) => {
    pendingConfirmResolve = resolve;
    window.requestAnimationFrame(() => $("#confirm-cancel")?.focus({ preventScroll: true }));
  });
}

const generationStageBlueprint = [
  { skill: "write-personal-vlog", label: "个人声音写作", phase: "创作" },
  { skill: "optimize-douyin-vlog", label: "抖音 Vlog 优化", phase: "提效" },
  { skill: "insert-book-quotes", label: "书库金句", phase: "书库" },
];

const materialGroupDefinitions = {
  opening: { label: "开场构想", count: "#opening-count", kicker: "OPENING IDEAS", description: "进入这条视频的视角、问题或开场原句。", defaultPriority: "optional", defaultTreatment: "rewrite" },
  insight: { label: "观点洞察", count: "#insight-count", kicker: "POINT OF VIEW", description: "这条视频真正想留下的判断、感受和思想发展。", defaultPriority: "must", defaultTreatment: "elaborate" },
  daily: { label: "日常细节", count: "#daily-count", kicker: "DAILY DETAILS", description: "动作、场景与生活切片，让抽象判断落到真实生活。", defaultPriority: "optional", defaultTreatment: "rewrite" },
  event: { label: "核心事件", count: "#event-count", kicker: "CORE EVENTS", description: "推动故事发生变化的行动、节点和结果。", defaultPriority: "must", defaultTreatment: "rewrite" },
  quotes: { label: "对话与原句", count: "#quotes-count", kicker: "VOICE & QUOTES", description: "人物原话、现场声音和需要保留的真实表达。", defaultPriority: "must", defaultTreatment: "verbatim" },
  ending_reference: { label: "收束意象", count: "#ending-reference-count", kicker: "ENDING IMAGE", description: "用于回扣主题、留下余味的画面或句子。", defaultPriority: "optional", defaultTreatment: "elaborate" }
};

const materialPriorityLabels = { must: "必用", optional: "选用" };
const materialTreatmentLabels = { verbatim: "原句", rewrite: "改写（默认）", elaborate: "阐释" };
const materialUsageLabels = {
  stale: "待重新分析",
  untracked: "待重新分析",
  linked: "已关联",
  used: "已关联",
  transformed: "已关联",
  unused: "未采用",
  conflicted: "有冲突"
};

function normalizeMaterialUsage(status) {
  if (["used", "transformed"].includes(status)) return "linked";
  if (status === "untracked" || !status) return "stale";
  return ["linked", "unused", "conflicted", "stale"].includes(status) ? status : "stale";
}

function defaultBookIds() {
  return Object.keys(books);
}

function replaceBookCatalog(items) {
  const colors = ["red", "blue", "gold", "green"];
  books = Object.fromEntries((Array.isArray(items) ? items : []).map((item, index) => {
    const id = String(item?.id || "").trim();
    return [id, {
      ...item,
      id,
      title: String(item?.title || "未命名书籍"),
      author: String(item?.author || "作者未填写"),
      color: colors[index % colors.length],
      scope: String(item?.description || "个人精神书库")
    }];
  }).filter(([id]) => id));
  activeBooks = validBookIds(activeBooks);
}

function validBookIds(ids) {
  return Array.isArray(ids) ? ids.filter((id) => books[id]) : [];
}

function noteCountForBook(book) {
  const summary = Array.isArray(bookNotesState.summary) ? bookNotesState.summary : [];
  const plainTitle = String(book.title || "").replace(/[《》]/g, "");
  const item = summary.find((entry) => {
    const label = String(entry.book || "");
    return label === book.title || label.replace(/[《》]/g, "") === plainTitle;
  });
  return Number(item?.count || 0);
}

function quotableCountForBook(book) {
  const summary = Array.isArray(bookNotesState.summary) ? bookNotesState.summary : [];
  const plainTitle = String(book.title || "").replace(/[《》]/g, "");
  const item = summary.find((entry) => {
    const label = String(entry.book || "");
    return label === book.title || label.replace(/[《》]/g, "") === plainTitle;
  });
  return Number(item?.quotable_count || 0);
}

function ensureProjectState(project) {
  ensureProjectMaterials(project);
  ensureMaterialItems(project);
  if (!["fresh", "rewrite"].includes(project.generation_mode)) {
    project.generation_mode = "fresh";
  }
  if (!["default", "parallelism", "six-stage", "contrast-first"].includes(project.narrative_mode)) {
    project.narrative_mode = "default";
  }
  if (!["auto", "manual"].includes(project.target_length_mode)) {
    project.target_length_mode = "auto";
  }
  if (!["restrained", "standard", "amplified"].includes(project.book_quote_strategy)) {
    project.book_quote_strategy = "standard";
  }
  if (!Array.isArray(project.active_dna_ids)) {
    project.active_dna_ids = [];
  }
  const parsedTargetLength = Number(project.target_length);
  project.target_length = Number.isFinite(parsedTargetLength)
    ? Math.max(300, Math.min(3000, Math.round(parsedTargetLength / 50) * 50))
    : 1200;
  if (!Object.prototype.hasOwnProperty.call(project, "selected_books")) {
    project.selected_books = defaultBookIds();
  } else {
    project.selected_books = validBookIds(project.selected_books);
  }
  if (!Array.isArray(project.versions)) {
    project.versions = [];
  }
  if (!Array.isArray(project.locked_paragraphs)) {
    project.locked_paragraphs = [];
  }
  if (typeof project.archived !== "boolean") {
    project.archived = false;
  }
  if (!Array.isArray(project.material_coverage)) {
    project.material_coverage = [];
  }
  if (!["current", "stale", "empty"].includes(project.material_coverage_state)) {
    project.material_coverage_state = project.material_coverage.length ? "stale" : "empty";
  }
  return project;
}

function currentVersions() {
  const project = ensureProjectState(projects[activeProject]);
  versions = project.versions;
  return project.versions;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2200);
}

function setSaveState(label, state = "") {
  const saveState = $("#save-state");
  const mobileSaveState = $("#mobile-save-state");
  [saveState, mobileSaveState].forEach((element) => {
    if (!element) return;
    element.textContent = label;
    if (state) element.dataset.state = state;
    else delete element.dataset.state;
  });
}
