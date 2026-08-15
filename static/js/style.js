"use strict";

function parseSkillSections(markdown) {
  const sections = [];
  let current = { title: "总览", lines: [] };
  String(markdown || "").split(/\r?\n/).forEach((line) => {
    const match = line.match(/^##\s+(.+)$/);
    if (match) {
      if (current.lines.some((item) => item.trim())) sections.push({ title: current.title, body: current.lines.join("\n").trim() });
      current = { title: match[1].trim(), lines: [] };
      return;
    }
    if (!line.match(/^#\s+/)) current.lines.push(line);
  });
  if (current.lines.some((item) => item.trim())) sections.push({ title: current.title, body: current.lines.join("\n").trim() });
  return sections;
}

function renderSkillRuleText(value) {
  const text = String(value || "").trim();
  if (!text) return `<p class="style-empty-copy">本版本没有这一节规则。</p>`;
  return text.split(/\n{2,}/).map((block) => `<p>${escapeHtml(block).replace(/\n/g, "<br>")}</p>`).join("");
}

function renderAuditCopy(value) {
  return paragraphBlocks(value).map((block) => `<p>${escapeHtml(block)}</p>`).join("");
}

function renderStyleAuditIssues(audit) {
  const issues = Array.isArray(audit?.unsupported_claims) ? audit.unsupported_claims : null;
  if (!issues) return `<aside class="style-output-issues unknown">该次旧对照没有保存逐条事实审校。</aside>`;
  if (!issues.length) return `<aside class="style-output-issues passed">未发现素材外具体事实。</aside>`;
  return `<aside class="style-output-issues failed"><strong>${issues.length} 条无依据细节</strong>${issues.slice(0, 8).map((item) => `<span>${escapeHtml(typeof item === "string" ? item : (item.claim || item.issue || JSON.stringify(item)))}</span>`).join("")}</aside>`;
}

function ratioLabel(value) {
  const number = Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "未评估";
}

const STYLE_AUDIT_GROUPS = [
  { title: "版本总览", current: ["总览", "版本目标", "规则优先级"], candidate: ["总览", "版本目标", "规则优先级"] },
  { title: "创作者定位", current: ["创作者定位"], candidate: ["创作者定位"] },
  { title: "输入与事实", current: ["输入协议", "输入理解", "事实边界", "素材表达边界"], candidate: ["输入协议", "输入理解", "事实边界", "素材表达边界"] },
  { title: "风格 DNA", current: ["写作方法核心", "稳定风格 DNA", "核心创作 DNA"], candidate: ["写作方法核心", "稳定风格 DNA", "核心创作 DNA"] },
  { title: "叙事结构", current: ["段落推进模板", "叙事引擎", "叙事策略", "情绪曲线模板"], candidate: ["段落推进模板", "叙事引擎", "叙事策略", "情绪曲线模板"] },
  { title: "语言节奏", current: ["语言节奏"], candidate: ["语言节奏"] },
  { title: "开头与结尾", current: ["开头类型库", "开头与结尾", "开头、主体与结尾调度"], candidate: ["开头类型库", "开头与结尾", "开头、主体与结尾调度"] },
  { title: "任务模式", current: ["任务模式"], candidate: ["任务模式"] },
  { title: "书库与限制", current: ["书库使用原则", "书库原则", "可选增强", "禁止事项", "反 AI 味检查清单", "生成前后检查"], candidate: ["书库使用原则", "书库原则", "可选增强", "禁止事项", "反 AI 味检查清单", "生成前后检查"] },
  { title: "输出形态", current: ["输出形态", "输出契约"], candidate: ["输出形态", "输出契约"] }
];

function groupedSkillText(sectionMap, sectionNames) {
  return [...sectionMap.entries()]
    .filter(([title]) => sectionNames.some((name) => title === name || title.startsWith(`${name}（`)))
    .map(([title, body]) => `【${title}】\n${body}`)
    .join("\n\n");
}

function hasCompleteStyleABCopies(candidate) {
  const evaluation = candidate?.evaluation || {};
  const comparison = evaluation.ab_test || {};
  return Boolean(
    evaluation.ab_test_completed
    && String(comparison.current_copy || "").trim()
    && String(comparison.candidate_copy || "").trim()
  );
}

function hasReviewableStyleAB(candidate) {
  const comparison = candidate?.evaluation?.ab_test || {};
  return hasCompleteStyleABCopies(candidate) && comparison.passed === true;
}

function canOverrideStylePublish(candidate) {
  return Boolean(
    candidate?.evaluation?.ab_test_required
    && hasCompleteStyleABCopies(candidate)
    && !hasReviewableStyleAB(candidate)
  );
}

function renderStyleMechanisms() {
  const current = styleAuditData?.current;
  const candidate = styleAuditData?.candidate;
  const skillCount = skillStatus?.catalog?.skills?.length || 0;
  $("#style-mechanism-strip").innerHTML = `
    <div><strong>创作版本</strong><span>${escapeHtml(current?.version || "未发布")}${candidate ? ` → ${escapeHtml(candidate.version)} 候选` : ""}</span></div>
    <div><strong>产品运行能力</strong><span>${skillCount} 个功能 Skill，不是风格规则数量</span></div>
    <div><strong>历史文稿用法</strong><span>只蒸馏写作规律，不检索原段落拼接</span></div>
    <div><strong>失败策略</strong><span>模型或审校失败就停止，不用模板文案覆盖正文</span></div>
  `;
}

function renderStyleRules() {
  const currentSections = parseSkillSections(styleAuditData?.current?.skill_content);
  const candidateSections = parseSkillSections(styleAuditData?.candidate?.skill_content);
  const currentMap = new Map(currentSections.map((item) => [item.title, item.body]));
  const candidateMap = new Map(candidateSections.map((item) => [item.title, item.body]));
  const groups = STYLE_AUDIT_GROUPS.map((group) => ({
    ...group,
    currentText: groupedSkillText(currentMap, group.current),
    candidateText: groupedSkillText(candidateMap, group.candidate)
  })).filter((group) => group.currentText || group.candidateText);
  if (!groups.some((group) => group.title === styleAuditSection)) {
    styleAuditSection = groups[0]?.title || "版本总览";
  }
  const activeGroup = groups.find((group) => group.title === styleAuditSection) || groups[0] || {};
  const currentText = activeGroup.currentText || "";
  const candidateText = activeGroup.candidateText || "";
  $("#style-audit-body").innerHTML = `
    <div class="style-rule-layout">
      <nav class="style-section-nav" aria-label="风格规则章节">
        ${groups.map((group) => {
          const changed = group.currentText !== group.candidateText;
          const changeLabel = !group.currentText ? "新增" : (!group.candidateText ? "移除" : (changed ? "有变化" : "一致"));
          return `<button class="${group.title === styleAuditSection ? "active" : ""} ${changed ? "changed" : ""}" data-style-section="${escapeHtml(group.title)}" type="button"><span>${escapeHtml(group.title)}</span><i>${changeLabel}</i></button>`;
        }).join("")}
      </nav>
      <div class="style-rule-compare">
        <section>
          <header><strong>${escapeHtml(styleAuditData?.current?.version || "当前版本")}</strong><span>已发布</span></header>
          <div class="style-rule-copy">${renderSkillRuleText(currentText)}</div>
        </section>
        <section>
          <header><strong>${escapeHtml(styleAuditData?.candidate?.version || "无候选版本")}</strong><span>${styleAuditData?.candidate ? "候选" : "未生成"}</span></header>
          <div class="style-rule-copy">${renderSkillRuleText(candidateText)}</div>
        </section>
      </div>
    </div>
  `;
  $$("[data-style-section]").forEach((button) => {
    button.addEventListener("click", () => {
      styleAuditSection = button.dataset.styleSection;
      renderStyleRules();
    });
  });
}

function renderStyleOutputs() {
  const evaluation = styleAuditData?.candidate?.evaluation || {};
  const ab = evaluation.ab_test || {};
  const currentCopy = ab.current_copy || "";
  const candidateCopy = ab.candidate_copy || "";
  if (!currentCopy || !candidateCopy) {
    $("#style-audit-body").innerHTML = `
      <div class="style-audit-empty">
        <strong>还没有可回看的 A/B 成稿</strong>
        <p>旧版对照只保存了指标，没有保存两篇正文。点击下方“重新生成 A/B”后，两版正文会持久保留在这里。</p>
      </div>
    `;
    return;
  }
  const currentMetrics = ab.current_expression_metrics || {};
  const candidateMetrics = ab.candidate_expression_metrics || {};
  const currentIssues = Array.isArray(ab.current_audit?.unsupported_claims) ? ab.current_audit.unsupported_claims.length : null;
  const candidateIssues = Array.isArray(ab.candidate_audit?.unsupported_claims) ? ab.candidate_audit.unsupported_claims.length : null;
  const comparisonPassed = ab.passed === true;
  $("#style-audit-body").innerHTML = `
    <div class="style-output-gate ${comparisonPassed ? "passed" : "failed"}">
      <strong>${comparisonPassed ? "事实门禁通过" : "事实门禁未通过，禁止发布"}</strong>
      <span>${comparisonPassed ? "现在只需要判断哪一版更像你。" : "正文仍可对照查看；请先检查两版上方的无依据细节。"}</span>
    </div>
    <div class="style-output-summary">
      <span>审核重点：是否真正展开素材、是否像你、是否新增事实、是否自然收束</span>
      <span>${escapeHtml(ab.current_version || styleAuditData.current?.version)}：非素材原句 ${ratioLabel(currentMetrics.new_expression_ratio)} · ${ab.current_passed === true ? "审校通过" : `${currentIssues ?? "?"} 条无依据细节`}</span>
      <span>${escapeHtml(ab.candidate_version || styleAuditData.candidate?.version)}：非素材原句 ${ratioLabel(candidateMetrics.new_expression_ratio)} · ${ab.candidate_passed === true ? "审校通过" : `${candidateIssues ?? "?"} 条无依据细节`}</span>
    </div>
    <div class="style-output-compare ${comparisonPassed ? "" : "invalid"}">
      <section>
        <header><strong>${escapeHtml(ab.current_version || "当前版本")}</strong><span>${String(currentCopy).replace(/\s/g, "").length} 字</span></header>
        <div>${renderStyleAuditIssues(ab.current_audit)}${renderAuditCopy(currentCopy)}</div>
      </section>
      <section>
        <header><strong>${escapeHtml(ab.candidate_version || "候选版本")}</strong><span>${String(candidateCopy).replace(/\s/g, "").length} 字</span></header>
        <div>${renderStyleAuditIssues(ab.candidate_audit)}${renderAuditCopy(candidateCopy)}</div>
      </section>
    </div>
  `;
}

function renderStyleEvidence() {
  const candidate = styleAuditData?.candidate;
  const evaluation = candidate?.evaluation || {};
  const documents = candidate?.evidence?.documents || [];
  const conflicts = Array.isArray(evaluation.conflicts) ? evaluation.conflicts : [];
  const improvements = Array.isArray(evaluation.improvements) ? evaluation.improvements : [];
  const abComplete = hasCompleteStyleABCopies(candidate);
  const abReady = hasReviewableStyleAB(candidate);
  const recommendation = !abComplete
    ? "暂不发布：先重新生成并保存两版完整 A/B 成稿。"
    : (!abReady ? "暂不发布：A/B 已生成，但至少一版存在素材外事实或原句复用问题。" :
      (conflicts.length ? `建议暂不发布：仍有 ${conflicts.length} 项规则冲突需要你判断。` : "已具备发布条件，仍以你对 A/B 成稿的主观判断为准。"));
  $("#style-audit-body").innerHTML = `
    <div class="style-evidence-layout">
      <section class="style-evidence-summary">
        <div class="style-review-verdict ${abReady && !conflicts.length ? "ready" : "hold"}">${escapeHtml(recommendation)}</div>
        <h3>蒸馏结论</h3>
        <p>${escapeHtml(evaluation.summary || "当前版本尚未生成候选评估。")}</p>
        <div class="style-score-list">
          <div><span>证据覆盖</span><strong>${ratioLabel(evaluation.evidence_coverage)}</strong></div>
          <div><span>事实边界</span><strong>${ratioLabel(evaluation.fact_boundary)}</strong></div>
          <div><span>过拟合风险（越低越好）</span><strong>${ratioLabel(evaluation.overfit_risk)}</strong></div>
        </div>
        <h3>语料口径</h3>
        <div class="style-document-list">
          ${documents.map((doc) => `<div><span>${escapeHtml(doc.filename || "历史文稿")}</span><b>${escapeHtml(doc.maturity || "final_script")} · ${Number(doc.weight ?? 1).toFixed(1)}</b></div>`).join("") || "<p>暂无候选语料记录。</p>"}
        </div>
      </section>
      <section class="style-risk-list">
        <h3>发布前需要判断</h3>
        ${conflicts.map((item) => `<article><b>冲突</b><p>${escapeHtml(item)}</p></article>`).join("") || "<p>未发现明确规则冲突。</p>"}
        ${improvements.slice(0, 6).map((item) => `<article><b>建议</b><p>${escapeHtml(item)}</p></article>`).join("")}
      </section>
    </div>
  `;
}

function renderStyleAudit() {
  if (!styleAuditData) return;
  renderStyleMechanisms();
  $$("[data-style-audit-tab]").forEach((button) => {
    const isActive = button.dataset.styleAuditTab === styleAuditTab;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-selected", String(isActive));
    button.tabIndex = isActive ? 0 : -1;
  });
  if (styleAuditTab === "outputs") renderStyleOutputs();
  else if (styleAuditTab === "evidence") renderStyleEvidence();
  else renderStyleRules();
  const candidate = styleAuditData.candidate;
  const abComplete = hasCompleteStyleABCopies(candidate);
  const abCompleted = hasReviewableStyleAB(candidate);
  const canOverride = canOverrideStylePublish(candidate);
  $("#rerun-style-ab").classList.toggle("hidden", !candidate);
  $("#publish-style-audit").classList.toggle("hidden", !candidate);
  $("#publish-style-audit").disabled = Boolean(candidate && !abCompleted && !canOverride);
  $("#publish-style-audit").textContent = !candidate
    ? "发布候选 Skill"
    : (canOverride ? `确认风险并发布 ${candidate.version}` : `发布 ${candidate.version}`);
  $("#style-audit-decision").textContent = !candidate
    ? "当前没有待审核候选版本。"
    : (abCompleted
      ? "A/B 已通过事实门禁。请按 1 → 2 → 3 完成审核后再决定是否发布。"
      : (abComplete ? "A/B 已生成但自动门禁未通过；确认效果满意后，可保留风险记录并由创作者发布。" : "缺少两版完整 A/B 正文，候选版本暂不可发布。"));
}

async function openStyleAudit(tab = "rules") {
  styleAuditTab = tab;
  const audit = $("#style-audit");
  audit.classList.remove("hidden");
  audit.setAttribute("aria-hidden", "false");
  overlayManager.open({
    id: 'style-audit',
    element: audit,
    lockMode: 'modal',
    onRequestClose: closeStyleAudit
  });
  window.requestAnimationFrame(() => $("#close-style-audit").focus({ preventScroll: true }));
  $("#style-audit-body").innerHTML = `<div class="style-audit-empty"><strong>正在加载版本规则</strong></div>`;
  try {
    if (!skillStatus) await loadSkillStatus();
    const versions = skillStatus?.style?.versions || [];
    const currentMeta = versions.find((item) => item.status === "published");
    const candidateMeta = versions.find((item) => item.status === "candidate");
    if (!currentMeta) throw new Error("没有可审核的已发布风格版本");
    const [currentResponse, candidateResponse] = await Promise.all([
      XZJApi.request(`/api/xiangzhongjing/style-versions/${currentMeta.id}`),
      candidateMeta ? XZJApi.request(`/api/xiangzhongjing/style-versions/${candidateMeta.id}`) : Promise.resolve(null)
    ]);
    if (!currentResponse.ok || (candidateResponse && !candidateResponse.ok)) throw new Error("风格版本加载失败");
    styleAuditData = {
      current: await currentResponse.json(),
      candidate: candidateResponse ? await candidateResponse.json() : null
    };
    styleAuditSection = "";
    renderStyleAudit();
  } catch (error) {
    $("#style-audit-body").innerHTML = `<div class="style-audit-empty"><strong>${escapeHtml(error.message)}</strong></div>`;
  }
}

function closeStyleAudit() {
  overlayManager.close('style-audit');
  $("#style-audit").classList.add("hidden");
  $("#style-audit").setAttribute("aria-hidden", "true");
}

async function runStyleAuditComparison() {
  const candidateId = styleAuditData?.candidate?.id || pendingStyleCandidate?.id;
  if (!candidateId) return;
  const button = $("#rerun-style-ab");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "A/B 生成中";
  try {
    const response = await XZJApi.request(`/api/xiangzhongjing/style-versions/${candidateId}/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ materials: projectMaterialsSnapshot() })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "A/B 对照失败"));
    await loadSkillStatus();
    const detailResponse = await XZJApi.request(`/api/xiangzhongjing/style-versions/${candidateId}`);
    if (!detailResponse.ok) throw new Error("A/B 结果读取失败");
    styleAuditData.candidate = await detailResponse.json();
    styleAuditTab = "outputs";
    renderStyleAudit();
    showToast(data.passed ? "两版 A/B 已通过事实门禁，可以开始风格审核" : "A/B 已保存，但事实门禁未通过，候选版本不可发布");
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function renderStyleReview(result) {
  const panel = $("#style-review");
  if (!panel || !result) return;
  const documents = result.documents || [];
  const evaluation = result.evaluation || {};
  const candidate = result.candidate || pendingStyleCandidate;
  const abComplete = hasCompleteStyleABCopies({ ...candidate, evaluation });
  const abReady = hasReviewableStyleAB({ ...candidate, evaluation });
  pendingStyleCandidate = candidate || pendingStyleCandidate;
  panel.innerHTML = `
    <div class="style-review-head">
      <div><strong>${escapeHtml(candidate?.version || "候选 Skill")}</strong><span>${abReady ? "A/B 已通过事实门禁，等待你决定是否发布" : (abComplete ? "A/B 已生成，但事实门禁未通过" : "待审核：需要重新生成并保存完整 A/B")}</span></div>
      <div class="style-review-buttons">
        <button class="outline-button compact strong" data-open-style-audit type="button">审核规则与效果</button>
        <button class="outline-button compact" data-compare-style="${escapeHtml(candidate?.id || "")}" type="button">重新生成 A/B</button>
      </div>
    </div>
    <div class="style-review-summary">${escapeHtml(evaluation.summary || "已完成分级蒸馏，下一步比较两版真实产出。")}</div>
    <div class="style-review-docs">${documents.map((doc) => `<span><b>${escapeHtml(doc.maturity || "未分级")}</b>${escapeHtml(doc.filename || "")}</span>`).join("")}</div>
    ${result.evidence?.excluded_placeholders?.length ? `<p class="style-review-excluded">已排除：${escapeHtml(result.evidence.excluded_placeholders.join("、"))}</p>` : ""}
  `;
  panel.classList.remove("hidden");
  panel.querySelector("[data-open-style-audit]")?.addEventListener("click", () => openStyleAudit("rules"));
  panel.querySelector("[data-compare-style]")?.addEventListener("click", () => compareStyleCandidate(Number(candidate?.id)));
}

async function compareStyleCandidate(candidateId) {
  if (!candidateId) return;
  const button = $("[data-compare-style]");
  if (button) {
    button.disabled = true;
    button.textContent = "对照生成中";
  }
  try {
    const response = await XZJApi.request(`/api/xiangzhongjing/style-versions/${candidateId}/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ materials: projectMaterialsSnapshot() })
    });
    const data = await response.json();
    if (!response.ok) throw new Error(apiError(data, "A/B 对照失败"));
    await loadSkillStatus();
    await openStyleAudit("outputs");
    showToast(data.passed ? "A/B 已通过事实门禁，可以开始风格审核" : "A/B 已保存，但事实门禁未通过，候选版本不可发布");
  } catch (error) {
    showToast(error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "重新生成 A/B";
    }
  }
}
