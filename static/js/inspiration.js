"use strict";

const inspirationTypes = [
  { id: "theme", label: "主题签", prompt: "我缺一个主题", tone: "今天适合写什么", target: "insight", accent: "red" },
  { id: "emotion", label: "情绪签", prompt: "我缺一种情绪", tone: "今天用什么情绪进入", target: "opening", accent: "blue" },
  { id: "event", label: "事件签", prompt: "我缺一个事件", tone: "从生活抓一个变化点", target: "event", accent: "green" },
  { id: "book", label: "书库签", prompt: "我想从书里开始", tone: "让一句书中话打开思考", target: "quotes", accent: "gold" },
  { id: "mirror", label: "镜中签", prompt: "我想问问自己", tone: "让另一个自己推你一下", target: "insight", accent: "red" },
  { id: "action", label: "行动签", prompt: "我只想先动一下", tone: "给今天一个具体动作", target: "daily", accent: "blue" }
];

let viewedInspirationId = "";

const inspirationBanks = {
  theme: [
    { title: "重新命名", keywords: ["观察", "变化", "开始"], text: "今天先别急着找答案，试着给最近反复出现的变化重新起一个名字。", question: "最近哪件小事，正在改变你看待生活的方式？", action: "写下三个具体画面，再为它们找一个共同主题。", quote: "", source: "" },
    { title: "未完成的事", keywords: ["悬念", "继续", "选择"], text: "未完成不等于失败，它也可能是一个值得继续追问的入口。", question: "最近哪件没有结果的事，仍然让你在意？", action: "只写事情的起点、停顿和你此刻的新判断。", quote: "", source: "" },
    { title: "日常偏移", keywords: ["细节", "习惯", "转折"], text: "真正的变化常常先发生在日常安排里，然后才被我们意识到。", question: "最近哪个习惯悄悄发生了变化？", action: "从一个生活动作写到它背后的原因。", quote: "", source: "" }
  ],
  emotion: [
    { title: "安静用力", keywords: ["克制", "积累", "清醒"], text: "情绪不一定要爆发，它也可以成为推动一件事慢慢发生的力量。", question: "最近哪一次沉默，其实包含了很多决定？", action: "写出当时没有说出口的那句话。", quote: "", source: "" },
    { title: "允许疲惫", keywords: ["疲惫", "节奏", "恢复"], text: "承认疲惫不是停下，而是重新找到可以继续的节奏。", question: "最近什么让你累，又为什么仍然值得？", action: "写下那天结束前的最后一个动作。", quote: "", source: "" },
    { title: "轻微兴奋", keywords: ["期待", "发现", "靠近"], text: "有些期待很小，却足以让普通的一天变得不一样。", question: "最近哪件小事让你提前期待明天？", action: "把期待写成一个可以拍到的画面。", quote: "", source: "" }
  ],
  event: [
    { title: "计划之外", keywords: ["意外", "反应", "变化"], text: "计划之外发生的事，最容易暴露一个人真正重视什么。", question: "最近哪件意外让你临时改变了安排？", action: "列出意外发生前、当下和之后各一个画面。", quote: "", source: "" },
    { title: "重复路线", keywords: ["秩序", "场所", "生活"], text: "重复的路线里，也藏着一个人最近的生活重心。", question: "你最近最常出现在哪三个地方？", action: "用三个地点串成一段蒙太奇。", quote: "", source: "" },
    { title: "一次相逢", keywords: ["人物", "对话", "回声"], text: "一次普通的交流，也可能让原本模糊的想法突然变清楚。", question: "最近谁的一句话让你停下来想了很久？", action: "写出那句话，以及你当时没有说出口的回应。", quote: "", source: "" }
  ],
  book: [
    { title: "打开书库", keywords: ["原句", "联想", "理解"], text: "去自己的精神书库里找一句最近真正读进去的话，不必先证明它有多深刻。", question: "这句话为什么偏偏在今天重新出现？", action: "写下原句、你的理解，以及它对应的一件真实小事。", quote: "", source: "个人精神书库" },
    { title: "反向追问", keywords: ["观点", "反问", "边界"], text: "一本书的价值不只在于给答案，也在于帮助你提出更准确的问题。", question: "你最想反问书中哪个观点？", action: "先写认同，再写保留，最后写你的选择。", quote: "", source: "个人精神书库" },
    { title: "一句落地", keywords: ["引用", "事件", "时机"], text: "好的引文不是装饰，而是在事件已经走到那里时，替你把判断说得更准。", question: "哪一件真实经历，值得由书中的一句话照亮？", action: "先写事件，再决定原句应该出现在哪个转念之后。", quote: "", source: "个人精神书库" }
  ],
  mirror: [
    { title: "问问过去", keywords: ["自己", "时间", "选择"], text: "先不问别人怎么看，问问更早的自己为什么会走到今天。", question: "一年前的你会如何理解现在这个选择？", action: "写一段过去的你与现在的你的对话。", quote: "", source: "" },
    { title: "保留什么", keywords: ["本心", "变化", "边界"], text: "成长会改变很多东西，但你仍然可以决定哪些部分不交出去。", question: "最近的变化里，你最想保留自己身上的什么？", action: "写一个改变，再写一个不变。", quote: "", source: "" },
    { title: "诚实回答", keywords: ["诚实", "犹豫", "决定"], text: "有些问题不是没有答案，只是答案暂时不够体面。", question: "如果不用向任何人解释，你真正想怎么做？", action: "先写最诚实的答案，再写现实边界。", quote: "", source: "" }
  ],
  action: [
    { title: "三格蒙太奇", keywords: ["画面", "节奏", "发展"], text: "今天不要先讲道理，先让三个具体画面把主题托起来。", question: "今天最值得留下的三个画面是什么？", action: "每个画面只写地点、动作和变化。", quote: "", source: "" },
    { title: "一句开场", keywords: ["开头", "钩子", "交流"], text: "先完成一句真的想对观众说的话，剩下的内容可以从它慢慢展开。", question: "如果只能告诉观众一件事，你会先说什么？", action: "写五个不同版本的第一句话。", quote: "", source: "" },
    { title: "回扣练习", keywords: ["首尾", "呼应", "余味"], text: "结尾不必突然拔高，让开头那句话经历全文以后重新回来就够了。", question: "你想让哪句话在结尾再次出现？", action: "写一个开头，再写一个改变含义后的回扣。", quote: "", source: "" }
  ]
};

function todayKey() {
  const date = new Date();
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function inspirationHash(value) {
  return String(value).split("").reduce((sum, char) => ((sum << 5) - sum + char.charCodeAt(0)) >>> 0, 0);
}

function inspirationTypeMeta(type) {
  return inspirationTypes.find((item) => item.id === type) || inspirationTypes[0];
}

function todayInspirationDraw() {
  const date = todayKey();
  return inspirationDraws.find((item) => item.date === date && item.locked);
}

function buildInspirationDraw(type) {
  const date = todayKey();
  const bank = inspirationBanks[type] || inspirationBanks.theme;
  const index = inspirationHash(`${date}:${type}:${activeProject}`) % bank.length;
  const seed = bank[index];
  const meta = inspirationTypeMeta(type);
  return {
    id: `inspiration_${Date.now()}`,
    date,
    type,
    type_label: meta.label,
    title: seed.title,
    keywords: seed.keywords,
    text: seed.text,
    question: seed.question,
    prompts: [
      seed.question,
      "它为什么偏偏在今天重新出现？",
      "它可以成为这条视频里的开头、转念还是回扣？"
    ],
    action: seed.action,
    quote: seed.quote,
    source: seed.source,
    target_group: meta.target,
    favorited: false,
    converted_to: [],
    locked: true,
    created_at: new Date().toISOString()
  };
}

function renderInspirationPage() {
  const draw = todayInspirationDraw();
  if (draw) activeInspirationType = draw.type;
  if (activeInspirationType && !inspirationTypes.some((item) => item.id === activeInspirationType)) {
    activeInspirationType = "";
  }
  renderInspirationTypes(draw);
  renderInspirationStage(draw);
  const viewedDraw = inspirationDraws.find((item) => item.id === viewedInspirationId);
  renderInspirationResult(viewedDraw || draw);
  renderInspirationHistory();
}

function renderInspirationTypes(draw) {
  const target = $("#inspiration-type-grid");
  if (!target) return;
  target.innerHTML = inspirationTypes.map((type) => {
    const selected = activeInspirationType === type.id;
    const lockedOut = Boolean(draw && draw.type !== type.id);
    return `
      <button class="inspiration-type-card ${selected ? "selected" : ""} ${lockedOut ? "locked-out" : ""}" data-inspiration-type="${type.id}" type="button" aria-pressed="${String(selected)}" ${draw ? "disabled" : ""}>
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
  $("#inspiration-slip-label").textContent = draw ? draw.title : (meta?.label || "匣中镜");
  $("#inspiration-today-state").textContent = draw ? `今日已抽：${draw.type_label}` : "今日未抽";
  $("#inspiration-picked-label").textContent = draw ? draw.type_label : (meta?.label || "未选择");
  $("#inspiration-phase").textContent = draw ? "今日签已定" : (meta ? "等待开匣" : "等待选择");
  $("#inspiration-stage-title").textContent = draw ? `今日签：${draw.title}` : (meta ? `今日将抽：${meta.label}` : "先选一类签");
  $("#inspiration-stage-desc").textContent = draw
    ? "今日签类已经锁定，明天会重新开放选择。"
    : "抽签前可以切换签类，抽出后今日不可再抽其他签。";
  $("#inspiration-lock-note").textContent = draw
    ? "今日已完成抽签，可收藏、转项目、加入素材或带去问镜中人。"
    : "今天只能问匣中镜一次，选好再抽。";
  button.disabled = Boolean(draw || !meta);
  button.textContent = draw ? "今日已抽签" : (meta ? `抽今日${meta.label}` : "先选一类签");
}

function inspirationKeywordHtml(draw) {
  return (draw.keywords || []).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("");
}

function inspirationPromptHtml(draw) {
  const prompts = Array.isArray(draw.prompts) && draw.prompts.length ? draw.prompts : [draw.question].filter(Boolean);
  return prompts.map((item, index) => `
    <li>
      <b>${String(index + 1).padStart(2, "0")}</b>
      <span>${escapeHtml(item)}</span>
    </li>
  `).join("");
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
  target.innerHTML = `
    <article class="inspiration-draw-card ${revealing ? "is-revealing" : ""}" data-draw-id="${escapeHtml(draw.id)}">
      <div class="draw-card-head">
        <span>${escapeHtml(draw.type_label)} · ${escapeHtml(isToday ? "今日签" : draw.date)}</span>
        <button class="inspiration-favorite ${draw.favorited ? "active" : ""}" data-inspiration-favorite="${escapeHtml(draw.id)}" type="button">${draw.favorited ? "已收藏" : "收藏"}</button>
      </div>
      <h2 data-reveal>${escapeHtml(draw.title)}</h2>
      <div class="inspiration-keywords" data-reveal>${inspirationKeywordHtml(draw)}</div>
      <p class="draw-text" data-reveal>${escapeHtml(draw.text)}</p>
      <div class="draw-prompts" data-reveal>
        <span>今日三问</span>
        <ol>${inspirationPromptHtml(draw)}</ol>
      </div>
      <div class="draw-action" data-reveal>
        <span>今日动作</span>
        <p>${escapeHtml(draw.action)}</p>
      </div>
      <div class="draw-quote" data-reveal>
        <span>${escapeHtml(draw.source || "匣中镜")} · 直引</span>
        <p>${escapeHtml(draw.quote)}</p>
      </div>
      ${conversions ? `<div class="inspiration-converted-note">已转化 ${conversions} 次，可在项目素材或对话入口继续使用。</div>` : ""}
      <div class="inspiration-card-actions">
        <button class="top-action primary" data-inspiration-new-project="${escapeHtml(draw.id)}" type="button">以此新建项目</button>
        <label>
          <span>加入素材</span>
          <select id="inspiration-target-group">
            ${optionsHtml(Object.entries(materialGroupDefinitions).map(([key, value]) => [key, value.label]), draw.target_group)}
          </select>
        </label>
        <button class="top-action" data-inspiration-add-material="${escapeHtml(draw.id)}" type="button">加入当前项目</button>
        <button class="top-action" data-inspiration-ask-mirror="${escapeHtml(draw.id)}" type="button">问镜中人</button>
      </div>
    </article>
  `;
}

function renderInspirationHistory() {
  const target = $("#inspiration-history-list");
  if (!target) return;
  const sorted = [...inspirationDraws].sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))).slice(0, 30);
  $("#inspiration-history-count").textContent = `${sorted.length} 支`;
  if (!sorted.length) {
    target.innerHTML = `
      <div class="inspiration-history-empty">
        <strong>还没有历史签</strong>
        <span>抽出第一支今日签后，这里会按时间记录。</span>
      </div>
    `;
    return;
  }
  target.innerHTML = sorted.map((draw) => `
    <button class="inspiration-history-item ${viewedInspirationId === draw.id ? "active" : ""}" data-inspiration-view="${escapeHtml(draw.id)}" type="button" aria-label="查看 ${escapeHtml(draw.date)} 的${escapeHtml(draw.type_label)}「${escapeHtml(draw.title)}」">
      <span>${escapeHtml(draw.date)}</span>
      <strong>${escapeHtml(draw.title)}</strong>
      <small>${escapeHtml(draw.type_label)} · ${(draw.keywords || []).map(escapeHtml).join(" / ")}</small>
    </button>
  `).join("");
}

function setInspirationPhase(label) {
  const target = $("#inspiration-phase");
  if (target) target.textContent = label;
}

function inspirationSleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function drawDailyInspiration() {
  if (todayInspirationDraw()) {
    showToast("今日已经抽过签了，明天再问匣中镜一次");
    return;
  }
  const button = $("#draw-inspiration");
  const box = $("#inspiration-box");
  const type = activeInspirationType;
  if (!type) {
    showToast("先选择今天要抽哪一类签");
    return;
  }
  button.disabled = true;
  button.textContent = "唤醒中";
  setInspirationPhase("唤醒匣中镜");
  if (navigator.vibrate) navigator.vibrate(10);
  box.classList.add("is-drawing");
  await inspirationSleep(520);
  setInspirationPhase("开匣");
  button.textContent = "开匣中";
  await inspirationSleep(720);
  setInspirationPhase("抽签");
  button.textContent = "抽签中";
  await inspirationSleep(980);
  setInspirationPhase("显字");
  await inspirationSleep(630);
  const draw = buildInspirationDraw(type);
  viewedInspirationId = draw.id;
  inspirationDraws = [draw, ...inspirationDraws.filter((item) => item.date !== draw.date)].slice(0, 365);
  box.classList.remove("is-drawing");
  box.classList.add("locked");
  setInspirationPhase("今日签已定");
  renderInspirationPage();
  renderInspirationResult(draw, true);
  await persistState("now");
  showToast(`已抽出今日${draw.type_label}`);
}

function markDrawConverted(draw, label) {
  if (!Array.isArray(draw.converted_to)) draw.converted_to = [];
  if (!draw.converted_to.includes(label)) draw.converted_to.push(label);
}

function inspirationMaterialText(draw) {
  return [
    `【${draw.type_label}｜${draw.title}】${draw.text}`,
    `今日提问：${draw.question}`,
    `今日动作：${draw.action}`,
    draw.quote ? `${draw.source || "书库"}：${draw.quote}` : ""
  ].filter(Boolean).join("\n");
}

function addInspirationToCurrentProject(id) {
  const draw = inspirationDraws.find((item) => item.id === id);
  const project = projects[activeProject];
  if (!draw || !project) return;
  const select = $("#inspiration-target-group");
  const group = materialGroupDefinitions[select?.value] ? select.value : draw.target_group;
  ensureProjectState(project);
  ensureMaterialItems(project)[group].push(newMaterialItem(inspirationMaterialText(draw), group));
  invalidateMaterialCoverage(project);
  syncLegacyMaterialFields(project);
  markDrawConverted(draw, `material:${activeProject}:${group}`);
  renderProjects();
  renderInspirationHistory();
  persistState("now");
  showToast(`已加入「${project.title}」的${materialGroupDefinitions[group].label}`);
}

function createProjectFromInspiration(id) {
  const draw = inspirationDraws.find((item) => item.id === id);
  if (!draw) return;
  const projectId = `project_${Date.now()}`;
  projects[projectId] = {
    id: projectId,
    title: draw.title,
    description: draw.text,
    updated: "刚刚创建",
    version: "草稿",
    tags: ["灵感匣签", draw.type_label, ...(draw.keywords || []).slice(0, 2)],
    materials: {
      theme: draw.title,
      insight: draw.text,
      opening: draw.question,
      daily: draw.action,
      event: "",
      quotes: draw.quote ? `${draw.source || "书库"}：${draw.quote}` : "",
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
    copy: `从「${draw.title}」开始写下这条文案。\n\n${draw.text}`
  };
  ensureProjectState(projects[projectId]);
  ensureMaterialItems(projects[projectId], true);
  markDrawConverted(draw, `project:${projectId}`);
  activeProject = projectId;
  renderProjects();
  persistState("now");
  selectProject(projectId, { openEditor: true });
  switchEditorTab("materials");
  showToast(`已从「${draw.title}」新建项目`);
}

function askMirrorWithInspiration(id) {
  const draw = inspirationDraws.find((item) => item.id === id);
  if (!draw) return;
  switchPage("mirror");
  window.setTimeout(() => {
    const input = $("#dialogue-input");
    if (!input) return;
    input.value = `今天我抽到了「${draw.title}」：${draw.text}\n\n你作为镜中人，帮我用我自己的语气聊聊：${draw.question}`;
    input.focus();
  }, 180);
}

function toggleInspirationFavorite(id) {
  const draw = inspirationDraws.find((item) => item.id === id);
  if (!draw) return;
  draw.favorited = !draw.favorited;
  if (navigator.vibrate) navigator.vibrate(8);
  renderInspirationPage();
  persistState("now");
  showToast(draw.favorited ? "已收藏这支签" : "已取消收藏");
}

document.addEventListener("click", (event) => {
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
  const view = event.target.closest("[data-inspiration-view]");
  if (view) {
    viewedInspirationId = view.dataset.inspirationView;
    renderInspirationPage();
    $("#inspiration-result")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
});
