const strategyContent = {
  a: {
    label: "RECOMMENDED NOW",
    title: "单人创作操作系统",
    summary: "继续服务真实的创作者本人创作流程，证明它能够稳定地比通用模型更像本人、更快发稿。",
    focus: "质量证明",
    focusDetail: "建立首稿采用率、编辑距离、发布耗时与风格人工评分。",
    gate: "接下来 3-5 个真实项目",
    gateDetail: ["无感记录重生成与编辑距离", "记录创作耗时与最终采用", "v2.1 保留为稳定基线"],
  },
  b: {
    label: "NEXT VALIDATION",
    title: "垂直生活 Vlog 创作工具",
    summary: "将风格蒸馏与文案工作流复制到 10-30 位同类创作者，验证产品能否从“对一个人有效”转向“方法可复制”。",
    focus: "蒸馏标准化",
    focusDetail: "上传语料、评估证据、发布 Skill 和首稿生成必须能在无开发陪同下完成。",
    gate: "路线 A 指标达标后启动",
    gateDetail: ["60 分钟完成首个 Skill", "80% 用户独立完成", "新用户首稿采用 >= 50%"],
  },
  c: {
    label: "LONG-TERM OPTION",
    title: "创作者数字分身平台",
    summary: "让写作、对话、知识和人设资产共用一个持续进化的个人模型。这条路线想象空间最大，也最容易在核心价值未证明时消耗资源。",
    focus: "资产复用证据",
    focusDetail: "镜中人与书中人先作为思考实验，只在对话资产真实进入创作时扩大投入。",
    gate: "不在当前阶段主动扩张",
    gateDetail: ["对话资产复用率 >= 30%", "人格一致性 >= 4/5", "不降低核心发稿率"],
  },
};

const architectureContent = {
  current: {
    title: "已落地：单人创作 OS 的模块化单体",
    summary: "保留 FastAPI、SQLite 和原生前端的本地效率，同时建立清晰的 API、应用、交互和样式边界。",
    stats: [["main.py", "52 行"], ["Frontend", "8 JS / 10 CSS"], ["Contracts", "Pydantic"], ["Tests", "98 通过"]],
    layers: [
      ["体验层", "NATIVE MODULES", [["核心结构", "831 行语义 HTML"], ["交互模块", "API / 素材 / 工作区 / 生成 / 对话"], ["样式分层", "10 个有序 CSS 领域"], ["图标与响应式", "本地 Lucide + 移动导航"]]],
      ["接口层", "FASTAPI ROUTERS", [["Pages", "页面与静态资源"], ["Generation", "生成与编辑"], ["Library / Style", "书库与风格版本"], ["Dialogue / State", "对话与状态"]]],
      ["应用层", "USE CASES", [["Generation", "写作与运行边界"], ["Library Support", "书库支撑"], ["Style", "蒸馏与版本"], ["Compatibility Engine", "隔离旧 DeepSeek 引擎"]]],
      ["数据层", "LOCAL SQLITE", [["app_state", "revision 乐观冲突"], ["Serial Save", "前端串行保存"], ["Publication", "日记持久化失败回滚"], ["Privacy", "127.0.0.1 本地边界"]]],
    ],
    risks: [["DONE", "前后端已建立领域边界"], ["DONE", "多窗口静默覆盖已转为 409 冲突"], ["DONE", "默认本地绑定 127.0.0.1"], ["WATCH", "DeepSeek 兼容引擎仍需渐进内聚"]],
  },
  target: {
    title: "后续：证据驱动的个人创作核心",
    summary: "不更换技术栈，不扩张多用户。架构只围绕生成稳定、风格可比、发稿更快继续演进。",
    stats: [["样本", "3-5 项目"], ["Stable", "v2.1"], ["Candidate", "v2.2"], ["Decision", "人工审核"]],
    layers: [
      ["产品层", "REAL WORKFLOW", [["创作台", "真实项目与素材"], ["个人 Skill", "v2.1 稳定 / v2.2 候选"], ["发布日记", "最终采用与时间"], ["思考空间", "不与项目强绑定"]]],
      ["应用层", "FOCUSED SERVICES", [["Generation", "生成、字数、编排与书库支撑"], ["Editing", "原句 / 改写 / 阐释"], ["Style", "蒸馏、版本、A/B"], ["Dialogue", "镜中人与书中人"]]],
      ["AI 运行层", "SHORT SKILL CHAIN", [["个人写作", "风格化拓展"], ["爆款 Vlog", "平台结构优化"], ["金句植入", "直接引用与语义衔接"], ["证据记录", "不打断创作"]]],
      ["数据层", "MEASUREMENT", [["Regeneration", "重生成次数"], ["Edit Distance", "从首稿到最终稿"], ["Creative Time", "从项目到发布"], ["Adoption", "采用 / 小改 / 重写 / 放弃"]]],
    ],
    risks: [["RULE", "不为架构而架构"], ["RULE", "不改动 v2.1 稳定版"], ["RULE", "v2.2 不经人工审核不发布"], ["RULE", "先证明比通用模型更像本人、更快发稿"]],
  },
};

function renderStrategy(key) {
  const data = strategyContent[key];
  const target = document.querySelector("#strategy-detail");
  if (!data || !target) return;
  target.innerHTML = `
    <div>
      <span>${data.label}</span>
      <h3>${data.title}</h3>
      <p>${data.summary}</p>
    </div>
    <div>
      <span>FOCUS</span>
      <strong>${data.focus}</strong>
      <p>${data.focusDetail}</p>
    </div>
    <div>
      <span>GATE</span>
      <strong>${data.gate}</strong>
      <ul>${data.gateDetail.map((item) => `<li>${item}</li>`).join("")}</ul>
    </div>`;
}

function renderArchitecture(key) {
  const data = architectureContent[key];
  const target = document.querySelector("#architecture-panel");
  if (!data || !target) return;
  const layers = data.layers.map(([label, kicker, modules]) => `
    <section class="architecture-layer">
      <div class="layer-label"><span>${kicker}</span><strong>${label}</strong></div>
      <div class="layer-modules">
        ${modules.map(([title, note]) => `<div><strong>${title}</strong><small>${note}</small></div>`).join("")}
      </div>
    </section>`).join("");
  target.innerHTML = `
    <div class="architecture-intro">
      <div><h3>${data.title}</h3><p>${data.summary}</p></div>
      <dl>${data.stats.map(([label, value]) => `<div><dt>${label}</dt><dd>${value}</dd></div>`).join("")}</dl>
    </div>
    <div class="architecture-stack">${layers}</div>
    <div class="architecture-risks">
      ${data.risks.map(([level, risk]) => `<div><span>${level}</span><strong>${risk}</strong></div>`).join("")}
    </div>`;
}

function setupTabGroup(selector, dataKey, render, initial) {
  const buttons = [...document.querySelectorAll(selector)];
  let activeValue = initial;
  const apply = (value, focus = false) => {
    activeValue = value;
    buttons.forEach((button) => {
      const active = button.dataset[dataKey] === activeValue;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && focus) button.focus();
    });
    render(activeValue);
  };
  buttons.forEach((button, index) => {
    button.addEventListener("click", () => apply(button.dataset[dataKey]));
    button.addEventListener("keydown", (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === 'ArrowLeft') next = (index - 1 + buttons.length) % buttons.length;
      if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = buttons.length - 1;
      apply(buttons[next].dataset[dataKey], true);
    });
  });
  apply(initial);
}

function setupRoadmapFilter() {
  const buttons = [...document.querySelectorAll("[data-roadmap-filter]")];
  const phases = [...document.querySelectorAll("[data-roadmap-tags]")];
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const filter = button.dataset.roadmapFilter;
      buttons.forEach((item) => item.classList.toggle("active", item === button));
      phases.forEach((phase) => {
        const tags = String(phase.dataset.roadmapTags || "").split(" ");
        phase.classList.toggle("filtered-out", filter !== "all" && !tags.includes(filter));
      });
    });
  });
}

function setupReadingProgress() {
  const bar = document.querySelector("#reading-progress-bar");
  const update = () => {
    const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
    const progress = Math.max(0, Math.min(1, window.scrollY / max));
    if (bar) bar.style.width = `${progress * 100}%`;
  };
  update();
  window.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
}

function setupActiveNavigation() {
  const links = [...document.querySelectorAll(".evaluation-nav a")];
  const entries = links.map((link) => ({
    link,
    section: document.querySelector(link.getAttribute("href")),
  })).filter((item) => item.section);
  if (!("IntersectionObserver" in window)) return;
  const observer = new IntersectionObserver((observed) => {
    const visible = observed.filter((item) => item.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    links.forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${visible.target.id}`));
  }, { rootMargin: "-25% 0px -60%", threshold: [0.05, 0.2, 0.5] });
  entries.forEach((item) => observer.observe(item.section));
}

document.querySelector("#print-review")?.addEventListener("click", () => window.print());
setupTabGroup("[data-strategy]", "strategy", renderStrategy, "a");
setupTabGroup("[data-architecture]", "architecture", renderArchitecture, "current");
setupRoadmapFilter();
setupReadingProgress();
setupActiveNavigation();
