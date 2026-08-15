"use strict";

function formatDiaryDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value || "刚刚");
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function sortedDiaryEntries() {
  return [...diaryEntries].sort((a, b) => String(a.published_at || "").localeCompare(String(b.published_at || "")));
}

function renderDiary() {
  const entries = sortedDiaryEntries();
  const page = Math.max(1, Math.min(100, activeDiaryPage));
  const entry = entries[page - 1] || null;
  activeDiaryPage = page;
  $("#diary-entry-count").textContent = `${entries.length} / 100`;
  $("#diary-page-number").textContent = String(page).padStart(2, "0");
  $("#diary-page-title").textContent = entry?.project_title || (page > entries.length ? "这一页还在等下一次发布" : "还没有发布记录");
  $("#diary-page-date").textContent = entry ? formatDiaryDate(entry.published_at) : (entries.length ? "空白页" : "等待第一篇作品");
  $("#diary-page-status").textContent = entry ? `第 ${page} 页 · 已发布` : `第 ${page} 页 · 空白`;
  $("#diary-prev").disabled = page <= 1;
  $("#diary-next").disabled = page >= 100;
  $("#delete-diary-entry").classList.toggle("hidden", !entry);
  $("#delete-diary-entry").disabled = !entry;
  if (!entry) {
    $("#diary-page-body").innerHTML = `
      <div class="diary-empty">
        <span class="diary-empty-mark">${page > entries.length ? "…" : "J"}</span>
        <strong>${page > entries.length ? "这一页留给下一次正式发布。" : "把第一篇正式发布的文案，写进这里。"}</strong>
        <p>${page > entries.length ? "日记本会按已发布时间继续向后装订，不会覆盖前面的作品。" : "回到当前项目，点击「发布到日记」，它会成为日记本的第 01 页。"}</p>
        <button class="top-action primary" data-diary-action="workspace" type="button">返回创作台</button>
      </div>
    `;
    return;
  }
  const copy = String(entry.copy || "").trim();
  $("#diary-page-body").innerHTML = `
    <article class="diary-entry">
      <div class="diary-entry-meta">
        <span>${escapeHtml(entry.project_title || "未命名稿件")}</span>
        <span>${escapeHtml(entry.version || "草稿")}</span>
      </div>
      <p class="diary-entry-description">${escapeHtml(entry.description || "一条被正式发布的创作记录。")}</p>
      <div class="diary-entry-copy">${escapeHtml(copy).replace(/\n/g, "<br>")}</div>
      <div class="diary-entry-signature">
        <span>已发布于 ${escapeHtml(formatDiaryDate(entry.published_at))}</span>
        <span>匣中镜 · 个人创作</span>
      </div>
    </article>
  `;
}

async function publishCurrentProject() {
  const project = projects[activeProject];
  if (!project) return;
  const copy = String($("#copy-editor")?.value || project.copy || "").trim();
  if (!copy || copy.length < 20) {
    showToast("先完成一版可发布的文案稿");
    return;
  }
  if (diaryEntries.length >= 100) {
    showToast("日记本已装订满 100 页");
    return;
  }
  const latest = diaryEntries[diaryEntries.length - 1];
  if (latest && latest.project_id === project.id && latest.copy === copy) {
    showToast("这一版已经发布到日记本");
    return;
  }
  const publishedAt = new Date().toISOString();
  const previousPublishedAt = project.last_published_at || "";
  project.copy = copy;
  project.last_published_at = publishedAt;
  const diaryEntry = {
    id: `diary_${Date.now()}`,
    project_id: project.id,
    project_title: project.title,
    description: project.description,
    version: project.version || "草稿",
    copy,
    published_at: publishedAt
  };
  diaryEntries.push(diaryEntry);
  activeDiaryPage = diaryEntries.length;
  const saved = await persistState("now");
  if (!saved) {
    diaryEntries = diaryEntries.filter((item) => item.id !== diaryEntry.id);
    project.last_published_at = previousPublishedAt;
    activeDiaryPage = Math.max(1, diaryEntries.length);
    renderDiary();
    showToast("发布未保存，请处理自动保存问题后重试");
    return;
  }
  $("#publish-diary").textContent = "发布新版";
  renderDiary();
  showToast(`已发布，写入日记本第 ${String(activeDiaryPage).padStart(2, "0")} 页`);
}

async function deleteCurrentDiaryEntry() {
  const entries = sortedDiaryEntries();
  const page = Math.max(1, Math.min(100, activeDiaryPage));
  const entry = entries[page - 1] || null;
  if (!entry) {
    showToast("这一页还没有可删除的发布记录");
    return;
  }
  const confirmed = await requestConfirm({
    title: "删除这页日记？",
    message: `将从日记本中删除第 ${String(page).padStart(2, "0")} 页「${entry.project_title || "未命名稿件"}」。删除后不会影响原项目文案，但这条发布记录会从日记本移除。`,
    confirmText: "确认删除",
    danger: true
  });
  if (!confirmed) return;
  diaryEntries = diaryEntries.filter((item) => item.id !== entry.id);
  activeDiaryPage = Math.min(page, Math.max(1, diaryEntries.length));
  await persistState("now");
  renderDiary();
  showToast("已删除这页日记");
}

function snapshotState() {
  const project = projects[activeProject];
  if (project) {
    ensureProjectState(project);
    activeBooks = validBookIds(project.selected_books);
    project.versions = currentVersions();
  }
  return {
    _revision: stateRevision,
    projects,
    activeProject,
    activePage,
    activeInspirationType,
    inspirationDraws,
    activeBooks,
    versions,
    diaryEntries
  };
}

async function persistState(mode = "debounced") {
  window.clearTimeout(persistTimer);
  hasPendingChanges = true;
  const run = async () => {
    try {
      const response = await XZJApi.request("/api/xiangzhongjing/state", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(snapshotState())
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(
          response.status === 409
            ? "另一个窗口已更新工作区，请刷新后再继续"
            : `状态保存失败（${response.status}）`
        );
        error.status = response.status;
        throw error;
      }
      stateRevision = Number(data.revision || stateRevision);
      hasPendingChanges = false;
      persistFailed = false;
      return true;
    } catch (error) {
      persistFailed = true;
      console.warn("Failed to persist Xiangzhongjing state", error);
      setSaveState("保存失败", "failed");
      showToast(error.status === 409 ? error.message : "自动保存失败，请检查本地服务后重试");
      return false;
    }
  };
  const enqueue = () => {
    persistInFlight = persistInFlight.then(run, run);
    return persistInFlight;
  };
  if (mode === "now") {
    return enqueue();
  } else {
    persistTimer = window.setTimeout(enqueue, 500);
    return true;
  }
}

window.addEventListener("beforeunload", (event) => {
  if (!hasPendingChanges) return;
  event.preventDefault();
  event.returnValue = "";
});

async function hydrateState() {
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/state");
    if (!response.ok) return;
    const state = await response.json();
    stateRevision = Number(state._revision || 0);
    if (state.projects && typeof state.projects === "object" && Object.keys(state.projects).length) {
      projects = state.projects;
    }
    if (state.activeProject && projects[state.activeProject]) {
      activeProject = state.activeProject;
    }
    if (state.activePage) {
      const storedPage = state.activePage === "dialogue" ? "mirror" : state.activePage;
      if (["workspace", "editor", "inspiration", "diary", "distill", "library", "mirror", "book-person", "assets", "covers", "profile", "dna", "settings"].includes(storedPage)) activePage = storedPage;
    }
    if (typeof state.activeInspirationType === "string") {
      activeInspirationType = state.activeInspirationType;
    }
    if (Array.isArray(state.inspirationDraws)) {
      inspirationDraws = state.inspirationDraws.slice(0, 365);
    }
    if (Array.isArray(state.activeBooks)) {
      activeBooks = state.activeBooks.filter((id) => books[id]);
    }
    if (Array.isArray(state.versions) && state.versions.length) {
      versions = state.versions;
    }
    if (Array.isArray(state.diaryEntries)) {
      diaryEntries = state.diaryEntries.slice(0, 100);
      activeDiaryPage = diaryEntries.length || 1;
    }
  } catch (error) {
    console.warn("Failed to hydrate Xiangzhongjing state", error);
  }
}

function createStarterProject() {
  const id = `project_${Date.now()}`;
  return {
    id,
    title: "我的第一条 Vlog",
    description: "从一个真实事件和一个此刻仍在思考的问题开始。",
    updated: "刚刚创建",
    version: "草稿",
    tags: ["新项目"],
    materials: {
      theme: "",
      insight: "",
      opening: "",
      daily: "",
      event: "",
      quotes: "",
      ending_reference: ""
    },
    copy: ""
  };
}

function migrateProjectState() {
  if (!Object.keys(projects).length) {
    const starter = createStarterProject();
    projects[starter.id] = starter;
    activeProject = starter.id;
  }
  Object.values(projects).forEach((project) => ensureProjectState(project));
  const active = projects[activeProject] || Object.values(projects)[0];
  if (active && active.id !== activeProject) {
    activeProject = active.id;
  }
  if (active && !active.versions.length && Array.isArray(versions) && versions.length) {
    active.versions = versions;
  }
  activeBooks = validBookIds(active?.selected_books || []);
  versions = active?.versions || [];
}

function renderProjects() {
  renderProjectBoard();
  updateWorkspaceSummary();
}

function renderProjectBoard() {
  const board = $("#project-board");
  if (!board) return;
  const query = projectFilter.trim().toLowerCase();
  const visibleProjects = Object.values(projects).filter((project) => {
    ensureProjectState(project);
    if (Boolean(project.archived) !== showArchived) return false;
    return !query || `${project.title} ${project.description || ""} ${(project.tags || []).join(" ")}`.toLowerCase().includes(query);
  });
  if (!visibleProjects.length) {
    board.innerHTML = `
      <div class="project-board-empty">
        <strong>${showArchived ? "还没有归档项目" : "没有找到匹配的项目"}</strong>
        <span>${showArchived ? "项目归档后会保留在这里，可随时恢复。" : "换一个筛选词，或新建一个创作项目。"}</span>
      </div>
    `;
    return;
  }
  const visualAssets = [
    "/static/icons/notebook-tabs.svg",
    "/static/icons/book-open-text.svg",
    "/static/icons/dna.svg",
    "/static/icons/file-pen-line.svg"
  ];
  board.innerHTML = visibleProjects.map((project, index) => {
    ensureProjectState(project);
    const health = materialHealth(project);
    const copyChars = String(project.copy || "").replace(/\s/g, "").length;
    const bookCount = validBookIds(project.selected_books).length;
    const versionCount = Array.isArray(project.versions) ? project.versions.length : 0;
    const visualAsset = visualAssets[index % visualAssets.length];
    const visualTone = ["sun", "sky", "mint", "coral"][index % 4];
    return `
      <article class="project-card ${project.id === activeProject ? "active" : ""}">
        <div class="project-card-head" data-tone="${visualTone}">
          <span class="project-dot ${project.id === "next" ? "empty" : ""}">
            <img src="${visualAsset}" alt="" width="24" height="24" aria-hidden="true">
          </span>
        </div>
        <div class="project-card-copy">
          <div class="project-card-title-line">
            <h2>${escapeHtml(project.title)}</h2>
            <div class="project-card-status">
              <span class="material-health ${health.level}">${health.label}</span>
              ${project.archived ? '<span class="project-archived-label">已归档</span>' : ""}
            </div>
          </div>
          <p>${escapeHtml(project.description || "从一个主题开始，把今天发生的事写成一条线。")}</p>
        </div>
        <div class="project-card-meta">
          <span data-kind="daily"><b>${health.dailyCount}</b> 日常</span>
          <span data-kind="event"><b>${health.eventCount}</b> 事件</span>
          <span data-kind="book"><b>${bookCount}</b> 书库</span>
          <span data-kind="version"><b>${versionCount}</b> 版本</span>
          <span data-kind="length"><b>${copyChars}</b> 字</span>
        </div>
        <div class="project-card-actions">
          <a class="top-action project-open-action" data-open-project="${project.id}" href="?page=editor&amp;project=${escapeHtml(project.id)}&amp;tab=copy"><img src="/static/icons/file-pen-line.svg" alt="" width="16" height="16" aria-hidden="true"><span>打开</span></a>
          <button class="project-archive-action" data-archive-project="${project.id}" type="button"><img src="/static/icons/library-big.svg" alt="" width="16" height="16" aria-hidden="true"><span>${project.archived ? "恢复" : "归档"}</span></button>
          <button class="project-delete-action" data-delete-project="${project.id}" type="button">删除</button>
        </div>
      </article>
    `;
  }).join("");
  $$("[data-open-project]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      selectProject(link.dataset.openProject, { openEditor: true });
    });
  });
  $$("[data-delete-project]").forEach((button) => {
    button.addEventListener("click", () => deleteProject(button.dataset.deleteProject));
  });
  $$("[data-archive-project]").forEach((button) => {
    button.addEventListener("click", () => toggleProjectArchive(button.dataset.archiveProject));
  });
}

function toggleProjectArchive(id) {
  const project = projects[id];
  if (!project) return;
  ensureProjectState(project);
  project.archived = !project.archived;
  if (id === activeProject) {
    $(".project-status").innerHTML = `<span></span>${project.archived ? "已归档" : "创作中"}`;
    $(".project-status").classList.toggle("archived", project.archived);
    $("#archive-project").textContent = project.archived ? "恢复项目" : "归档项目";
  }
  renderProjects();
  persistState("now");
  showToast(project.archived ? `已归档「${project.title}」，可在归档视图恢复` : `已恢复「${project.title}」`);
}

async function deleteProject(id) {
  const project = projects[id];
  if (!project) return;
  if (Object.keys(projects).length <= 1) {
    showToast("至少保留一个项目，无法删除最后一个项目");
    return;
  }
  const confirmed = await requestConfirm({
    title: `删除「${project.title}」？`,
    message: "项目中的素材、文案和版本记录都会被删除，且无法从归档中恢复。",
    confirmText: "删除项目",
    danger: true
  });
  if (!confirmed) return;
  delete projects[id];
  if (activeProject === id) {
    activeProject = Object.keys(projects)[0];
    selectProject(activeProject);
    switchPage("workspace");
  } else {
    renderProjects();
    persistState("now");
  }
  showToast(`已删除「${project.title}」`);
}

function updateWorkspaceSummary() {
  const project = projects[activeProject];
  if (!project || !$("#workspace-project-count")) return;
  const health = materialHealth(project);
  $("#workspace-project-count").textContent = Object.values(projects).filter((item) => !item.archived).length;
  $("#workspace-active-title").textContent = project.title;
  $("#workspace-material-state").textContent = health.label;
}

function fillMaterials(project) {
  ensureMaterialItems(project);
  syncLegacyMaterialFields(project);
  const materials = ensureProjectMaterials(project);
  $("#material-opening").value = materials.opening;
  $("#material-insight").value = materials.insight;
  $("#material-daily").value = materials.daily;
  $("#material-event").value = materials.event;
  $("#material-quotes").value = materials.quotes;
  $("#material-ending-reference").value = materials.ending_reference;
  $("#clipboard-source").value = project.clipboard_source || "";
  renderClipboardResult(project.import_result || null, false);
  renderProjectMeta(project);
  updateMaterialPreviews();
  syncGenerationLengthControl(project);
}

function selectProject(id, options = {}) {
  if (!projects[id]) return;
  activeProject = id;
  const project = projects[id];
  ensureProjectState(project);
  $(".project-status").innerHTML = `<span></span>${project.archived ? "已归档" : "创作中"}`;
  $(".project-status").classList.toggle("archived", project.archived);
  activeBooks = validBookIds(project.selected_books);
  setGenerationMode(project.generation_mode || "fresh", false);
  setNarrativeMode(project.narrative_mode || "default", false);
  setBookQuoteStrategy(project.book_quote_strategy || "standard", false);
  versions = project.versions;
  $("#breadcrumb-title").textContent = project.title;
  renderProjectMeta(project);
  $("#project-updated").textContent = project.updated;
  $("#project-version").textContent = project.version;
  $("#archive-project").textContent = project.archived ? "恢复项目" : "归档项目";
  $("#publish-diary").textContent = project.last_published_at ? "发布新版" : "发布到日记";
  $("#copy-editor").value = project.copy;
  fillMaterials(project);
  renderLockedParagraphs();
  updateCount();
  renderProjects();
  renderBooks();
  if (typeof renderDnaChips === "function") renderDnaChips();
  renderRetrieval();
  renderVersions();
  updateStrategy();
  activeDialogueSession = "";
  activeDialogueMessages = [];
  activeDialogueMemory = {};
  if (activePage === "mirror" || activePage === "book-person") {
    renderDialogueAll();
    loadDialogueSessions();
  }
  if (options.persist !== false) persistState();
  if (options.openEditor) {
    switchPage("editor", { historyMode: options.historyMode || "push" });
  } else if (activePage === "editor") {
    syncUrlState(options.historyMode || "replace");
  }
  if (!options.silent) showToast(`已打开「${project.title}」`);
}

function renderBooks() {
  renderBookCatalogOptions();
  const project = projects[activeProject];
  if (project) {
    ensureProjectState(project);
    activeBooks = validBookIds(project.selected_books);
  }
  const target = $("#book-list");
  if (!target) return;
  const catalog = Object.values(books);
  if (!catalog.length) {
    target.innerHTML = `<div class="retrieval-empty"><strong>书库还是空的</strong><span>新建一本书并上传原文或阅读笔记，创作时才能调用你的精神书库。</span></div>`;
    return;
  }
  target.innerHTML = catalog.map((book) => {
    const noteCount = noteCountForBook(book);
    const quotableCount = quotableCountForBook(book);
    const selected = activeBooks.includes(book.id);
    return `
    <article class="book-item ${selected ? "selected" : ""}" data-library-book="${escapeHtml(book.id)}" role="button" tabindex="0" aria-pressed="${selected}">
      <span class="book-mark ${book.color}">${escapeHtml(book.title.replace(/[《》]/g, "").slice(0, 1) || "书")}</span>
      <span class="book-copy">
        <strong>${book.title}</strong>
        <small>${book.author} · ${noteCount ? `${quotableCount} 条可引用 / ${noteCount} 条总素材` : "等待阅读笔记"}</small>
      </span>
      <span class="book-check"></span>
      <button class="library-book-remove" data-delete-library-book="${escapeHtml(book.id)}" type="button" aria-label="移除 ${escapeHtml(book.title)}">移除</button>
    </article>`;
  }).join("");
  $$('[data-delete-library-book]').forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const book = books[button.dataset.deleteLibraryBook];
      const confirmed = await requestConfirm({
        title: "从书库移除这本书？",
        message: `「${book?.title || "这本书"}」将停止参与创作，对应书中人也会归档。已保存的历史会话不会删除。`,
        confirmText: "确认移除",
        danger: true
      });
      if (!confirmed) return;
      const response = await XZJApi.request(`/api/xiangzhongjing/library/books/${encodeURIComponent(button.dataset.deleteLibraryBook)}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(apiError(data, "移除书籍失败"));
        return;
      }
      await loadBookNotesState();
      await loadLibraryPersonas();
      await loadDialoguePersonas();
      showToast("书籍已移出当前书库");
    });
  });
  $$('[data-library-book]').forEach((item) => {
    const toggle = () => {
      const id = item.dataset.libraryBook;
      activeBooks = activeBooks.includes(id)
        ? activeBooks.filter((bookId) => bookId !== id)
        : [...activeBooks, id];
      if (project) project.selected_books = validBookIds(activeBooks);
      renderBooks();
      updateStrategy();
      persistState();
    };
    item.addEventListener("click", toggle);
    item.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
  });
}

function renderBookCatalogOptions() {
  const uploadSelect = $("#book-note-target");
  const viewerSelect = $("#book-library-filter");
  if (uploadSelect) {
    const current = uploadSelect.value;
    uploadSelect.innerHTML = [
      '<option value="">新建 / 自动识别</option>',
      ...Object.values(books).map((book) => `<option value="${escapeHtml(book.id)}">${escapeHtml(book.title)}</option>`)
    ].join("");
    uploadSelect.value = books[current] ? current : "";
  }
  if (viewerSelect) {
    const current = viewerSelect.value;
    viewerSelect.innerHTML = [
      '<option value="all">全部书籍</option>',
      ...Object.values(books).map((book) => `<option value="${escapeHtml(book.id)}">${escapeHtml(book.title)}</option>`)
    ].join("");
    viewerSelect.value = current === "all" || books[current] ? current : "all";
  }
}

function renderRetrieval() {
  const target = $("#retrieval-list");
  if (!target) return;
  const summary = Array.isArray(bookNotesState.summary) ? bookNotesState.summary : [];
  if (!summary.length) {
    target.innerHTML = `<div class="retrieval-empty">还没有本地阅读笔记。可以点击“导入已提供笔记”，或上传自己的摘录文件。</div>`;
    return;
  }
  target.innerHTML = Object.values(books).map((book) => {
    const count = noteCountForBook(book);
    const quotableCount = quotableCountForBook(book);
    return `
      <div class="retrieval-item">
        <span class="retrieval-mark ${book.color}"></span>
        <div>
          <strong>${book.title}</strong>
          <p>${book.scope} · ${count ? `${quotableCount} 条可引用，${count} 条总素材` : "暂未沉淀本地笔记"}</p>
        </div>
      </div>
    `;
  }).join("");
}

function renderResearch(candidates, raw = "") {
  const target = $("#book-library-research-list");
  if (!target) return;
  const list = Array.isArray(candidates) ? candidates : [];
  if (!list.length) {
    target.innerHTML = `<div class="research-item"><strong>暂无笔记</strong><p>${escapeHtml(raw || "上传或导入阅读笔记后，这里会显示已沉淀的素材。")}</p></div>`;
    return;
  }
  const typeLabels = {
    direct_quote: "可引用原句",
    reading_note: "阅读笔记",
    context_excerpt: "上下文摘录",
    metadata: "目录信息"
  };
  const statusLabels = {
    valid: "已通过",
    pending_review: "待复核",
    quarantined: "已隔离"
  };
  target.innerHTML = list.map((item) => `
    <article class="research-item">
      <div class="research-head">
        <strong>${escapeHtml(item.book || "书库素材")}</strong>
        <span class="book-quality-tags">
          <span class="book-material-tag type-${escapeHtml(item.material_type || "context_excerpt")}">${escapeHtml(typeLabels[item.material_type] || "历史素材")}</span>
          <span class="book-material-tag status-${escapeHtml(item.quality_status || "pending_review")}">${escapeHtml(statusLabels[item.quality_status] || "待复核")}</span>
        </span>
      </div>
      ${item.quote ? `<blockquote>${escapeHtml(item.quote)}</blockquote>` : ""}
      ${item.quality_reason || item.fit ? `<p>${escapeHtml(item.quality_reason || item.fit || "")}</p>` : ""}
      <small>${escapeHtml(item.attribution || "来源未标人物")} · ${escapeHtml(item.source_title || item.source_type || "阅读资料")} · ${escapeHtml(item.source_locator || item.created_at || "来源已记录")}</small>
    </article>
  `).join("");
}

function clearResearch() {
  const target = $("#book-library-research-list");
  if (target) target.innerHTML = "";
}

function bookIdFromTitle(title) {
  const value = String(title || "");
  return Object.values(books).find((book) => value.includes(book.title.replace(/[《》]/g, "")) || value.includes(book.title))?.id || "";
}

function renderBookLibraryView() {
  const filter = $("#book-library-filter")?.value || "all";
  const qualityFilter = $("#book-library-quality-filter")?.value || "all";
  const recent = Array.isArray(bookNotesState.recent) ? bookNotesState.recent : [];
  const list = recent.filter((item) => {
    if (filter !== "all" && bookIdFromTitle(item.book) !== filter) return false;
    if (qualityFilter === "quotable") return item.material_type === "direct_quote" && item.quality_status === "valid";
    if (qualityFilter === "reference") return ["reading_note", "context_excerpt"].includes(item.material_type) && item.quality_status !== "quarantined";
    if (["pending_review", "quarantined"].includes(qualityFilter)) return item.quality_status === qualityFilter;
    return true;
  });
  const summary = Array.isArray(bookNotesState.summary) ? bookNotesState.summary : [];
  const total = list.length;
  const visible = list.slice(0, bookLibraryVisibleLimit);
  $("#book-library-count").textContent = `显示 ${visible.length} / ${total} 条`;
  $("#book-library-summary").innerHTML = summary.map((item) => {
    const book = Object.values(books).find((candidate) => item.book === candidate.title);
    if (filter !== "all" && book?.id !== filter) return "";
    return `
      <div class="book-library-summary-item">
        <strong>${escapeHtml(item.book || "书库")}</strong>
        <span>共 ${Number(item.count || 0)} · 可引用 ${Number(item.quotable_count || 0)} · 待复核 ${Number(item.pending_count || 0)} · 隔离 ${Number(item.quarantined_count || 0)}</span>
      </div>
    `;
  }).join("");
  renderResearch(visible, total ? "" : "当前筛选下还没有阅读笔记。");
  const loadMore = $("#book-library-load-more");
  if (loadMore) {
    loadMore.classList.toggle("hidden", visible.length >= total);
    loadMore.textContent = `继续加载（剩余 ${Math.max(0, total - visible.length)} 条）`;
  }
}

function openBookLibraryViewer() {
  const viewer = $("#book-library-viewer");
  if (!viewer) return;
  if (activePage !== "library") switchPage("library", { historyMode: "push" });
  renderBookLibraryView();
  viewer.classList.remove("hidden");
  viewer.setAttribute("aria-hidden", "false");
  overlayManager.open({
    id: "book-library-viewer",
    element: viewer,
    lockMode: "modal",
    onRequestClose: closeBookLibraryViewer
  });
  window.requestAnimationFrame(() => $("#close-book-library")?.focus({ preventScroll: true }));
}

function closeBookLibraryViewer() {
  const viewer = $("#book-library-viewer");
  if (!viewer) return;
  viewer.classList.add("hidden");
  viewer.setAttribute("aria-hidden", "true");
  overlayManager.close("book-library-viewer");
}

function renderBookDiagnostics(state = "clear", payload = {}) {
  const panel = $("#book-diagnostics");
  if (!panel) return;
  if (activePage !== "library" && state !== "clear") return;
  if (state === "clear") {
    panel.innerHTML = "";
    panel.classList.add("hidden");
    return;
  }
  const detail = payload.detail || payload.details || {};
  const candidates = payload.candidates || detail.candidates || [];
  const title = payload.title || (state === "loading" ? "正在读取本地书库" : (state === "success" ? "本地书库匹配完成" : "本地书库匹配失败"));
  const message = payload.message || detail.message || "DeepSeek 只从你已沉淀的阅读笔记原文中选择直接引文，不联网、不转述。";
  panel.innerHTML = `
    <div class="book-diagnostic-head ${state}">
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(activeBooks.length ? `${activeBooks.length} 本已选` : "未选择书籍")}</span>
    </div>
    <p>${escapeHtml(message)}</p>
    ${candidates.length ? `<small>已准备 ${candidates.length} 条本地候选，生成时由书库支撑 Skill 选择最自然的一至两条。</small>` : ""}
    ${detail.next_action ? `<div class="diagnostic-next">${escapeHtml(detail.next_action)}</div>` : ""}
  `;
  panel.classList.remove("hidden");
}

function updateStrategy() {
  const label = "生成链路里自动判断";
  $("#selected-book-count").textContent = label;
}

async function loadBookNotesState() {
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/book-notes");
    if (!response.ok) return;
    bookNotesState = await response.json();
    replaceBookCatalog(bookNotesState.books || []);
    Object.values(projects).forEach((project) => {
      if (!Object.prototype.hasOwnProperty.call(project, "selected_books")) {
        project.selected_books = defaultBookIds();
      } else {
        project.selected_books = validBookIds(project.selected_books);
      }
    });
    if (projects[activeProject]) activeBooks = validBookIds(projects[activeProject].selected_books);
    const summary = Array.isArray(bookNotesState.summary) ? bookNotesState.summary : [];
    const total = summary
      .reduce((sum, item) => sum + Number(item.count || 0), 0);
    const quotable = summary.reduce((sum, item) => sum + Number(item.quotable_count || 0), 0);
    $("#library-state").textContent = total
      ? `${quotable} 条可引用 / ${total} 条总素材`
      : `${Object.keys(books).length} 本已接入`;
    renderBooks();
    // The compact catalog is required by project generation on every page.
    // Citation details and library-only diagnostics stay isolated to the library page.
    if (activePage !== "library") {
      updateStrategy();
      return;
    }
    renderRetrieval();
    renderBookLibraryView();
    updateStrategy();
  } catch (error) {
    console.warn("Failed to load book notes", error);
  }
}
