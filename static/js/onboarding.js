"use strict";

let onboardingState = null;

function renderOnboardingStatus(data) {
  onboardingState = data;
  const stages = Array.isArray(data?.stages) ? data.stages : [];
  const progress = data?.progress || { ready: 0, total: stages.length || 7 };
  const value = $("#onboarding-progress-value");
  const label = $("#onboarding-progress-label");
  const list = $("#onboarding-stage-list");
  if (!value || !label || !list) return;
  value.textContent = `${Number(progress.ready || 0)} / ${Number(progress.total || stages.length)}`;
  label.textContent = data?.ready ? "核心能力已就绪" : "继续完成个人化配置";
  list.innerHTML = stages.map((stage, index) => `
    <article class="onboarding-stage ${stage.ready ? "ready" : ""}">
      <span class="onboarding-stage-index">${stage.ready ? "✓" : index + 1}</span>
      <div class="onboarding-stage-copy">
        <strong>${escapeHtml(stage.title || "配置项")}</strong>
        <span>${escapeHtml(stage.detail || "等待配置")}</span>
      </div>
      <button class="${stage.ready ? "outline-button" : "top-action primary"} compact" data-onboarding-page="${escapeHtml(stage.action_page || "workspace")}" type="button">${stage.ready ? "查看" : "去完成"}</button>
    </article>
  `).join("");
  const next = data?.next_stage || stages[stages.length - 1] || null;
  $("#onboarding-next-title").textContent = next?.title || "开始你的第一篇创作";
  $("#onboarding-next-detail").textContent = next?.detail || "核心配置已经完成，可以从一个真实事件开始。";
  const nextButton = $("#onboarding-next-action");
  nextButton.dataset.onboardingPage = next?.action_page || "workspace";
  nextButton.textContent = next ? "继续配置" : "进入创作台";
  $$('[data-onboarding-page]').forEach((button) => {
    button.onclick = () => switchPage(button.dataset.onboardingPage || "workspace");
  });
}

async function loadOnboardingStatus() {
  const list = $("#onboarding-stage-list");
  if (list && !onboardingState) {
    list.innerHTML = '<div class="onboarding-stage"><span class="onboarding-stage-index">···</span><div class="onboarding-stage-copy"><strong>正在检查本地能力</strong><span>读取模型、DNA、书库与对话配置</span></div></div>';
  }
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/onboarding/status");
    if (!response.ok) throw new Error("无法读取首次配置状态");
    const data = await response.json();
    renderOnboardingStatus(data);
    return data;
  } catch (error) {
    if (list) list.innerHTML = `<div class="onboarding-stage"><span class="onboarding-stage-index">!</span><div class="onboarding-stage-copy"><strong>检查失败</strong><span>${escapeHtml(error.message)}</span></div></div>`;
    return null;
  }
}

function selectedPersonaBookIds() {
  return Array.from($("#library-persona-books")?.selectedOptions || []).map((option) => option.value).filter(Boolean);
}

function renderLibraryPersonas(payload) {
  const personas = (Array.isArray(payload?.personas) ? payload.personas : []).filter((item) => item.type === "book");
  const select = $("#library-persona-books");
  const list = $("#library-persona-list");
  if (!select || !list) return;
  const selected = new Set(selectedPersonaBookIds());
  select.innerHTML = Object.values(books).map((book) => `
    <option value="${escapeHtml(book.id)}" ${selected.has(book.id) ? "selected" : ""}>${escapeHtml(book.title)} · ${escapeHtml(book.author)}</option>
  `).join("");
  $("#library-persona-count").textContent = `${personas.length} 位`;
  if (!personas.length) {
    list.innerHTML = '<div class="retrieval-empty"><strong>还没有书中人</strong><span>先导入书籍，再选择人物身份和表达气质。</span></div>';
    return;
  }
  list.innerHTML = personas.map((persona) => {
    const titles = (persona.book_ids || []).map((id) => books[id]?.title || id).join("、");
    return `
      <article class="library-persona-item">
        <div><strong>${escapeHtml(persona.name)}</strong><button class="library-persona-delete" data-delete-book-persona="${escapeHtml(persona.id)}" type="button">删除</button></div>
        <span>${escapeHtml(titles || "未绑定书籍")}</span>
        <p>${escapeHtml(persona.description || persona.voice || "从个人书库出发进行交流。")}</p>
      </article>
    `;
  }).join("");
  $$('[data-delete-book-persona]').forEach((button) => {
    button.onclick = async () => {
      const confirmed = await requestConfirm({
        title: "删除这位书中人？",
        message: "已有会话会继续保留，这位人物将不再出现在新会话选择中。",
        confirmText: "确认删除",
        danger: true
      });
      if (!confirmed) return;
      const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/personas/${encodeURIComponent(button.dataset.deleteBookPersona)}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        showToast(apiError(data, "删除书中人失败"));
        return;
      }
      await loadLibraryPersonas();
      await loadDialoguePersonas();
      showToast("书中人已移出人物列表");
    };
  });
}

async function loadLibraryPersonas() {
  if (!$("#library-persona-list")) return;
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/dialogue/personas");
    if (!response.ok) return;
    renderLibraryPersonas(await response.json());
  } catch (error) {
    console.warn("Failed to load book personas", error);
  }
}

$("#refresh-onboarding")?.addEventListener("click", () => loadOnboardingStatus());
$("#onboarding-next-action")?.addEventListener("click", (event) => {
  switchPage(event.currentTarget.dataset.onboardingPage || "workspace");
});

$("#suggest-library-persona")?.addEventListener("click", async () => {
  const bookIds = selectedPersonaBookIds();
  if (!bookIds.length) {
    showToast("请先选择书中人绑定的书籍");
    return;
  }
  const response = await XZJApi.request("/api/xiangzhongjing/dialogue/personas/suggest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ book_ids: bookIds })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    showToast(apiError(data, "无法生成建议"));
    return;
  }
  const suggestion = data.suggestion || {};
  $("#library-persona-name").value = suggestion.name || "";
  $("#library-persona-description").value = suggestion.description || "";
  $("#library-persona-voice").value = suggestion.voice || "";
});

$("#library-persona-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const bookIds = selectedPersonaBookIds();
  if (!bookIds.length) {
    showToast("请至少绑定一本书");
    return;
  }
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/dialogue/personas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: $("#library-persona-name").value.trim(),
        book_ids: bookIds,
        description: $("#library-persona-description").value.trim(),
        voice: $("#library-persona-voice").value.trim()
      })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(apiError(data, "创建书中人失败"));
    form.reset();
    await loadLibraryPersonas();
    await loadDialoguePersonas();
    await loadOnboardingStatus();
    showToast(`已创建书中人「${data.persona?.name || "新人物"}」`);
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
});

