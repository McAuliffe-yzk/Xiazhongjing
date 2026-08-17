"use strict";

const inspirationTypes = [
  { id: "theme", label: "主题签", prompt: "我缺一个主题", tone: "找到一条值得展开的命题", accent: "red" },
  { id: "emotion", label: "情绪签", prompt: "我缺一种情绪", tone: "说透尚未解决的情绪张力", accent: "blue" },
  { id: "event", label: "事件签", prompt: "我缺一个事件", tone: "从近况里找到可拍的变化", accent: "green" },
  { id: "book", label: "书库签", prompt: "我想从书里开始", tone: "让有效原句在正确时机出现", accent: "gold" },
  { id: "mirror", label: "镜中签", prompt: "我想问问自己", tone: "让过去与现在彼此追问", accent: "red" },
  { id: "action", label: "行动签", prompt: "我只想先动一下", tone: "完成一个具体创作动作", accent: "blue" }
];

let viewedInspirationId = "";
let inspirationToday = null;
let inspirationServerDate = "";
let inspirationLoaded = false;
let inspirationLoading = false;
let inspirationDrawing = false;
let inspirationArchiveFilters = { type: "", status: "all" };
let inspirationMetrics = null;
let pendingInspirationFeedback = null;
let inspirationPhaseLabel = "";
let inspirationDrawStartedAt = 0;
let inspirationElapsedTimer = null;

const inspirationFeedbackReasons = [
  ["too_vague", "太空泛"],
  ["repetitive", "与以前重复"],
  ["irrelevant", "与近况无关"],
  ["unlike_me", "不像我"],
  ["not_shootable", "不方便拍"]
];

function todayKey() {
  if (inspirationServerDate) return inspirationServerDate;
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function inspirationTypeMeta(type) {
  return inspirationTypes.find((item) => item.id === type) || inspirationTypes[0];
}

function todayInspirationDraw() {
  return inspirationToday?.locked ? inspirationToday : null;
}

function replaceInspirationDraw(draw) {
  if (!draw?.id) return;
  if (inspirationToday?.id === draw.id) inspirationToday = draw;
  const index = inspirationDraws.findIndex((item) => item.id === draw.id);
  if (index >= 0) inspirationDraws[index] = draw;
  else if (!draw.deleted_at) inspirationDraws.unshift(draw);
}

function inspirationArchiveQuery() {
  const params = new URLSearchParams({
    status: inspirationArchiveFilters.status,
    limit: "365"
  });
  if (inspirationArchiveFilters.type) params.set("type", inspirationArchiveFilters.type);
  if (inspirationArchiveFilters.status === "deleted") params.set("include_deleted", "true");
  return params.toString();
}

async function loadInspirationPage({ silent = false } = {}) {
  if (inspirationLoading) return;
  inspirationLoading = true;
  if (!silent) renderInspirationPage();
  try {
    const [todayPayload, archivePayload, metricsPayload] = await Promise.all([
      XZJApi.json("/api/xiangzhongjing/inspiration/today"),
      XZJApi.json(`/api/xiangzhongjing/inspiration/archive?${inspirationArchiveQuery()}`),
      XZJApi.json("/api/xiangzhongjing/inspiration/metrics?days=14").catch(() => null)
    ]);
    inspirationServerDate = todayPayload.server_date || archivePayload.server_date || todayKey();
    inspirationToday = todayPayload.draw || null;
    inspirationDraws = Array.isArray(archivePayload.items) ? archivePayload.items : [];
    inspirationMetrics = metricsPayload || inspirationMetrics;
    if (inspirationToday) activeInspirationType = inspirationToday.type;
    inspirationLoaded = true;
  } catch (error) {
    console.warn("Failed to load inspiration archive", error);
    if (!silent) showToast(`灵感匣签加载失败：${error.message}`);
  } finally {
    inspirationLoading = false;
    renderInspirationPage();
  }
}

function inspirationDrawById(id) {
  if (inspirationToday?.id === id) return inspirationToday;
  return inspirationDraws.find((item) => item.id === id) || null;
}

function renderInspirationPage() {
  const draw = todayInspirationDraw();
  if (draw) activeInspirationType = draw.type;
  if (activeInspirationType && !inspirationTypes.some((item) => item.id === activeInspirationType)) {
    activeInspirationType = "";
  }
  renderInspirationTypes(draw);
  renderInspirationStage(draw);
  const viewedDraw = inspirationDrawById(viewedInspirationId);
  renderInspirationResult(viewedDraw || draw);
  renderInspirationHistory();
  renderInspirationLearningSummary();
  syncInspirationArchiveControls();
}

function renderInspirationTypes(draw) {
  const target = $("#inspiration-type-grid");
  if (!target) return;
  target.innerHTML = inspirationTypes.map((type) => {
    const selected = activeInspirationType === type.id;
    const lockedOut = Boolean(draw && draw.type !== type.id);
    return `
      <button class="inspiration-type-card ${selected ? "selected" : ""} ${lockedOut ? "locked-out" : ""}" data-inspiration-type="${type.id}" type="button" aria-pressed="${String(selected)}" ${(draw || inspirationDrawing || inspirationLoading) ? "disabled" : ""}>
        <span class="type-orbit ${type.accent}"></span>
        <strong>${escapeHtml(type.prompt)}</strong>
        <small>${escapeHtml(type.label)} · ${escapeHtml(type.tone)}</small>
      </button>
    `;
  }).join("");
}

function renderInspirationStage(draw) {
  const meta = activeInspirationType ? inspirationTypeMeta(activeInspirationType) : null;
  const box = $("#inspiration-box");
  const button = $("#draw-inspiration");
  if (!box || !button) return;
  box.classList.toggle("locked", Boolean(draw));
  box.classList.toggle("selected", Boolean(activeInspirationType && !draw));
  if (inspirationLoading && !inspirationLoaded) {
    $("#inspiration-slip-label").textContent = "读取中";
    $("#inspiration-today-state").textContent = "正在确认今日状态";
    $("#inspiration-phase").textContent = "翻阅匣签档案";
    $("#inspiration-stage-title").textContent = "正在读取你的今日签";
    $("#inspiration-stage-desc").textContent = "匣中镜正在确认今天是否已经抽过，并同步历史记录。";
    $("#inspiration-lock-note").textContent = "同一天在不同标签页打开，也会返回同一支签。";
    button.disabled = true;
    button.textContent = "正在读取";
    return;
  }
  $("#inspiration-slip-label").textContent = draw ? draw.title : (meta?.label || "匣中镜");
  $("#inspiration-today-state").textContent = draw ? `今日 · ${draw.type_label}` : "今日未抽";
  $("#inspiration-picked-label").textContent = draw ? draw.type_label : (meta?.label || "未选择");
  if (!inspirationDrawing) $("#inspiration-phase").textContent = draw ? "今日签已定" : (meta ? "等待开匣" : "等待选择");
  $("#inspiration-stage-title").textContent = draw ? `今日签：${draw.title}` : (meta ? `今日将抽：${meta.label}` : "先选一类签");
  $("#inspiration-stage-desc").textContent = draw
    ? (draw.deleted_at ? "这支今日签已移入最近删除，恢复后可继续使用。" : "这支签由个人 DNA、近期创作轨迹、历史记忆与有效书库共同生成。")
    : "六类签会走不同的思考路径。抽出后，今天不会再生成第二支。";
  $("#inspiration-lock-note").textContent = draw
    ? "结果不会自动写入任何项目，由你决定收藏、转项目、加入素材或带去问镜中人。"
    : "生成失败不会消耗今日机会；成功显签后才会锁定。";
  button.disabled = Boolean(draw || !meta || inspirationDrawing || inspirationLoading);
  button.textContent = draw ? "今日已抽签" : (meta ? `抽今日${meta.label}` : "先选一类签");
}

function inspirationKeywordHtml(draw) {
  return (draw.keywords || []).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("");
}

function inspirationPromptHtml(draw) {
  const prompts = Array.isArray(draw.three_questions) && draw.three_questions.length
    ? draw.three_questions
    : (Array.isArray(draw.prompts) ? draw.prompts : [draw.question].filter(Boolean));
  return prompts.slice(0, 3).map((item, index) => `
    <li>
      <b>${String(index + 1).padStart(2, "0")}</b>
      <span>${escapeHtml(item)}</span>
    </li>
  `).join("");
}

function inspirationScenesHtml(draw) {
  const scenes = Array.isArray(draw.shootable_scenes) ? draw.shootable_scenes : [];
  if (!scenes.length) return "";
  return `
    <div class="draw-scenes" data-reveal>
      <span>可拍场景</span>
      <ul>${scenes.slice(0, 3).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </div>
  `;
}

function inspirationQuoteHtml(draw) {
  if (!draw.quote) return "";
  const source = [draw.quote_source || draw.source, draw.quote_attribution].filter(Boolean).join(" · ");
  return `
    <div class="draw-quote" data-reveal>
      <span>${escapeHtml(source || "精神书库")} · 已验证原句</span>
      <p>“${escapeHtml(draw.quote)}”</p>
      ${draw.quote_locator ? `<small>${escapeHtml(draw.quote_locator)}</small>` : ""}
    </div>
  `;
}

function inspirationSourcesHtml(draw) {
  const sources = Array.isArray(draw.context_sources) ? draw.context_sources : [];
  if (!sources.length) return "";
  return `
    <details class="inspiration-sources">
      <summary>查看这支签参考了什么</summary>
      <div>${sources.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div>
    </details>
  `;
}

function inspirationFeedbackHtml(draw) {
  if (draw.deleted_at) return "";
  const stored = draw.feedback && typeof draw.feedback === "object" ? draw.feedback : {};
  const pending = pendingInspirationFeedback?.id === draw.id ? pendingInspirationFeedback : null;
  const verdict = pending?.verdict || stored.verdict || "";
  const reasons = pending?.reasons || stored.reasons || [];
  const note = pending?.note ?? stored.note ?? "";
  const showReasons = verdict === "not_useful";
  return `
    <section class="inspiration-feedback" aria-label="评价这支灵感签">
      <div class="inspiration-feedback-head">
        <div><strong>它更接近你，还是偏了？</strong><span>${stored.verdict ? "已记录，可随时修改" : "留下一个直觉就够了"}</span></div>
        <div class="inspiration-feedback-choice" role="group" aria-label="灵感签是否有用">
          <button class="${verdict === "useful" ? "active" : ""}" data-inspiration-feedback="useful" data-draw-id="${escapeHtml(draw.id)}" type="button" aria-pressed="${String(verdict === "useful")}">有启发</button>
          <button class="${verdict === "not_useful" ? "active negative" : ""}" data-inspiration-feedback="not_useful" data-draw-id="${escapeHtml(draw.id)}" type="button" aria-pressed="${String(verdict === "not_useful")}">不适合我</button>
        </div>
      </div>
      ${showReasons ? `
        <div class="inspiration-feedback-detail">
          <div class="inspiration-feedback-reasons">
            ${inspirationFeedbackReasons.map(([value, label]) => `
              <label class="${reasons.includes(value) ? "selected" : ""}">
                <input type="checkbox" value="${value}" data-inspiration-feedback-reason="${escapeHtml(draw.id)}" ${reasons.includes(value) ? "checked" : ""}>
                <span>${label}</span>
              </label>
            `).join("")}
          </div>
          <div class="inspiration-feedback-note">
            <input data-inspiration-feedback-note="${escapeHtml(draw.id)}" value="${escapeHtml(note)}" maxlength="400" placeholder="还有哪里偏了？可不填">
            <button data-inspiration-feedback-submit="${escapeHtml(draw.id)}" type="button">记录反馈</button>
          </div>
        </div>
      ` : ""}
    </section>
  `;
}

function renderInspirationResult(draw, revealing = false) {
  const target = $("#inspiration-result");
  if (!target) return;
  if (!draw) {
    target.classList.add("hidden");
    target.innerHTML = "";
    return;
  }
  target.classList.remove("hidden");
  const isToday = draw.date === todayKey();
  const conversions = Array.isArray(draw.converted_to) ? draw.converted_to.length : 0;
  const deleted = Boolean(draw.deleted_at);
  const elapsed = Number(draw.total_latency_ms || draw.latency_ms || 0);
  target.innerHTML = `
    <article class="inspiration-draw-card ${revealing ? "is-revealing" : ""} ${deleted ? "is-deleted" : ""}" data-draw-id="${escapeHtml(draw.id)}">
      <div class="draw-card-head">
        <span>${escapeHtml(draw.type_label)} · ${escapeHtml(isToday ? "今日签" : draw.date)}${elapsed ? ` · 生成 ${(elapsed / 1000).toFixed(1)} 秒` : ""}</span>
        <div class="draw-card-tools">
          ${deleted
            ? `<button class="inspiration-favorite" data-inspiration-restore="${escapeHtml(draw.id)}" type="button">恢复</button>`
            : `<button class="inspiration-favorite ${draw.favorited ? "active" : ""}" data-inspiration-favorite="${escapeHtml(draw.id)}" type="button">${draw.favorited ? "已收藏" : "收藏"}</button>
               <button class="inspiration-delete" data-inspiration-delete="${escapeHtml(draw.id)}" type="button">删除</button>`}
        </div>
      </div>
      <h2 data-reveal>${escapeHtml(draw.title)}</h2>
      <div class="inspiration-keywords" data-reveal>${inspirationKeywordHtml(draw)}</div>
      <p class="draw-text" data-reveal>${escapeHtml(draw.core_insight || draw.text || "")}</p>
      ${draw.why_today ? `<div class="draw-why" data-reveal><span>为什么是今天</span><p>${escapeHtml(draw.why_today)}</p></div>` : ""}
      <div class="draw-prompts" data-reveal>
        <span>今日三问</span>
        <ol>${inspirationPromptHtml(draw)}</ol>
      </div>
      ${inspirationScenesHtml(draw)}
      <div class="draw-action" data-reveal>
        <span>今日行动</span>
        <p>${escapeHtml(draw.action)}</p>
      </div>
      ${inspirationQuoteHtml(draw)}
      ${inspirationSourcesHtml(draw)}
      ${conversions ? `<div class="inspiration-converted-note">已产生 ${conversions} 次明确转化</div>` : ""}
      ${inspirationFeedbackHtml(draw)}
      ${deleted ? "" : `
        <div class="inspiration-card-actions">
          <button class="top-action primary" data-inspiration-new-project="${escapeHtml(draw.id)}" type="button">以此新建项目</button>
          <label>
            <span>加入素材类别</span>
            <select id="inspiration-target-group">
              ${optionsHtml(Object.entries(materialGroupDefinitions).map(([key, value]) => [key, value.label]), draw.target_group)}
            </select>
          </label>
          <button class="top-action" data-inspiration-add-material="${escapeHtml(draw.id)}" type="button">加入当前项目</button>
          <button class="top-action" data-inspiration-ask-mirror="${escapeHtml(draw.id)}" type="button">问镜中人</button>
        </div>
      `}
    </article>
  `;
}

function syncInspirationArchiveControls() {
  const type = $("#inspiration-archive-type");
  const status = $("#inspiration-archive-status");
  if (type) type.value = inspirationArchiveFilters.type;
  if (status) status.value = inspirationArchiveFilters.status;
}

function percentageLabel(value, hasSample) {
  return hasSample ? `${Math.round(Number(value || 0) * 100)}%` : "--";
}

function renderInspirationLearningSummary() {
  const target = $("#inspiration-learning-summary");
  if (!target) return;
  const metrics = inspirationMetrics;
  if (!metrics || !Number(metrics.draw_count || 0)) {
    target.innerHTML = `<div><strong>正在积累个人灵感偏好</strong><span>从下一次反馈开始，匣中镜会记录哪些灵感真正进入了创作。</span></div>`;
    return;
  }
  const hasFeedback = Number(metrics.feedback_count || 0) > 0;
  const hasLatency = Number(metrics.latency?.samples || 0) > 0;
  target.innerHTML = `
    <div class="inspiration-learning-title"><strong>近 ${Number(metrics.period_days || 14)} 天</strong><span>${Number(metrics.draw_count || 0)} 支签正在形成你的灵感偏好</span></div>
    <dl>
      <div><dt>有启发</dt><dd>${percentageLabel(metrics.rates?.useful, hasFeedback)}</dd></div>
      <div><dt>进入创作</dt><dd>${percentageLabel(metrics.rates?.conversion, true)}</dd></div>
      <div><dt>最终发布</dt><dd>${Number(metrics.published_count || 0)} 支</dd></div>
      <div><dt>平均生成</dt><dd>${hasLatency ? `${(Number(metrics.latency.average_ms || 0) / 1000).toFixed(1)}s` : "--"}</dd></div>
    </dl>
  `;
}

function renderInspirationHistory() {
  const target = $("#inspiration-history-list");
  if (!target) return;
  $("#inspiration-history-count").textContent = inspirationLoading ? "读取中" : `${inspirationDraws.length} 支`;
  if (inspirationLoading && !inspirationLoaded) {
    target.innerHTML = `<div class="inspiration-history-empty"><strong>正在同步匣签档案</strong><span>今日结果与历史转化状态会一起加载。</span></div>`;
    return;
  }
  if (!inspirationDraws.length) {
    target.innerHTML = `
      <div class="inspiration-history-empty">
        <strong>${inspirationArchiveFilters.status === "deleted" ? "最近删除为空" : "这个筛选下还没有匣签"}</strong>
        <span>${inspirationArchiveFilters.status === "all" ? "抽出第一支今日签后，这里会按时间记录。" : "可以切换筛选条件查看其它记录。"}</span>
      </div>
    `;
    return;
  }
  target.innerHTML = inspirationDraws.map((draw) => `
    <button class="inspiration-history-item ${viewedInspirationId === draw.id ? "active" : ""}" data-inspiration-view="${escapeHtml(draw.id)}" type="button" aria-label="查看 ${escapeHtml(draw.date)} 的${escapeHtml(draw.type_label)}「${escapeHtml(draw.title)}」">
      <span>${escapeHtml(draw.date)}</span>
      <strong>${escapeHtml(draw.title)}</strong>
      <small>${escapeHtml(draw.type_label)} · ${(draw.keywords || []).map(escapeHtml).join(" / ")}</small>
      <em>${inspirationHistoryStatus(draw)}</em>
    </button>
  `).join("");
}

function inspirationHistoryStatus(draw) {
  if (draw.deleted_at) return "最近删除";
  if (draw.conversion_status === "converted") return "已转化";
  if (draw.feedback?.verdict === "useful") return "有启发";
  if (draw.feedback?.verdict === "not_useful") return "不适合";
  if (draw.favorited) return "已收藏";
  return "未使用";
}

function setInspirationPhase(label) {
  inspirationPhaseLabel = label;
  const target = $("#inspiration-phase");
  if (!target) return;
  const elapsed = inspirationDrawing && inspirationDrawStartedAt
    ? Math.max(0, Math.floor((performance.now() - inspirationDrawStartedAt) / 1000))
    : 0;
  target.textContent = `${label}${elapsed ? ` · ${elapsed}s` : ""}`;
}

function inspirationSleep(ms) {
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  return new Promise((resolve) => window.setTimeout(resolve, reduced ? 20 : ms));
}

async function drawDailyInspiration() {
  if (todayInspirationDraw()) {
    showToast("今日已经抽过签了，明天再问匣中镜一次");
    return;
  }
  const button = $("#draw-inspiration");
  const box = $("#inspiration-box");
  const type = activeInspirationType;
  if (!type || inspirationDrawing) {
    if (!type) showToast("先选择今天要抽哪一类签");
    return;
  }
  inspirationDrawing = true;
  inspirationDrawStartedAt = performance.now();
  window.clearInterval(inspirationElapsedTimer);
  inspirationElapsedTimer = window.setInterval(() => setInspirationPhase(inspirationPhaseLabel), 1000);
  renderInspirationTypes(null);
  button.disabled = true;
  button.textContent = "拾取近况";
  setInspirationPhase("拾取近况");
  if (navigator.vibrate) navigator.vibrate(10);
  box.classList.add("is-drawing");
  const request = XZJApi.json("/api/xiangzhongjing/inspiration/draw", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type })
  });
  try {
    await inspirationSleep(360);
    setInspirationPhase("对照本心");
    button.textContent = "对照本心";
    await inspirationSleep(440);
    setInspirationPhase("翻阅记忆");
    button.textContent = "翻阅记忆";
    await inspirationSleep(520);
    setInspirationPhase("显签");
    button.textContent = "正在显签";
    await inspirationSleep(380);
    const payload = await request;
    const draw = payload.draw;
    if (!draw) throw new Error("灵感签结果为空");
    inspirationServerDate = payload.server_date || draw.date;
    inspirationToday = draw;
    activeInspirationType = draw.type;
    viewedInspirationId = draw.id;
    if (!draw.deleted_at) {
      inspirationDraws = [draw, ...inspirationDraws.filter((item) => item.id !== draw.id && item.date !== draw.date)];
    }
    box.classList.remove("is-drawing");
    box.classList.add("locked");
    inspirationDrawing = false;
    inspirationDrawStartedAt = 0;
    window.clearInterval(inspirationElapsedTimer);
    renderInspirationPage();
    renderInspirationResult(draw, Boolean(payload.created));
    showToast(payload.created ? `已抽出今日${draw.type_label}` : "已返回今天已经生成的匣签");
  } catch (error) {
    box.classList.remove("is-drawing");
    inspirationDrawing = false;
    inspirationDrawStartedAt = 0;
    window.clearInterval(inspirationElapsedTimer);
    setInspirationPhase("等待重试");
    renderInspirationPage();
    if (error.status === 409) await loadInspirationPage({ silent: true });
    showToast(`没有消耗今日机会：${error.message}`);
  }
}

async function patchInspirationDraw(id, patch) {
  const draw = await XZJApi.json(`/api/xiangzhongjing/inspiration/draws/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch)
  });
  replaceInspirationDraw(draw);
  if (patch.conversion || Object.prototype.hasOwnProperty.call(patch, "favorited")) {
    refreshInspirationMetrics();
  }
  return draw;
}

async function refreshInspirationMetrics() {
  try {
    inspirationMetrics = await XZJApi.json("/api/xiangzhongjing/inspiration/metrics?days=14");
    renderInspirationLearningSummary();
  } catch (error) {
    console.warn("Failed to refresh inspiration metrics", error);
  }
}

async function saveInspirationFeedback(id, verdict, reasons = [], note = "") {
  try {
    const draw = await XZJApi.json(`/api/xiangzhongjing/inspiration/draws/${encodeURIComponent(id)}/feedback`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict, reasons, note })
    });
    replaceInspirationDraw(draw);
    pendingInspirationFeedback = null;
    await refreshInspirationMetrics();
    renderInspirationPage();
    showToast(verdict === "useful" ? "已记下：这支签有启发" : "已记录偏差，之后会避开类似方向");
  } catch (error) {
    showToast(`反馈保存失败：${error.message}`);
  }
}

function selectInspirationFeedback(id, verdict) {
  const draw = inspirationDrawById(id);
  if (!draw) return;
  if (verdict === "useful") {
    saveInspirationFeedback(id, "useful");
    return;
  }
  const stored = draw.feedback && typeof draw.feedback === "object" ? draw.feedback : {};
  pendingInspirationFeedback = {
    id,
    verdict: "not_useful",
    reasons: Array.isArray(stored.reasons) ? [...stored.reasons] : [],
    note: stored.note || ""
  };
  renderInspirationPage();
  $(`[data-inspiration-feedback-reason="${CSS.escape(id)}"]`)?.focus();
}

function inspirationMaterialText(draw) {
  return [
    `【${draw.type_label}｜${draw.title}】${draw.core_insight || draw.text || ""}`,
    draw.why_today ? `为什么是今天：${draw.why_today}` : "",
    ...(draw.three_questions || draw.prompts || []).slice(0, 3).map((item) => `继续追问：${item}`),
    ...(draw.shootable_scenes || []).slice(0, 3).map((item) => `可拍场景：${item}`),
    `今日行动：${draw.action}`,
    draw.quote ? `${draw.quote_source || draw.source || "书库"}：${draw.quote}` : ""
  ].filter(Boolean).join("\n");
}

async function addInspirationToCurrentProject(id) {
  const draw = inspirationDrawById(id);
  const project = projects[activeProject];
  if (!draw || !project) return;
  const select = $("#inspiration-target-group");
  const group = materialGroupDefinitions[select?.value] ? select.value : draw.target_group;
  ensureProjectState(project);
  ensureMaterialItems(project)[group].push(newMaterialItem(inspirationMaterialText(draw), group));
  invalidateMaterialCoverage(project);
  syncLegacyMaterialFields(project);
  renderProjects();
  const saved = await persistState("now");
  if (!saved) return;
  try {
    await patchInspirationDraw(id, { conversion: `material:${activeProject}:${group}` });
    renderInspirationPage();
  } catch (error) {
    console.warn("Failed to record inspiration conversion", error);
  }
  showToast(`已加入「${project.title}」的${materialGroupDefinitions[group].label}`);
}

async function createProjectFromInspiration(id) {
  const draw = inspirationDrawById(id);
  if (!draw) return;
  const projectId = `project_${Date.now()}`;
  projects[projectId] = {
    id: projectId,
    title: draw.title,
    description: draw.core_insight || draw.text || "",
    updated: "刚刚创建",
    version: "草稿",
    tags: ["灵感匣签", draw.type_label, ...(draw.keywords || []).slice(0, 2)],
    materials: {
      theme: draw.title,
      insight: [draw.core_insight || draw.text, draw.why_today].filter(Boolean).join("\n"),
      opening: (draw.three_questions || draw.prompts || [draw.question]).filter(Boolean)[0] || "",
      daily: draw.action,
      event: (draw.shootable_scenes || []).join("\n"),
      quotes: draw.quote ? `${draw.quote_source || draw.source || "书库"}：${draw.quote}` : "",
      ending_reference: ""
    },
    generation_mode: "fresh",
    narrative_mode: "default",
    book_quote_strategy: "standard",
    target_length_mode: "auto",
    target_length: 1200,
    clipboard_source: "",
    import_result: null,
    selected_books: defaultBookIds(),
    active_dna_ids: [],
    versions: [],
    locked_paragraphs: [],
    archived: false,
    material_coverage: [],
    copy: `从「${draw.title}」开始写下这条文案。\n\n${draw.core_insight || draw.text || ""}`
  };
  ensureProjectState(projects[projectId]);
  ensureMaterialItems(projects[projectId], true);
  activeProject = projectId;
  renderProjects();
  const saved = await persistState("now");
  if (!saved) return;
  try {
    await patchInspirationDraw(id, { conversion: `project:${projectId}` });
  } catch (error) {
    console.warn("Failed to record inspiration conversion", error);
  }
  selectProject(projectId, { openEditor: true });
  switchEditorTab("materials");
  showToast(`已从「${draw.title}」新建项目`);
}

async function askMirrorWithInspiration(id) {
  const draw = inspirationDrawById(id);
  if (!draw) return;
  try {
    await patchInspirationDraw(id, { conversion: "mirror:conversation" });
  } catch (error) {
    console.warn("Failed to record mirror conversion", error);
  }
  switchPage("mirror");
  window.setTimeout(() => {
    const input = $("#dialogue-input");
    if (!input) return;
    const question = (draw.three_questions || draw.prompts || [draw.question]).filter(Boolean)[0] || "你怎么看这支签？";
    input.value = `今天我抽到了「${draw.title}」：${draw.core_insight || draw.text || ""}\n\n你作为镜中人，和我聊聊：${question}`;
    input.focus();
  }, 180);
}

async function toggleInspirationFavorite(id) {
  const draw = inspirationDrawById(id);
  if (!draw) return;
  try {
    const updated = await patchInspirationDraw(id, { favorited: !draw.favorited });
    if (navigator.vibrate) navigator.vibrate(8);
    renderInspirationPage();
    showToast(updated.favorited ? "已收藏这支签" : "已取消收藏");
  } catch (error) {
    showToast(`收藏状态更新失败：${error.message}`);
  }
}

async function deleteInspirationDraw(id) {
  const draw = inspirationDrawById(id);
  if (!draw) return;
  const confirmed = await requestConfirm({
    title: "移入最近删除？",
    message: `「${draw.title}」会保留在最近删除中；如果是今日签，删除后也不会获得第二次抽签机会。`,
    confirmText: "确认删除",
    danger: true
  });
  if (!confirmed) return;
  try {
    await XZJApi.json(`/api/xiangzhongjing/inspiration/draws/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (inspirationToday?.id === id) inspirationToday = { ...inspirationToday, deleted_at: new Date().toISOString() };
    viewedInspirationId = "";
    await loadInspirationPage({ silent: true });
    showToast("已移入最近删除");
  } catch (error) {
    showToast(`删除失败：${error.message}`);
  }
}

async function restoreInspirationDraw(id) {
  try {
    const draw = await XZJApi.json(`/api/xiangzhongjing/inspiration/draws/${encodeURIComponent(id)}/restore`, { method: "POST" });
    if (inspirationToday?.id === id) inspirationToday = draw;
    viewedInspirationId = draw.id;
    await loadInspirationPage({ silent: true });
    showToast("已恢复这支签");
  } catch (error) {
    showToast(`恢复失败：${error.message}`);
  }
}

async function updateInspirationArchiveFilters() {
  inspirationArchiveFilters = {
    type: $("#inspiration-archive-type")?.value || "",
    status: $("#inspiration-archive-status")?.value || "all"
  };
  viewedInspirationId = "";
  await loadInspirationPage();
}

document.addEventListener("change", (event) => {
  const reason = event.target.closest("[data-inspiration-feedback-reason]");
  if (reason) {
    const id = reason.dataset.inspirationFeedbackReason;
    if (pendingInspirationFeedback?.id !== id) return;
    const values = new Set(pendingInspirationFeedback.reasons || []);
    if (reason.checked) values.add(reason.value);
    else values.delete(reason.value);
    pendingInspirationFeedback.reasons = [...values];
    reason.closest("label")?.classList.toggle("selected", reason.checked);
    return;
  }
  if (event.target.matches("#inspiration-archive-type, #inspiration-archive-status")) {
    updateInspirationArchiveFilters();
  }
});

document.addEventListener("input", (event) => {
  const note = event.target.closest("[data-inspiration-feedback-note]");
  if (!note || pendingInspirationFeedback?.id !== note.dataset.inspirationFeedbackNote) return;
  pendingInspirationFeedback.note = note.value;
});

document.addEventListener("click", (event) => {
  const feedback = event.target.closest("[data-inspiration-feedback]");
  if (feedback) {
    selectInspirationFeedback(feedback.dataset.drawId, feedback.dataset.inspirationFeedback);
    return;
  }
  const feedbackSubmit = event.target.closest("[data-inspiration-feedback-submit]");
  if (feedbackSubmit) {
    const id = feedbackSubmit.dataset.inspirationFeedbackSubmit;
    const pending = pendingInspirationFeedback?.id === id ? pendingInspirationFeedback : null;
    saveInspirationFeedback(id, "not_useful", pending?.reasons || [], pending?.note || "");
    return;
  }
  const typeButton = event.target.closest("[data-inspiration-type]");
  if (typeButton) {
    activeInspirationType = typeButton.dataset.inspirationType;
    viewedInspirationId = "";
    renderInspirationPage();
    persistState();
    return;
  }
  if (event.target.closest("#draw-inspiration")) {
    drawDailyInspiration();
    return;
  }
  const newProject = event.target.closest("[data-inspiration-new-project]");
  if (newProject) {
    createProjectFromInspiration(newProject.dataset.inspirationNewProject);
    return;
  }
  const addMaterial = event.target.closest("[data-inspiration-add-material]");
  if (addMaterial) {
    addInspirationToCurrentProject(addMaterial.dataset.inspirationAddMaterial);
    return;
  }
  const askMirror = event.target.closest("[data-inspiration-ask-mirror]");
  if (askMirror) {
    askMirrorWithInspiration(askMirror.dataset.inspirationAskMirror);
    return;
  }
  const favorite = event.target.closest("[data-inspiration-favorite]");
  if (favorite) {
    toggleInspirationFavorite(favorite.dataset.inspirationFavorite);
    return;
  }
  const remove = event.target.closest("[data-inspiration-delete]");
  if (remove) {
    deleteInspirationDraw(remove.dataset.inspirationDelete);
    return;
  }
  const restore = event.target.closest("[data-inspiration-restore]");
  if (restore) {
    restoreInspirationDraw(restore.dataset.inspirationRestore);
    return;
  }
  const view = event.target.closest("[data-inspiration-view]");
  if (view) {
    viewedInspirationId = view.dataset.inspirationView;
    renderInspirationPage();
    $("#inspiration-result")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});
