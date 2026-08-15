"use strict";

const moduleDomains = {
  creation: "创作生产",
  intelligence: "创作者智能",
  knowledge: "思考与知识",
  identity: "身份与视觉"
};

const productModules = {
  workspace: {
    title: "创作台",
    domain: "creation",
    summary: "管理全部创作项目，并快速回到上一次真实创作现场。",
    value: "把项目主题、活跃状态、归档和当前入口统一到一个稳定的项目层，不让用户每次都从零寻找内容。",
    outputs: ["新建项目", "搜索项目", "项目归档", "恢复归档", "删除确认", "当前项目入口"],
    boundary: "归档不删除素材、版本、日记和封面；项目源稿与发布快照各自独立。"
  },
  editor: {
    title: "当前项目",
    domain: "creation",
    summary: "在一个页面完成素材输入、完整文案生成、人工精修、版本保存和正式发布。",
    value: "让从真实生活材料到可录制文案的路径连续、可控，并保留用户每一次人工修改的权威性。",
    outputs: ["六类素材", "新写/改写", "四种叙事模式", "字数硬约束", "金句策略", "版本与发布"],
    boundary: "改写当前稿时，编辑器正文是唯一事实和内容边界，原始项目素材不再进入模型。"
  },
  inspiration: {
    title: "灵感匣签",
    domain: "creation",
    summary: "每天从六类签中只选择一类抽取一次，让灵感成为一个有仪式感但无负担的入口。",
    value: "当用户没有明确选题时，用主题、情绪、事件、书库、镜中或行动六种角度打开今天的创作。",
    outputs: ["每日一次", "六类签", "今日三问", "今日动作", "新建项目", "转素材/问镜中人"],
    boundary: "抽出后按本地日期锁定；历史签可回看，但不能反复抽取制造选择疲劳。"
  },
  diary: {
    title: "日记本",
    domain: "creation",
    summary: "把每一次正式发布按时间装订成第 01-100 页的创作日记。",
    value: "让发布不只是一次导出，而成为能被复盘的个人创作历程，并触发无负担质量观察。",
    outputs: ["发布快照", "时间排序", "翻页阅读", "100 页", "删除确认", "质量观察触发"],
    boundary: "删除日记页不删除项目源稿；日记保存的是发布当下的不可联动快照。"
  },
  distill: {
    title: "内容蒸馏",
    domain: "intelligence",
    summary: "从成熟历史视频正文中提炼可执行、可审核、可发布和可回退的个人创作 Skill。",
    value: "把“像本人”从一句模糊提示词变成有版本、有证据、有优先级的长期个人能力。",
    outputs: ["历史稿上传", "正文隔离", "候选 Skill", "A/B 审核", "版本发布", "v2.1 回退"],
    boundary: "当前运行发布版为 v2.2；候选版本必须由用户明确发布，指标不会自动替用户升级。"
  },
  dna: {
    title: "DNA 试剂",
    domain: "intelligence",
    summary: "将其他博主样本蒸馏为可选的轻量表达风味，并按项目显式启用。",
    value: "在不稀释创作者本人个人 DNA 的前提下，尝试一种局部节奏或表达气质。",
    outputs: ["样本粘贴/上传", "外部风味蒸馏", "开关管理", "项目选择", "最多少量启用"],
    boundary: "外部试剂不得带入对方事实、身份、事件、观点或原句，也不能覆盖个人主风格。"
  },
  settings: {
    title: "设置与 Skill 管理",
    domain: "intelligence",
    summary: "可视化管理文本模型、生图、可选搜索服务与当前产品的系统 Skill。",
    value: "让关键配置与真实运行文件可见、可测试、可修改，降低交接和部署门槛。",
    outputs: ["模型配置", "生图配置", "搜索配置", "连接测试", "Skill 查看/编辑", "恢复内置版本"],
    boundary: "个人创作 Skill 与流程 Skill 分区；团队旧 Skill 不得静默覆盖当前本地最新版。"
  },
  library: {
    title: "精神书库",
    domain: "knowledge",
    summary: "管理《剑来》《埃隆·马斯克传》《道德经》及个人阅读资料，并为生成提供质量可控的直接引文。",
    value: "让金句来自用户拥有的真实资料，在叙事转念中增强思想密度，而不是调用模型记忆拼句。",
    outputs: ["548 条素材", "243 条可用直引", "本地笔记上传", "质量分层", "来源定位", "生成时自动支撑"],
    boundary: "只有 direct_quote + valid 进入生成；文案引用不联网、不转述、不由模型补全。"
  },
  mirror: {
    title: "镜中人",
    domain: "knowledge",
    summary: "与由个人 Skill、11 篇历史文稿记忆、全局人设资产和会话记忆共同构成的另一个自己交流。",
    value: "获得像创作者本人一样的追问和思考延展，而不是通用助手式建议。",
    outputs: ["开放式对话", "11 篇记忆包", "会话管理", "长短期记忆", "身份语气", "主动沉淀"],
    boundary: "不绑定当前项目、不自动写入创作素材；历史记忆提供表达与思考证据，不迁移旧事实。"
  },
  book: {
    title: "书中人",
    domain: "knowledge",
    summary: "分别与马斯克、陈平安、齐静春和老子四位书中人格进行开放式交流。",
    value: "从行动、道路、担当和取舍四种思想框架讨论真实问题，并保留来源边界。",
    outputs: ["四位人格", "独立会话", "思考中状态", "本地书库依据", "可选联网增强", "引用核验"],
    boundary: "每位人格的会话独立；联网搜索只增强当前对话，不进入文案书库链路。"
  },
  assets: {
    title: "资产库",
    domain: "knowledge",
    summary: "独立管理镜中人与书中人对话中被用户主动确认的沉淀素材。",
    value: "让长期交流不消失在聊天记录里，同时避免未经确认的对话内容污染创作项目。",
    outputs: ["镜中人分类", "书中人分类", "来源会话", "对话对象", "搜索筛选", "更改所属类别"],
    boundary: "删除会话不自动删除已沉淀资产；资产也不会自动进入当前项目。"
  },
  profile: {
    title: "个人信息",
    domain: "identity",
    summary: "像个人主页一样管理头像、显示身份、创作者定位、栏目和视觉偏好。",
    value: "建立全局统一的创作者身份，并为封面生成提供稳定的形象与视觉上下文。",
    outputs: ["头像", "显示名与账号", "创作者定位", "栏目方向", "风格关键词", "视觉偏好"],
    boundary: "个人信息是全局身份资产，不绑定某一个创作项目。"
  },
  covers: {
    title: "封面图",
    domain: "identity",
    summary: "在封面资产与生成工作台两个子页中，生成、保存、下载并管理项目封面。",
    value: "把作品从完整文案推进到可发布视觉，并逐步形成特定栏目的稳定封面语言。",
    outputs: ["项目绑定", "默认头像参考", "自定义参考图", "风格预设", "本地资产", "下载/回项目"],
    boundary: "图片和元数据本地保存；API Key 只来自安全配置，第三方失败显示真实原因。"
  }
};

const executionContracts = {
  generation: {
    kicker: "FRESH DRAFT",
    title: "从项目素材新写",
    summary: "读取当前项目素材和所有显式生成参数，用个人 DNA 将事实发展成完整叙事，而非整理素材。",
    input: "主题、六类素材、叙事模式、字数、书籍、金句策略、可选 DNA 试剂",
    rules: ["素材作为事实边界和叙事燃料", "至少建立事件之间的对照、因果或递进", "依次执行个人写作、抖音优化、书库支撑", "禁止新增素材中不存在的具体事实"]
  },
  rewrite: {
    kicker: "CURRENT COPY ONLY",
    title: "只改写当前编辑器正文",
    summary: "用户已经修改过的正文拥有最高权威。系统只基于这份文本和个人 DNA 优化，不回头读取旧素材。",
    input: "当前编辑器正文、锁定段落、叙事/字数/书库策略、个人 Skill",
    rules: ["不读取项目主题、洞察、日常或事件素材", "不恢复用户已经删除的旧内容", "保留当前稿事实、人物、日期、对话和立场", "优化段落推进、思考关系、长短句呼吸和收束"]
  },
  length: {
    kicker: "HARD LENGTH CONTRACT",
    title: "手动字数是最终硬约束",
    summary: "自动模式由素材密度决定篇幅；手动模式要求每个阶段和最终稿都进入严格范围。",
    input: "自动，或 300-3000 字的手动上限",
    rules: ["下限为上限减 10%，且至少减 60 字", "初稿、抖音优化、书库植入后分别复核", "超出时调用个人写作 Skill 校准，不做机械截断", "最终仍不合格则失败，不覆盖编辑器"]
  },
  narrative: {
    kicker: "ONE STRATEGY AT A TIME",
    title: "四种模式只改变叙事运动",
    summary: "默认、排比递进、六段式和先抑后扬只激活用户选择的一种；事实、DNA 与长度契约始终优先。",
    input: "默认 / 排比递进 / 六段式 / 先抑后扬",
    rules: ["默认：事实先于结论，自由组织回扣", "排比：3-5 个层级变化后具体收回", "六段：引入、发展、高潮、沉淀、回扣、升华", "先抑后扬：变化必须由真实行动或理解触发"]
  },
  quotes: {
    kicker: "DIRECT QUOTE ONLY",
    title: "先判断时机，再匹配金句",
    summary: "只从本地通过质量门的直接引文中选择；模型不能改写、补全或凭记忆创造书中原句。",
    input: "已选书籍 + 克制/标准/增强策略 + 完整文案",
    rules: ["克制目标 1 条", "标准目标 2 条、最多 3 条", "增强目标 3 条且承担不同叙事作用", "没有自然位置时减少数量并说明原因"]
  },
  dialogue: {
    kicker: "USER-CONTROLLED MEMORY",
    title: "对话不自动污染创作",
    summary: "聊天与项目完全解耦。只有用户主动点击沉淀的片段才进入独立资产库，并保留来源。",
    input: "镜中人/书中人会话 + 用户主动选择的片段",
    rules: ["资产记录来源会话与对话对象", "支持分类、搜索和更改所属类别", "删除会话不自动删除资产", "资产不自动写入当前项目"]
  }
};

function renderModule(key) {
  const item = productModules[key] || productModules.workspace;
  const target = document.getElementById("module-detail");
  if (!target) return;
  target.dataset.domain = item.domain;
  target.setAttribute("aria-labelledby", `module-tab-${key}`);
  target.innerHTML = `
    <div class="module-meta">
      <span class="module-domain">${moduleDomains[item.domain]}</span>
      <span class="module-state">当前已实现</span>
    </div>
    <h3>${item.title}</h3>
    <p class="module-summary">${item.summary}</p>
    <div class="module-value"><span>USER VALUE</span><p>${item.value}</p></div>
    <div class="module-outputs">${item.outputs.map((value) => `<span>${value}</span>`).join("")}</div>
    <div class="module-boundary"><strong>边界：</strong>${item.boundary}</div>
  `;
}

function renderContract(key) {
  const item = executionContracts[key] || executionContracts.generation;
  const target = document.getElementById("contract-detail");
  if (!target) return;
  target.setAttribute("aria-labelledby", `contract-tab-${key}`);
  target.innerHTML = `
    <div class="contract-primary">
      <span>${item.kicker}</span>
      <h3>${item.title}</h3>
      <p>${item.summary}</p>
      <div class="contract-input"><strong>本次输入</strong><small>${item.input}</small></div>
    </div>
    <ol class="contract-rules">
      ${item.rules.map((rule, index) => `<li><b>${String(index + 1).padStart(2, "0")}</b><span>${rule}</span></li>`).join("")}
    </ol>
  `;
}

function activateTab(button, selector, renderer, keyName) {
  document.querySelectorAll(selector).forEach((item) => {
    const active = item === button;
    item.classList.toggle("active", active);
    item.setAttribute("aria-selected", String(active));
  });
  renderer(button.dataset[keyName]);
}

document.querySelectorAll("[data-module]").forEach((button) => {
  button.addEventListener("click", () => activateTab(button, "[data-module]", renderModule, "module"));
});

document.querySelectorAll("[data-contract]").forEach((button) => {
  button.addEventListener("click", () => activateTab(button, "[data-contract]", renderContract, "contract"));
});

const navLinks = [...document.querySelectorAll(".prd-nav a")];
const sections = navLinks
  .map((link) => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((entry) => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    navLinks.forEach((link) => {
      const active = link.getAttribute("href") === `#${visible.target.id}`;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    });
  }, { rootMargin: "-20% 0px -65%", threshold: [0.05, 0.2, 0.5] });
  sections.forEach((section) => observer.observe(section));
}

renderModule("workspace");
renderContract("generation");
