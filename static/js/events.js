"use strict";

$("#copy-editor").addEventListener("input", () => {
  projects[activeProject].copy = $("#copy-editor").value;
  invalidateMaterialCoverage(projects[activeProject]);
  $("#save-state").textContent = "未保存";
  updateCount();
  renderLockedParagraphs();
  persistState();
});

$("#copy-editor").addEventListener("select", renderLockedParagraphs);
$("#copy-editor").addEventListener("click", renderLockedParagraphs);
$("#lock-paragraph").addEventListener("click", toggleParagraphLock);

$("#generation-diagnostics").addEventListener("click", (event) => {
  const button = event.target.closest("[data-retry-generation]");
  if (!button) return;
  generateCopy(button.dataset.retryGeneration);
});

$("#project-filter").addEventListener("input", (event) => {
  projectFilter = event.target.value;
  renderProjectBoard();
});

$("#toggle-archived").addEventListener("click", () => {
  showArchived = !showArchived;
  syncArchivedToggle();
  renderProjectBoard();
  syncUrlState("push");
});

$("#archive-project").addEventListener("click", () => {
  toggleProjectArchive(activeProject);
});

$$('[data-style-feedback]').forEach((button) => {
  button.addEventListener("click", async () => {
    const project = projects[activeProject];
    const feedback = $("#style-feedback-text").value.trim();
    button.disabled = true;
    try {
      const response = await XZJApi.request("/api/xiangzhongjing/style-feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: activeProject,
          style_version: project.last_style_version || skillStatus?.style?.published_version || "v2.0",
          decision: button.dataset.styleFeedback,
          feedback,
          copy_snapshot: $("#copy-editor").value
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(apiError(data, "反馈保存失败"));
      $("#style-feedback-text").value = "";
      showToast(button.dataset.styleFeedback === "keep" ? "已记录为正向风格证据" : "已记录为下一版修正规则");
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  });
});

$$(".editor-tab").forEach((button) => {
  button.addEventListener("click", () => switchEditorTab(button.dataset.editorTab));
  button.addEventListener("keydown", (event) => {
    const tabs = [...$$(".editor-tab")];
    const index = tabs.indexOf(button);
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    switchEditorTab(tabs[nextIndex].dataset.editorTab);
    tabs[nextIndex].focus();
  });
});

$$(sidebarNavSelector).forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    switchPage(link.dataset.page);
  });
});

$$("[data-dialogue-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    dialogueMode = button.dataset.dialogueMode === "book" ? "book" : "mirror";
    if (dialogueMode === "book" && activeDialoguePersona === "mirror-self") {
      activeDialoguePersona = dialoguePersonas.find((item) => item.type === "book")?.id || "";
    }
    activeDialogueSession = "";
    activeDialogueMessages = [];
    activeDialogueMemory = {};
    renderDialogueAll();
    await loadDialogueSessions();
    await loadDialogueAssets();
  });
});

$("#dialogue-persona-picker").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-dialogue-persona]");
  if (!button) return;
  await switchDialoguePersona(button.dataset.dialoguePersona);
});

$("#dialogue-persona-dock").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-dialogue-persona]");
  if (!button) return;
  await switchDialoguePersona(button.dataset.dialoguePersona);
});

$("#new-dialogue-session").addEventListener("click", async () => {
  try {
    await createDialogueSession();
    showToast("已新建交流会话");
  } catch (error) {
    showToast(error.message);
  }
});
$("#refresh-dialogue-assets").addEventListener("click", async () => {
  await loadDialogueAssets();
  showToast("沉淀资产库已刷新");
});
$("#dialogue-asset-search").addEventListener("input", (event) => {
  dialogueAssetQuery = event.target.value.trim();
  renderDialogueAssets();
});
$("#dialogue-asset-type-filter").addEventListener("change", (event) => {
  dialogueAssetTypeFilter = event.target.value || "all";
  renderDialogueAssets();
});
$("#refresh-asset-page").addEventListener("click", async () => {
  await loadDialogueAssets();
  showToast("资产库已刷新");
});
$("#asset-page-search").addEventListener("input", (event) => {
  dialogueAssetQuery = event.target.value.trim();
  renderDialogueAssets();
});
$("#asset-page-type-filter").addEventListener("change", (event) => {
  dialogueAssetTypeFilter = event.target.value || "all";
  renderDialogueAssets();
});
$$("[data-asset-scope]").forEach((button) => {
  button.addEventListener("click", () => {
    dialogueAssetScope = button.dataset.assetScope || "all";
    renderDialogueAssetPage();
  });
});
$("#clear-asset-filters").addEventListener("click", () => {
  dialogueAssetScope = "all";
  dialogueAssetQuery = "";
  dialogueAssetTypeFilter = "all";
  renderDialogueAssets();
});
document.addEventListener("change", async (event) => {
  const select = event.target.closest("[data-asset-type-update]");
  if (!select) return;
  await updateDialogueAssetType(select.dataset.assetTypeUpdate, select.value, select);
});
$("#asset-category-board").addEventListener("click", (event) => {
  if (!event.target.closest("[data-clear-asset-filters]")) return;
  dialogueAssetScope = "all";
  dialogueAssetQuery = "";
  dialogueAssetTypeFilter = "all";
  renderDialogueAssets();
});

$("#dialogue-session-list").addEventListener("click", async (event) => {
  if (event.target.closest("[data-new-dialogue-session]")) {
    try {
      await createDialogueSession();
      showToast("已新建交流会话");
    } catch (error) {
      showToast(error.message);
    }
    return;
  }
  const menuTrigger = event.target.closest("[data-dialogue-session-menu]");
  if (menuTrigger) {
    event.stopPropagation();
    openDialogueSessionMenu(menuTrigger.dataset.dialogueSessionMenu, menuTrigger);
    return;
  }
  const button = event.target.closest("[data-dialogue-session]");
  if (!button) return;
  try {
    await selectDialogueSession(button.dataset.dialogueSession);
  } catch (error) {
    showToast(error.message);
  }
});

$("#dialogue-composer").addEventListener("submit", sendDialogueMessage);
$("#dialogue-session-search").addEventListener("input", async (event) => {
  dialogueSessionQuery = event.target.value.trim();
  await loadDialogueSessions();
});
$("#dialogue-trash-toggle").addEventListener("click", async () => {
  dialogueTrashMode = !dialogueTrashMode;
  activeDialogueSession = "";
  activeDialogueMessages = [];
  activeDialogueMemory = {};
  dialogueMessagesBefore = "";
  dialogueMessagesHasMore = false;
  $("#dialogue-trash-toggle").textContent = dialogueTrashMode ? "返回会话" : "最近删除";
  renderDialogueAll();
  await loadDialogueSessions();
});
$(".dialogue-session-panel").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-dialogue-bulk-clear]");
  if (!button) return;
  try {
    await bulkClearDialogueSessions();
  } catch (error) {
    showToast(error.message);
  }
});
$("#dialogue-session-menu").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-dialogue-session-action]");
  if (!button) return;
  try {
    await handleDialogueSessionAction(button.dataset.dialogueSessionAction);
  } catch (error) {
    showToast(error.message);
  }
});
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("#dialogue-session-menu") && !event.target.closest("[data-dialogue-session-menu]") && !event.target.closest("#dialogue-chat-menu")) {
    closeDialogueSessionMenu();
  }
});
$("#dialogue-chat-menu").addEventListener("click", (event) => {
  event.stopPropagation();
  if (!activeDialogueSession) {
    showToast("先新建或打开一段会话");
    return;
  }
  openDialogueSessionMenu(activeDialogueSession, event.currentTarget);
});
$("#dialogue-context-toggle").addEventListener("click", () => {
  if (activePage === "assets") {
    switchPage(dialogueMode === "book" ? "book-person" : "mirror");
    return;
  }
  dialogueAssetScope = dialogueMode === "book" ? "book" : "mirror";
  dialogueContextOpen = false;
  switchPage("assets");
});
$("#dialogue-context-close").addEventListener("click", () => {
  dialogueContextOpen = false;
  renderDialogueContext();
});
$("#dialogue-scroll-latest").addEventListener("click", () => scrollDialogueToLatest());
$("#dialogue-thread").addEventListener("scroll", () => {
  const target = $("#dialogue-thread");
  if (target.scrollTop <= 64) loadOlderDialogueMessages();
  if (dialogueNearBottom(target)) $("#dialogue-scroll-latest").classList.add("hidden");
});
$("#dialogue-thread").addEventListener("click", async (event) => {
  const prompt = event.target.closest("[data-dialogue-prompt]");
  if (prompt) {
    const input = $("#dialogue-input");
    input.value = prompt.dataset.dialoguePrompt || "";
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
    input.focus();
    return;
  }
  const retry = event.target.closest("[data-dialogue-retry]");
  if (retry) {
    await retryDialogueMessage(retry.dataset.dialogueRetry);
    return;
  }
  const copy = event.target.closest("[data-dialogue-copy]");
  if (copy) {
    const message = activeDialogueMessages.find((item) => item.id === copy.dataset.dialogueCopy);
    if (!message) return;
    try {
      await navigator.clipboard.writeText(message.content || "");
      showToast("已复制回复");
    } catch (_) {
      showToast("复制失败，请手动选择文本");
    }
    return;
  }
  const evidence = event.target.closest("[data-dialogue-evidence]");
  if (evidence) {
    const messageId = evidence.dataset.dialogueEvidence;
    if (dialogueEvidenceOpen.has(messageId)) dialogueEvidenceOpen.delete(messageId);
    else dialogueEvidenceOpen.add(messageId);
    renderDialogueThread({ preserveScroll: true });
    return;
  }
  const feedback = event.target.closest("[data-dialogue-feedback]");
  if (feedback) {
    feedback.disabled = true;
    try {
      await submitDialogueFeedback(feedback.dataset.messageId, feedback.dataset.dialogueFeedback);
    } catch (error) {
      showToast(error.message);
    } finally {
      feedback.disabled = false;
    }
    return;
  }
  const extract = event.target.closest("[data-dialogue-extract]");
  if (!extract) return;
  try {
    await extractDialogueItem(extract.dataset.messageId, Number(extract.dataset.dialogueExtract));
  } catch (error) {
    showToast(error.message);
  }
});
$("#dialogue-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#dialogue-composer").requestSubmit();
  }
});
$("#dialogue-input").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 132)}px`;
});
$("#dialogue-rename-cancel").addEventListener("click", () => closeDialogueRenameDialog(false));
$("#dialogue-rename-accept").addEventListener("click", saveDialogueRename);
$("#dialogue-rename-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    saveDialogueRename();
  }
});
$("#dialogue-rename-dialog").addEventListener("click", (event) => {
  if (event.target.id === "dialogue-rename-dialog") closeDialogueRenameDialog(false);
});

$("#publish-diary").addEventListener("click", publishCurrentProject);
$("#diary-prev").addEventListener("click", () => {
  activeDiaryPage = Math.max(1, activeDiaryPage - 1);
  renderDiary();
});
$("#diary-next").addEventListener("click", () => {
  activeDiaryPage = Math.min(100, activeDiaryPage + 1);
  renderDiary();
});
$("#delete-diary-entry").addEventListener("click", deleteCurrentDiaryEntry);
$("#diary-open-workspace").addEventListener("click", () => switchPage("workspace"));
$("#diary-page-body").addEventListener("click", (event) => {
  if (event.target.closest("[data-diary-action='workspace']")) switchPage("workspace");
});

$("#view-book-library").addEventListener("click", openBookLibraryViewer);
$("#view-book-library-inline").addEventListener("click", openBookLibraryViewer);
$("#close-book-library").addEventListener("click", closeBookLibraryViewer);
$("#book-library-viewer").addEventListener("click", (event) => {
  if (event.target.id === "book-library-viewer") closeBookLibraryViewer();
});
$("#book-library-filter").addEventListener("change", () => {
  bookLibraryVisibleLimit = 80;
  renderBookLibraryView();
});
$("#book-library-quality-filter").addEventListener("change", () => {
  bookLibraryVisibleLimit = 80;
  renderBookLibraryView();
});
$("#book-library-load-more").addEventListener("click", () => {
  bookLibraryVisibleLimit += 80;
  renderBookLibraryView();
});

$$("[data-generate-copy]").forEach((button) => button.addEventListener("click", () => generateCopy()));
$("#generate-copy").addEventListener("click", () => generateCopy());
$("#save-version").addEventListener("click", saveVersion);
$("#mobile-save-version").addEventListener("click", () => {
  saveVersion();
  $(".topbar-more").removeAttribute("open");
});
$$('[data-generation-mode]').forEach((button) => {
  button.addEventListener("click", () => setGenerationMode(button.dataset.generationMode));
});
$$('[data-narrative-mode]').forEach((button) => {
  button.addEventListener("click", () => setNarrativeMode(button.dataset.narrativeMode));
});
$$('[data-book-quote-strategy]').forEach((button) => {
  button.addEventListener("click", () => setBookQuoteStrategy(button.dataset.bookQuoteStrategy));
});
$("#generation-length-mode").addEventListener("change", (event) => {
  setGenerationLengthMode(event.target.value);
});
$("#generation-target-length").addEventListener("change", (event) => {
  setGenerationTargetLength(event.target.value);
});
$("#generation-target-length").addEventListener("input", (event) => {
  previewGenerationTargetLength(event.target.value);
});

$("#edit-project-meta").addEventListener("click", () => {
  const project = projects[activeProject];
  renderProjectMeta(project);
  $("#project-meta-editor").classList.remove("hidden");
  $("#edit-project-meta").setAttribute("aria-expanded", "true");
  $("#project-theme-input").focus();
});

function closeProjectMetaEditor() {
  $("#project-meta-editor").classList.add("hidden");
  $("#edit-project-meta").setAttribute("aria-expanded", "false");
  renderProjectMeta(projects[activeProject]);
}

$("#cancel-project-meta").addEventListener("click", closeProjectMetaEditor);
$("#project-meta-editor").addEventListener("submit", (event) => {
  event.preventDefault();
  const project = projects[activeProject];
  const nextTitle = $("#project-theme-input").value.trim();
  const nextDescription = $("#project-description-input").value.trim();
  if (!nextTitle) {
    showToast("项目主题不能为空");
    $("#project-theme-input").focus();
    return;
  }
  project.title = nextTitle;
  project.description = nextDescription || "补充一句这条视频想讲什么。";
  project.materials = {
    ...ensureProjectMaterials(project),
    theme: nextTitle
  };
  invalidateMaterialCoverage(project);
  closeProjectMetaEditor();
  $("#breadcrumb-title").textContent = project.title;
  renderProjects();
  updateWorkspaceSummary();
  scheduleMaterialPersist();
  showToast("项目主题与简介已更新");
});

function syncMaterialFilterControls() {
  $("#material-search").value = materialFilters.query;
  $("#material-status-filter").value = materialFilters.status;
}

function syncArchivedToggle() {
  const toggle = $("#toggle-archived");
  if (!toggle) return;
  toggle.setAttribute("aria-pressed", String(showArchived));
  toggle.classList.toggle("active", showArchived);
  toggle.textContent = showArchived ? "返回项目" : "查看归档";
}

function applyUrlViewState(state) {
  if (!state) return;
  if (state.group && materialGroupDefinitions[state.group]) activeMaterialGroup = state.group;
  materialFilters.query = state.materialQuery || "";
  materialFilters.status = state.materialStatus || "all";
  if (state.mode) generationMode = state.mode;
  showArchived = Boolean(state.archived);
}

function clearMaterialFilters() {
  materialFilters = { query: "", status: "all" };
  syncMaterialFilterControls();
  renderMaterialBoard();
  syncUrlState("replace");
}

function setActiveMaterialGroup(group) {
  if (!materialGroupDefinitions[group] || group === activeMaterialGroup) return;
  activeMaterialGroup = group;
  materialFilters.query = "";
  selectedMaterialIds.clear();
  materialSelectionMode = false;
  syncMaterialFilterControls();
  renderMaterialBoard();
  syncUrlState("push");
}

function materialDrawerLockMode() {
  return window.matchMedia('(max-width: 1040px)').matches ? 'modal' : 'none';
}

function openMaterialDrawer(type) {
  if (type !== 'import') return;
  const drawer = $("#material-drawer");
  const backdrop = $("#material-drawer-backdrop");
  $("#material-drawer-kicker").textContent = "智能整理";
  $("#material-drawer-title").textContent = "AI 导入素材";
  $$('[data-material-drawer-panel]').forEach((panel) => panel.classList.toggle("hidden", panel.dataset.materialDrawerPanel !== type));
  drawer.classList.remove("hidden");
  backdrop.classList.remove("hidden");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.setAttribute("aria-hidden", "false");
  overlayManager.open({
    id: 'material-drawer',
    element: drawer,
    backdrop,
    lockMode: materialDrawerLockMode(),
    onRequestClose: closeMaterialDrawer
  });
  window.requestAnimationFrame(() => {
    drawer.classList.add("open");
    backdrop.classList.add("open");
    $("#clipboard-source")?.focus();
  });
}

function closeMaterialDrawer() {
  const drawer = $("#material-drawer");
  const backdrop = $("#material-drawer-backdrop");
  drawer.classList.remove("open");
  backdrop.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.setAttribute("aria-hidden", "true");
  overlayManager.close('material-drawer');
  window.setTimeout(() => {
    if (!drawer.classList.contains("open")) {
      drawer.classList.add("hidden");
      backdrop.classList.add("hidden");
    }
  }, 220);
}

function materialActionPopoverOpen() {
  const popover = $("#material-action-popover");
  return Boolean(popover?.classList.contains("open"));
}

function closeMaterialActionPopover({ restoreFocus = true } = {}) {
  const popover = $("#material-action-popover");
  if (!popover) return;
  const trigger = activeMaterialMenu?.trigger;
  if (trigger?.isConnected) trigger.setAttribute("aria-expanded", "false");
  popover.classList.remove("open");
  popover.setAttribute("aria-hidden", "true");
  activeMaterialMenu = null;
  if (restoreFocus && trigger?.isConnected) window.requestAnimationFrame(() => trigger.focus());
}

function positionMaterialActionPopover() {
  if (!activeMaterialMenu || !materialActionPopoverOpen()) return;
  const popover = $("#material-action-popover");
  const trigger = activeMaterialMenu.trigger;
  if (!trigger?.isConnected) {
    closeMaterialActionPopover({ restoreFocus: false });
    return;
  }
  popover.style.removeProperty("top");
  popover.style.removeProperty("right");
  popover.style.removeProperty("bottom");
  popover.style.removeProperty("left");
  const triggerRect = trigger.getBoundingClientRect();
  const menuRect = popover.getBoundingClientRect();
  const viewportWidth = window.visualViewport?.width || window.innerWidth;
  const viewportHeight = window.visualViewport?.height || window.innerHeight;
  const edge = 12;
  const gap = 8;
  const availableBelow = viewportHeight - triggerRect.bottom - edge;
  const availableAbove = triggerRect.top - edge;
  const openBelow = availableBelow >= menuRect.height + gap || availableBelow >= availableAbove;
  const idealTop = openBelow ? triggerRect.bottom + gap : triggerRect.top - menuRect.height - gap;
  const maxTop = Math.max(edge, viewportHeight - menuRect.height - edge);
  const maxLeft = Math.max(edge, viewportWidth - menuRect.width - edge);
  const top = Math.min(Math.max(edge, idealTop), maxTop);
  const left = Math.min(Math.max(edge, triggerRect.right - menuRect.width), maxLeft);
  popover.dataset.placement = openBelow ? "bottom" : "top";
  popover.style.top = `${Math.round(top)}px`;
  popover.style.left = `${Math.round(left)}px`;
}

function openMaterialActionPopover(trigger) {
  const row = trigger.closest(".material-row");
  const group = row?.dataset.materialGroup;
  const id = row?.dataset.materialId;
  const items = group ? ensureMaterialItems(projects[activeProject])[group] : [];
  const index = items.findIndex((item) => item.id === id);
  const item = items[index];
  if (!item) return;
  if (activeMaterialMenu?.id === id && materialActionPopoverOpen()) {
    closeMaterialActionPopover();
    return;
  }
  closeMaterialActionPopover({ restoreFocus: false });
  activeMaterialMenu = { id, group, trigger };
  $("#material-action-title").textContent = `${materialGroupDefinitions[group].label} ${String(index + 1).padStart(2, "0")}`;
  $("#material-action-priority").innerHTML = optionsHtml(Object.entries(materialPriorityLabels), item.priority);
  $("#material-action-treatment").innerHTML = optionsHtml(Object.entries(materialTreatmentLabels), item.treatment);
  $("#material-action-move-up").disabled = index === 0;
  $("#material-action-move-down").disabled = index === items.length - 1;
  trigger.setAttribute("aria-expanded", "true");
  const popover = $("#material-action-popover");
  popover.classList.add("open");
  popover.setAttribute("aria-hidden", "false");
  window.requestAnimationFrame(() => {
    positionMaterialActionPopover();
    $("#material-action-priority").focus({ preventScroll: true });
  });
}

function updateActiveMaterialAction(field, value) {
  if (!activeMaterialMenu) return;
  const items = ensureMaterialItems(projects[activeProject])[activeMaterialMenu.group] || [];
  const item = items.find((candidate) => candidate.id === activeMaterialMenu.id);
  if (!item) {
    closeMaterialActionPopover({ restoreFocus: false });
    return;
  }
  item[field] = value;
  scheduleMaterialPersist();
}

function moveActiveMaterialAction(direction) {
  if (!activeMaterialMenu) return;
  const { group, id } = activeMaterialMenu;
  const items = ensureMaterialItems(projects[activeProject])[group] || [];
  const index = items.findIndex((item) => item.id === id);
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= items.length) return;
  captureMaterialUndo("已调整素材顺序");
  [items[index], items[nextIndex]] = [items[nextIndex], items[index]];
  invalidateMaterialCoverage(projects[activeProject]);
  closeMaterialActionPopover({ restoreFocus: false });
  renderMaterialBoard();
  scheduleMaterialPersist();
}

function deleteActiveMaterialAction() {
  if (!activeMaterialMenu) return;
  const { group, id } = activeMaterialMenu;
  const items = ensureMaterialItems(projects[activeProject])[group] || [];
  if (!items.some((item) => item.id === id)) return;
  captureMaterialUndo("已删除 1 条素材");
  projects[activeProject].material_items[group] = items.filter((item) => item.id !== id);
  invalidateMaterialCoverage(projects[activeProject]);
  selectedMaterialIds.delete(id);
  expandedMaterialRows.delete(id);
  closeMaterialActionPopover({ restoreFocus: false });
  renderMaterialBoard();
  scheduleMaterialPersist();
}

function addMaterialItem(group) {
  const project = projects[activeProject];
  captureMaterialUndo(`已新增 1 条${materialGroupDefinitions[group].label}`);
  const item = newMaterialItem("", group);
  ensureMaterialItems(project)[group].push(item);
  invalidateMaterialCoverage(project);
  activeMaterialGroup = group;
  materialFilters = { query: "", status: "all" };
  syncMaterialFilterControls();
  renderMaterialBoard();
  window.requestAnimationFrame(() => {
    const row = document.querySelector(`[data-material-id="${CSS.escape(item.id)}"]`);
    const textarea = row?.querySelector("[data-material-text]");
    textarea?.focus();
    resizeMaterialTextarea(textarea);
  });
  scheduleMaterialPersist();
}

function applyMaterialBatch(field, value) {
  if (!value || !selectedMaterialIds.size) return;
  captureMaterialUndo(`已批量设置 ${selectedMaterialIds.size} 条素材`);
  Object.values(ensureMaterialItems(projects[activeProject])).flat().forEach((item) => {
    if (selectedMaterialIds.has(item.id)) item[field] = value;
  });
  renderMaterialBoard();
  scheduleMaterialPersist();
}

$("#editor-materials").addEventListener("input", (event) => {
  const row = event.target.closest(".material-row");
  if (!row || !event.target.matches("[data-material-text]")) return;
  const items = ensureMaterialItems(projects[activeProject])[row.dataset.materialGroup];
  const item = items.find((candidate) => candidate.id === row.dataset.materialId);
  if (!item) return;
  item.text = event.target.value;
  invalidateMaterialCoverage(projects[activeProject]);
  resizeMaterialTextarea(event.target);
  syncLegacyMaterialFields();
  renderMaterialCoverage();
  setMaterialSaveState("编辑中", "saving");
  scheduleMaterialPersist();
});

$("#editor-materials").addEventListener("change", (event) => {
  if (event.target.matches("[data-material-select]")) {
    const row = event.target.closest(".material-row");
    if (!row) return;
    if (event.target.checked) selectedMaterialIds.add(row.dataset.materialId);
    else selectedMaterialIds.delete(row.dataset.materialId);
    updateMaterialSelectionBar();
    return;
  }
  const row = event.target.closest(".material-row");
  if (!row || !event.target.matches("[data-material-field]")) return;
  const items = ensureMaterialItems(projects[activeProject])[row.dataset.materialGroup];
  const item = items.find((candidate) => candidate.id === row.dataset.materialId);
  if (!item) return;
  item[event.target.dataset.materialField] = event.target.value;
  invalidateMaterialCoverage(projects[activeProject]);
  syncLegacyMaterialFields();
  renderMaterialCoverage();
  scheduleMaterialPersist();
});

$("#editor-materials").addEventListener("click", (event) => {
  const groupTab = event.target.closest("[data-material-group-tab]");
  if (groupTab) {
    setActiveMaterialGroup(groupTab.dataset.materialGroupTab);
    return;
  }
  const drawerButton = event.target.closest("[data-open-material-drawer]");
  if (drawerButton) {
    openMaterialDrawer(drawerButton.dataset.openMaterialDrawer);
    return;
  }
  const addButton = event.target.closest("[data-add-material]");
  if (addButton) {
    addMaterialItem(addButton.dataset.addMaterial);
    return;
  }
  const menuTrigger = event.target.closest("[data-material-menu-trigger]");
  if (menuTrigger) {
    openMaterialActionPopover(menuTrigger);
    return;
  }
  const rowAction = event.target.closest("[data-material-action]");
  if (rowAction) {
    const row = rowAction.closest(".material-row");
    if (!row) return;
    if (rowAction.dataset.materialAction === "evidence") {
      if (expandedMaterialRows.has(row.dataset.materialId)) expandedMaterialRows.delete(row.dataset.materialId);
      else expandedMaterialRows.add(row.dataset.materialId);
      renderMaterialBoard();
      return;
    }
  }
  const coverageStatus = event.target.closest("[data-material-filter-status]");
  if (coverageStatus) {
    const status = coverageStatus.dataset.materialFilterStatus;
    materialFilters.status = materialFilters.status === status ? "all" : status;
    syncMaterialFilterControls();
    renderMaterialBoard();
    return;
  }
  if (event.target.closest("[data-clear-material-filters]")) {
    clearMaterialFilters();
  }
});

$("#add-material-current").addEventListener("click", () => addMaterialItem(activeMaterialGroup));
$("#toggle-material-selection").addEventListener("click", () => {
  materialSelectionMode = !materialSelectionMode;
  if (!materialSelectionMode) selectedMaterialIds.clear();
  updateMaterialSelectionBar();
});

const materialDrawerBackdrop = $("#material-drawer-backdrop");
const materialDrawer = $("#material-drawer");
if (materialDrawerBackdrop?.parentElement !== document.body) document.body.appendChild(materialDrawerBackdrop);
if (materialDrawer?.parentElement !== document.body) document.body.appendChild(materialDrawer);
$("#close-material-drawer").addEventListener("click", closeMaterialDrawer);
$("#material-drawer-backdrop").addEventListener("click", closeMaterialDrawer);
const materialActionPopover = $("#material-action-popover");
if (materialActionPopover?.parentElement !== document.body) document.body.appendChild(materialActionPopover);
$("#close-material-action").addEventListener("click", () => closeMaterialActionPopover());
$("#material-action-priority").addEventListener("change", (event) => updateActiveMaterialAction("priority", event.target.value));
$("#material-action-treatment").addEventListener("change", (event) => updateActiveMaterialAction("treatment", event.target.value));
$("#material-action-move-up").addEventListener("click", () => moveActiveMaterialAction(-1));
$("#material-action-move-down").addEventListener("click", () => moveActiveMaterialAction(1));
$("#material-action-delete").addEventListener("click", deleteActiveMaterialAction);
window.addEventListener("resize", () => {
  positionMaterialActionPopover();
  if ($("#material-drawer").classList.contains("open")) {
    overlayManager.updateLock('material-drawer', materialDrawerLockMode());
  }
});
document.addEventListener("scroll", (event) => {
  if (!materialActionPopoverOpen() || $("#material-action-popover").contains(event.target)) return;
  closeMaterialActionPopover({ restoreFocus: false });
}, true);
document.addEventListener("pointerdown", (event) => {
  if (!materialActionPopoverOpen()) return;
  if ($("#material-action-popover").contains(event.target) || activeMaterialMenu?.trigger?.contains(event.target)) return;
  closeMaterialActionPopover({ restoreFocus: false });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && materialActionPopoverOpen()) closeMaterialActionPopover();
});

$("#undo-material-change").addEventListener("click", restoreMaterialUndo);
$("#clear-material-selection").addEventListener("click", () => {
  selectedMaterialIds.clear();
  materialSelectionMode = false;
  updateMaterialSelectionBar();
  renderMaterialBoard();
});
$("#delete-selected-materials").addEventListener("click", async () => {
  if (!selectedMaterialIds.size) return;
  const confirmed = await requestConfirm({
    title: `删除 ${selectedMaterialIds.size} 条素材？`,
    message: "删除后 10 秒内可撤销；超过撤销时间后会随项目状态一起保存。",
    confirmText: "删除素材",
    danger: true
  });
  if (!confirmed) return;
  captureMaterialUndo(`已删除 ${selectedMaterialIds.size} 条素材`);
  Object.keys(ensureMaterialItems(projects[activeProject])).forEach((group) => {
    projects[activeProject].material_items[group] = ensureMaterialItems(projects[activeProject])[group]
      .filter((item) => !selectedMaterialIds.has(item.id));
  });
  invalidateMaterialCoverage(projects[activeProject]);
  selectedMaterialIds.clear();
  renderMaterialBoard();
  scheduleMaterialPersist();
});

$("#material-batch-priority").addEventListener("change", (event) => {
  applyMaterialBatch("priority", event.target.value);
  event.target.value = "";
});

$("#material-search").addEventListener("input", (event) => {
  materialFilters.query = event.target.value;
  renderMaterialBoard();
  syncUrlState("replace");
});
[["#material-status-filter", "status"]].forEach(([selector, key]) => {
  $(selector).addEventListener("change", (event) => {
    materialFilters[key] = event.target.value;
    renderMaterialBoard();
    syncUrlState("replace");
  });
});
$("#clear-material-filters").addEventListener("click", clearMaterialFilters);
$("#filter-material-audit").addEventListener("click", () => {
  const project = projects[activeProject];
  const items = Object.values(ensureMaterialItems(project)).flat().filter((item) => item.text.trim());
  const hasPending = items.some((item) => normalizeMaterialUsage(item.usage_status) === "stale");
  const hasConflict = items.some((item) => normalizeMaterialUsage(item.usage_status) === "conflicted");
  materialFilters.status = hasPending ? "stale" : (hasConflict ? "conflicted" : "unused");
  syncMaterialFilterControls();
  renderMaterialBoard();
  syncUrlState("replace");
});

$("#editor-materials").addEventListener("dragstart", (event) => {
  const handle = event.target.closest("[data-material-drag-handle]");
  const row = handle?.closest(".material-row");
  if (!row) return;
  draggedMaterialId = row.dataset.materialId;
  row.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", draggedMaterialId);
});

$("#editor-materials").addEventListener("dragover", (event) => {
  const row = event.target.closest(".material-row");
  if (!row || !draggedMaterialId || row.dataset.materialId === draggedMaterialId) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  $$("#material-active-list .material-row").forEach((item) => item.classList.toggle("drag-over", item === row));
});

$("#editor-materials").addEventListener("drop", (event) => {
  const row = event.target.closest(".material-row");
  if (!row || !draggedMaterialId || row.dataset.materialId === draggedMaterialId) return;
  event.preventDefault();
  const items = ensureMaterialItems(projects[activeProject])[activeMaterialGroup];
  const sourceIndex = items.findIndex((item) => item.id === draggedMaterialId);
  const targetIndex = items.findIndex((item) => item.id === row.dataset.materialId);
  if (sourceIndex < 0 || targetIndex < 0) return;
  captureMaterialUndo("已调整素材顺序");
  const [moved] = items.splice(sourceIndex, 1);
  items.splice(targetIndex, 0, moved);
  draggedMaterialId = "";
  renderMaterialBoard();
  scheduleMaterialPersist();
});

$("#editor-materials").addEventListener("dragend", () => {
  draggedMaterialId = "";
  $$("#material-active-list .material-row").forEach((row) => row.classList.remove("dragging", "drag-over"));
});

function syncMobileSaveState() {
  const desktop = $("#save-state");
  const mobile = $("#mobile-save-state");
  if (!desktop || !mobile) return;
  if (desktop.dataset.state === "failed" && !desktop.textContent.includes("失败")) {
    delete desktop.dataset.state;
  }
  mobile.textContent = desktop.textContent;
  if (desktop.dataset.state) mobile.dataset.state = desktop.dataset.state;
  else delete mobile.dataset.state;
}

new MutationObserver(syncMobileSaveState).observe($("#save-state"), {
  attributes: true,
  attributeFilter: ["data-state"],
  childList: true,
  characterData: true,
  subtree: true
});

$("#read-clipboard").addEventListener("click", async () => {
  if (!navigator.clipboard?.readText) {
    showToast("当前浏览器不支持读取剪贴板");
    return;
  }
  const button = $("#read-clipboard");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "读取中";
  try {
    const text = await navigator.clipboard.readText();
    $("#clipboard-source").value = text;
    showToast(text.trim() ? "剪贴板已读取" : "剪贴板为空");
  } catch (error) {
    showToast("无法读取剪贴板，可以手动粘贴");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

$("#parse-clipboard").addEventListener("click", async () => {
  const button = $("#parse-clipboard");
  const originalText = button.textContent;
  let raw = $("#clipboard-source").value.trim();
  if (!raw && navigator.clipboard?.readText) {
    try {
      raw = (await navigator.clipboard.readText()).trim();
      $("#clipboard-source").value = raw;
    } catch (error) {
      raw = "";
    }
  }
  if (!raw) {
    showToast("请先粘贴一段素材");
    return;
  }
  button.disabled = true;
  button.textContent = "识别中";
  $("#save-state").textContent = "正在识别素材";
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/parse-materials", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: raw })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "素材识别失败"));
    pendingMaterialImport = {
      data,
      projectId: activeProject,
      previousSource: projects[activeProject].clipboard_source || ""
    };
    renderClipboardResult(data, true);
    setMaterialSaveState("等待确认", "pending");
    showToast("识别完成，请选择合并或替换");
  } catch (error) {
    $("#save-state").textContent = "素材识别失败";
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

$("#clipboard-result").addEventListener("click", async (event) => {
  const action = event.target.closest("[data-import-action]");
  if (!action || !pendingMaterialImport) return;
  if (pendingMaterialImport.projectId !== activeProject) {
    pendingMaterialImport = null;
    renderClipboardResult(null);
    showToast("项目已切换，请重新识别素材");
    return;
  }
  if (action.dataset.importAction === "cancel") {
    $("#clipboard-source").value = pendingMaterialImport.previousSource || "";
    pendingMaterialImport = null;
    renderClipboardResult(projects[activeProject].import_result || null, false);
    setMaterialSaveState("已自动保存", "saved");
    showToast("已取消本次导入");
    return;
  }
  const selectedFields = [...$("#clipboard-result").querySelectorAll("[data-import-field]:checked")].map((input) => input.dataset.importField);
  if (!selectedFields.length) {
    showToast("至少选择一个要导入的字段");
    return;
  }
  const mode = action.dataset.importAction;
  if (mode === "replace") {
    const confirmed = await requestConfirm({
      title: "替换所选素材？",
      message: "替换会清空所选字段当前已有内容，再写入本次 AI 识别结果。",
      confirmText: "替换素材",
      danger: true
    });
    if (!confirmed) return;
  }
  captureMaterialUndo(mode === "replace" ? "已替换所选素材" : "已合并所选素材");
  const data = pendingMaterialImport.data;
  applyParsedMaterials(data, selectedFields, mode);
  pendingMaterialImport = null;
  renderClipboardResult(data, false);
  scheduleMaterialPersist();
  showToast(mode === "replace" ? "已替换所选素材" : "已合并所选素材");
});

function applyBookNotesResponse(data) {
  bookNotesState = {
    summary: Array.isArray(data.summary) ? data.summary : [],
    recent: Array.isArray(data.recent) ? data.recent : [],
    books: Array.isArray(data.books) ? data.books : []
  };
  replaceBookCatalog(bookNotesState.books);
  const project = projects[activeProject];
  if (project) {
    project.selected_books = validBookIds(project.selected_books);
    if (!project.selected_books.length && bookNotesState.books.length === 1) {
      project.selected_books = [bookNotesState.books[0].id];
    }
    activeBooks = validBookIds(project.selected_books);
  }
  const total = bookNotesState.summary.reduce((sum, item) => sum + Number(item.count || 0), 0);
  const quotable = bookNotesState.summary.reduce((sum, item) => sum + Number(item.quotable_count || 0), 0);
  $("#library-state").textContent = total ? `${quotable} 条可引用 / ${total} 条总素材` : `${bookNotesState.books.length} 本已接入`;
  renderBooks();
  renderRetrieval();
  renderBookLibraryView();
}

$("#seed-book-notes").addEventListener("click", async () => {
  const button = $("#seed-book-notes");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "导入中";
  renderBookDiagnostics("loading", { title: "正在导入阅读笔记", message: "正在读取你提供的 PDF/docx，并沉淀为精神书库素材。" });
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/book-notes/seed", { method: "POST" });
    const data = await response.json();
    if (!response.ok) {
      const detail = apiErrorPayload(data);
      throw new Error(detail.message || "阅读笔记导入失败");
    }
    applyBookNotesResponse(data);
    await loadLibraryPersonas();
    await loadOnboardingStatus();
    const imported = Array.isArray(data.imported) ? data.imported : [];
    const currentTotal = bookNotesState.summary.reduce((sum, item) => sum + Number(item.count || 0), 0);
    const count = imported.reduce((sum, item) => sum + Number(item.count || 0), 0);
    const message = data.already_available
      ? `已提供的阅读笔记素材已经在书库中，共 ${currentTotal} 条。`
      : `已从 ${imported.length} 份文件沉淀 ${count} 条书库素材，生成文案时会自动调用。`;
    renderBookDiagnostics("success", { title: data.already_available ? "阅读笔记已在书库中" : "阅读笔记已导入", message });
    showToast(data.already_available ? `书库已有 ${currentTotal} 条阅读笔记素材` : `已沉淀 ${count} 条阅读笔记素材`);
  } catch (error) {
    renderBookDiagnostics("failed", { title: "阅读笔记导入失败", message: error.message });
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

$("#book-note-upload").addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = $("#book-note-files").files;
  if (!files.length) {
    showToast("请先选择阅读笔记文件");
    return;
  }
  const form = event.currentTarget;
  const button = form.querySelector('button[type="submit"]');
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "沉淀中";
  renderBookDiagnostics("loading", { title: "正在沉淀阅读笔记", message: "会先解析文件，再按书籍归属保存为可生成调用的素材。" });
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/book-notes/upload", {
      method: "POST",
      body: new FormData(form)
    });
    const data = await response.json();
    if (!response.ok) {
      const detail = apiErrorPayload(data);
      throw new Error(detail.message || "阅读笔记上传失败");
    }
    applyBookNotesResponse(data);
    await loadLibraryPersonas();
    await loadOnboardingStatus();
    const imported = Array.isArray(data.imported) ? data.imported : [];
    const count = imported.reduce((sum, item) => sum + Number(item.count || 0), 0);
    renderBookDiagnostics("success", { title: "阅读笔记已沉淀", message: `已新增 ${count} 条精神书库素材。` });
    form.reset();
    showToast(`已新增 ${count} 条书库素材`);
  } catch (error) {
    renderBookDiagnostics("failed", { title: "阅读笔记沉淀失败", message: error.message });
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});

function renderDistillVersionTimeline(items = []) {
  const target = $("#distill-version-list");
  if (!target) return;
  const formatter = new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
  const versions = Array.isArray(items) ? items.slice(0, 5) : [];
  if (!versions.length) {
    target.innerHTML = '<div class="distill-version-empty">还没有可审核的 Skill 版本。</div>';
    return;
  }
  const statusLabels = { published: "已发布", candidate: "待审核", archived: "历史版本" };
  target.innerHTML = versions.map((item) => {
    const dateValue = item.published_at || item.created_at;
    const date = dateValue ? formatter.format(new Date(dateValue)) : "时间未知";
    const summary = item.evaluation?.summary || item.evaluation?.reason || "保留该版本的规则与审核记录。";
    return `
      <article class="distill-version-item ${escapeHtml(item.status || "archived")}">
        <span class="version-rail-dot" aria-hidden="true"></span>
        <div><strong>${escapeHtml(item.version || "未命名版本")}</strong><p>${escapeHtml(summary)}</p></div>
        <span class="version-timeline-meta"><b>${escapeHtml(statusLabels[item.status] || item.status || "历史版本")}</b><time datetime="${escapeHtml(dateValue || "")}">${escapeHtml(date)}</time></span>
      </article>`;
  }).join("");
}

function formatQualityDuration(value) {
  const seconds = Math.max(0, Number(value || 0));
  if (!seconds) return "—";
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours} 小时${minutes ? ` ${minutes} 分` : ""}`;
}

function renderQualityObservation(data = {}) {
  const sampleCount = Number(data.sample_count || 0);
  const targetSamples = Number(data.target_samples || 5);
  const averages = data.averages || {};
  const adoptionCounts = data.adoption_counts || {};
  const accepted = Number(adoptionCounts.direct || 0) + Number(adoptionCounts.light_edit || 0);
  $("#quality-observation-progress").textContent = `${sampleCount} / ${targetSamples} 个已发布项目`;
  $("#quality-regeneration-count").textContent = sampleCount
    ? Number(averages.regenerations || 0).toFixed(1)
    : "—";
  $("#quality-edit-distance").textContent = sampleCount
    ? `${Math.round(Number(averages.edit_distance_ratio || 0) * 100)}%`
    : "—";
  $("#quality-creation-time").textContent = sampleCount
    ? formatQualityDuration(averages.creation_seconds)
    : "—";
  $("#quality-adoption-count").textContent = sampleCount ? `${accepted} / ${sampleCount}` : "—";
  const target = $("#quality-observation-list");
  const outcomes = Array.isArray(data.outcomes) ? data.outcomes : [];
  if (!outcomes.length) {
    target.innerHTML = '<div class="quality-observation-empty">已开始自动记录；等待下一个真实项目发布后累计。</div>';
    return;
  }
  const adoptionLabels = {
    direct: "直接采用",
    light_edit: "小改采用",
    major_edit: "大改采用",
    no_ai_baseline: "无 AI 基线"
  };
  target.innerHTML = outcomes.map((item) => `
    <article class="quality-observation-item">
      <strong title="${escapeHtml(item.project_title || item.project_id || "未命名项目")}">${escapeHtml(item.project_title || item.project_id || "未命名项目")}</strong>
      <span class="quality-adoption ${escapeHtml(item.adoption_status || "")}">${escapeHtml(adoptionLabels[item.adoption_status] || "已发布")}</span>
      <span>重生成 ${Number(item.regeneration_count || 0)} 次 · 编辑 ${Math.round(Number(item.edit_distance_ratio || 0) * 100)}%</span>
      <span>${escapeHtml(formatQualityDuration(item.creation_duration_seconds))}</span>
    </article>`).join("");
}

async function loadSkillStatus() {
  try {
    const [styleResponse, catalogResponse, qualityResponse] = await Promise.all([
      XZJApi.request("/api/xiangzhongjing/writing-skill"),
      XZJApi.request("/api/xiangzhongjing/skills"),
      XZJApi.request("/api/xiangzhongjing/quality-summary")
    ]);
    if (!styleResponse.ok || !catalogResponse.ok) return;
    const style = await styleResponse.json();
    const catalog = await catalogResponse.json();
    if (qualityResponse.ok) renderQualityObservation(await qualityResponse.json());
    skillStatus = { style, catalog };
    $("#reference-count").textContent = style.reference_documents;
    $("#style-version").textContent = style.published_version;
    $("#candidate-count").textContent = style.candidate_versions;
    $("#style-status").textContent = "已发布";
    $("#skill-count").textContent = `${catalog.skills.length} Skills`;
    $("#deepseek-state").classList.toggle("ready", Boolean(catalog.providers.llm.configured));
    renderDistillVersionTimeline(style.versions);
    pendingStyleCandidate = style.versions.find((item) => item.status === "candidate") || null;
    $("#show-style").textContent = pendingStyleCandidate
      ? `审核 ${style.published_version} / ${pendingStyleCandidate.version}`
      : `查看 ${style.published_version} 风格 DNA`;
    $("#publish-style").classList.toggle("hidden", !pendingStyleCandidate);
    if (pendingStyleCandidate) {
      const needsComparison = pendingStyleCandidate.evaluation?.ab_test_required && !hasCompleteStyleABCopies(pendingStyleCandidate);
      const canOverride = canOverrideStylePublish(pendingStyleCandidate);
      $("#publish-style").disabled = Boolean(needsComparison);
      $("#publish-style").textContent = needsComparison
        ? "先生成完整 A/B"
        : (canOverride ? `确认风险并发布 ${pendingStyleCandidate.version}` : `发布 ${pendingStyleCandidate.version} 候选 Skill`);
      const detailResponse = await XZJApi.request(`/api/xiangzhongjing/style-versions/${pendingStyleCandidate.id}`);
      if (detailResponse.ok) {
        const detail = await detailResponse.json();
        renderStyleReview({
          candidate: detail,
          documents: detail.evidence?.documents || [],
          evidence: detail.evidence || {},
          evaluation: detail.evaluation || pendingStyleCandidate.evaluation || {}
        });
      }
    } else {
      $("#publish-style").disabled = false;
      $("#style-review").classList.add("hidden");
    }
  } catch (error) {
    console.warn("Failed to load skill status", error);
  }
}

$("#show-style").addEventListener("click", () => {
  if (!skillStatus) {
    showToast("Skill 状态仍在加载");
    return;
  }
  openStyleAudit("rules");
});

async function publishPendingStyle(button) {
  if (!pendingStyleCandidate) return;
  const force = canOverrideStylePublish(pendingStyleCandidate);
  button.disabled = true;
  try {
    const response = await XZJApi.request(`/api/xiangzhongjing/style-versions/${pendingStyleCandidate.id}/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        force,
        reason: force ? "创作者完成 A/B 审核并确认候选版本效果满意" : ""
      })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "候选 Skill 发布失败"));
    showToast(`已发布个人创作 Skill ${data.version}`);
    pendingStyleCandidate = null;
    await loadSkillStatus();
    return true;
  } catch (error) {
    showToast(error.message);
    return false;
  } finally {
    button.disabled = false;
  }
}

$("#publish-style").addEventListener("click", async () => {
  await publishPendingStyle($("#publish-style"));
});

$("#reference-upload").addEventListener("change", async (event) => {
  const files = [...event.target.files];
  if (!files.length) return;
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  $("#save-state").textContent = `正在分级蒸馏 ${files.length} 篇历史稿件`;
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/upload-reference-batch", {
      method: "POST",
      body: form
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "稿件蒸馏失败"));
    pendingStyleCandidate = data.candidate;
    $("#save-state").textContent = "候选 Skill 待审核";
    renderStyleReview(data);
    showToast(`已生成 ${data.candidate.version} 候选 Skill，请先做 A/B 对照`);
    await loadSkillStatus();
    await loadOnboardingStatus();
  } catch (error) {
    $("#save-state").textContent = "蒸馏失败";
    showToast(error.message);
  } finally {
    event.target.value = "";
  }
});

$("#rewrite-selection").addEventListener("click", async () => {
  const editor = $("#copy-editor");
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  await requestAiEdit("selection-polish", $("#rewrite-selection"), { start, end });
});

function createNewProject() {
  const id = `project_${Date.now()}`;
  projects[id] = {
    id,
    title: "未命名稿件",
    description: "从一个主题开始，把今天发生的事写成一条属于自己的线。",
    updated: "尚未开始",
    version: "草稿",
    tags: ["待输入"],
    materials: {
      theme: "",
      insight: "",
      opening: "",
      daily: "",
      event: "",
      quotes: "",
      ending_reference: ""
    },
    generation_mode: "fresh",
    book_quote_strategy: "standard",
    clipboard_source: "",
    import_result: null,
    selected_books: defaultBookIds(),
    active_dna_ids: [],
    versions: [],
    locked_paragraphs: [],
    archived: false,
    material_coverage: [],
    copy: "从这里开始写下你的下一条文案。先不用急着完整，告诉我一个主题、一个洞察和一件真实发生的事。"
  };
  activeProject = id;
  persistState("now");
  renderProjects();
  selectProject(id, { openEditor: true });
  switchEditorTab("materials");
}

$("#home-new-project").addEventListener("click", createNewProject);

$("#close-style-audit").addEventListener("click", closeStyleAudit);
$("#style-audit").addEventListener("click", (event) => {
  if (event.target.id === "style-audit") closeStyleAudit();
});
$$("[data-style-audit-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    styleAuditTab = button.dataset.styleAuditTab;
    renderStyleAudit();
  });
  button.addEventListener("keydown", (event) => {
    const tabs = [...$$("[data-style-audit-tab]")];
    const index = tabs.indexOf(button);
    let nextIndex = null;
    if (event.key === "ArrowRight") nextIndex = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") nextIndex = (index - 1 + tabs.length) % tabs.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    styleAuditTab = tabs[nextIndex].dataset.styleAuditTab;
    renderStyleAudit();
    tabs[nextIndex].focus();
  });
});
$("#rerun-style-ab").addEventListener("click", runStyleAuditComparison);
$("#publish-style-audit").addEventListener("click", async () => {
  const published = await publishPendingStyle($("#publish-style-audit"));
  if (published) closeStyleAudit();
});

$("#edit-preview-text").addEventListener("input", () => {
  const text = getEditPreviewText();
  $("#edit-preview-count").textContent = `${text.replace(/\s/g, "").length} 字`;
  if (pendingEdit) pendingEdit.text = text;
});

$("#close-edit-preview").addEventListener("click", closeEditPreview);
$("#cancel-edit-preview").addEventListener("click", closeEditPreview);
$("#edit-preview").addEventListener("click", (event) => {
  if (event.target.id === "edit-preview") closeEditPreview();
});
$("#confirm-cancel").addEventListener("click", () => closeConfirmDialog(false));
$("#confirm-accept").addEventListener("click", () => closeConfirmDialog(true));
$("#confirm-dialog").addEventListener("click", (event) => {
  if (event.target.id === "confirm-dialog") closeConfirmDialog(false);
});

$("#accept-edit-preview").addEventListener("click", async () => {
  if (!pendingEdit) return;
  const editor = $("#copy-editor");
  const nextText = getEditPreviewText();
  const candidateText = pendingEdit.candidate(nextText);
  const lengthStatus = projectLengthStatus(candidateText);
  if (lengthStatus.constrained && !lengthStatus.withinRange) {
    showToast(`修改后为 ${lengthStatus.actual} 字，必须保持在 ${lengthStatus.min}-${lengthStatus.max} 字，暂未应用`);
    return;
  }
  saveVersionSnapshot(`AI 编辑前备份：${pendingEdit.title}`);
  pendingEdit.apply(nextText);
  projects[activeProject].copy = editor.value;
  invalidateMaterialCoverage(projects[activeProject]);
  updateCount();
  renderProjects();
  $("#save-state").textContent = "AI 编辑已应用";
  await persistState("now");
  showToast("已接受 AI 编辑，可从版本记录恢复");
  closeEditPreview();
});

$$("[data-command]").forEach((button) => {
  button.addEventListener("click", () => {
    requestAiEdit(button.dataset.command, button);
  });
});

window.addEventListener("popstate", () => {
  const state = readUrlState();
  applyUrlViewState(state);
  syncArchivedToggle();
  syncMaterialFilterControls();
  if (state.project && projects[state.project] && state.project !== activeProject) {
    selectProject(state.project, { silent: true, persist: false, historyMode: "none" });
  }
  if (state.mode) setGenerationMode(state.mode, false);
  if (state.tab) switchEditorTab(state.tab, { historyMode: "none" });
  renderProjectBoard();
  renderMaterialBoard();
  switchPage(state.page || "workspace", { historyMode: "none", persist: false, instant: true });
});

hydrateState().finally(async () => {
  await loadBookNotesState();
  migrateProjectState();
  const initialUrl = readUrlState();
  const startupReadiness = await loadOnboardingStatus();
  if (initialUrl.project && projects[initialUrl.project]) activeProject = initialUrl.project;
  if (initialUrl.page) activePage = initialUrl.page;
  else if (startupReadiness?.is_blank_install) activePage = "onboarding";
  if (initialUrl.tab) activeEditorTab = initialUrl.tab;
  applyUrlViewState(initialUrl);
  syncArchivedToggle();
  syncMaterialFilterControls();
  renderProjects();
  renderBooks();
  renderRetrieval();
  renderVersions();
  selectProject(activeProject, { silent: true, persist: false, historyMode: "none" });
  if (initialUrl.mode) setGenerationMode(initialUrl.mode, false);
  syncArchivedToggle();
  syncMaterialFilterControls();
  switchEditorTab(activeEditorTab, { historyMode: "none" });
  switchPage(activePage, { historyMode: "replace", persist: false, instant: true });
  window.scrollTo(0, 0);
  loadSkillStatus();
  if (typeof loadDnaReagents === "function") loadDnaReagents();
  loadDialoguePersonas();
  loadLibraryPersonas();
  if (activePage === "mirror" || activePage === "book-person") {
    loadDialogueSessions();
    loadDialogueAssets();
  }
});
