"use strict";

function setMaterialSaveState(label, state = "saved") {
  const indicator = $("#material-save-state");
  if (indicator) {
    indicator.textContent = label;
    indicator.dataset.state = state;
  }
  if (activePage === "editor" && !$("#editor-materials")?.classList.contains("hidden")) {
    setSaveState(label, state);
  }
}

function coverageFingerprint(project = projects[activeProject]) {
  if (!project) return "";
  const materialText = Object.entries(ensureMaterialItems(project))
    .map(([group, items]) => `${group}:${items.map((item) => item.text.trim()).join("|")}`)
    .join("||");
  return materialSignature(`${project.copy || ""}::${materialText}`);
}

function invalidateMaterialCoverage(project = projects[activeProject]) {
  if (!project) return;
  const hasExistingAudit = Boolean(project.material_coverage?.length || project.material_coverage_state === "current");
  project.material_coverage_state = hasExistingAudit ? "stale" : "empty";
  project.material_coverage_fingerprint = "";
  Object.values(ensureMaterialItems(project)).flat().forEach((item) => {
    if (item.text.trim()) {
      item.usage_status = hasExistingAudit ? "stale" : "stale";
      item.usage_evidence = "";
    }
  });
}

function renderProjectMeta(project = projects[activeProject]) {
  if (!project) return;
  ensureProjectMaterials(project);
  $("#project-title").textContent = project.title || "未命名项目";
  $("#project-description").textContent = project.description || "补充一句这条视频想讲什么。";
  $("#project-theme-input").value = project.title || "";
  $("#project-description-input").value = project.description || "";
}

function scheduleMaterialPersist() {
  window.clearTimeout(materialPersistTimer);
  setMaterialSaveState("保存中", "saving");
  materialPersistTimer = window.setTimeout(async () => {
    const saved = await persistState("now");
    setMaterialSaveState(saved ? "已自动保存" : "保存失败", saved ? "saved" : "failed");
  }, 500);
}

function materialSnapshot() {
  const project = projects[activeProject];
  return JSON.parse(JSON.stringify({
    materials: project.materials,
    material_items: project.material_items,
    material_coverage: project.material_coverage,
    material_coverage_state: project.material_coverage_state,
    material_coverage_version: project.material_coverage_version,
    material_coverage_fingerprint: project.material_coverage_fingerprint,
    title: project.title,
    description: project.description,
    tags: project.tags
  }));
}

function captureMaterialUndo(message) {
  materialUndoState = { snapshot: materialSnapshot(), message };
  const bar = $("#material-undo-bar");
  if (!bar) return;
  $("#material-undo-message").textContent = message;
  bar.classList.remove("hidden");
  window.clearTimeout(captureMaterialUndo.timer);
  captureMaterialUndo.timer = window.setTimeout(() => {
    materialUndoState = null;
    bar.classList.add("hidden");
  }, 10000);
}

function restoreMaterialUndo() {
  if (!materialUndoState) return;
  const project = projects[activeProject];
  Object.assign(project, materialUndoState.snapshot);
  materialUndoState = null;
  $("#material-undo-bar").classList.add("hidden");
  fillMaterials(project);
  renderMaterialBoard();
  scheduleMaterialPersist();
  showToast("已撤销上一次素材修改");
}

function materialSignature(value) {
  return String(value || "").replace(/[\s，。！？；：、“”‘’「」『』（）()【】《》〈〉…—\-.,!?;:'\"]+/g, "").toLowerCase();
}

function materialFilterActive() {
  return Boolean(materialFilters.query || materialFilters.status !== "all");
}

function materialRowMatches(item, group) {
  const query = materialFilters.query.trim().toLowerCase();
  const haystack = `${item.text || ""} ${item.usage_evidence || ""}`.toLowerCase();
  return (!query || haystack.includes(query))
    && (materialFilters.status === "all" || normalizeMaterialUsage(item.usage_status) === materialFilters.status);
}

function updateMaterialSelectionBar() {
  const bar = $("#material-selection-bar");
  if (!bar) return;
  const validIds = new Set(Object.values(ensureMaterialItems(projects[activeProject])).flat().map((item) => item.id));
  [...selectedMaterialIds].forEach((id) => {
    if (!validIds.has(id)) selectedMaterialIds.delete(id);
  });
  bar.classList.toggle("hidden", selectedMaterialIds.size === 0);
  $("#editor-materials")?.classList.toggle("material-selection-mode", materialSelectionMode || selectedMaterialIds.size > 0);
  const toggle = $("#toggle-material-selection");
  if (toggle) {
    toggle.textContent = materialSelectionMode ? "完成批量" : "批量管理";
    toggle.setAttribute("aria-pressed", String(materialSelectionMode));
  }
  $("#material-selected-count").textContent = String(selectedMaterialIds.size);
}

function apiError(data, fallback) {
  if (data && typeof data.detail === "object") {
    return data.detail.message || data.detail.code || fallback;
  }
  return data?.detail || fallback;
}

function apiErrorPayload(data) {
  if (data && typeof data.detail === "object") return data.detail;
  return { code: "REQUEST_FAILED", message: data?.detail || "请求失败" };
}

function ensureProjectMaterials(project) {
  if (!Object.prototype.hasOwnProperty.call(project, "clipboard_source")) {
    project.clipboard_source = "";
  }
  if (!Object.prototype.hasOwnProperty.call(project, "import_result")) {
    project.import_result = null;
  }
  project.materials = {
    theme: "",
    insight: "",
    opening: "",
    daily: "",
    event: "",
    quotes: "",
    ending_reference: "",
    ...(project.materials || {})
  };
  delete project.materials.content_type;
  if (project.materials.extra_thoughts?.trim()) {
    project.materials.insight = [project.materials.insight, project.materials.extra_thoughts]
      .filter((value) => String(value || "").trim())
      .join("\n");
    delete project.materials.extra_thoughts;
  }
  return project.materials;
}

function materialHealth(project) {
  const materials = ensureProjectMaterials(project);
  const items = ensureMaterialItems(project);
  const hasTheme = Boolean(String(materials.theme || "").trim());
  const hasInsight = items.insight.some((item) => String(item.text || "").trim());
  const dailyCount = items.daily.filter((item) => String(item.text || "").trim()).length;
  const eventCount = items.event.filter((item) => String(item.text || "").trim()).length;
  if (hasTheme && hasInsight && (dailyCount + eventCount) >= 4) {
    return { label: "可生成", level: "ready", dailyCount, eventCount };
  }
  if (hasTheme || hasInsight || dailyCount || eventCount) {
    return { label: "待补全", level: "partial", dailyCount, eventCount };
  }
  return { label: "待输入", level: "empty", dailyCount, eventCount };
}

function splitMaterialItems(text) {
  const raw = String(text || "").trim();
  if (!raw) return [];
  const lines = raw
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const candidates = lines.length > 1 ? lines : raw.split(/[；;]/).map((line) => line.trim()).filter(Boolean);
  return candidates
    .map((line) => line.replace(/^\s*(?:\d+|[一二三四五六七八九十]+)[\.、）)]\s*/, "").trim())
    .filter(Boolean);
}

function newMaterialItem(text, group) {
  const config = materialGroupDefinitions[group];
  return {
    id: `material_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    text: String(text || "").trim(),
    priority: config.defaultPriority,
    treatment: config.defaultTreatment,
    usage_status: "stale",
    usage_evidence: ""
  };
}

function ensureMaterialItems(project, forceFromMaterials = false) {
  const materials = ensureProjectMaterials(project);
  if (!project.material_items || typeof project.material_items !== "object") {
    project.material_items = {};
  }
  if (Array.isArray(project.material_items.extra_thoughts)) {
    const legacy = project.material_items.extra_thoughts;
    const current = Array.isArray(project.material_items.insight) ? project.material_items.insight : [];
    project.material_items.insight = [...current, ...legacy].filter((item) => String(item?.text || item || "").trim());
    delete project.material_items.extra_thoughts;
  }
  Object.keys(materialGroupDefinitions).forEach((group) => {
    const legacyItems = splitMaterialItems(materials[group]);
    if (forceFromMaterials || !Array.isArray(project.material_items[group]) || (!project.material_items[group].length && legacyItems.length)) {
      project.material_items[group] = legacyItems.map((text) => newMaterialItem(text, group));
    } else {
      project.material_items[group] = project.material_items[group].map((item) => ({
        ...newMaterialItem(typeof item === "string" ? item : item?.text, group),
        ...(typeof item === "object" && item ? item : {})
      }));
    }
  });
  return project.material_items;
}

function syncLegacyMaterialFields(project = projects[activeProject]) {
  if (!project) return;
  const items = ensureMaterialItems(project);
  const fields = {
    opening: "#material-opening",
    insight: "#material-insight",
    daily: "#material-daily",
    event: "#material-event",
    quotes: "#material-quotes",
    ending_reference: "#material-ending-reference"
  };
  Object.entries(fields).forEach(([group, selector]) => {
    const value = items[group].map((item, index) => `${index + 1}. ${item.text.trim()}`).filter((line) => !/^\d+\.\s*$/.test(line)).join("\n");
    $(selector).value = value;
    project.materials[group] = value;
  });
}

function optionsHtml(options, value) {
  return options.map(([key, label]) => `<option value="${key}" ${key === value ? "selected" : ""}>${label}</option>`).join("");
}

function resizeMaterialTextarea(textarea) {
  if (!textarea) return;
  textarea.style.height = "auto";
  const nextHeight = Math.max(textarea.scrollHeight, 44);
  textarea.style.height = `${nextHeight}px`;
  textarea.style.overflowY = "hidden";
}

function renderMaterialBoard() {
  closeMaterialActionPopover({ restoreFocus: false });
  const project = projects[activeProject];
  if (!project) return;
  const groups = ensureMaterialItems(project);
  if (!materialGroupDefinitions[activeMaterialGroup]) activeMaterialGroup = "opening";
  const config = materialGroupDefinitions[activeMaterialGroup];
  const items = groups[activeMaterialGroup];
  const nonEmptyItems = items.filter((item) => String(item.text || "").trim());
  const visibleItems = items.map((item, index) => ({ item, index })).filter(({ item }) => materialRowMatches(item, activeMaterialGroup));
  const target = $("#material-active-list");

  let totalCount = 0;
  Object.entries(materialGroupDefinitions).forEach(([group, definition]) => {
    const count = groups[group].filter((item) => String(item.text || "").trim()).length;
    totalCount += count;
    $(definition.count).textContent = String(count);
  });
  $("#material-total-count").textContent = String(totalCount);
  $$("[data-material-group-tab]").forEach((button) => {
    const active = button.dataset.materialGroupTab === activeMaterialGroup;
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "true" : "false");
  });
  $("#material-active-kicker").textContent = config.kicker;
  $("#material-active-title").textContent = config.label;
  $("#material-active-description").textContent = config.description;
  $("#add-material-current").textContent = `新增${config.label}`;
  if (!items.length) {
    target.innerHTML = `
      <div class="material-empty-state">
        <span>01</span>
        <strong>还没有${escapeHtml(config.label)}</strong>
        <p>${escapeHtml(config.description)}</p>
        <button class="tool-button strong" data-add-material="${activeMaterialGroup}" type="button">添加第一条</button>
      </div>`;
  } else if (!visibleItems.length) {
    target.innerHTML = `
      <div class="material-empty-state filtered">
        <span>0</span>
        <strong>没有匹配的${escapeHtml(config.label)}</strong>
        <p>清除搜索或筛选条件后再查看。</p>
        <button class="tool-button" data-clear-material-filters type="button">清除筛选</button>
      </div>`;
  } else {
    target.innerHTML = visibleItems.map(({ item, index }) => {
      const status = normalizeMaterialUsage(item.usage_status);
      const expanded = expandedMaterialRows.has(item.id);
      const selected = selectedMaterialIds.has(item.id);
      const evidence = item.usage_evidence || (status === "stale"
        ? "生成或修改文案后，重新分析即可看到这条素材的实际表达。"
        : "当前版本没有记录对应的使用句。");
      return `
        <article class="material-row usage-${escapeHtml(status)} ${expanded ? "expanded" : ""} ${selected ? "selected" : ""}" data-material-id="${escapeHtml(item.id)}" data-material-group="${activeMaterialGroup}">
          <div class="material-row-main">
            <button class="material-drag-handle" data-material-drag-handle draggable="true" type="button" title="拖拽排序" aria-label="拖拽第 ${index + 1} 条素材排序">⋮⋮</button>
            <label class="material-select-target">
              <input class="material-select" data-material-select type="checkbox" aria-label="选择${config.label}第 ${index + 1} 条素材" ${selected ? "checked" : ""}>
            </label>
            <b>${String(index + 1).padStart(2, "0")}</b>
            <textarea data-material-text spellcheck="false" aria-label="编辑${config.label}第 ${index + 1} 条素材" placeholder="写下一条真实素材…">${escapeHtml(item.text)}</textarea>
            <div class="material-row-actions">
              <button class="material-usage ${escapeHtml(status)} material-status-button" data-material-action="evidence" type="button" aria-expanded="${String(expanded)}">${escapeHtml(materialUsageLabels[status] || "待重新分析")}</button>
              <button class="material-more-trigger" data-material-menu-trigger type="button" title="更多操作" aria-label="管理${config.label}第 ${index + 1} 条素材" aria-haspopup="true" aria-controls="material-action-popover" aria-expanded="false">···</button>
            </div>
          </div>
          <div class="material-row-evidence ${expanded ? "" : "hidden"}">
            <span>素材原文 → 当前文案表达</span>
            <div><p>${escapeHtml(item.text || "尚未填写素材")}</p><i>→</i><p>${escapeHtml(evidence)}</p></div>
          </div>
        </article>`;
    }).join("");
  }
  target.querySelectorAll("[data-material-text]").forEach(resizeMaterialTextarea);
  syncLegacyMaterialFields(project);
  renderMaterialCoverage();
  updateMaterialSelectionBar();
}

function renderMaterialCoverage() {
  const project = projects[activeProject];
  if (!project) return;
  const items = Object.values(ensureMaterialItems(project)).flat();
  const nonEmptyItems = items.filter((item) => item.text.trim());

  const coverageState = project.material_coverage_state || (project.material_coverage?.length ? "stale" : "empty");
  const linked = nonEmptyItems.filter((item) => normalizeMaterialUsage(item.usage_status) === "linked").length;
  const unused = nonEmptyItems.filter((item) => normalizeMaterialUsage(item.usage_status) === "unused").length;
  const conflicted = nonEmptyItems.filter((item) => normalizeMaterialUsage(item.usage_status) === "conflicted").length;
  const stale = nonEmptyItems.filter((item) => normalizeMaterialUsage(item.usage_status) === "stale").length;
  const audit = $("#material-draft-audit");
  if (audit) {
    audit.classList.toggle("hidden", coverageState === "empty" && !project.copy?.trim());
    $("#material-draft-audit-summary").textContent = coverageState === "current"
      ? `与 ${project.material_coverage_version || project.version || "当前稿"} 对照：已关联 ${linked}/${nonEmptyItems.length}${stale ? ` · ${stale} 条待同步` : ""}`
      : "素材或文案已修改，当前对照结果需要重新分析。";
    $("#material-draft-audit-detail").textContent = `已关联 ${linked} · 未采用 ${unused} · 有冲突 ${conflicted} · 待重新分析 ${stale}`;
    audit.dataset.state = coverageState;
  }
}

function applyMaterialCoverage(coverage) {
  const project = projects[activeProject];
  if (!project || !Array.isArray(coverage)) return;
  const itemsByGroup = ensureMaterialItems(project);
  Object.entries(itemsByGroup).forEach(([group, items]) => {
    items.forEach((item) => {
      const match = coverage.find((candidate) => candidate && (
        String(candidate.id || "") === String(item.id || "") ||
        (candidate.group === group && String(candidate.text || "").trim() === String(item.text || "").trim())
      ));
      item.usage_status = normalizeMaterialUsage(match?.status || "unused");
      item.usage_evidence = match?.draft_evidence || match?.reason || "";
    });
  });
  project.material_coverage = coverage;
  project.material_coverage_state = "current";
  project.material_coverage_version = project.version || "当前稿";
  project.material_coverage_fingerprint = coverageFingerprint(project);
  renderMaterialBoard();
}

function updateMaterialPreviews() {
  renderMaterialBoard();
}

function formatStructuredItems(items) {
  if (!Array.isArray(items)) return "";
  return items
    .map((item, index) => {
      const text = typeof item === "object" ? (item.text || item.label || "") : item;
      return `${index + 1}. ${String(text || "").trim()}`;
    })
    .filter((line) => line.replace(/^\d+\.\s*/, "").trim())
    .join("\n");
}

const materialImportFields = [
  { key: "theme", label: "主题", kind: "scalar" },
  { key: "insight", label: "观点洞察", kind: "list" },
  { key: "opening", label: "开场构想", kind: "list" },
  { key: "daily", label: "日常素材", kind: "list" },
  { key: "event", label: "核心事件", kind: "list" },
  { key: "quotes", label: "对话与原句", kind: "list" },
  { key: "ending_reference", label: "收束意象", kind: "list" }
];

function importFieldValue(data, field) {
  const value = data?.materials?.[field.key];
  return String(value || "").trim();
}

function importFieldPreview(data, field) {
  const value = importFieldValue(data, field);
  if (!value) return [];
  return field.kind === "list" ? splitMaterialItems(value) : [value];
}

function appendMaterialText(existing, incoming, kind = "block") {
  const oldValue = String(existing || "").trim();
  const newValue = String(incoming || "").trim();
  if (!newValue) return oldValue;
  if (!oldValue) return newValue;
  if (kind === "list") {
    const lines = splitMaterialItems(oldValue);
    const known = new Set(lines.map(materialSignature));
    splitMaterialItems(newValue).forEach((line) => {
      const signature = materialSignature(line);
      if (signature && !known.has(signature)) {
        lines.push(line);
        known.add(signature);
      }
    });
    return lines.map((line, index) => `${index + 1}. ${line}`).join("\n");
  }
  if (materialSignature(oldValue).includes(materialSignature(newValue))) return oldValue;
  return `${oldValue}\n\n${newValue}`;
}

function replaceMaterialItems(project, group, value, mode) {
  const items = ensureMaterialItems(project)[group] || [];
  const incoming = splitMaterialItems(value);
  if (mode === "replace") {
    project.material_items[group] = incoming.map((text) => newMaterialItem(text, group));
    return;
  }
  const known = new Set(items.map((item) => materialSignature(item.text)).filter(Boolean));
  const nextItems = items.filter((item) => String(item.text || "").trim());
  incoming.forEach((text) => {
    const signature = materialSignature(text);
    if (signature && !known.has(signature)) {
      nextItems.push(newMaterialItem(text, group));
      known.add(signature);
    }
  });
  project.material_items[group] = nextItems;
}

function renderClipboardResult(data, pending = false) {
  const result = $("#clipboard-result");
  if (!data) {
    result.innerHTML = "";
    result.classList.add("hidden");
    return;
  }
  const section = (field) => {
    const list = importFieldPreview(data, field);
    if (!list.length) return "";
    return `
      <label class="import-section ${pending ? "pending" : "committed"}">
        ${pending ? `<input type="checkbox" data-import-field="${field.key}" checked>` : '<span class="import-checkmark">已导入</span>'}
        <span class="import-section-body">
          <strong>${field.label}<small>${list.length} 条</small></strong>
          ${list.slice(0, 5).map((text, index) => `<span class="import-preview-line"><b>${String(index + 1).padStart(2, "0")}</b>${escapeHtml(text)}</span>`).join("")}
          ${list.length > 5 ? `<em>还有 ${list.length - 5} 条</em>` : ""}
        </span>
      </label>
    `;
  };
  result.innerHTML = `
    <div class="import-result-head">
      <div><strong>${pending ? "识别结果待确认" : "最近一次导入"}</strong><span>${pending ? "选择要写入的字段，原有素材不会被静默覆盖" : "已写入当前项目，可继续编辑"}</span></div>
      ${pending ? `<span class="import-pending-badge">未写入</span>` : `<span class="import-committed-badge">已写入</span>`}
    </div>
    ${data.import_summary ? `<p class="import-summary">${escapeHtml(data.import_summary)}</p>` : ""}
    <div class="import-section-grid">${materialImportFields.map(section).join("")}</div>
    ${pending ? `
      <div class="import-result-actions">
        <button class="tool-button" data-import-action="cancel" type="button">取消</button>
        <button class="tool-button" data-import-action="merge" type="button">合并所选</button>
        <button class="tool-button strong" data-import-action="replace" type="button">替换所选</button>
      </div>
    ` : ""}
  `;
  result.classList.remove("hidden");
}

function applyParsedMaterials(data, selectedFields, mode = "merge") {
  const parsed = data.materials || {};
  const project = projects[activeProject];
  project.clipboard_source = $("#clipboard-source").value;
  project.import_result = data;
  const current = ensureProjectMaterials(project);
  selectedFields.forEach((key) => {
    const field = materialImportFields.find((candidate) => candidate.key === key);
    if (!field) return;
    const incoming = importFieldValue(data, field);
    if (!incoming) return;
    if (field.kind === "list") {
      replaceMaterialItems(project, key, incoming, mode);
      return;
    }
    current[key] = mode === "replace" ? incoming : (field.kind === "scalar" ? (current[key] || incoming) : appendMaterialText(current[key], incoming, field.kind));
  });
  project.materials = { ...current };
  syncLegacyMaterialFields(project);
  const themeChanged = selectedFields.includes("theme") && Boolean(importFieldValue(data, materialImportFields[0]));
  const insightChanged = selectedFields.includes("insight") && Boolean(importFieldValue(data, materialImportFields[2]));
  if (themeChanged && (mode === "replace" || !project.title || project.title === "未命名项目")) project.title = current.theme || project.title;
  if (insightChanged && (mode === "replace" || !project.description)) project.description = current.insight || project.description;
  const dailyCount = ensureMaterialItems(project).daily.filter((item) => item.text.trim()).length;
  const eventCount = ensureMaterialItems(project).event.filter((item) => item.text.trim()).length;
  project.tags = [...new Set([...(project.tags || []), current.theme || "", dailyCount ? `${dailyCount}日常` : "", eventCount ? `${eventCount}事件` : ""].filter(Boolean))];
  $("#project-title").textContent = project.title;
  $("#breadcrumb-title").textContent = project.title;
  $("#project-description").textContent = project.description;
  invalidateMaterialCoverage(project);
  renderProjectMeta(project);
  renderProjects();
  renderProjectBoard();
  updateWorkspaceSummary();
  renderMaterialBoard();
}
