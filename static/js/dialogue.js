"use strict";

function getDialogueThinkingState() {
  return typeof window.dialogueThinkingState === "string" ? window.dialogueThinkingState : "idle";
}

function setDialogueThinkingState(state) {
  window.dialogueThinkingState = state;
}

function setDialogueRuntimeProgress(stage = "", label = "", meta = {}) {
  dialogueRuntimeProgress = { stage, label, meta };
  window.dialogueRuntimeProgress = dialogueRuntimeProgress;
}

function dialoguePersonaById(id) {
  return dialoguePersonas.find((item) => item.id === id) || null;
}

function currentDialoguePersona() {
  if (dialogueMode === "mirror") return dialoguePersonas.find((item) => item.id === "mirror-self") || null;
  const active = dialoguePersonaById(activeDialoguePersona);
  return (active?.type === "book" ? active : null) || dialoguePersonas.find((item) => item.type === "book") || null;
}

function renderDialogueContext() {
  if (!$("#dialogue-context-list")) return;
  const persona = currentDialoguePersona();
  const contextPanel = $("#dialogue-context-panel");
  const workspace = $(".dialogue-workspace");
  const memoryItems = activeDialogueMemory && typeof activeDialogueMemory === "object"
    ? Object.keys(activeDialogueMemory).length
    : 0;
  $("#dialogue-project-binding").textContent = "独立交流";
  $("#dialogue-context-list").innerHTML = `
    <div><strong>当前人格</strong><span>${escapeHtml(persona?.name || "镜中人")} · ${escapeHtml(persona?.label || persona?.description || "个人风格与长期人设")}</span></div>
    <div><strong>对话记忆</strong><span>${activeDialogueMessages.length ? `本会话 ${activeDialogueMessages.length} 条消息` : "从第一句话开始建立"}${memoryItems ? " · 已有长期摘要" : ""}</span></div>
    <div><strong>个人记忆引擎</strong><span>${Number(dialogueMemoryEngineStatus.documents || 0)} 篇文稿 · ${Number(dialogueMemoryEngineStatus.total_chunks || 0)} 个原文片段 · ${Number(dialogueMemoryEngineStatus.active_memories || 0)} 条确认记忆</span></div>
    <div class="dialogue-context-counts">
      <span><b>交流范围</b>开放</span>
      <span><b>写入方式</b>全局沉淀</span>
    </div>
  `;
  contextPanel?.classList.toggle("open", dialogueContextOpen);
  contextPanel?.classList.toggle("hidden", !dialogueContextOpen);
  workspace?.classList.toggle("has-context-panel", dialogueContextOpen);
  const contextToggle = $("#dialogue-context-toggle");
  if (contextToggle) {
    contextToggle.textContent = activePage === "assets" ? "返回对话" : "资产库";
    contextToggle.setAttribute("aria-pressed", String(activePage === "assets"));
    contextToggle.setAttribute("aria-label", activePage === "assets" ? "返回对话页面" : "查看沉淀资产库");
    if (contextPanel) {
      contextPanel.style.top = "";
      contextPanel.style.right = "";
      contextPanel.style.maxHeight = "";
    }
  }
}

function renderDialoguePersona() {
  const persona = currentDialoguePersona();
  const isBook = dialogueMode === "book";
  const bookPersonas = dialoguePersonas.filter((item) => item.type === "book");
  $("#dialogue-hero-kicker").textContent = isBook ? "BOOK PERSON" : "MIRROR SELF";
  $("#dialogue-hero-title").textContent = isBook ? "书中人" : "镜中人";
  $("#dialogue-hero-copy").textContent = isBook
    ? "和精神书库中的思想人格开放交流。它不绑定项目，适合用来问取舍、行动、心气和长期主义。"
    : "和被蒸馏出来的自己开放交流。它不绑定项目，只把值得留下的念头沉淀为全局对话资产。";
  $$("[data-dialogue-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.dialogueMode === dialogueMode);
  });
  $("#dialogue-persona-picker").classList.add("hidden");
  $("#dialogue-use-search").closest("label").classList.toggle("hidden", !isBook);
  $("#dialogue-mode-label").textContent = isBook ? "BOOK PERSON" : "MIRROR SELF";
  $("#dialogue-chat-avatar").textContent = isBook ? (persona?.name || "书").slice(0, 1) : "镜";
  $("#dialogue-chat-title").textContent = isBook ? `和${persona?.name || "书中人"}聊一聊` : "和镜中人聊一聊";
  $("#dialogue-chat-subtitle").textContent = activeDialogueSession
    ? `${activeDialogueMessages.length} 条消息 · 独立交流`
    : "独立交流 · 全局沉淀";
  $("#dialogue-input").placeholder = isBook
    ? "和这个人物聊聊"
    : "随便说点什么";
  $("#dialogue-persona-card").innerHTML = `
    <span>${escapeHtml(persona?.type === "book" ? "书中人" : "镜中人")}</span>
    <strong>${escapeHtml(persona?.name || "镜中人")}</strong>
    <p>${escapeHtml(persona?.description || "基于个人风格、人设资产和长期记忆进行交流。")}</p>
  `;
  $("#dialogue-persona-picker").innerHTML = "";
  $("#dialogue-persona-dock").classList.toggle("hidden", !isBook);
  $("#dialogue-persona-dock").innerHTML = isBook && !bookPersonas.length ? `
    <div class="dialogue-persona-dock-label">
      <span>还没有书中人</span>
      <strong>先从精神书库创建</strong>
    </div>
    <button class="top-action primary" data-page="library" type="button">前往书库</button>
  ` : isBook ? `
    <div class="dialogue-persona-dock-label">
      <span>当前书中人</span>
      <strong>${escapeHtml(persona?.name || "选择人物")}</strong>
    </div>
    <div class="dialogue-persona-dock-options">
      ${bookPersonas.map((item) => `
        <button class="${item.id === activeDialoguePersona ? "active" : ""}" data-dialogue-persona="${escapeHtml(item.id)}" type="button">
          <strong>${escapeHtml(item.name)}</strong>
          <span>${escapeHtml(item.label || item.description || "")}</span>
        </button>
      `).join("")}
    </div>
  ` : "";
  const dialogueInput = $("#dialogue-input");
  const newSessionButton = $("#new-dialogue-session");
  if (dialogueInput) dialogueInput.disabled = isBook && !bookPersonas.length;
  if (newSessionButton) newSessionButton.disabled = isBook && !bookPersonas.length;
  $("#dialogue-persona-dock [data-page='library']")?.addEventListener("click", () => switchPage("library"));
  renderDialogueFlow();
}

function sessionMatchesDialogue(session) {
  if (!session || session.mode !== dialogueMode) return false;
  if (dialogueTrashMode ? !session.deleted_at : session.deleted_at) return false;
  if (dialogueMode === "book") return session.persona_id === activeDialoguePersona;
  return true;
}

const dialogueExtractLabels = {
  theme: "沉淀为主题念头",
  insight: "沉淀为观点洞察",
  opening: "沉淀为开场句",
  daily: "沉淀为生活片段",
  event: "沉淀为事件判断",
  quote: "沉淀为对话金句",
  quotes: "沉淀为对话金句",
  ending_reference: "沉淀为收束意象",
  persona_asset: "沉淀为人设资产"
};

function normalizeDialogueExtractType(type) {
  const raw = String(type || "thought").trim();
  return raw === "quotes" ? "quote" : raw;
}

function dialogueExtractLabel(type) {
  const normalized = normalizeDialogueExtractType(type);
  return dialogueExtractLabels[normalized] || "思考资产";
}

function dialogueAssetType(type) {
  const normalized = normalizeDialogueExtractType(type);
  return normalized === "persona_asset" ? "creator_belief" : `dialogue_${normalized}`;
}

const dialogueAssetTypeOptions = [
  ["dialogue_theme", "主题念头"],
  ["dialogue_insight", "观点洞察"],
  ["dialogue_opening", "开场句"],
  ["dialogue_daily", "生活片段"],
  ["dialogue_event", "事件判断"],
  ["dialogue_quote", "对话金句"],
  ["dialogue_ending_reference", "收束意象"],
  ["creator_belief", "人设资产"]
];

function dialogueAssetTypeLabel(type) {
  const normalized = String(type || "").replace(/^dialogue_/, "");
  const labels = {
    theme: "主题念头",
    insight: "观点洞察",
    opening: "开场句",
    daily: "生活片段",
    event: "事件判断",
    quote: "对话金句",
    ending_reference: "收束意象",
    creator_belief: "人设资产",
    persona_asset: "人设资产"
  };
  return labels[normalized] || "思考资产";
}

function canonicalDialogueAssetType(type) {
  const normalized = normalizedDialogueAssetType({ asset_type: type });
  return normalized === "creator_belief" || normalized === "persona_asset"
    ? "creator_belief"
    : `dialogue_${normalized || "insight"}`;
}

function renderAssetTypeSelect(asset, compact = false) {
  const current = canonicalDialogueAssetType(asset.asset_type);
  return `
    <label class="${compact ? "asset-type-inline compact" : "asset-type-inline"}">
      <span>所属类别</span>
      <select data-asset-type-update="${escapeHtml(asset.id)}" aria-label="更改沉淀素材所属类别">
        ${dialogueAssetTypeOptions.map(([value, label]) => `
          <option value="${escapeHtml(value)}" ${value === current ? "selected" : ""}>${escapeHtml(label)}</option>
        `).join("")}
      </select>
    </label>
  `;
}

function normalizedDialogueAssetType(asset) {
  return String(asset?.asset_type || "").replace(/^dialogue_/, "");
}

function dialogueAssetOriginMode(asset) {
  const mode = asset?.origin?.mode;
  if (mode === "mirror" || mode === "book" || mode === "manual") return mode;
  const sourceLabel = String(asset?.source_label || "");
  if (sourceLabel.includes("镜中人")) return "mirror";
  if (sourceLabel.includes("书中人") || ["马斯克", "陈平安", "齐静春", "老子"].some((name) => sourceLabel.includes(name))) return "book";
  return "manual";
}

function dialogueAssetOriginLabel(asset) {
  if (asset?.origin?.persona_name) return asset.origin.persona_name;
  const mode = dialogueAssetOriginMode(asset);
  if (mode === "mirror") return "镜中人";
  if (mode === "book") return "书中人";
  return "手动沉淀";
}

function filteredDialogueAssets({ scope = "all", type = dialogueAssetTypeFilter, query = dialogueAssetQuery } = {}) {
  const normalizedQuery = String(query || "").trim().toLowerCase();
  return dialogueAssets.filter((asset) => {
    const normalizedType = normalizedDialogueAssetType(asset);
    const matchesType = type === "all" || normalizedType === type;
    const matchesScope = scope === "all" || dialogueAssetOriginMode(asset) === scope;
    const searchText = [
      asset.title,
      asset.content,
      asset.source_label,
      asset.source,
      dialogueAssetOriginLabel(asset),
      dialogueAssetTypeLabel(asset.asset_type)
    ].filter(Boolean).join(" ").toLowerCase();
    return matchesScope && matchesType && (!normalizedQuery || searchText.includes(normalizedQuery));
  });
}

function renderDialogueAssets() {
  const target = $("#dialogue-asset-list");
  const summary = $("#dialogue-asset-summary");
  if (!target || !summary) return;
  if (dialogueAssetsLoading) {
    summary.textContent = "正在加载沉淀资产";
    target.innerHTML = `<div class="dialogue-asset-empty"><strong>正在加载资产库</strong><p>读取镜中人、书中人和历史文稿记忆中的沉淀素材。</p></div>`;
    renderDialogueAssetPage();
    return;
  }
  const filteredAssets = filteredDialogueAssets({ scope: "all" });
  summary.textContent = dialogueAssetQuery.trim() || dialogueAssetTypeFilter !== "all"
    ? `${filteredAssets.length} / ${dialogueAssets.length} 条资产 · ${dialogueReferenceMemoryCount || 0} 篇历史文稿记忆`
    : `${dialogueAssets.length} 条资产 · ${dialogueReferenceMemoryCount || 0} 篇历史文稿记忆`;
  if (!dialogueAssets.length) {
    target.innerHTML = `
      <div class="dialogue-asset-empty">
        <strong>还没有沉淀资产</strong>
        <p>和镜中人或书中人聊完后，点击回复下方的沉淀按钮，这里会记录来源和内容。</p>
      </div>
    `;
    renderDialogueAssetPage();
    return;
  }
  if (!filteredAssets.length) {
    target.innerHTML = `
      <div class="dialogue-asset-empty">
        <strong>没有符合条件的资产</strong>
        <p>换一个关键词或切换类型筛选，继续查看全部沉淀内容。</p>
      </div>
    `;
    renderDialogueAssetPage();
    return;
  }
  target.innerHTML = filteredAssets.slice(0, 100).map((asset) => `
    <article class="dialogue-asset-item">
      <div>
        <span>${escapeHtml(dialogueAssetTypeLabel(asset.asset_type))}</span>
        <time>${escapeHtml(formatDialogueTime(asset.created_at))}</time>
      </div>
      <strong>${escapeHtml(asset.title || dialogueAssetTypeLabel(asset.asset_type))}</strong>
      <p>${escapeHtml(asset.content || "")}</p>
      <small>来源：${escapeHtml(asset.source_label || asset.source || "手动沉淀")}</small>
      ${renderAssetTypeSelect(asset, true)}
    </article>
  `).join("");
  renderDialogueAssetPage();
}

function renderDialogueAssetPage() {
  const board = $("#asset-category-board");
  const summary = $("#asset-page-summary");
  const statGrid = $("#asset-summary-grid");
  if (!board || !summary || !statGrid) return;
  if (dialogueAssetsLoading) {
    summary.textContent = "正在加载资产";
    $("#asset-page-owner").textContent = "读取中";
    statGrid.innerHTML = ["总资产", "镜中人", "书中人", "当前筛选"].map((label) => `
      <div class="asset-stat-card loading"><span>${escapeHtml(label)}</span><strong>...</strong><small>加载中</small></div>
    `).join("");
    board.innerHTML = `<div class="asset-page-empty"><strong>正在整理资产库</strong><p>正在读取对话沉淀、来源标签和分类结果。</p></div>`;
    return;
  }
  const filteredAssets = filteredDialogueAssets({ scope: dialogueAssetScope });
  const scopedAssets = filteredDialogueAssets({ scope: dialogueAssetScope, type: "all", query: "" });
  const mirrorCount = dialogueAssets.filter((asset) => dialogueAssetOriginMode(asset) === "mirror").length;
  const bookCount = dialogueAssets.filter((asset) => dialogueAssetOriginMode(asset) === "book").length;
  const scopeLabels = { all: "全部来源", mirror: "镜中人", book: "书中人" };
  $("#asset-page-summary").textContent = `${filteredAssets.length} / ${dialogueAssets.length} 条资产 · ${dialogueReferenceMemoryCount || 0} 篇历史文稿记忆`;
  $("#asset-page-owner").textContent = `${scopeLabels[dialogueAssetScope] || "全部来源"} · ${scopedAssets.length} 条`;
  $("#asset-page-search").value = dialogueAssetQuery;
  $("#asset-page-type-filter").value = dialogueAssetTypeFilter;
  $$("[data-asset-scope]").forEach((button) => {
    const active = button.dataset.assetScope === dialogueAssetScope;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  statGrid.innerHTML = [
    ["总资产", dialogueAssets.length, "全部主动沉淀素材"],
    ["镜中人", mirrorCount, "来自自我对话"],
    ["书中人", bookCount, "来自精神书库人物"],
    ["当前筛选", filteredAssets.length, "正在显示的结果"]
  ].map(([label, value, hint]) => `
    <div class="asset-stat-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value))}</strong>
      <small>${escapeHtml(hint)}</small>
    </div>
  `).join("");
  if (!dialogueAssets.length) {
    board.innerHTML = `
      <div class="asset-page-empty">
        <strong>还没有沉淀资产</strong>
        <p>回到镜中人或书中人，在有价值的回复下点击沉淀按钮，这里会按来源和类型自动归档。</p>
      </div>
    `;
    return;
  }
  if (!filteredAssets.length) {
    board.innerHTML = `
      <div class="asset-page-empty">
        <strong>没有符合条件的素材</strong>
        <p>切换来源、类型或关键词，或者清空筛选后查看全部沉淀内容。</p>
        <button class="top-action" data-clear-asset-filters type="button">清空筛选</button>
      </div>
    `;
    return;
  }
  const categoryOrder = ["theme", "insight", "opening", "daily", "event", "quote", "ending_reference", "creator_belief"];
  const groups = categoryOrder
    .map((type) => [type, filteredAssets.filter((asset) => normalizedDialogueAssetType(asset) === type)])
    .filter(([, assets]) => assets.length);
  const uncategorized = filteredAssets.filter((asset) => !categoryOrder.includes(normalizedDialogueAssetType(asset)));
  if (uncategorized.length) groups.push(["other", uncategorized]);
  board.innerHTML = groups.map(([type, assets]) => `
    <section class="asset-category-column">
      <header>
        <div>
          <span>${escapeHtml(dialogueAssetTypeLabel(type))}</span>
          <strong>${assets.length}</strong>
        </div>
      </header>
      <div class="asset-category-list">
        ${assets.map((asset) => `
          <article class="asset-library-card">
            <div class="asset-card-meta">
              <span>${escapeHtml(dialogueAssetOriginLabel(asset))}</span>
              <time>${escapeHtml(formatDialogueTime(asset.created_at))}</time>
            </div>
            <strong>${escapeHtml(asset.title || dialogueAssetTypeLabel(asset.asset_type))}</strong>
            <p>${escapeHtml(asset.content || "")}</p>
            <small>来源：${escapeHtml(asset.source_label || asset.source || "手动沉淀")}</small>
            ${renderAssetTypeSelect(asset)}
          </article>
        `).join("")}
      </div>
    </section>
  `).join("");
}

async function loadDialogueAssets() {
  dialogueAssetsLoading = true;
  renderDialogueAssets();
  try {
    const [response, memoryResponse] = await Promise.all([
      XZJApi.request("/api/xiangzhongjing/dialogue/assets?limit=300"),
      XZJApi.request("/api/xiangzhongjing/dialogue/memory/status")
    ]);
    if (!response.ok) return;
    const data = await response.json();
    if (memoryResponse.ok) dialogueMemoryEngineStatus = await memoryResponse.json();
    dialogueAssets = Array.isArray(data.assets) ? data.assets : [];
    dialogueReferenceMemoryCount = Number(data.reference_memory_count || 0);
    renderDialogueAssets();
    renderDialogueAssetPage();
    renderDialogueContext();
  } catch (error) {
    console.warn("Failed to load dialogue assets", error);
  } finally {
    dialogueAssetsLoading = false;
    renderDialogueAssets();
  }
}

async function updateDialogueAssetType(assetId, assetType, select) {
  const asset = dialogueAssets.find((item) => item.id === assetId);
  if (!asset || asset.asset_type === assetType) return;
  const previousType = asset.asset_type;
  asset.asset_type = assetType;
  renderDialogueAssets();
  try {
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/assets/${encodeURIComponent(assetId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ asset_type: assetType })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "类别更新失败"));
    const updated = data.asset;
    dialogueAssets = dialogueAssets.map((item) => item.id === assetId ? { ...item, ...updated } : item);
    renderDialogueAssets();
    showToast(`已改为「${dialogueAssetTypeLabel(assetType)}」`);
  } catch (error) {
    const current = dialogueAssets.find((item) => item.id === assetId);
    if (current) current.asset_type = previousType;
    renderDialogueAssets();
    if (select) select.value = canonicalDialogueAssetType(previousType);
    showToast(error.message || "类别更新失败");
  }
}

function renderDialogueSessions() {
  const target = $("#dialogue-session-list");
  if (!target) return;
  const panel = $(".dialogue-session-panel");
  panel?.classList.toggle("trash-mode", dialogueTrashMode);
  const persona = currentDialoguePersona();
  $("#dialogue-session-title").textContent = dialogueTrashMode ? "最近删除" : "最近会话";
  $("#dialogue-session-caption").textContent = dialogueMode === "book"
    ? `${persona?.name || "书中人"} · ${dialogueTrashMode ? "删除记录" : "只显示当前人物会话"}`
    : (dialogueTrashMode ? "镜中人删除记录" : "镜中人全部会话");
  if (dialogueSessionsLoading) {
    const listHead = $(".dialogue-session-list-head");
    if (listHead) {
      listHead.innerHTML = `<span>${dialogueTrashMode ? "最近删除" : "最近会话"}</span><b>...</b>`;
    }
    target.innerHTML = `
      <div class="dialogue-session-loading">
        <span></span><span></span><span></span>
        <p>正在加载${dialogueTrashMode ? "最近删除" : "最近会话"}...</p>
      </div>
    `;
    return;
  }
  const visible = dialogueSessions.filter((session) => sessionMatchesDialogue(session));
  const listHead = $(".dialogue-session-list-head");
  if (listHead) {
    listHead.innerHTML = `
      <span>${dialogueTrashMode ? "最近删除" : "最近会话"}</span>
      <span class="dialogue-session-head-actions">
        <b>${visible.length}</b>
        ${visible.length ? `<button type="button" data-dialogue-bulk-clear>${dialogueTrashMode ? "清空" : "清空"}</button>` : ""}
      </span>
    `;
  }
  if (!visible.length) {
    const label = dialogueMode === "mirror" ? "镜中人" : "书中人";
    const isTrash = dialogueTrashMode;
    target.innerHTML = `
      <div class="dialogue-empty">
        <span class="dialogue-empty-mark">${dialogueMode === "mirror" ? "镜" : "书"}</span>
        <strong>${isTrash ? "最近删除为空" : `还没有${label}会话`}</strong>
        <p>${isTrash ? "删除会话保留 7 天。" : (dialogueMode === "mirror" ? "从一个念头开始，和自己聊聊。" : "选好人物后，新建一段对话。")}</p>
        ${isTrash ? "" : `<button class="outline-button compact" data-new-dialogue-session type="button">开始新会话</button>`}
      </div>
    `;
    return;
  }
  target.innerHTML = visible.map((session) => `
    <article class="dialogue-session-item ${session.id === activeDialogueSession ? "active" : ""} ${session.deleted_at ? "deleted" : ""}">
      <button class="dialogue-session-main" data-dialogue-session="${escapeHtml(session.id)}" type="button">
        <span class="dialogue-session-avatar" aria-hidden="true">${escapeHtml(session.mode === "mirror" ? "镜" : (dialoguePersonaById(session.persona_id)?.name || "书").slice(0, 1))}</span>
        <span class="dialogue-session-copy">
          <strong>${escapeHtml(session.title || "未命名会话")}</strong>
          <span>${escapeHtml(session.last_message_preview || "还没有消息")}</span>
        </span>
        <time datetime="${escapeHtml(session.last_message_at || session.updated_at || session.created_at || "")}">${escapeHtml(formatDialogueTime(session.last_message_at || session.updated_at || session.created_at))}</time>
      </button>
      <button class="dialogue-session-more" data-dialogue-session-menu="${escapeHtml(session.id)}" type="button" aria-label="${escapeHtml(session.title || "会话")}操作" title="会话操作">···</button>
    </article>
  `).join("");
}

async function bulkClearDialogueSessions() {
  const visible = dialogueSessions.filter((session) => sessionMatchesDialogue(session));
  if (!visible.length) {
    showToast(dialogueTrashMode ? "最近删除为空" : "当前没有可清空的会话");
    return;
  }
  const persona = currentDialoguePersona();
  const scope = dialogueMode === "book"
    ? `书中人「${persona?.name || "当前人物"}」`
    : "镜中人";
  const confirmed = await requestConfirm({
    title: dialogueTrashMode ? "永久清空最近删除？" : "清空当前会话列表？",
    message: dialogueTrashMode
      ? `将永久删除 ${scope} 最近删除中的 ${visible.length} 段会话，聊天记录和会话记忆无法恢复；已沉淀资产仍会保留。`
      : `将把 ${scope} 当前列表中的 ${visible.length} 段会话移入最近删除，已沉淀资产仍会保留。`,
    confirmText: dialogueTrashMode ? "永久清空" : "清空会话",
    danger: true
  });
  if (!confirmed) return;
  const ids = visible.map((session) => session.id);
  const response = await XZJApi.request("/api/xiangzhongjing/dialogue/sessions/bulk-delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_ids: ids,
      permanent: dialogueTrashMode
    })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(apiError(data, "批量清空失败"));
  if (activeDialogueSession && ids.includes(activeDialogueSession)) {
    activeDialogueSession = "";
    activeDialogueMessages = [];
    activeDialogueMemory = {};
    dialogueMessagesBefore = "";
    dialogueMessagesHasMore = false;
  }
  await loadDialogueSessions();
  renderDialogueAll();
  showToast(dialogueTrashMode ? `已永久删除 ${data.count || ids.length} 段会话` : `已移入最近删除 ${data.count || ids.length} 段会话`);
}

function renderDialogueFlow() {
  const target = $("#dialogue-flow");
  if (!target) return;
  const persona = currentDialoguePersona();
  const thinkingState = getDialogueThinkingState();
  const runtime = window.dialogueRuntimeProgress || {};
  const steps = dialogueMode === "book"
    ? [
        ["accepted", `书中人：${persona?.name || "待选择"}`],
        ["retrieving_library", "检索本地书库"],
        ["library_ready", $("#dialogue-use-search")?.checked ? "核对本地与联网来源" : "核对本地依据"],
        ["generating", "组织回答"],
        ["completed", "完成"]
      ]
    : [
        ["accepted", "镜中人"],
        ["retrieving_memory", "检索个人长期记忆"],
        ["memory_ready", "核对历史文稿依据"],
        ["generating", "组织回答"],
        ["completed", "完成"]
      ];
  const currentIndex = Math.max(0, steps.findIndex(([stage]) => stage === runtime.stage));
  target.classList.toggle("thinking", thinkingState === "thinking");
  target.classList.toggle("failed", thinkingState === "failed");
  const stateLabel = thinkingState === "thinking"
    ? (runtime.label || "正在思考")
    : thinkingState === "failed"
      ? "上次失败"
      : thinkingState === "done"
        ? "已回答"
        : "待交流";
  target.innerHTML = `
    <span class="dialogue-flow-state">${stateLabel}</span>
    <div>
      ${steps.map(([, step], index) => `<span class="${thinkingState === "thinking" && index <= currentIndex ? "active" : ""}">${escapeHtml(step)}</span>`).join("")}
    </div>
  `;
}

async function readDialogueEventStream(response, onEvent) {
  if (!response.body?.getReader) throw new Error("当前浏览器不支持对话进度流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      const dataLine = block.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      const event = JSON.parse(dataLine.slice(5).trim());
      await onEvent(event);
    }
    if (done) break;
  }
}

function formatDialogueTime(value) {
  if (!value) return "";
  const date = new Date(String(value).replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function dialogueNearBottom(target, threshold = 120) {
  return target.scrollHeight - target.scrollTop - target.clientHeight <= threshold;
}

function scrollDialogueToLatest({ smooth = true } = {}) {
  const target = $("#dialogue-thread");
  if (!target) return;
  target.scrollTo({ top: target.scrollHeight, behavior: smooth ? "smooth" : "auto" });
  $("#dialogue-scroll-latest")?.classList.add("hidden");
}

function dialogueWelcomePrompts() {
  const persona = currentDialoguePersona();
  if (dialogueMode === "mirror") {
    return [
      "我现在有点卡住，你觉得真正的问题是什么？",
      "如果你就是我，你会怎么处理今天这件事？",
      "帮我把这个念头聊成一个能写视频的切口。"
    ];
  }
  const name = persona?.name || "书中人";
  if (name === "马斯克") {
    return ["我现在该行动还是继续观察？", "这件事的第一性原理是什么？", "如果目标是长期主义，我该牺牲什么？"];
  }
  if (name === "老子") {
    return ["这件事里，我是不是太用力了？", "什么叫顺势而为？", "我该如何看待取舍和边界？"];
  }
  if (name === "齐静春") {
    return ["我该如何守住心气？", "这件事里真正重要的道理是什么？", "如果先立住本心，我该怎么做？"];
  }
  return ["我最近有个选择很难判断。", "你怎么看待一个人的心气和退路？", "我该如何把这件事讲成一条视频？"];
}

function renderDialogueThread({ preserveScroll = false } = {}) {
  const target = $("#dialogue-thread");
  if (!target) return;
  const shouldStick = preserveScroll ? dialogueNearBottom(target) : true;
  if (!activeDialogueSession) {
    const persona = currentDialoguePersona();
    const title = dialogueMode === "mirror"
      ? "你可以从任何一个念头开始。"
      : `和${persona?.name || "书中人"}聊聊你正在面对的事。`;
    const prompts = dialogueWelcomePrompts();
    target.innerHTML = `
      <div class="dialogue-welcome dialogue-welcome-chat">
        <span class="dialogue-message-avatar dialogue-welcome-avatar" aria-hidden="true">${dialogueMode === "mirror" ? "镜" : escapeHtml((persona?.name || "书").slice(0, 1))}</span>
        <div class="dialogue-welcome-bubble">
          <span class="dialogue-welcome-kicker">${dialogueMode === "mirror" ? "镜中人" : escapeHtml(persona?.name || "书中人")}</span>
          <strong>${escapeHtml(title)}</strong>
          <p>对话保持独立，不绑定项目；值得留下的内容会沉淀为全局对话资产。</p>
          <div class="dialogue-welcome-prompts" aria-label="快速提问建议">
            ${prompts.map((prompt) => `<button data-dialogue-prompt="${escapeHtml(prompt)}" type="button">${escapeHtml(prompt)}</button>`).join("")}
          </div>
        </div>
      </div>`;
    if (shouldStick) window.requestAnimationFrame(() => scrollDialogueToLatest({ smooth: false }));
    return;
  }
  if (!activeDialogueMessages.length) {
    const prompts = dialogueWelcomePrompts();
    target.innerHTML = `
      <div class="dialogue-welcome dialogue-welcome-chat compact">
        <span class="dialogue-message-avatar dialogue-welcome-avatar" aria-hidden="true">${dialogueMode === "mirror" ? "镜" : escapeHtml((currentDialoguePersona()?.name || "书").slice(0, 1))}</span>
        <div class="dialogue-welcome-bubble">
          <span class="dialogue-welcome-kicker">新会话</span>
          <strong>会话已创建</strong>
          <p>说出你现在卡住的地方，或先点一个问题开始。</p>
          <div class="dialogue-welcome-prompts" aria-label="快速提问建议">
            ${prompts.map((prompt) => `<button data-dialogue-prompt="${escapeHtml(prompt)}" type="button">${escapeHtml(prompt)}</button>`).join("")}
          </div>
        </div>
      </div>`;
    if (shouldStick) window.requestAnimationFrame(() => scrollDialogueToLatest({ smooth: false }));
    return;
  }
  target.innerHTML = activeDialogueMessages.map((message) => {
    const extractable = Array.isArray(message.extractable) ? message.extractable : [];
    const citations = Array.isArray(message.citations) ? message.citations : [];
    const grounding = message.payload?.grounding && typeof message.payload.grounding === "object"
      ? message.payload.grounding
      : {};
    const sources = Array.isArray(grounding.sources) ? grounding.sources : [];
    const feedback = message.feedback?.verdict || message.payload?.user_feedback || "";
    const evidenceOpen = dialogueEvidenceOpen.has(message.id);
    return `
      <article class="dialogue-message ${escapeHtml(message.role)}">
        <div class="dialogue-message-line">
          ${message.role === "assistant" ? `<span class="dialogue-message-avatar" aria-hidden="true">${dialogueMode === "mirror" ? "镜" : escapeHtml((currentDialoguePersona()?.name || "书").slice(0, 1))}</span>` : ""}
          <div class="dialogue-message-content">${escapeHtml(message.content).replace(/\n/g, "<br>")}</div>
        </div>
        <div class="dialogue-message-meta">
          <time>${escapeHtml(formatDialogueTime(message.created_at))}</time>
          ${message.status === "pending" ? `<span class="dialogue-message-status">正在发送</span>` : ""}
          ${message.status === "failed" ? `<span class="dialogue-message-status failed">发送失败</span><button class="dialogue-inline-action" data-dialogue-retry="${escapeHtml(message.id)}" type="button">重试</button>` : ""}
          ${message.role === "assistant" ? `<button class="dialogue-inline-action" data-dialogue-copy="${escapeHtml(message.id)}" type="button">复制</button>` : ""}
        </div>
        ${message.role === "assistant" && message.status !== "failed" ? `
          <div class="dialogue-feedback-bar" aria-label="校准这条回复">
            <button class="${feedback === "like_self" ? "active" : ""}" data-dialogue-feedback="like_self" data-message-id="${escapeHtml(message.id)}" type="button">像我</button>
            <button class="${feedback === "unlike_self" ? "active" : ""}" data-dialogue-feedback="unlike_self" data-message-id="${escapeHtml(message.id)}" type="button">不像我</button>
            <button class="${feedback === "remember" ? "active" : ""}" data-dialogue-feedback="remember" data-message-id="${escapeHtml(message.id)}" type="button">记住</button>
            <button class="${feedback === "forget" ? "active danger" : ""}" data-dialogue-feedback="forget" data-message-id="${escapeHtml(message.id)}" type="button">忘掉</button>
            ${sources.length ? `<button class="evidence-toggle ${evidenceOpen ? "active" : ""}" data-dialogue-evidence="${escapeHtml(message.id)}" type="button" aria-expanded="${evidenceOpen}">查看依据 <span>${sources.length}</span></button>` : ""}
          </div>
          ${evidenceOpen && sources.length ? `
            <section class="dialogue-grounding" aria-label="本轮回答依据">
              <header>
                <div><strong>本轮调用依据</strong><span>${escapeHtml(grounding.retrieval || "local_retrieval")}</span></div>
                ${grounding.search?.requested ? `<em>${grounding.search.used ? `联网补充 ${Number(grounding.search.result_count || 0)} 条` : "联网未补充，使用本地书库"}</em>` : ""}
              </header>
              <div class="dialogue-grounding-list">
                ${sources.slice(0, 10).map((source) => `
                  <article>
                    <span>${escapeHtml(dialogueGroundingLabel(source))}</span>
                    <strong>${escapeHtml(source.title || source.source_filename || "个人记忆")}</strong>
                    <p>${escapeHtml(source.content || "").replace(/\n/g, "<br>")}</p>
                    ${source.source_locator ? `<small>${escapeHtml(source.source_locator)}</small>` : ""}
                  </article>
                `).join("")}
              </div>
            </section>
          ` : ""}
        ` : ""}
        ${citations.length ? `
          <div class="dialogue-citations">
            ${citations.slice(0, 3).map((item) => `<span>${escapeHtml(item.book || item.attribution || "书库")} · ${escapeHtml(item.source_status || "support")}</span>`).join("")}
          </div>
        ` : ""}
        ${extractable.length ? `
          <div class="dialogue-extractable">
            ${extractable.map((item, index) => `
              <button data-dialogue-extract="${index}" data-message-id="${escapeHtml(message.id)}" type="button">
                <b>${escapeHtml(dialogueExtractLabel(item.type))}</b>
                <span>${escapeHtml(item.text)}</span>
              </button>
            `).join("")}
          </div>
        ` : ""}
      </article>
    `;
  }).join("");
  if (shouldStick) {
    window.requestAnimationFrame(() => scrollDialogueToLatest({ smooth: false }));
  } else if (!dialogueSending) {
    $("#dialogue-scroll-latest")?.classList.remove("hidden");
  }
}

function dialogueGroundingLabel(source) {
  const labels = {
    history_document: "历史文稿",
    creator_memory: "长期记忆",
    persona_asset: "人设资产",
    book_citation: "本地书库"
  };
  return labels[source?.source_type] || "对话依据";
}

async function submitDialogueFeedback(messageId, action) {
  if (!activeDialogueSession || !messageId) return;
  const response = await XZJApi.request(
    `/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(activeDialogueSession)}/messages/${encodeURIComponent(messageId)}/feedback`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    }
  );
  const data = await response.json();
  if (!response.ok) throw new Error(apiError(data, "回复校准失败"));
  const message = activeDialogueMessages.find((item) => item.id === messageId);
  if (message) message.feedback = { verdict: action, updated_at: new Date().toISOString() };
  renderDialogueThread({ preserveScroll: true });
  const labels = {
    like_self: "已标记为像我",
    unlike_self: "已记录这次不像我",
    remember: "已写入跨会话长期记忆",
    forget: "已忘记由这条回复确认的记忆"
  };
  showToast(labels[action] || "已记录");
}

function renderDialogueAll() {
  renderDialogueContext();
  renderDialoguePersona();
  $("#dialogue-trash-toggle").textContent = dialogueTrashMode ? "返回会话" : "最近删除";
  $("#dialogue-session-search").value = dialogueSessionQuery;
  renderDialogueSessions();
  renderDialogueThread();
  renderDialogueAssets();
}

async function loadDialoguePersonas() {
  try {
    const response = await XZJApi.request("/api/xiangzhongjing/dialogue/personas");
    if (!response.ok) return;
    const data = await response.json();
    dialoguePersonas = Array.isArray(data.personas) ? data.personas : [];
    if (dialogueMode === "book" && dialoguePersonaById(activeDialoguePersona)?.type !== "book") {
      activeDialoguePersona = dialoguePersonas.find((item) => item.type === "book")?.id || "";
    }
    if (!dialoguePersonas.some((item) => item.id === activeDialoguePersona)) {
      activeDialoguePersona = dialoguePersonas.find((item) => item.type === "book")?.id || "mirror-self";
    }
    renderDialoguePersona();
  } catch (error) {
    console.warn("Failed to load dialogue personas", error);
  }
}

async function loadDialogueSessions({ selectFirst = false } = {}) {
  dialogueSessionsLoading = true;
  renderDialogueSessions();
  try {
    const params = new URLSearchParams({
      mode: dialogueMode,
      ...(dialogueMode === "book" ? { persona_id: activeDialoguePersona } : {}),
      ...(dialogueSessionQuery ? { query: dialogueSessionQuery } : {}),
      ...(dialogueTrashMode ? { include_deleted: "true" } : {})
    });
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions?${params.toString()}`);
    if (!response.ok) return;
    const data = await response.json();
    dialogueSessions = Array.isArray(data.sessions) ? data.sessions : [];
    if (selectFirst && !activeDialogueSession) {
      const match = dialogueSessions.find((session) => sessionMatchesDialogue(session));
      if (match) await selectDialogueSession(match.id);
    }
    renderDialogueSessions();
  } catch (error) {
    console.warn("Failed to load dialogue sessions", error);
  } finally {
    dialogueSessionsLoading = false;
    renderDialogueSessions();
  }
}

async function switchDialoguePersona(personaId) {
  const next = dialoguePersonaById(personaId);
  if (!next || next.type !== "book") return;
  activeDialoguePersona = personaId;
  activeDialogueSession = "";
  activeDialogueMessages = [];
  activeDialogueMemory = {};
  dialogueMessagesBefore = "";
  dialogueMessagesHasMore = false;
  dialogueTrashMode = false;
  setDialogueThinkingState("idle");
  renderDialogueAll();
  await loadDialogueSessions();
  await loadDialogueAssets();
}

async function createDialogueSession() {
  const persona = currentDialoguePersona();
  const title = dialogueMode === "mirror"
    ? "镜中人 · 新会话"
    : `书中人 · ${persona?.name || "新会话"}`;
  const response = await XZJApi.request("/api/xiangzhongjing/dialogue/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: dialogueMode,
      persona_id: persona?.id || activeDialoguePersona,
      title
    })
  });
  const data = await response.json();
  if (!response.ok) throw new Error(apiError(data, "会话创建失败"));
  activeDialogueSession = data.id;
  activeDialogueMessages = [];
  activeDialogueMemory = {};
  dialogueMessagesBefore = "";
  dialogueMessagesHasMore = false;
  dialogueTrashMode = false;
  await loadDialogueSessions();
  renderDialogueContext();
  renderDialogueThread();
  return data;
}

async function selectDialogueSession(id) {
  const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(id)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(apiError(data, "会话读取失败"));
  if (data.session?.mode) dialogueMode = data.session.mode === "book" ? "book" : "mirror";
  if (data.session?.mode === "book" && data.session?.persona_id) {
    activeDialoguePersona = data.session.persona_id;
  }
  activeDialogueSession = id;
  activeDialogueMessages = Array.isArray(data.messages) ? data.messages : [];
  dialogueMessagesBefore = data.messages_page?.next_before || "";
  dialogueMessagesHasMore = Boolean(data.messages_page?.has_more);
  activeDialogueMemory = data.memory && typeof data.memory === "object" ? data.memory : {};
  dialogueTrashMode = false;
  renderDialoguePersona();
  renderDialogueContext();
  renderDialogueSessions();
  renderDialogueThread({ preserveScroll: false });
}

async function loadOlderDialogueMessages() {
  const target = $("#dialogue-thread");
  if (!target || !activeDialogueSession || !dialogueMessagesHasMore || dialogueLoadingHistory) return;
  dialogueLoadingHistory = true;
  const previousHeight = target.scrollHeight;
  const previousTop = target.scrollTop;
  target.classList.add("is-loading-history");
  try {
    const params = new URLSearchParams({ before: dialogueMessagesBefore, limit: "30" });
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(activeDialogueSession)}/messages?${params.toString()}`);
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "历史消息加载失败"));
    activeDialogueMessages = [...(Array.isArray(data.messages) ? data.messages : []), ...activeDialogueMessages];
    dialogueMessagesBefore = data.next_before || "";
    dialogueMessagesHasMore = Boolean(data.has_more);
    renderDialogueThread({ preserveScroll: true });
    window.requestAnimationFrame(() => {
      target.scrollTop = target.scrollHeight - previousHeight + previousTop;
    });
  } catch (error) {
    showToast(error.message);
  } finally {
    target.classList.remove("is-loading-history");
    dialogueLoadingHistory = false;
  }
}

async function sendDialogueMessage(event) {
  event.preventDefault();
  if (dialogueSending) return;
  const input = $("#dialogue-input");
  const message = input.value.trim();
  if (!message) {
    showToast("先写一句你想交流的问题");
    return;
  }
  dialogueSending = true;
  setDialogueThinkingState("thinking");
  setDialogueRuntimeProgress("accepted", "正在提交问题");
  $("#send-dialogue").disabled = true;
  $("#send-dialogue").textContent = "思考中";
  renderDialogueFlow();
  try {
    if (!activeDialogueSession) await createDialogueSession();
    activeDialogueMessages.push({
      id: `local_${Date.now()}`,
      role: "user",
      content: message,
      extractable: [],
      citations: [],
      status: "pending",
      created_at: new Date().toISOString()
    });
    input.value = "";
    renderDialogueThread();
    renderDialogueContext();
    const response = await window.fetch(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(activeDialogueSession)}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({
        message,
        use_search: $("#dialogue-use-search").checked
      })
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(apiError(data, "对话失败"));
    }
    let data = null;
    await readDialogueEventStream(response, async (streamEvent) => {
      if (streamEvent.type === "stage") {
        setDialogueRuntimeProgress(streamEvent.stage, streamEvent.label, streamEvent.meta || {});
        renderDialogueFlow();
        return;
      }
      if (streamEvent.type === "error") {
        throw new Error(streamEvent.error?.message || "对话失败");
      }
      if (streamEvent.type === "result") data = streamEvent.data;
    });
    if (!data) throw new Error("对话链路没有返回完整结果");
    await selectDialogueSession(activeDialogueSession);
    await loadDialogueSessions();
    setDialogueThinkingState("done");
    setDialogueRuntimeProgress("completed", "回答已完成");
    renderDialogueFlow();
    showToast("交流完成，可沉淀有价值的句子");
  } catch (error) {
    setDialogueThinkingState("failed");
    setDialogueRuntimeProgress("", "");
    if (activeDialogueSession) {
      try {
        await selectDialogueSession(activeDialogueSession);
      } catch (_) {
        const latest = activeDialogueMessages[activeDialogueMessages.length - 1];
        if (latest?.role === "user") latest.status = "failed";
        renderDialogueThread({ preserveScroll: true });
      }
    }
    renderDialogueFlow();
    showToast(error.message);
  } finally {
    dialogueSending = false;
    $("#send-dialogue").disabled = false;
    $("#send-dialogue").textContent = "发送";
  }
}

async function retryDialogueMessage(messageId) {
  if (dialogueSending || !activeDialogueSession) return;
  dialogueSending = true;
  $("#send-dialogue").disabled = true;
  try {
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(activeDialogueSession)}/messages/${encodeURIComponent(messageId)}/retry`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "重试失败"));
    await selectDialogueSession(activeDialogueSession);
    await loadDialogueSessions();
    showToast("已重新生成回复");
  } catch (error) {
    showToast(error.message);
    try { await selectDialogueSession(activeDialogueSession); } catch (_) { /* keep visible state */ }
  } finally {
    dialogueSending = false;
    $("#send-dialogue").disabled = false;
  }
}

function dialogueSessionById(id) {
  return dialogueSessions.find((session) => session.id === id) || null;
}

function closeDialogueSessionMenu() {
  const menu = $("#dialogue-session-menu");
  if (!menu) return;
  menu.classList.add("hidden");
  dialogueMenuSessionId = "";
}

function openDialogueSessionMenu(sessionId, anchor) {
  const session = dialogueSessionById(sessionId);
  const menu = $("#dialogue-session-menu");
  if (!session || !menu || !anchor) return;
  dialogueMenuSessionId = sessionId;
  const deleted = Boolean(session.deleted_at);
  menu.innerHTML = deleted
    ? `<button type="button" data-dialogue-session-action="restore" role="menuitem">恢复会话</button><button type="button" class="danger" data-dialogue-session-action="permanent" role="menuitem">永久删除</button>`
    : `<button type="button" data-dialogue-session-action="rename" role="menuitem">重命名</button><button type="button" data-dialogue-session-action="pin" role="menuitem">${session.pinned_at ? "取消置顶" : "置顶会话"}</button><button type="button" data-dialogue-session-action="clear" role="menuitem">清空聊天记录</button><button type="button" class="danger" data-dialogue-session-action="delete" role="menuitem">删除会话</button>`;
  menu.classList.remove("hidden");
  const rect = anchor.getBoundingClientRect();
  const width = 164;
  menu.style.left = `${Math.max(10, Math.min(window.innerWidth - width - 10, rect.right - width))}px`;
  menu.style.top = `${Math.min(window.innerHeight - 180, rect.bottom + 6)}px`;
}

function closeDialogueRenameDialog(saved = false) {
  const dialog = $("#dialogue-rename-dialog");
  if (!dialog) return;
  dialog.classList.add("hidden");
  dialog.setAttribute("aria-hidden", "true");
  overlayManager.close("dialogue-rename-dialog");
  if (!saved) dialogueRenameSessionId = "";
}

function openDialogueRenameDialog(sessionId) {
  const session = dialogueSessionById(sessionId);
  const dialog = $("#dialogue-rename-dialog");
  if (!session || !dialog) return;
  dialogueRenameSessionId = sessionId;
  $("#dialogue-rename-input").value = session.title || "";
  dialog.classList.remove("hidden");
  dialog.setAttribute("aria-hidden", "false");
  overlayManager.open({
    id: "dialogue-rename-dialog",
    element: dialog,
    lockMode: "modal",
    onRequestClose: () => closeDialogueRenameDialog(false)
  });
  window.requestAnimationFrame(() => $("#dialogue-rename-input").focus({ preventScroll: true }));
}

async function saveDialogueRename() {
  const title = $("#dialogue-rename-input").value.trim();
  if (!title || !dialogueRenameSessionId) {
    showToast("请输入会话标题");
    return;
  }
  const button = $("#dialogue-rename-accept");
  button.disabled = true;
  try {
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(dialogueRenameSessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "会话重命名失败"));
    closeDialogueRenameDialog(true);
    dialogueRenameSessionId = "";
    await loadDialogueSessions();
    showToast("会话标题已更新");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function handleDialogueSessionAction(action) {
  const sessionId = dialogueMenuSessionId;
  const session = dialogueSessionById(sessionId);
  closeDialogueSessionMenu();
  if (!session) return;
  if (action === "rename") {
    openDialogueRenameDialog(sessionId);
    return;
  }
  if (action === "pin") {
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned: !session.pinned_at })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "置顶操作失败"));
    await loadDialogueSessions();
    showToast(session.pinned_at ? "已取消置顶" : "会话已置顶");
    return;
  }
  if (action === "clear") {
    const confirmed = await requestConfirm({
      title: "清空这段会话？",
      message: "会话标题和人物会保留，聊天记录与本会话记忆将被清除。已主动沉淀的全局资产不会受影响。",
      confirmText: "清空记录",
      danger: true
    });
    if (!confirmed) return;
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(sessionId)}/messages`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "清空会话失败"));
    if (activeDialogueSession === sessionId) {
      activeDialogueMessages = [];
      activeDialogueMemory = {};
      dialogueMessagesBefore = "";
      dialogueMessagesHasMore = false;
      renderDialogueAll();
    }
    await loadDialogueSessions();
    showToast("聊天记录已清空");
    return;
  }
  if (action === "delete") {
    const confirmed = await requestConfirm({
      title: `删除“${session.title || "未命名会话"}”？`,
      message: "会话会进入最近删除并保留 7 天。已主动沉淀的人格资产不会被删除。",
      confirmText: "删除会话",
      danger: true
    });
    if (!confirmed) return;
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "删除会话失败"));
    if (activeDialogueSession === sessionId) {
      activeDialogueSession = "";
      activeDialogueMessages = [];
      activeDialogueMemory = {};
      dialogueMessagesBefore = "";
      dialogueMessagesHasMore = false;
    }
    await loadDialogueSessions();
    renderDialogueAll();
    showToast("会话已移入最近删除");
    return;
  }
  if (action === "restore") {
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(sessionId)}/restore`, { method: "POST" });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "恢复会话失败"));
    await loadDialogueSessions();
    showToast("会话已恢复");
    return;
  }
  if (action === "permanent") {
    const confirmed = await requestConfirm({
      title: "永久删除这段会话？",
      message: "聊天记录和会话记忆将无法恢复。已主动沉淀的人格资产仍会保留。",
      confirmText: "永久删除",
      danger: true
    });
    if (!confirmed) return;
    const response = await XZJApi.request(`/api/xiangzhongjing/dialogue/sessions/${encodeURIComponent(sessionId)}?permanent=true`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "永久删除失败"));
    await loadDialogueSessions();
    showToast("会话已永久删除");
  }
}

async function extractDialogueItem(messageId, index) {
  const message = activeDialogueMessages.find((item) => item.id === messageId);
  const item = message?.extractable?.[index];
  if (!item?.text) return;
  await XZJApi.request("/api/xiangzhongjing/dialogue/extract", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      target: "persona_asset",
      project_id: "",
      asset_type: dialogueAssetType(item.type),
      title: `来自${dialogueMode === "book" ? "书中人" : "镜中人"} · ${dialogueExtractLabel(item.type)}`,
      text: item.text,
      source: `dialogue:${activeDialogueSession}`
    })
  }).then(async (response) => {
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "对话资产沉淀失败"));
    const label = dialogueExtractLabel(item.type);
    $("#dialogue-extract-log").innerHTML = `<span>${escapeHtml(label)} · 全局资产：${escapeHtml(item.text.slice(0, 36))}</span>` + $("#dialogue-extract-log").innerHTML;
    await loadDialogueAssets();
    showToast("已沉淀为全局资产，不会自动写入当前项目");
  });
}
