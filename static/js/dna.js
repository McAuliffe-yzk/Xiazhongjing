"use strict";

let dnaSearchQuery = "";
let dnaEditorTrigger = null;

function activeDnaSet(project = projects[activeProject]) {
  ensureProjectState(project);
  return new Set((project.active_dna_ids || []).map((id) => Number(id)));
}

function renderDnaChips() {
  const target = $("#generation-dna-chips");
  if (!target) return;
  const project = ensureProjectState(projects[activeProject]);
  const activeIds = activeDnaSet(project);
  const selected = dnaReagents.filter((item) => activeIds.has(Number(item.id)));
  if (!dnaReagents.length) {
    target.innerHTML = `<span class="generation-dna-empty">未创建外部试剂</span>`;
    return;
  }
  target.innerHTML = `
    ${selected.length ? selected.map((item) => `
      <button class="generation-dna-chip active" data-dna-toggle="${Number(item.id)}" type="button" title="点击关闭">${escapeHtml(item.name)}</button>
    `).join("") : `<span class="generation-dna-empty">未启用外部试剂</span>`}
    ${dnaReagents.filter((item) => !activeIds.has(Number(item.id))).slice(0, 3).map((item) => `
      <button class="generation-dna-chip" data-dna-toggle="${Number(item.id)}" type="button" title="点击启用">${escapeHtml(item.name)}</button>
    `).join("")}
  `;
}

function renderDnaPage() {
  const list = $("#dna-reagent-list");
  if (!list) return;
  const query = dnaSearchQuery.trim().toLowerCase();
  const project = ensureProjectState(projects[activeProject]);
  const activeIds = activeDnaSet(project);
  const items = dnaReagents.filter((item) => {
    const haystack = `${item.name || ""} ${(item.tags || []).join(" ")} ${item.notes || ""}`.toLowerCase();
    return !query || haystack.includes(query);
  });
  $("#dna-reagent-count").textContent = `${dnaReagents.length} 个试剂`;
  if (!items.length) {
    list.innerHTML = `
      <div class="dna-empty">
        <span class="dna-empty-visual" aria-hidden="true"><img src="/static/icons/dna.svg" alt="" width="34" height="34"></span>
        <div class="dna-empty-copy">
          <strong>${query ? "没有匹配的 DNA 试剂" : "先做第一支风味试剂"}</strong>
          <p>${query ? "换一个名称或标签继续查找。" : "放入一段真正喜欢的创作者文案，系统会提炼语言节奏、叙事习惯和表达偏好。它不会替换你的个人 DNA。"}</p>
          ${query ? "" : '<button class="top-action primary" data-dna-empty-create type="button">开始蒸馏</button>'}
        </div>
        ${query ? "" : `
          <div class="dna-empty-steps" aria-label="创建 DNA 试剂流程">
            <span><b>1</b><i><strong>放入样本</strong><small>至少 300 字完整正文</small></i></span>
            <span><b>2</b><i><strong>蒸馏风味</strong><small>提取可解释的表达特征</small></i></span>
            <span><b>3</b><i><strong>按需启用</strong><small>生成时才参与创作</small></i></span>
          </div>
        `}
      </div>
    `;
    return;
  }
  list.innerHTML = items.map((item) => {
    const active = activeIds.has(Number(item.id));
    const tags = Array.isArray(item.tags) ? item.tags : [];
    return `
      <article class="dna-card ${active ? "active" : ""}">
        <div class="dna-card-main">
          <span class="dna-card-mark"><img src="/static/icons/dna.svg" alt="" width="24" height="24" aria-hidden="true"></span>
          <div>
            <h2>${escapeHtml(item.name)}</h2>
            <p>${escapeHtml(item.notes || "语言风味试剂，仅作为可选调味层。")}</p>
            <div class="dna-card-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || "<span>未标注</span>"}</div>
          </div>
        </div>
        <div class="dna-card-actions">
          <button class="outline-button compact" data-dna-toggle="${Number(item.id)}" type="button">${active ? "从当前项目移除" : "加入当前项目"}</button>
          <button class="outline-button compact" data-dna-detail="${Number(item.id)}" type="button">查看</button>
          <button class="outline-button compact danger" data-dna-delete="${Number(item.id)}" type="button">删除</button>
        </div>
      </article>
    `;
  }).join("");
}

function toggleDnaForActiveProject(reagentId) {
  const project = ensureProjectState(projects[activeProject]);
  const id = Number(reagentId);
  const activeIds = activeDnaSet(project);
  if (activeIds.has(id)) activeIds.delete(id);
  else activeIds.add(id);
  project.active_dna_ids = [...activeIds];
  persistState();
  renderDnaChips();
  renderDnaPage();
}

function openDnaEditor() {
  dnaEditorTrigger = document.activeElement;
  $("#dna-editor")?.classList.remove("hidden");
  $("#dna-name")?.focus();
}

function closeDnaEditor() {
  $("#dna-editor")?.classList.add("hidden");
  $("#dna-create-form")?.reset();
  if (dnaEditorTrigger instanceof HTMLElement) dnaEditorTrigger.focus();
  dnaEditorTrigger = null;
}

async function loadDnaReagents() {
  try {
    const data = await XZJApi.json("/api/xiangzhongjing/dna-reagents");
    dnaReagents = Array.isArray(data.reagents) ? data.reagents : [];
    renderDnaChips();
    renderDnaPage();
  } catch (error) {
    console.warn("Failed to load DNA reagents", error);
    renderDnaChips();
  }
}

async function createDnaReagent(event) {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type='submit']");
  const originalText = submit?.textContent || "";
  if (submit) {
    submit.disabled = true;
    submit.textContent = "蒸馏中…";
  }
  try {
    await XZJApi.json("/api/xiangzhongjing/dna-reagents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("#dna-name").value,
        notes: $("#dna-notes").value,
        source_text: $("#dna-source-text").value,
        source_kind: "paste"
      })
    });
    closeDnaEditor();
    await loadDnaReagents();
    showToast("外部 DNA 试剂已保存");
  } catch (error) {
    showToast(error.message || "DNA 试剂创建失败");
  } finally {
    if (submit) {
      submit.disabled = false;
      submit.textContent = originalText;
    }
  }
}

async function deleteDnaReagent(id) {
  const confirmed = await requestConfirm({
    title: "删除 DNA 试剂？",
    message: "删除后，已启用它的项目会同步移除该试剂，但不会影响已有文案。",
    confirmText: "删除试剂",
    danger: true
  });
  if (!confirmed) return;
  try {
    await XZJApi.json(`/api/xiangzhongjing/dna-reagents/${Number(id)}`, { method: "DELETE" });
    Object.values(projects).forEach((project) => {
      ensureProjectState(project);
      project.active_dna_ids = (project.active_dna_ids || []).filter((value) => Number(value) !== Number(id));
    });
    persistState();
    await loadDnaReagents();
    showToast("DNA 试剂已删除");
  } catch (error) {
    showToast(error.message || "删除失败");
  }
}

document.addEventListener("click", async (event) => {
  if (event.target.closest("[data-dna-empty-create]")) {
    openDnaEditor();
    return;
  }
  const toggle = event.target.closest("[data-dna-toggle]");
  if (toggle) {
    toggleDnaForActiveProject(toggle.dataset.dnaToggle);
    return;
  }
  const detail = event.target.closest("[data-dna-detail]");
  if (detail) {
    try {
      const item = await XZJApi.json(`/api/xiangzhongjing/dna-reagents/${Number(detail.dataset.dnaDetail)}`);
      alert(`${item.name}\n\n${item.content || ""}`);
    } catch (error) {
      showToast(error.message || "读取试剂失败");
    }
    return;
  }
  const del = event.target.closest("[data-dna-delete]");
  if (del) {
    deleteDnaReagent(del.dataset.dnaDelete);
  }
});

$("#generation-dna-manage")?.addEventListener("click", () => switchPage("dna"));
$("#dna-new-reagent")?.addEventListener("click", openDnaEditor);
$("#dna-editor-close")?.addEventListener("click", closeDnaEditor);
$("#dna-editor-cancel")?.addEventListener("click", closeDnaEditor);
$("#dna-create-form")?.addEventListener("submit", createDnaReagent);
$("#dna-search-input")?.addEventListener("input", (event) => {
  dnaSearchQuery = event.target.value || "";
  renderDnaPage();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#dna-editor")?.classList.contains("hidden")) closeDnaEditor();
});
