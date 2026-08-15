"use strict";

const settingsSkillCopy = {
  "adapt-douyin-vlog": "为完成稿生成标题、封面钩子、评论问题和口播提示，不改写正文。",
  "architect-vlog-narrative": "把项目素材拆成事实账本和六段叙事骨架，防止初稿按素材顺序照抄。",
  "audit-vlog-copy": "编辑或局部改写后的事实与风格审校，阻止无依据细节覆盖正文。",
  "audit-writing-quality": "完整文案的最终质量门，检查个人风格、叙事展开、事实边界与平台适配。",
  "book-person-dialogue": "书中人开放对话 Skill，基于书库人物和全局书库证据进行思考交流。",
  "compose-vlog-copy": "旧版编排 Skill，当前主链路已拆分为更清晰的三段式生成，保留用于兼容。",
  "distill-blogger-dna": "把其他博主样本蒸馏成可选语言风味试剂，不复制身份、事实或原句。",
  "distill-personal-style": "把创作者历史文案蒸馏为候选个人创作 DNA，审核发布后才进入生成链路。",
  "draft-personal-vlog": "旧版初稿 Skill，当前由「个人声音写作」承担主写作任务，保留用于兼容。",
  "edit-vlog-copy": "基于当前文案执行全文或选区改写，保留事实边界并输出可审计修改点。",
  "insert-book-quotes": "从本地精神书库候选里选择并植入 1-3 条直接引文，不联网、不自拟金句。",
  "inspect-content-style": "内容检查员，用于诊断生成稿与个人风格之间的差异并给出优化方向。",
  "mirror-self-dialogue": "镜中人开放对话 Skill，让对话更像与另一个自己交流。",
  "optimize-douyin-vlog": "在不替换个人声音的前提下优化抖音口播节奏、开头进入和观看留存。",
  "parse-creation-materials": "把粘贴的散乱素材识别成开场、洞察、日常、事件、金句等结构化素材。",
  "plan-vlog-narrative": "旧版叙事规划 Skill，当前由「叙事架构」承担主规划任务，保留用于兼容。",
  "research-book-quotes": "从本地精神书库中匹配候选直接引文，作为书库金句植入前置步骤。",
  "rewrite-material-expression": "旧版素材去重表达 Skill，当前主生成链路已内置反照抄规则，保留用于兼容。",
  "style-audit": "旧版风格审校 Skill，当前主要由内容检查员和质量门承担，保留用于兼容。",
  "summarize-dialogue-memory": "把镜中人和书中人对话压缩成长期记忆与可沉淀资产。",
  "verify-book-quotes": "旧版联网逐字核验 Skill，当前书库策略已转向本地候选直引，保留用于兼容。",
  "write-personal-vlog": "当前核心写作 Skill，调用已发布个人 DNA，把素材发展成个人化完整文案。"
};

const settingsCompatibilitySkills = new Set([
  "compose-vlog-copy",
  "draft-personal-vlog",
  "plan-vlog-narrative",
  "rewrite-material-expression",
  "style-audit",
  "verify-book-quotes"
]);

const settingsMainChainSkills = new Set([
  "architect-vlog-narrative",
  "write-personal-vlog",
  "optimize-douyin-vlog",
  "insert-book-quotes",
  "edit-vlog-copy",
  "parse-creation-materials",
  "distill-personal-style",
  "mirror-self-dialogue",
  "book-person-dialogue",
  "summarize-dialogue-memory"
]);

function renderSettingsConfig(values = {}) {
  const form = $("#settings-config-form");
  if (!form) return;
  Object.entries(values).forEach(([key, value]) => {
    const input = form.elements[key];
    if (input) input.value = value || "";
  });
  $("#settings-config-state").textContent = "本地配置";
}

function renderPersonalDnaStatus(style = {}) {
  const target = $("#settings-dna-status");
  if (!target) return;
  const version = style.published_version || "未发布";
  const docs = Number(style.reference_documents || 0);
  const chars = Number(style.chars || 0);
  const candidates = Number(style.candidate_versions || 0);
  target.innerHTML = `
    <div>
      <span class="settings-dna-kicker">PERSONAL DNA</span>
      <strong>当前个人创作 DNA：${escapeHtml(version)}</strong>
      <p>基于 ${docs} 篇历史文案沉淀，约 ${chars} 字规则。生成文案时系统 Skill 会调用这一版个人 DNA；下方列表只是产品工具链。</p>
    </div>
    <span>${candidates ? `${candidates} 个候选待审核` : "已发布"}</span>
  `;
}

function settingsSkillStatus(skill, enabled, core) {
  if (settingsCompatibilitySkills.has(skill.name)) return "兼容保留";
  if (!enabled) return "当前未启用";
  if (settingsMainChainSkills.has(skill.name)) return "当前链路";
  if (skill.name === "distill-blogger-dna") return "可选试剂";
  return core ? "系统核心" : "自定义";
}

function renderSettingsSkills(skills = []) {
  const target = $("#settings-skill-list");
  if (!target) return;
  $("#settings-skill-count").textContent = `${skills.length} 个`;
  if (!skills.length) {
    target.innerHTML = `<div class="settings-empty">暂无 Skill 注册信息。重启服务后会自动同步内置 Skills。</div>`;
    return;
  }
  target.innerHTML = skills.map((skill) => {
    const core = Number(skill.core || 0) === 1;
    const enabled = Number(skill.enabled || 0) === 1;
    const status = settingsSkillStatus(skill, enabled, core);
    const description = settingsSkillCopy[skill.name] || skill.description || skill.name;
    const lockReason = core && enabled ? "核心 Skill 不能在设置页停用，避免生成链路被误关。" : "";
    return `
      <article class="settings-skill-item ${settingsCompatibilitySkills.has(skill.name) ? "compat" : ""}">
        <div>
          <div class="settings-skill-meta">
            <span class="settings-skill-phase">${escapeHtml(skill.phase || "其它")}</span>
            <span class="settings-skill-status">${escapeHtml(status)}</span>
          </div>
          <strong>${escapeHtml(skill.display_name || skill.name)}</strong>
          <p>${escapeHtml(description)}</p>
          <small>系统标识：${escapeHtml(skill.name)}${lockReason ? ` · ${escapeHtml(lockReason)}` : ""}</small>
        </div>
        <div class="settings-skill-actions">
          <span>${core ? "内置核心" : escapeHtml(skill.source || "custom")}</span>
          <button class="outline-button compact" data-settings-skill-toggle="${escapeHtml(skill.name)}" data-enabled="${enabled ? "1" : "0"}" ${core && enabled ? "disabled" : ""} type="button">${enabled ? "已启用" : "已停用"}</button>
          <button class="outline-button compact" data-settings-skill-detail="${escapeHtml(skill.name)}" type="button">查看</button>
        </div>
      </article>
    `;
  }).join("");
}

async function loadSettingsPage() {
  try {
    const [config, skills, style] = await Promise.all([
      XZJApi.json("/api/xiangzhongjing/settings/config"),
      XZJApi.json("/api/xiangzhongjing/skills-admin/list"),
      XZJApi.json("/api/xiangzhongjing/writing-skill")
    ]);
    settingsState = { config, skills, style };
    renderSettingsConfig(config.values || {});
    renderPersonalDnaStatus(style || {});
    renderSettingsSkills(skills.skills || []);
  } catch (error) {
    console.warn("Failed to load settings", error);
    $("#settings-config-state").textContent = "读取失败";
  }
}

async function saveSettingsConfig(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {};
  [...form.elements].forEach((field) => {
    if (!field.name) return;
    payload[field.name] = field.value;
  });
  try {
    await XZJApi.json("/api/xiangzhongjing/settings/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    showToast("配置已保存");
    await loadSettingsPage();
    await loadSkillStatus();
    await loadOnboardingStatus();
  } catch (error) {
    showToast(error.message || "配置保存失败");
  }
}

async function testSettingsProvider(provider) {
  try {
    const data = await XZJApi.json("/api/xiangzhongjing/settings/config/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider })
    });
    showToast(data.message || "检查完成");
    await loadOnboardingStatus();
  } catch (error) {
    showToast(error.message || "检查失败");
  }
}

async function toggleSettingsSkill(name, enabled) {
  try {
    await XZJApi.json(`/api/xiangzhongjing/skills/${encodeURIComponent(name)}/enabled`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled })
    });
    await loadSettingsPage();
    await loadSkillStatus();
  } catch (error) {
    showToast(error.message || "Skill 状态修改失败");
  }
}

document.addEventListener("click", async (event) => {
  const toggle = event.target.closest("[data-settings-skill-toggle]");
  if (toggle) {
    toggleSettingsSkill(toggle.dataset.settingsSkillToggle, toggle.dataset.enabled === "1");
    return;
  }
  const detail = event.target.closest("[data-settings-skill-detail]");
  if (detail) {
    try {
      const item = await XZJApi.json(`/api/xiangzhongjing/skills/${encodeURIComponent(detail.dataset.settingsSkillDetail)}`);
      alert(`${item.display_name || item.name}\n\n${item.instructions || item.description || ""}`);
    } catch (error) {
      showToast(error.message || "读取 Skill 失败");
    }
  }
});

$("#settings-config-form")?.addEventListener("submit", saveSettingsConfig);
$("#settings-test-deepseek")?.addEventListener("click", () => testSettingsProvider("deepseek"));
$("#settings-test-tavily")?.addEventListener("click", () => testSettingsProvider("tavily"));
$("#settings-test-image")?.addEventListener("click", () => testSettingsProvider("image"));
