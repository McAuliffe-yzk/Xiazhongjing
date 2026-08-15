"use strict";

function updateCount() {
  const count = $("#copy-editor").value.replace(/\s/g, "").length;
  $("#copy-count").textContent = `${count} 字`;
}

function projectLengthStatus(text, project = projects[activeProject]) {
  const actual = String(text || "").replace(/\s/g, "").length;
  if (!project || project.target_length_mode !== "manual") {
    return { constrained: false, actual, withinRange: true, min: null, max: null };
  }
  const max = Math.max(300, Math.min(3000, Number(project.target_length) || 1200));
  const tolerance = Math.max(60, Math.round(max * 0.1));
  const min = Math.max(240, max - tolerance);
  return { constrained: true, actual, withinRange: actual >= min && actual <= max, min, max };
}

let narrativeMode = "default";
let generationStartTime = 0;

function setGenerationMode(mode, shouldPersist = true) {
  generationMode = mode === "rewrite" ? "rewrite" : "fresh";
  const project = projects[activeProject];
  if (project) project.generation_mode = generationMode;
  $$('[data-generation-mode]').forEach((button) => {
    button.classList.toggle("active", button.dataset.generationMode === generationMode);
  });
  const generateButton = $("#generate-copy");
  if (generateButton && !generateButton.disabled) {
    generateButton.textContent = generationMode === "rewrite" ? "重写当前稿" : "生成文案稿";
  }
  $$('[data-generate-copy]').forEach((button) => {
    if (!button.disabled) button.textContent = generationMode === "rewrite" ? "重写当前稿" : "生成文案稿";
  });
  updateUrl();
  if (shouldPersist) persistState();
}

function setNarrativeMode(mode, shouldPersist = true) {
  narrativeMode = mode || "default";
  const project = projects[activeProject];
  if (project) project.narrative_mode = narrativeMode;
  $$('[data-narrative-mode]').forEach((button) => {
    button.classList.toggle("active", button.dataset.narrativeMode === narrativeMode);
  });
  if (shouldPersist) {
    syncUrlState("replace");
    persistState();
  }
}

function setBookQuoteStrategy(strategy, shouldPersist = true) {
  bookQuoteStrategy = ["restrained", "standard", "amplified"].includes(strategy) ? strategy : "standard";
  const project = projects[activeProject];
  if (project) project.book_quote_strategy = bookQuoteStrategy;
  $$('[data-book-quote-strategy]').forEach((button) => {
    button.classList.toggle("active", button.dataset.bookQuoteStrategy === bookQuoteStrategy);
  });
  if (shouldPersist) {
    syncUrlState("replace");
    persistState();
  }
}

function syncGenerationLengthControl(project = projects[activeProject]) {
  const control = $("#generation-length-control");
  const modeSelect = $("#generation-length-mode");
  const targetInput = $("#generation-target-length");
  const status = $("#generation-length-status");
  if (!control || !modeSelect || !targetInput || !status || !project) return;
  const mode = project.target_length_mode === "manual" ? "manual" : "auto";
  const target = Number(project.target_length) || 1200;
  modeSelect.value = mode;
  targetInput.value = String(target);
  targetInput.classList.toggle("hidden", mode !== "manual");
  const unitSpan = document.querySelector(".gen-length-unit");
  if (unitSpan) unitSpan.classList.toggle("hidden", mode !== "manual");
  status.textContent = mode === "manual" ? `上限 ${target} 字` : "字数自动";
}

function setGenerationLengthMode(mode, shouldPersist = true) {
  const project = projects[activeProject];
  if (!project) return;
  project.target_length_mode = mode === "manual" ? "manual" : "auto";
  syncGenerationLengthControl(project);
  if (shouldPersist) persistState();
}

function setGenerationTargetLength(value, shouldPersist = true) {
  const project = projects[activeProject];
  if (!project) return;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return;
  project.target_length = Math.max(300, Math.min(3000, Math.round(numeric / 50) * 50));
  syncGenerationLengthControl(project);
  if (shouldPersist) persistState();
}

function commitGenerationLengthFromControls(project = projects[activeProject], shouldPersist = true) {
  if (!project) return;
  const modeSelect = $("#generation-length-mode");
  const targetInput = $("#generation-target-length");
  project.target_length_mode = modeSelect?.value === "manual" ? "manual" : "auto";
  if (project.target_length_mode === "manual") {
    const numeric = Number(targetInput?.value);
    if (Number.isFinite(numeric)) {
      project.target_length = Math.max(300, Math.min(3000, Math.round(numeric / 50) * 50));
    }
  }
  syncGenerationLengthControl(project);
  if (shouldPersist) persistState();
}

function previewGenerationTargetLength(value) {
  const project = projects[activeProject];
  if (!project || project.target_length_mode !== "manual") return;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return;
  const target = Math.max(300, Math.min(3000, Math.round(numeric / 50) * 50));
  $("#generation-length-status").textContent = `上限 ${target} 字`;
}

function resetGenerationTimeline() {
  generationTimeline = generationStageBlueprint.map((stage) => ({
    ...stage,
    status: "waiting",
    latency_ms: null,
    message: ""
  }));
}

function updateTimelineStage(skill, status, payload = {}) {
  let index = generationTimeline.findIndex((stage) => stage.skill === skill);
  if (index < 0) {
    generationTimeline.push({
      skill,
      label: payload.label || skill,
      phase: payload.phase || "",
      status: "waiting",
      latency_ms: null,
      message: ""
    });
    index = generationTimeline.length - 1;
  }
  generationTimeline[index] = {
    ...generationTimeline[index],
    label: payload.label || generationTimeline[index].label,
    phase: payload.phase || generationTimeline[index].phase,
    status,
    latency_ms: payload.trace?.latency_ms ?? payload.latency_ms ?? generationTimeline[index].latency_ms,
    message: payload.message || generationTimeline[index].message,
    audit: payload.audit || generationTimeline[index].audit,
    detail: payload.detail || generationTimeline[index].detail
  };
}

function issueList(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") return [JSON.stringify(value)];
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

function renderGenerationDiagnostics(state, payload = {}) {
  const panel = $("#generation-diagnostics");
  if (!panel) return;
  if (state === "clear") {
    panel.innerHTML = "";
    panel.classList.add("hidden");
    return;
  }
  const audit = payload.audit || payload.details || {};
  const unsupported = issueList(audit.unsupported_claims);
  const critical = issueList(audit.critical_issues);
  const phase = state === "loading" ? "running" : (state === "success" ? "success" : "failed");
  const title = payload.title || (state === "loading" ? "正在执行创作 Skill 链路" : (state === "success" ? "生成链路已通过" : "Skill 链路被拦截"));
  const message = payload.message || "个人风格撰写、抖音 Vlog 优化与书库金句支撑会依次执行。";
  const elapsedMs = Number(payload.elapsed_ms || 0);
  const elapsedLabel = elapsedMs > 0 ? `${(elapsedMs / 1000).toFixed(elapsedMs >= 10000 ? 1 : 2)}s` : "";
  const timeline = payload.timeline || generationTimeline;
  const detail = payload.detail || payload.details || {};
  const nextAction = detail.next_action || audit.next_action || "";
  const bookSupport = payload.book_support && typeof payload.book_support === "object"
    ? payload.book_support
    : null;
  const stageOutline = Array.isArray(payload.stage_outline) ? payload.stage_outline.slice(0, 6) : [];
  const publishPack = payload.douyin_publish_pack && typeof payload.douyin_publish_pack === "object"
    ? payload.douyin_publish_pack
    : null;
  const supports = Array.isArray(bookSupport?.supports)
    ? bookSupport.supports.filter((item) => item && item.mode === "exact_quote").slice(0, 3)
    : [];
  const bookSupportStatus = String(bookSupport?.status || "");
  const bookSupportTitle = supports.length
    ? `已同步加入 ${supports.length} 处书库金句`
    : (bookSupportStatus === "disabled" || bookSupportStatus === "off"
      ? "本次未启用书库金句"
      : "本次没有强行植入书库内容");
  const bookSupportReason = String(bookSupport?.reason || "").trim();
  panel.innerHTML = `
    <div class="diagnostic-head">
      <span class="diagnostic-state ${phase}"></span>
      <div>
        <strong>${escapeHtml(title)}</strong>
        <p>${escapeHtml(message)}</p>
      </div>
      ${elapsedLabel ? `<span class="diagnostic-runtime">耗时 ${escapeHtml(elapsedLabel)}</span>` : ""}
    </div>
    ${timeline.length ? `
      <div class="skill-timeline">
        ${timeline.map((item) => `
          <div class="skill-node ${escapeHtml(item.status || "waiting")}">
            <span class="skill-node-dot"></span>
            <div>
              <strong>${escapeHtml(item.label || item.skill)}</strong>
              <small>${escapeHtml(item.phase || "")}</small>
              ${item.message ? `<p>${escapeHtml(item.message)}</p>` : ""}
            </div>
          </div>
        `).join("")}
      </div>
    ` : ""}
    ${unsupported.length || critical.length ? `
      <div class="diagnostic-issues">
        ${critical.slice(0, 4).map((item) => `<p><b>审校</b>${escapeHtml(item)}</p>`).join("")}
        ${unsupported.slice(0, 6).map((item) => `<p><b>未支持</b>${escapeHtml(typeof item === "string" ? item : JSON.stringify(item))}</p>`).join("")}
      </div>
    ` : ""}
    ${bookSupport ? `
      <section class="generation-book-support" aria-label="本次生成的书库支撑">
        <div class="generation-book-support-head">
          <div>
            <span class="eyebrow">BOOK SUPPORT</span>
            <strong>${escapeHtml(bookSupportTitle)}</strong>
          </div>
          <span class="generation-book-support-count">${escapeHtml(activeBooks.length ? `${activeBooks.length} 本已选` : "未选择书籍")}</span>
        </div>
        ${supports.length ? `
          <div class="generation-book-support-list">
            ${supports.map((item) => {
              const source = `${item.attribution || "原文"} · ${item.book || "书库"}`;
              return `
                <article class="generation-book-support-item quote">
                  <div class="generation-book-support-item-head">
                    <span class="generation-book-support-mode">原文金句</span>
                    <strong>${escapeHtml(item.book || "书库素材")}</strong>
                  </div>
                  <p>${escapeHtml(item.text || "")}</p>
                  <small>${escapeHtml(source)}${item.source_title ? ` · ${escapeHtml(item.source_title)}` : ""}</small>
                  ${item.reason ? `<span class="generation-book-support-reason">${escapeHtml(item.reason)}</span>` : ""}
                  ${/^https?:\/\//.test(String(item.source_url || "")) ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">查看来源</a>` : ""}
                </article>
              `;
            }).join("")}
          </div>
        ` : `<p class="generation-book-support-empty">${escapeHtml(bookSupportReason || "当前文案没有自然的书库支撑位置，已保留你的个人表达。")}</p>`}
      </section>
    ` : ""}
    ${stageOutline.length ? `
      <section class="generation-stage-outline" aria-label="六段创作框架">
        <div class="generation-book-support-head">
          <div>
            <span class="eyebrow">CREATOR FRAMEWORK</span>
            <strong>个人六段创作框架</strong>
          </div>
          <span class="generation-book-support-count">v1</span>
        </div>
        <div class="generation-stage-outline-list">
          ${stageOutline.map((item, index) => `
            <article>
              <b>${String(index + 1).padStart(2, "0")}</b>
              <div>
                <strong>${escapeHtml(item.label || item.stage || "阶段")}</strong>
                <p>${escapeHtml(item.evidence || item.purpose || "")}</p>
              </div>
            </article>
          `).join("")}
        </div>
      </section>
    ` : ""}
    ${publishPack ? `
      <section class="generation-publish-pack" aria-label="抖音发布适配包">
        <div class="generation-book-support-head">
          <div>
            <span class="eyebrow">DOUYIN PACK</span>
            <strong>${publishPack.status === "ready" ? "发布前适配包已生成" : "发布适配包暂未生成"}</strong>
          </div>
          ${publishPack.scores ? `<span class="generation-book-support-count">口播 ${escapeHtml(String(publishPack.scores.spoken_rhythm || "—"))}/10</span>` : ""}
        </div>
        ${publishPack.status === "ready" ? `
          <div class="generation-publish-grid">
            <div>
              <strong>标题候选</strong>
              ${(publishPack.titles || []).slice(0, 3).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无标题候选</p>"}
            </div>
            <div>
              <strong>封面钩子</strong>
              ${(publishPack.cover_hooks || []).slice(0, 2).map((item) => `<p>${escapeHtml(item)}</p>`).join("") || "<p>暂无封面钩子</p>"}
            </div>
            <div>
              <strong>评论区问题</strong>
              <p>${escapeHtml(publishPack.comment_question || "暂无")}</p>
            </div>
            <div>
              <strong>口播提示</strong>
              ${(publishPack.spoken_notes || []).slice(0, 3).map((item) => `<p><b>${escapeHtml(item.location || "提示")}</b>${escapeHtml(item.note || "")}</p>`).join("") || "<p>暂无口播提示</p>"}
            </div>
          </div>
        ` : `<p class="generation-book-support-empty">${escapeHtml(publishPack.reason || "正文已生成，可稍后重新生成发布包。")}</p>`}
      </section>
    ` : ""}
    ${nextAction ? `<div class="diagnostic-next">${escapeHtml(nextAction)}</div>` : ""}
    ${state === "failed" && failedGenerationId ? `<button class="diagnostic-retry" data-retry-generation="${escapeHtml(failedGenerationId)}" type="button">从失败节点重试</button>` : ""}
  `;
  panel.classList.remove("hidden");
}

function switchPage(page, options = {}) {
  const requestedPage = page === "dialogue" ? "mirror" : page;
  const safePage = ["onboarding", "workspace", "editor", "inspiration", "diary", "distill", "library", "mirror", "book-person", "assets", "covers", "profile", "dna", "settings"].includes(requestedPage) ? requestedPage : "workspace";
  const pageChanged = activePage !== safePage;
  activePage = safePage;
  if (pageChanged && (safePage === "mirror" || safePage === "book-person")) {
    dialogueContextOpen = false;
  }
  if (safePage === "mirror") dialogueMode = "mirror";
  if (safePage === "book-person") {
    dialogueMode = "book";
    if (activeDialoguePersona === "mirror-self") {
      activeDialoguePersona = dialoguePersonas.find((item) => item.type === "book")?.id || "";
    }
  }
  document.body.dataset.activePage = safePage;
  const pageLabels = {
    onboarding: "开始使用",
    workspace: "创作台",
    editor: "创作台",
    inspiration: "灵感匣签",
    diary: "创作档案",
    distill: "内容蒸馏",
    library: "精神书库",
    mirror: "镜中人",
    "book-person": "书中人",
    assets: "资产库",
    covers: "封面图",
    profile: "个人信息",
    dna: "DNA 试剂",
    settings: "系统设置"
  };
  const pageTitles = {
    onboarding: "个人系统就绪检查",
    workspace: "项目管理",
    editor: projects[activeProject].title,
    inspiration: "每日一签",
    diary: "日记本",
    distill: "个人风格",
    library: "书库管理",
    mirror: "和自己对话",
    "book-person": "和书中人物对话",
    assets: "对话沉淀资产",
    covers: "Image 2.0 创作",
    profile: "身份资产",
    dna: "外部博主风味",
    settings: "配置与 Skills"
  };
  const panelKey = safePage === "book-person" ? "mirror" : safePage;
  $$(".app-page").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.pagePanel !== panelKey);
    panel.classList.toggle("active", panel.dataset.pagePanel === panelKey);
  });
  $$(sidebarNavSelector).forEach((link) => {
    const isActive = link.dataset.page === safePage;
    const destination = new URL(window.location.href);
    destination.searchParams.set("page", link.dataset.page);
    if (link.dataset.page === "onboarding" || link.dataset.page === "inspiration" || link.dataset.page === "mirror" || link.dataset.page === "book-person" || link.dataset.page === "diary" || link.dataset.page === "assets" || link.dataset.page === "covers" || link.dataset.page === "profile" || link.dataset.page === "dna" || link.dataset.page === "settings") {
      destination.searchParams.delete("project");
    } else {
      destination.searchParams.set("project", activeProject);
    }
    destination.searchParams.delete("tab");
    link.href = `${destination.pathname}${destination.search}`;
    link.classList.toggle("active", isActive);
    if (isActive) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const mobileMore = $(".mobile-nav-more");
  if (mobileMore) {
    mobileMore.classList.toggle("active", ["onboarding", "mirror", "book-person", "diary", "assets", "covers", "profile", "dna", "settings"].includes(safePage));
    mobileMore.removeAttribute("open");
  }
  $("#breadcrumb-section").textContent = pageLabels[safePage];
  $("#breadcrumb-title").textContent = pageTitles[safePage];
  $("#save-version").classList.toggle("hidden", safePage !== "editor");
  $("#publish-diary").classList.toggle("hidden", safePage !== "editor");
  $("#generation-mode-control").classList.toggle("hidden", safePage !== "editor");
  $("#generation-length-control").classList.toggle("hidden", safePage !== "editor");
  $("#save-state").classList.toggle("hidden", safePage !== "editor");
  $("#dialogue-context-toggle").classList.toggle("hidden", !(safePage === "mirror" || safePage === "book-person" || safePage === "assets"));
  if (safePage !== "library") {
    renderBookDiagnostics("clear");
    clearResearch();
    closeBookLibraryViewer();
  }
  syncGenerationLengthControl(projects[activeProject]);
  updateWorkspaceSummary();
  if (safePage === "diary") renderDiary();
  if (safePage === "inspiration" && typeof renderInspirationPage === "function") renderInspirationPage();
  if (safePage === "library") loadBookNotesState();
  if (safePage === "library") loadLibraryPersonas();
  if (safePage === "onboarding") loadOnboardingStatus();
  if (safePage === "assets") {
    renderDialogueContext();
    loadDialogueAssets();
  }
  if (safePage === "dna" && typeof loadDnaReagents === "function") loadDnaReagents();
  if (safePage === "settings" && typeof loadSettingsPage === "function") loadSettingsPage();
  if (safePage === "covers" && typeof loadCoversPage === "function") loadCoversPage();
  if (safePage === "profile" && typeof loadCreatorProfilePage === "function") loadCreatorProfilePage();
  if (pageChanged) {
    window.scrollTo({ top: 0, behavior: options.instant ? "auto" : "smooth" });
  }
  syncUrlState(options.historyMode || (pageChanged ? "push" : "replace"));
  if (options.persist !== false) persistState();
  if (safePage === "mirror" || safePage === "book-person") {
    renderDialogueAll();
    loadDialoguePersonas();
    loadDialogueSessions();
    loadDialogueAssets();
  }
}

function saveVersionSnapshot(note = "保存当前文案稿") {
  const project = projects[activeProject];
  ensureProjectState(project);
  const projectVersions = currentVersions();
  project.copy = $("#copy-editor").value;
  const nextVersion = `v0.${projectVersions.length + 1}`;
  projectVersions.unshift({
    label: nextVersion,
    time: "刚刚",
    note,
    copy: project.copy,
    locked_paragraphs: [...(project.locked_paragraphs || [])]
  });
  versions = projectVersions;
  project.version = nextVersion;
  $("#project-version").textContent = nextVersion;
  renderVersions();
  return nextVersion;
}

function projectMaterialsSnapshot() {
  const project = projects[activeProject];
  ensureProjectMaterials(project);
  ensureMaterialItems(project);
  syncLegacyMaterialFields(project);
  return {
    ...project.materials,
    theme: project.materials.theme || project.title,
    material_items: project.material_items
  };
}



function paragraphBlocks(text) {
  return String(text || "").split(/\n{2,}/).map((block) => block.trim()).filter(Boolean);
}

function selectedParagraphs(editor) {
  const text = editor.value;
  const start = editor.selectionStart ?? 0;
  const end = editor.selectionEnd ?? start;
  const before = text.slice(0, start);
  const after = text.slice(end);
  const blockStart = Math.max(0, before.lastIndexOf("\n\n") + 2);
  const blockEndIndex = after.indexOf("\n\n");
  const blockEnd = blockEndIndex < 0 ? text.length : end + blockEndIndex;
  return paragraphBlocks(text.slice(blockStart, blockEnd));
}

function renderLockedParagraphs() {
  const project = projects[activeProject];
  if (!project) return;
  const copy = $("#copy-editor").value;
  project.locked_paragraphs = (project.locked_paragraphs || []).filter((paragraph) => paragraph && copy.includes(paragraph));
  $("#locked-count").textContent = `${project.locked_paragraphs.length} 段已锁定`;
  $("#lock-paragraph").classList.toggle("active", selectedParagraphs($("#copy-editor")).some((paragraph) => project.locked_paragraphs.includes(paragraph)));
}

function toggleParagraphLock() {
  const project = projects[activeProject];
  const editor = $("#copy-editor");
  const targets = selectedParagraphs(editor);
  if (!targets.length) {
    showToast("将光标放在需要保护的段落内");
    return;
  }
  const allLocked = targets.every((paragraph) => project.locked_paragraphs.includes(paragraph));
  if (allLocked) {
    project.locked_paragraphs = project.locked_paragraphs.filter((paragraph) => !targets.includes(paragraph));
    showToast("已解除段落锁定");
  } else {
    project.locked_paragraphs = [...new Set([...project.locked_paragraphs, ...targets])];
    showToast("已锁定段落，AI 编辑和改写不得改动它");
  }
  renderLockedParagraphs();
  persistState();
}

function selectionTouchesLocked(selection) {
  const project = projects[activeProject];
  if (!selection || !project?.locked_paragraphs?.length) return false;
  const selected = $("#copy-editor").value.slice(selection.start, selection.end);
  return project.locked_paragraphs.some((paragraph) => selected.includes(paragraph) || paragraph.includes(selected));
}

function replaceOpening(copy, opening) {
  const trimmedOpening = opening.trim();
  if (!trimmedOpening) return copy;
  const blocks = copy.split(/\n{2,}/);
  if (blocks.length <= 1) return trimmedOpening;
  return `${trimmedOpening}\n\n${blocks.slice(1).join("\n\n")}`;
}

function renderEditDiagnostics({ discardedCount = 0, message = "", detail = null } = {}) {
  const panel = $("#edit-preview-diagnostics");
  const detailLines = issueList(detail?.details || detail?.critical_issues || detail?.unsupported_claims || detail?.message || "");
  if (!discardedCount && !message && !detailLines.length) {
    panel.innerHTML = "";
    panel.classList.add("hidden");
    return;
  }
  panel.innerHTML = `
    ${message ? `<p>${escapeHtml(message)}</p>` : ""}
    ${discardedCount ? `<p><b>${discardedCount}</b> 个候选未通过事实审校</p>` : ""}
    ${detailLines.length ? `<div class="edit-diagnostic-list">${detailLines.slice(0, 5).map((item) => `<span>${escapeHtml(typeof item === "string" ? item : JSON.stringify(item))}</span>`).join("")}</div>` : ""}
  `;
  panel.classList.remove("hidden");
}

function setEditPreviewText(text) {
  $("#edit-preview-text").textContent = String(text || "");
}

function getEditPreviewText() {
  return $("#edit-preview-text").innerText.replace(/\u00a0/g, " ").trim();
}

function renderEditChangeSummary(changes = [], metrics = {}) {
  const panel = $("#edit-change-summary");
  const items = Array.isArray(changes)
    ? changes.filter((item) => item?.point && item?.location && item?.reason)
    : [];
  if (!items.length) {
    panel.innerHTML = "";
    panel.classList.add("hidden");
    return;
  }
  const ratio = Number(metrics?.changed_ratio);
  const patchCount = Number(metrics?.valid_patch_count);
  const metricText = Number.isFinite(patchCount) && patchCount > 0
    ? `${patchCount} 段结构重写`
    : (Number.isFinite(ratio) && ratio > 0
      ? `有效变化 ${Math.round(ratio * 100)}%`
      : `${items.length} 处关键调整`);
  panel.innerHTML = `
    <header class="edit-change-head">
      <div>
        <span class="eyebrow">本次优化</span>
        <strong>${items.length} 处</strong>
      </div>
      <span>${metricText}</span>
    </header>
    <div class="edit-change-columns" aria-hidden="true">
      <span>核心优化点</span>
      <span>优化位置</span>
      <span>简述原因</span>
    </div>
    <div class="edit-change-list">
      ${items.map((item) => `
        <article class="edit-change-row">
          <strong>${escapeHtml(item.point)}</strong>
          <span>${escapeHtml(item.location)}</span>
          <p>${escapeHtml(item.reason)}</p>
        </article>
      `).join("")}
    </div>
  `;
  panel.classList.remove("hidden");
}

function diffOriginalHtml(originalText, nextText) {
  const nextBlocks = new Set(paragraphBlocks(nextText));
  return paragraphBlocks(originalText).map((block) => `<p class="${nextBlocks.has(block) ? "diff-same" : "diff-removed"}">${escapeHtml(block)}</p>`).join("");
}

function openEditPreview({ title, note, originalText, text, options = [], changes = [], metrics = {}, trace = [], audit = null, discardedCount = 0, apply, candidate = (nextText) => nextText, acceptLabel = "接受修改", showDiff = false, failed = false, failureDetail = null }) {
  pendingEdit = failed ? null : { title, text, originalText, changes, metrics, apply, candidate };
  $("#edit-preview-title").textContent = title;
  $("#edit-preview-note").textContent = note;
  if (showDiff) {
    $("#edit-original-text").innerHTML = diffOriginalHtml(originalText || "", text || "");
  } else {
    $("#edit-original-text").textContent = originalText || "";
  }
  $("#edit-original-count").textContent = `${(originalText || "").replace(/\s/g, "").length} 字`;
  setEditPreviewText(text);
  $("#edit-preview-count").textContent = `${String(text || "").replace(/\s/g, "").length} 字`;
  renderEditDiagnostics({ trace, audit, discardedCount, message: failed ? "本次 AI 编辑没有通过有效改写门禁，正文未被修改。" : "", detail: failureDetail });
  renderEditChangeSummary(changes, metrics);
  $("#accept-edit-preview").textContent = acceptLabel;
  $("#accept-edit-preview").classList.toggle("hidden", failed);
  $("#accept-edit-preview").disabled = failed;
  $("#cancel-edit-preview").textContent = failed ? "关闭" : "取消";
  $("#edit-preview-status").textContent = failed ? "未应用任何修改" : "预览不会直接覆盖正文";
  $("#edit-preview-text").setAttribute("contenteditable", failed ? "false" : "true");
  $("#edit-preview").classList.toggle("edit-preview-failed", failed);
  const optionsPanel = $("#opening-options");
  if (options.length) {
    optionsPanel.classList.remove("hidden");
    optionsPanel.innerHTML = options.map((option, index) => `
      <button class="opening-option ${index === 0 ? "selected" : ""}" data-opening-index="${index}" type="button">
        <strong>${escapeHtml(option.label || `开头 ${index + 1}`)}</strong>
        <span>${escapeHtml((option.text || "").slice(0, 92))}</span>
      </button>
    `).join("");
    $$(".opening-option").forEach((button) => {
      button.addEventListener("click", () => {
        const option = options[Number(button.dataset.openingIndex)];
        if (!option) return;
        $$(".opening-option").forEach((item) => item.classList.remove("selected"));
        button.classList.add("selected");
        setEditPreviewText(option.text);
        $("#edit-preview-count").textContent = `${option.text.replace(/\s/g, "").length} 字`;
        pendingEdit.text = option.text;
        pendingEdit.changes = option.changes || [];
        pendingEdit.metrics = option.metrics || {};
        renderEditChangeSummary(pendingEdit.changes, pendingEdit.metrics);
      });
    });
  } else {
    optionsPanel.classList.add("hidden");
    optionsPanel.innerHTML = "";
  }
  const preview = $("#edit-preview");
  preview.classList.remove("hidden");
  preview.setAttribute("aria-hidden", "false");
  $(".edit-preview-body").scrollTop = 0;
  overlayManager.open({
    id: 'edit-preview',
    element: preview,
    lockMode: 'modal',
    onRequestClose: closeEditPreview
  });
  window.requestAnimationFrame(() => $("#close-edit-preview").focus({ preventScroll: true }));
}

function openEditFailure({ title, message, originalText, detail }) {
  openEditPreview({
    title,
    note: message,
    originalText,
    text: "未生成可接受的有效改写。",
    failed: true,
    failureDetail: detail,
    acceptLabel: "不可应用",
    apply: null
  });
}

function closeEditPreview() {
  pendingEdit = null;
  overlayManager.close('edit-preview');
  $("#edit-preview").classList.add("hidden");
  $("#edit-preview").setAttribute("aria-hidden", "true");
  $("#accept-edit-preview").textContent = "接受修改";
  $("#accept-edit-preview").classList.remove("hidden");
  $("#accept-edit-preview").disabled = false;
  $("#cancel-edit-preview").textContent = "取消";
  $("#edit-preview-text").setAttribute("contenteditable", "true");
  $("#edit-preview").classList.remove("edit-preview-failed");
}

async function requestAiEdit(action, button, selection = null) {
  const editor = $("#copy-editor");
  commitGenerationLengthFromControls(projects[activeProject]);
  const fullCopy = editor.value;
  if (!fullCopy.trim()) {
    showToast("请先生成或填写一版文案");
    return;
  }
  const selectedText = selection ? fullCopy.slice(selection.start, selection.end) : "";
  if (selection && !selectedText.trim()) {
    showToast("请先选中一段要改写的文案");
    return;
  }
  if (selectionTouchesLocked(selection)) {
    showToast("选中范围包含锁定段落，请先解除锁定");
    return;
  }

  const labels = {
    shorten: "全文收束",
    "more-personal": "更像我",
    "rebuild-opening": "重写开头",
    "selection-polish": "局部改写"
  };
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "生成中";
  $("#save-state").textContent = "正在生成 AI 编辑预览";
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/edit-copy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        command: selection ? $("#selection-command").value : "",
        full_copy: fullCopy,
        selected_text: selectedText,
        selection_start: selection?.start,
        selection_end: selection?.end,
        materials: projectMaterialsSnapshot(),
        locked_paragraphs: projects[activeProject].locked_paragraphs || [],
        target_length_mode: projects[activeProject].target_length_mode || "auto",
        target_length: projects[activeProject].target_length || 1200,
        active_dna_ids: projects[activeProject].active_dna_ids || []
      })
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = apiErrorPayload(data);
      openEditFailure({
        title: `${labels[action]}未应用`,
        message: detail.message || detail.code || "AI 编辑失败",
        originalText: selection ? selectedText : fullCopy,
        detail
      });
      throw new Error(detail.message || detail.code || "AI 编辑失败");
    }

    if (data.mode === "opening_options") {
      const openingOriginal = fullCopy.split(/\n{2,}/)[0] || fullCopy;
      const options = Array.isArray(data.options)
        ? data.options.filter((option) => {
          const text = String(option?.text || "").trim();
          return text && materialSignature(text) !== materialSignature(openingOriginal);
        })
        : [];
      const firstOption = options[0];
      if (data.metrics?.meaningful === false || !firstOption) {
        const detail = data.audit || data.metrics || { message: "模型返回的开头与原文没有形成有效差异。" };
        openEditFailure({
          title: `${labels[action]}未应用`,
          message: "重写开头没有产生有效变化，已拦截。",
          originalText: openingOriginal,
          detail
        });
        throw new Error("重写开头没有产生有效变化");
      }
      openEditPreview({
        title: labels[action],
        note: "选择一个开头，接受后只替换当前文案第一段。",
        originalText: openingOriginal,
        text: firstOption.text,
        options,
        changes: firstOption.changes || [],
        metrics: firstOption.metrics || {},
        trace: data.trace,
        discardedCount: data.discarded_count || 0,
        apply: (nextText) => {
          editor.value = replaceOpening(editor.value, nextText);
        },
        candidate: (nextText) => replaceOpening(fullCopy, nextText)
      });
      $("#save-state").textContent = "AI 编辑预览待确认";
      showToast("已生成 AI 编辑预览");
      return;
    }

    const previewText = data.text || "";
    const comparisonSource = selection ? selectedText : fullCopy;
    if (!String(previewText || "").trim() || data.metrics?.meaningful === false || materialSignature(previewText) === materialSignature(comparisonSource)) {
      const detail = data.audit || data.metrics || { message: "模型返回结果与原文高度一致。" };
      openEditFailure({
        title: `${labels[action]}未应用`,
        message: "AI 返回结果没有产生有效改写，已拦截，正文未被覆盖。",
        originalText: comparisonSource,
        detail
      });
      throw new Error("AI 编辑没有产生有效改写");
    }
    openEditPreview({
      title: labels[action],
      note: selection ? "接受后只替换你选中的这段文字。" : "接受后会替换当前全文，并自动保存编辑前备份。",
      originalText: selection ? selectedText : fullCopy,
      text: previewText,
      changes: data.changes || [],
      metrics: data.metrics || {},
      trace: data.trace,
      audit: data.audit,
      apply: (nextText) => {
        if (selection) {
          editor.value = editor.value.slice(0, selection.start) + nextText + editor.value.slice(selection.end);
          editor.focus();
          editor.setSelectionRange(selection.start, selection.start + nextText.length);
        } else {
          editor.value = nextText;
        }
      },
      candidate: (nextText) => selection
        ? fullCopy.slice(0, selection.start) + nextText + fullCopy.slice(selection.end)
        : nextText
    });
    $("#save-state").textContent = "AI 编辑预览待确认";
    showToast("已生成 AI 编辑预览");
  } catch (error) {
    $("#save-state").textContent = "AI 编辑失败";
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function consumeSseResponse(response, handlers = {}) {
  if (!response.body || !window.TextDecoder) {
    throw new Error("当前浏览器不支持流式读取");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalResult = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const eventLine = chunk.split("\n").find((line) => line.startsWith("event:"));
      const dataLine = chunk.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const eventName = eventLine ? eventLine.replace("event:", "").trim() : "message";
      const data = JSON.parse(dataLine.replace("data:", "").trim());
      if (eventName === "final") {
        finalResult = data.result;
      }
      if (handlers[eventName]) {
        handlers[eventName](data);
      }
    }
  }
  return finalResult;
}

function applyGeneratedCopy(data) {
  const project = projects[activeProject];
  if (data.length?.mode === "manual" && data.length?.within_range === false) {
    throw new Error(`生成结果为 ${data.length.actual} 字，超过 ${data.length.max} 字上限，已阻止覆盖编辑器`);
  }
  $("#copy-editor").value = data.copy;
  project.copy = data.copy;
  project.materials = projectMaterialsSnapshot();
  project.selected_books = validBookIds(activeBooks);
  project.generation_id = data.generation_id || "";
  project.last_style_version = data.style_version || skillStatus?.style?.published_version || "";
  project.version = project.version === "草稿" ? "v0.1" : project.version;
  $("#project-version").textContent = project.version;
  const supports = Array.isArray(data.book_support?.supports) ? data.book_support.supports : [];
  $("#selected-book-count").textContent = supports.length
    ? `已同步 ${supports.length} 处`
    : (project.selected_books.length ? `${project.selected_books.length} 本已选` : "未选择");
  const lengthInfo = data.length || {};
  $("#generation-length-status").textContent = lengthInfo.mode === "manual"
    ? `上限 ${lengthInfo.max || project.target_length} 字 · 实际 ${lengthInfo.actual || String(data.copy || "").replace(/\s/g, "").length} 字`
    : `实际 ${lengthInfo.actual || String(data.copy || "").replace(/\s/g, "").length} 字 · 自动`;
  updateCount();
  applyMaterialCoverage(data.material_coverage || []);
  renderLockedParagraphs();
  renderProjects();
  $("#save-state").textContent = `已由 ${data.model} 生成`;
  renderGenerationDiagnostics("success", {
    message: `个人风格撰写与抖音 Vlog 优化已完成，并同步处理书库金句${data.resumed_stages?.length ? `，恢复了 ${data.resumed_stages.length} 个检查点` : ""}。`,
    elapsed_ms: generationStartTime ? Math.round((globalThis.performance?.now ? globalThis.performance.now() : Date.now()) - generationStartTime) : 0,
    trace: data.trace,
    audit: data.audit,
    timeline: generationTimeline,
    book_support: data.book_support || null,
    stage_outline: data.stage_outline || [],
    douyin_publish_pack: data.douyin_publish_pack || null
  });
}

async function generateCopy(retryId = "") {
  const project = projects[activeProject];
  commitGenerationLengthFromControls(project);
  const editorCopy = $("#copy-editor").value;
  if (generationMode === "rewrite" && !editorCopy.trim()) {
    showToast("当前文案为空，无法执行重写");
    return;
  }
  const buttons = [$("#generate-copy"), ...$$('[data-generate-copy]')].filter(Boolean);
  const originalTexts = new Map(buttons.map((button) => [button, button.textContent]));
  buttons.forEach((button) => {
    button.disabled = true;
    button.textContent = "生成中…";
  });
  generationStartTime = globalThis.performance?.now ? globalThis.performance.now() : Date.now();
  $("#save-state").textContent = "正在调用 DeepSeek";
  resetGenerationTimeline();
  renderGenerationDiagnostics("loading", {
    message: generationMode === "rewrite"
      ? "正在仅基于当前文案与个人 DNA Skill 优化，项目原始素材不会参与。"
      : "正在把素材发展为个人风格初稿，再做抖音 Vlog 优化与书库金句支撑。"
  });

  try {
    project.materials = projectMaterialsSnapshot();
    activeBooks = validBookIds(project.selected_books);
    const response = await XZJApi.request("/api/xiangzhongjing/generate-copy-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: activeProject,
        generation_id: retryId,
        materials: generationMode === "rewrite" ? {} : project.materials,
        generation_mode: generationMode,
        narrative_mode: narrativeMode,
        source_copy: generationMode === "rewrite" ? editorCopy : "",
        selected_books: project.selected_books,
        locked_paragraphs: project.locked_paragraphs || [],
        book_support_mode: "integrated",
        book_quote_strategy: project.book_quote_strategy || bookQuoteStrategy || "standard",
        creator_framework_version: "yzk_v1",
        target_length_mode: project.target_length_mode || "auto",
        target_length: project.target_length || 1200,
        active_dna_ids: project.active_dna_ids || []
      })
    });
    if (!response.ok) {
      const data = await response.json();
      const detail = apiErrorPayload(data);
      renderGenerationDiagnostics("failed", {
        message: detail.message || "生成请求失败",
        details: detail.details || detail
      });
      throw new Error(detail.message || detail.code || "生成请求失败");
    }
    const data = await consumeSseResponse(response, {
      generation_created(event) {
        failedGenerationId = event.generation_id || retryId || "";
        project.generation_id = failedGenerationId;
      },
      stage_started(event) {
        updateTimelineStage(event.skill, "running", event);
        renderGenerationDiagnostics("loading", { message: event.message || "Skill 正在执行。" });
      },
      stage_finished(event) {
        updateTimelineStage(event.skill, event.passed === false ? "warning" : "success", event);
        renderGenerationDiagnostics("loading", {
          message: event.message || "Skill 已完成，继续进入下一步。",
          audit: event.audit || null,
          book_support: event.book_support || null
        });
      },
      stage_failed(event) {
        failedGenerationId = event.generation_id || failedGenerationId;
        const detail = event.detail || {};
        updateTimelineStage(event.skill || "skill-chain", "failed", {
          ...event,
          message: detail.message || event.message || "Skill 链路被拦截。"
        });
        renderGenerationDiagnostics("failed", {
          title: event.label ? `${event.label}被拦截` : "Skill 链路被拦截",
          message: detail.message || "生成请求失败",
          details: detail.details || detail,
          detail
        });
      }
    });
    if (!data?.copy) {
      throw new Error("生成链路没有返回可用文案");
    }
    applyGeneratedCopy(data);
    failedGenerationId = "";
    await persistState("now");
    const supportStatus = String(data.book_support?.status || "");
    showToast(supportStatus === "none"
      ? "文案稿已生成，本次没有合适的本地原文金句"
      : "已完成个人风格撰写、抖音优化和本地书库金句支撑");
  } catch (error) {
    $("#save-state").textContent = "生成失败";
    showToast(error.message);
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
      button.textContent = originalTexts.get(button) || (generationMode === "rewrite" ? "重写当前稿" : "生成文案稿");
    });
  }
}

function saveVersion() {
  const nextVersion = saveVersionSnapshot("保存当前文案稿");
  $("#save-state").textContent = "已保存";
  renderProjects();
  persistState("now");
  showToast(`已保存 ${nextVersion}`);
}

function renderVersions() {
  const projectVersions = currentVersions();
  $("#version-count").textContent = `${projectVersions.length} 个版本`;
  if (!projectVersions.length) {
    $("#version-list").innerHTML = `<div class="version-empty">这条稿件还没有保存过版本。</div>`;
    return;
  }
  $("#version-list").innerHTML = projectVersions.map((version, index) => `
    <article class="version-item ${index === 0 ? "current" : ""}">
      <span class="version-icon">${index === 0 ? "●" : "○"}</span>
      <span>
        <strong>${version.label}${index === 0 ? " 当前版本" : ""}</strong>
        <small>${version.note}</small>
      </span>
      <span class="version-actions">
        <time>${version.time}</time>
        <button data-version-action="diff" data-index="${index}" type="button">对比</button>
        <button data-version-action="restore" data-index="${index}" type="button">恢复</button>
      </span>
    </article>
  `).join("");
  $$("[data-version-action]").forEach((action) => {
    action.addEventListener("click", (event) => {
      event.stopPropagation();
      const version = currentVersions()[Number(action.dataset.index)];
      if (!version) return;
      if (action.dataset.versionAction === "restore") {
        if (!version.copy) {
          showToast("这个示例版本没有保存正文快照");
          return;
        }
        $("#copy-editor").value = version.copy;
        projects[activeProject].copy = version.copy;
        invalidateMaterialCoverage(projects[activeProject]);
        projects[activeProject].locked_paragraphs = [...(version.locked_paragraphs || [])];
        updateCount();
        renderLockedParagraphs();
        persistState();
        showToast(`已恢复 ${version.label}`);
      } else {
        if (!version.copy) {
          showToast("这个示例版本没有保存正文快照");
          return;
        }
        openEditPreview({
          title: `${version.label} 与当前稿`,
          note: "左侧标出已被改动的旧段落，右侧是当前文案。恢复前会保留当前版本。",
          originalText: version.copy,
          text: $("#copy-editor").value,
          showDiff: true,
          acceptLabel: `恢复 ${version.label}`,
          apply: () => {
            $("#copy-editor").value = version.copy;
            projects[activeProject].locked_paragraphs = [...(version.locked_paragraphs || [])];
          }
        });
      }
    });
  });
}

function switchEditorTab(tab, options = {}) {
  const safeTab = ["copy", "materials", "versions"].includes(tab) ? tab : "copy";
  activeEditorTab = safeTab;
  $$(".editor-tab").forEach((button) => {
    const isActive = button.dataset.editorTab === safeTab;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
    button.tabIndex = isActive ? 0 : -1;
  });
  $$(".editor-panel").forEach((panel) => {
    const isActive = panel.id === `editor-${safeTab}`;
    panel.classList.toggle("hidden", !isActive);
  });
  $("#page-editor")?.classList.toggle("materials-active", safeTab === "materials");
  if (safeTab === "materials") {
    window.requestAnimationFrame(() => {
      $$("#editor-materials [data-material-text]").forEach(resizeMaterialTextarea);
    });
  }
  if (activePage === "editor") syncUrlState(options.historyMode || "push");
}
