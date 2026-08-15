"use strict";

let coverProfileState = null;
let coverPresetsState = [];
let coverImagesState = [];
let activeCoverTab = "assets";
let activeCoverDraftId = "";
let coverDraftSaveTimer = null;
let coverPresetTrigger = null;

function coverProjects() {
  return Object.entries(projects).map(([key, project]) => ({
    ...project,
    id: project.id || key
  }));
}

function coverProject(projectId = "") {
  return projects[projectId]
    || coverProjects().find((project) => project.id === projectId)
    || null;
}

function coverProjectOptions(selectedId = "") {
  return coverProjects().map((project) => `
    <option value="${escapeHtml(project.id)}" ${project.id === selectedId ? "selected" : ""}>
      ${escapeHtml(project.title || "未命名项目")}
    </option>
  `).join("");
}

function coverPresetOptions(selectedId = "") {
  return coverPresetsState.map((preset) => `
    <option value="${escapeHtml(preset.id)}" ${preset.id === selectedId ? "selected" : ""}>
      ${escapeHtml(preset.name)}
    </option>
  `).join("");
}

function coverStatusLabel(status) {
  return {
    blank: "待生成",
    generating: "生成中",
    completed: "已完成",
    failed: "失败"
  }[status] || "待生成";
}

function selectedPresetPrompt(presetId) {
  return coverPresetsState.find((preset) => preset.id === presetId)?.prompt || "";
}

function profileTokens(value, fallback = []) {
  const tokens = String(value || "")
    .split(/[，,、/｜|\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  return (tokens.length ? tokens : fallback).slice(0, 6);
}

function formatProfileCount(value) {
  return new Intl.NumberFormat("zh-CN", {
    notation: Number(value) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: 1
  }).format(Number(value) || 0);
}

function renderProfileReadiness(profile = {}) {
  const publicFields = ["display_name", "handle", "bio", "location", "platforms"];
  const creatorFields = ["creator_positioning", "content_columns", "style_keywords", "visual_preferences"];
  const publicCount = publicFields.filter((key) => String(profile[key] || "").trim()).length;
  const creatorCount = creatorFields.filter((key) => String(profile[key] || "").trim()).length;
  const avatarReady = Boolean(profile.avatar_url || profile.avatar_path);
  const completed = publicCount + creatorCount + (avatarReady ? 1 : 0);
  const percentage = Math.round((completed / 10) * 100);
  if ($("#profile-completeness")) {
    $("#profile-completeness").value = percentage;
    $("#profile-completeness").textContent = `${percentage}%`;
  }
  if ($("#profile-completeness-value")) $("#profile-completeness-value").textContent = `${percentage}%`;
  if ($("#profile-public-status")) {
    $("#profile-public-status").textContent = publicCount === publicFields.length ? "已完善" : `${publicCount}/${publicFields.length}`;
  }
  if ($("#profile-creator-status")) {
    $("#profile-creator-status").textContent = creatorCount === creatorFields.length ? "已完善" : `${creatorCount}/${creatorFields.length}`;
  }
  if ($("#profile-avatar-status")) $("#profile-avatar-status").textContent = avatarReady ? "已上传" : "未上传";
}

function renderProfileStats() {
  const diaryCount = Array.isArray(diaryEntries) ? diaryEntries.length : 0;
  const coverCount = Array.isArray(coverImagesState)
    ? coverImagesState.filter((cover) => cover.status === "completed" && cover.image_url).length
    : 0;
  const bookCount = Array.isArray(bookNotesState?.summary)
    ? bookNotesState.summary.reduce((sum, item) => sum + Number(item.count || 0), 0)
    : 0;
  if ($("#profile-stat-diary")) $("#profile-stat-diary").textContent = formatProfileCount(diaryCount);
  if ($("#profile-stat-covers")) $("#profile-stat-covers").textContent = formatProfileCount(coverCount);
  if ($("#profile-stat-books")) $("#profile-stat-books").textContent = formatProfileCount(bookCount);
}

function renderCoverProfile() {
  const profile = coverProfileState || {};
  const displayName = profile.display_name || "创作者";
  const bio = profile.bio || "个人创作者";
  const handle = String(profile.handle || "creator").trim() || "creator";
  const normalizedHandle = handle.replace(/^@+/, "");
  const sidebarAvatar = $("#sidebar-profile-avatar");
  if (sidebarAvatar) {
    sidebarAvatar.innerHTML = profile.avatar_url
      ? `<img src="${escapeHtml(profile.avatar_url)}" alt="用户头像" width="36" height="36">`
      : "Z";
  }
  if ($("#sidebar-profile-name")) $("#sidebar-profile-name").textContent = displayName;
  if ($("#sidebar-profile-bio")) $("#sidebar-profile-bio").textContent = bio;
  const homeAvatar = $("#profile-home-avatar");
  if (homeAvatar) {
    homeAvatar.innerHTML = profile.avatar_url
      ? `<img src="${escapeHtml(profile.avatar_url)}" alt="用户标准正面形象图" width="88" height="88" fetchpriority="high">`
      : "<span>Z</span>";
  }
  if ($("#profile-home-name")) $("#profile-home-name").textContent = displayName;
  if ($("#profile-home-handle")) $("#profile-home-handle").textContent = `@${normalizedHandle}`;
  if ($("#profile-home-bio")) $("#profile-home-bio").textContent = profile.creator_positioning || bio;
  if ($("#profile-home-location")) $("#profile-home-location").textContent = profile.location || "未填写所在地";
  if ($("#profile-home-platforms")) $("#profile-home-platforms").textContent = profile.platforms || "抖音 · 小红书 · B站";
  const tagTarget = $("#profile-home-tags");
  if (tagTarget) {
    const tags = [
      ...profileTokens(profile.style_keywords, ["个人表达", "真实经历", "持续创作"]),
      ...profileTokens(profile.content_columns, [])
    ];
    tagTarget.innerHTML = tags.slice(0, 6).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("");
  }
  renderProfileStats();
  renderProfileReadiness(profile);
  const form = $("#cover-profile-form");
  if (form) {
    form.elements.display_name.value = profile.display_name || "创作者";
    form.elements.handle.value = profile.handle || "creator";
    form.elements.bio.value = profile.bio || "个人创作者";
    form.elements.location.value = profile.location || "";
    form.elements.creator_positioning.value = profile.creator_positioning || "";
    form.elements.platforms.value = profile.platforms || "";
    form.elements.content_columns.value = profile.content_columns || "";
    form.elements.style_keywords.value = profile.style_keywords || "";
    form.elements.visual_preferences.value = profile.visual_preferences || "";
    form.elements.cover_negative_prompt.value = profile.cover_negative_prompt || "";
  }
  if ($("#profile-save-status")) $("#profile-save-status").textContent = "资料已同步";
}

async function loadCreatorProfileSummary() {
  try {
    coverProfileState = await XZJApi.json("/api/xiangzhongjing/covers/profile");
    renderCoverProfile();
    await loadOnboardingStatus();
  } catch (error) {
    console.warn("Failed to load creator profile", error);
  }
}

async function loadCreatorProfilePage() {
  try {
    const [profile, images, notes] = await Promise.all([
      XZJApi.json("/api/xiangzhongjing/covers/profile"),
      XZJApi.json("/api/xiangzhongjing/covers/images"),
      XZJApi.json("/api/xiangzhongjing/book-notes")
    ]);
    coverProfileState = profile;
    coverImagesState = images.covers || [];
    bookNotesState = notes || bookNotesState;
    renderCoverProfile();
    await loadOnboardingStatus();
  } catch (error) {
    console.warn("Failed to load creator profile page", error);
    showToast(error.message || "个人信息页加载失败");
  }
}

function formatCoverDate(value) {
  if (!value) return "刚刚生成";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "已保存到本地";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric"
  }).format(date);
}

function setCoverTab(tab, { updateUrl = true } = {}) {
  activeCoverTab = tab === "studio" ? "studio" : "assets";
  $$('[data-cover-tab]').forEach((button) => {
    const selected = button.dataset.coverTab === activeCoverTab;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  $$('[data-cover-view]').forEach((view) => {
    view.classList.toggle("hidden", view.dataset.coverView !== activeCoverTab);
  });
  if (updateUrl) {
    const destination = new URL(window.location.href);
    destination.searchParams.set("page", "covers");
    destination.searchParams.set("coverTab", activeCoverTab);
    window.history.replaceState({}, "", `${destination.pathname}${destination.search}`);
  }
}

function renderCoverAssetCard(cover) {
  const project = coverProject(cover.project_id) || {};
  const projectId = cover.project_id || project.id || "";
  const title = cover.title || cover.project_title || project.title || "未命名封面";
  const projectTitle = cover.project_title || project.title || "未绑定项目";
  const projectHref = `?page=editor&amp;project=${encodeURIComponent(projectId)}&amp;tab=copy`;
  return `
    <article class="cover-asset-card" data-cover-id="${escapeHtml(cover.id)}">
      <div class="cover-photo">
        <img src="${escapeHtml(cover.image_url)}" alt="${escapeHtml(title)}" width="1024" height="1536" loading="lazy">
      </div>
      <div class="cover-asset-copy">
        <span>${escapeHtml(projectTitle)}</span>
        <h3>${escapeHtml(title)}</h3>
        <small>${escapeHtml(formatCoverDate(cover.generated_at))} · 本地保存</small>
      </div>
      <div class="cover-asset-actions">
        ${projectId ? `<a class="outline-button compact" data-cover-open-project="${escapeHtml(projectId)}" href="${projectHref}">进入项目</a>` : ""}
        <a class="top-action compact" href="${escapeHtml(cover.image_url)}" download="${escapeHtml(title)}.png">下载图片</a>
      </div>
    </article>
  `;
}

function renderCoverStudioCard(cover) {
  const project = coverProject(cover.project_id) || coverProject(activeProject) || coverProjects()[0] || {};
  const prompt = cover.prompt || selectedPresetPrompt(cover.preset_id);
  return `
    <article class="cover-studio-card" data-cover-id="${escapeHtml(cover.id)}" data-cover-status="${escapeHtml(cover.status)}">
      <div class="cover-studio-preview">
        <div class="cover-photo ${cover.status === "generating" ? "loading" : ""}">
          ${cover.image_url
            ? `<img src="${escapeHtml(cover.image_url)}" alt="${escapeHtml(cover.title || "封面图")}" width="1024" height="1536">`
            : `<span>封面预览</span>`}
        </div>
        <div class="cover-card-status">
          <span id="cover-draft-save-status">${cover.status === "generating" ? "正在生成…" : "草稿已自动保存"}</span>
          <b class="${cover.status === "failed" ? "failed" : ""}">${escapeHtml(coverStatusLabel(cover.status))}</b>
        </div>
      </div>
      <div class="cover-studio-controls">
        <div class="cover-card-controls">
          <label class="cover-card-field">
            <span>绑定项目</span>
            <select data-cover-field="project_id">${coverProjectOptions(cover.project_id || project.id)}</select>
          </label>
          <label class="cover-card-field">
            <span>封面标题</span>
            <input data-cover-field="title" maxlength="80" autocomplete="off" value="${escapeHtml(cover.title || project.title || "")}">
          </label>
          <label class="cover-card-field">
            <span>人物参考</span>
            <select data-cover-reference-mode>
              <option value="default">使用个人头像</option>
              <option value="custom" ${cover.reference_url ? "selected" : ""}>使用本张参考图</option>
            </select>
          </label>
          <div class="cover-reference-row">
            <label class="cover-upload-button">
              <span>${cover.reference_url ? "更换参考图" : "上传参考图"}</span>
              <input data-cover-reference-upload type="file" accept="image/png,image/jpeg,image/webp" aria-label="上传本张封面的参考图">
            </label>
            ${cover.reference_url ? `<a class="outline-button compact" href="${escapeHtml(cover.reference_url)}" target="_blank" rel="noreferrer">查看参考</a>` : ""}
          </div>
          <label class="cover-card-field">
            <span>封面风格</span>
            <select data-cover-field="preset_id">${coverPresetOptions(cover.preset_id || "ink-cover")}</select>
          </label>
          <label class="cover-card-field">
            <span>风格 Prompt</span>
            <textarea data-cover-field="prompt" rows="5">${escapeHtml(prompt)}</textarea>
          </label>
        </div>
        ${cover.error_message ? `<div class="cover-error">${escapeHtml(cover.error_message)}</div>` : ""}
        <div class="cover-card-actions">
          <button class="top-action primary" data-cover-generate type="button" ${cover.status === "generating" ? "disabled" : ""}>生成并存入资产</button>
        </div>
      </div>
    </article>
  `;
}

function renderCoverWall() {
  const target = $("#cover-wall");
  if (!target) return;
  const assets = coverImagesState.filter((cover) => cover.status === "completed" && cover.image_url);
  $("#cover-wall-count").textContent = `${assets.length} 张`;
  if (!assets.length) {
    target.innerHTML = `
      <div class="cover-empty">
        <strong>还没有封面资产</strong>
        <p>生成完成的封面会自动保存并出现在这里。</p>
        <button class="top-action primary" data-cover-new-draft type="button">生成第一张封面</button>
      </div>
    `;
    return;
  }
  target.innerHTML = assets.map(renderCoverAssetCard).join("");
}

function renderCoverStudio() {
  const target = $("#cover-studio-workbench");
  if (!target) return;
  const drafts = coverImagesState.filter((cover) => cover.status !== "completed");
  const draft = drafts.find((cover) => cover.id === activeCoverDraftId) || drafts[0];
  if (!draft) {
    target.innerHTML = `
      <div class="cover-empty cover-studio-empty">
        <strong>创作台暂时为空</strong>
        <p>新建一张封面，配置会自动保存为本地草稿。</p>
        <button class="top-action primary" data-cover-new-draft type="button">新建封面</button>
      </div>
    `;
    return;
  }
  activeCoverDraftId = draft.id;
  target.innerHTML = renderCoverStudioCard(draft);
}

function renderCoversPage() {
  renderCoverWall();
  renderCoverStudio();
  setCoverTab(activeCoverTab, { updateUrl: false });
}

async function loadCoversPage() {
  try {
    const requestedTab = new URLSearchParams(window.location.search).get("coverTab");
    activeCoverTab = requestedTab === "studio" ? "studio" : "assets";
    const [presets, images] = await Promise.all([
      XZJApi.json("/api/xiangzhongjing/covers/presets"),
      XZJApi.json("/api/xiangzhongjing/covers/images")
    ]);
    coverPresetsState = presets.presets || [];
    coverImagesState = images.covers || [];
    if (!coverProfileState) loadCreatorProfileSummary();
    renderCoversPage();
  } catch (error) {
    console.warn("Failed to load covers", error);
    showToast(error.message || "封面图页面加载失败");
  }
}

async function saveCoverProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector("button[type='submit']");
  const status = $("#profile-save-status");
  if (submit) submit.disabled = true;
  if (status) status.textContent = "正在保存…";
  try {
    coverProfileState = await XZJApi.json("/api/xiangzhongjing/covers/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        display_name: form.elements.display_name.value,
        handle: form.elements.handle.value,
        bio: form.elements.bio.value,
        location: form.elements.location.value,
        creator_positioning: form.elements.creator_positioning.value,
        platforms: form.elements.platforms.value,
        content_columns: form.elements.content_columns.value,
        style_keywords: form.elements.style_keywords.value,
        visual_preferences: form.elements.visual_preferences.value,
        cover_negative_prompt: form.elements.cover_negative_prompt.value
      })
    });
    renderCoverProfile();
    showToast("用户信息已保存");
  } catch (error) {
    if (status) status.textContent = "保存失败，请检查后重试";
    showToast(error.message || "保存用户信息失败");
  } finally {
    if (submit) submit.disabled = false;
  }
}

async function uploadCoverAvatar(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const body = new FormData();
  body.append("file", file);
  if ($("#profile-save-status")) $("#profile-save-status").textContent = "正在上传头像…";
  try {
    coverProfileState = await XZJApi.json("/api/xiangzhongjing/covers/profile/avatar", {
      method: "POST",
      body
    });
    renderCoverProfile();
    showToast("头像参考图已更新");
  } catch (error) {
    if ($("#profile-save-status")) $("#profile-save-status").textContent = "头像上传失败，请重试";
    showToast(error.message || "头像上传失败");
  } finally {
    event.target.value = "";
  }
}

async function createCoverCard() {
  const existingDraft = coverImagesState.find((cover) => cover.status !== "completed");
  if (existingDraft) {
    activeCoverDraftId = existingDraft.id;
    setCoverTab("studio");
    renderCoverStudio();
    showToast("已打开未完成的封面草稿");
    return;
  }
  const project = coverProject(activeProject) || coverProjects()[0] || {};
  try {
    const created = await XZJApi.json("/api/xiangzhongjing/covers/images", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: project.id || "",
        project_title: project.title || "",
        title: project.title || "未命名封面",
        preset_id: coverPresetsState[0]?.id || "ink-cover"
      })
    });
    coverImagesState = [created, ...coverImagesState.filter((cover) => cover.id !== created.id)];
    activeCoverDraftId = created.id;
    setCoverTab("studio");
    renderCoversPage();
    showToast("已创建封面草稿");
  } catch (error) {
    showToast(error.message || "新建封面卡失败");
  }
}

function coverPayload(card) {
  const projectId = card.querySelector("[data-cover-field='project_id']")?.value || "";
  const project = coverProject(projectId) || {};
  return {
    project_id: projectId,
    project_title: project.title || "",
    title: card.querySelector("[data-cover-field='title']")?.value || project.title || "",
    preset_id: card.querySelector("[data-cover-field='preset_id']")?.value || "ink-cover",
    prompt: card.querySelector("[data-cover-field='prompt']")?.value || ""
  };
}

function mergeCover(cover) {
  if (!cover?.id) return;
  coverImagesState = coverImagesState.some((item) => item.id === cover.id)
    ? coverImagesState.map((item) => item.id === cover.id ? { ...item, ...cover } : item)
    : [cover, ...coverImagesState];
}

async function saveCoverDraft(card, { quiet = false } = {}) {
  if (!card) return null;
  const coverId = card.dataset.coverId;
  try {
    const saved = await XZJApi.json(`/api/xiangzhongjing/covers/images/${encodeURIComponent(coverId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(coverPayload(card))
    });
    mergeCover(saved);
    const status = card.querySelector("#cover-draft-save-status");
    if (status && saved.status !== "generating") status.textContent = "草稿已自动保存";
    if (!quiet) showToast("封面草稿已保存");
    return saved;
  } catch (error) {
    const status = card.querySelector("#cover-draft-save-status");
    if (status) status.textContent = "保存失败，请重试";
    if (!quiet) showToast(error.message || "封面草稿保存失败");
    return null;
  }
}

function queueCoverDraftSave(card) {
  if (!card || card.dataset.coverStatus === "generating") return;
  window.clearTimeout(coverDraftSaveTimer);
  const status = card.querySelector("#cover-draft-save-status");
  if (status) status.textContent = "等待保存…";
  coverDraftSaveTimer = window.setTimeout(() => saveCoverDraft(card, { quiet: true }), 650);
}

async function uploadCoverReference(input) {
  const card = input.closest("[data-cover-id]");
  const file = input.files?.[0];
  if (!card || !file) return;
  const body = new FormData();
  body.append("file", file);
  try {
    window.clearTimeout(coverDraftSaveTimer);
    await saveCoverDraft(card, { quiet: true });
    const updated = await XZJApi.json(`/api/xiangzhongjing/covers/images/${encodeURIComponent(card.dataset.coverId)}/reference`, {
      method: "POST",
      body
    });
    mergeCover(updated);
    renderCoverStudio();
    showToast("参考图已上传");
  } catch (error) {
    showToast(error.message || "参考图上传失败");
  } finally {
    input.value = "";
  }
}

async function generateCoverCard(card) {
  if (!card) return;
  const coverId = card.dataset.coverId;
  const referenceMode = card.querySelector("[data-cover-reference-mode]")?.value || "default";
  const payload = { ...coverPayload(card), use_default_avatar: referenceMode === "default" };
  try {
    window.clearTimeout(coverDraftSaveTimer);
    const saved = await XZJApi.json(`/api/xiangzhongjing/covers/images/${encodeURIComponent(coverId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    mergeCover(saved);
    coverImagesState = coverImagesState.map((item) => (
      item.id === coverId ? { ...saved, status: "generating", error_message: "" } : item
    ));
    activeCoverDraftId = coverId;
    setCoverTab("studio");
    renderCoverStudio();
    const result = await XZJApi.json(`/api/xiangzhongjing/covers/images/${encodeURIComponent(coverId)}/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    mergeCover(result);
    if (result.status === "completed") {
      activeCoverDraftId = "";
      setCoverTab("assets");
      renderCoversPage();
      showToast("封面生成完成，已保存到封面资产");
    } else {
      renderCoverStudio();
      showToast("封面生成失败，请查看创作台提示");
    }
  } catch (error) {
    const latest = await XZJApi.json("/api/xiangzhongjing/covers/images").catch(() => ({ covers: [] }));
    coverImagesState = latest.covers || coverImagesState;
    renderCoverStudio();
    showToast(error.message || "封面生成失败");
  }
}

function openCoverPresetModal(trigger) {
  coverPresetTrigger = trigger || null;
  const modal = $("#cover-preset-modal");
  const form = $("#cover-preset-form");
  if (!modal || !form) return;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("cover-preset-lock");
  form.reset();
  form.elements.name.focus();
}

function closeCoverPresetModal() {
  const modal = $("#cover-preset-modal");
  if (modal) {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }
  document.body.classList.remove("cover-preset-lock");
  coverPresetTrigger?.focus?.();
  coverPresetTrigger = null;
}

function keepCoverPresetFocusInside(event, modal) {
  if (event.key !== "Tab") return false;
  const focusable = [...modal.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href]'
  )].filter((element) => element.offsetParent !== null);
  if (!focusable.length) return false;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
    return true;
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
    return true;
  }
  return false;
}

async function createCoverPreset(event) {
  event?.preventDefault();
  const form = $("#cover-preset-form");
  if (!form) return;
  const submit = form.querySelector("button[type='submit']");
  const name = form.elements.name.value.trim();
  const prompt = form.elements.prompt.value.trim();
  if (!name || !prompt) return;
  if (submit) submit.disabled = true;
  try {
    const preset = await XZJApi.json("/api/xiangzhongjing/covers/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, prompt })
    });
    coverPresetsState = [...coverPresetsState, preset];
    const draft = coverImagesState.find((cover) => cover.id === activeCoverDraftId);
    if (draft) {
      draft.preset_id = preset.id;
      draft.prompt = preset.prompt;
    }
    renderCoverStudio();
    const card = $("#cover-studio-workbench [data-cover-id]");
    if (card && draft) await saveCoverDraft(card, { quiet: true });
    closeCoverPresetModal();
    showToast("封面风格预设已创建");
  } catch (error) {
    showToast(error.message || "预设创建失败");
  } finally {
    if (submit) submit.disabled = false;
  }
}

document.addEventListener("change", (event) => {
  if (event.target.matches("#cover-avatar-input")) {
    uploadCoverAvatar(event);
    return;
  }
  if (event.target.matches("[data-cover-reference-upload]")) {
    uploadCoverReference(event.target);
    return;
  }
  if (event.target.matches("[data-cover-field='project_id']")) {
    const card = event.target.closest("[data-cover-id]");
    const project = coverProject(event.target.value) || {};
    const titleInput = card?.querySelector("[data-cover-field='title']");
    if (titleInput && project.title) titleInput.value = project.title;
    queueCoverDraftSave(card);
    return;
  }
  if (event.target.matches("[data-cover-field='preset_id']")) {
    const card = event.target.closest("[data-cover-id]");
    const promptField = card?.querySelector("[data-cover-field='prompt']");
    if (promptField) promptField.value = selectedPresetPrompt(event.target.value);
    queueCoverDraftSave(card);
  }
});

document.addEventListener("input", (event) => {
  if (event.target.matches("[data-cover-field='title'], [data-cover-field='prompt']")) {
    queueCoverDraftSave(event.target.closest("[data-cover-id]"));
  }
});

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-cover-new-draft]")) {
    createCoverCard();
    return;
  }
  const tab = event.target.closest("[data-cover-tab]");
  if (tab) {
    setCoverTab(tab.dataset.coverTab);
    return;
  }
  const generate = event.target.closest("[data-cover-generate]");
  if (generate) {
    generateCoverCard(generate.closest("[data-cover-id]"));
    return;
  }
  if (event.target.closest("[data-cover-create-preset]")) {
    openCoverPresetModal(event.target.closest("[data-cover-create-preset]"));
    return;
  }
  const openProject = event.target.closest("[data-cover-open-project]");
  if (openProject) {
    event.preventDefault();
    selectProject(openProject.dataset.coverOpenProject, { openEditor: true });
    return;
  }
  if (event.target.closest("#cover-preset-close, #cover-preset-cancel")) {
    closeCoverPresetModal();
    return;
  }
  if (event.target.id === "cover-preset-modal") {
    closeCoverPresetModal();
  }
});

document.addEventListener("keydown", (event) => {
  const modal = $("#cover-preset-modal");
  if (modal && !modal.classList.contains("hidden")) {
    if (event.key === "Escape") {
      closeCoverPresetModal();
      return;
    }
    if (keepCoverPresetFocusInside(event, modal)) return;
  }
  if (!event.target.matches("[data-cover-tab]")) return;
  const tabs = [...$$('[data-cover-tab]')];
  const index = tabs.indexOf(event.target);
  const nextIndex = event.key === "ArrowRight"
    ? (index + 1) % tabs.length
    : event.key === "ArrowLeft"
      ? (index - 1 + tabs.length) % tabs.length
      : null;
  if (nextIndex === null) return;
  event.preventDefault();
  setCoverTab(tabs[nextIndex].dataset.coverTab);
  tabs[nextIndex].focus();
});

$("#cover-preset-form")?.addEventListener("submit", createCoverPreset);
$("#cover-profile-form")?.addEventListener("submit", saveCoverProfile);
$("#cover-profile-form")?.addEventListener("input", () => {
  if ($("#profile-save-status")) $("#profile-save-status").textContent = "有未保存的修改";
});
loadCreatorProfileSummary();
