const $ = (sel) => document.querySelector(sel);

const fileInput = $("#fileInput");
const dropzone = $("#dropzone");
const uploadForm = $("#uploadForm");
const uploadStatus = $("#uploadStatus");
const docList = $("#docList");
const reindexBtn = $("#reindexBtn");
const healthMeta = $("#healthMeta");
const messages = $("#messages");
const chatForm = $("#chatForm");
const chatInput = $("#chatInput");
const sendBtn = $("#sendBtn");
const uploadBtn = $("#uploadBtn");
const knowledgeBaseSelect = $("#knowledgeBaseSelect");
const knowledgeBaseName = $("#knowledgeBaseName");
const newKnowledgeBaseBtn = $("#newKnowledgeBaseBtn");
const saveKnowledgeBaseBtn = $("#saveKnowledgeBaseBtn");
const deleteKnowledgeBaseBtn = $("#deleteKnowledgeBaseBtn");
const skillSelect = $("#skillSelect");
const skillName = $("#skillName");
const skillContent = $("#skillContent");
const skillStatus = $("#skillStatus");
const newSkillBtn = $("#newSkillBtn");
const saveSkillBtn = $("#saveSkillBtn");
const deleteSkillBtn = $("#deleteSkillBtn");
const schemeTitle = $("#schemeTitle");
const documentMetric = $("#documentMetric");
const indexedMetric = $("#indexedMetric");
const skillBadge = $("#skillBadge");
const skillSummaryName = $("#skillSummaryName");
const schemeDialog = $("#schemeDialog");
const schemeDialogForm = $("#schemeDialogForm");
const newSchemeName = $("#newSchemeName");
const confirmNewSchemeBtn = $("#confirmNewSchemeBtn");
const skillDialog = $("#skillDialog");
const skillDialogForm = $("#skillDialogForm");
const newSkillName = $("#newSkillName");
const newSkillContent = $("#newSkillContent");
const confirmNewSkillBtn = $("#confirmNewSkillBtn");
const cadForm = $("#cadForm");
const cadDescription = $("#cadDescription");
const cadGenerateBtn = $("#cadGenerateBtn");
const cadStatus = $("#cadStatus");
const cadResult = $("#cadResult");

let knowledgeBases = [];
let currentKnowledgeBaseId = null;
let skills = [];
let currentSkillId = null;

function setStatus(text, kind = "") {
  uploadStatus.textContent = text || "";
  uploadStatus.className = `status ${kind}`.trim();
}

function setSkillStatus(text, kind = "") {
  skillStatus.textContent = text || "";
  skillStatus.className = `status ${kind}`.trim();
}

function setCadStatus(text, kind = "") {
  cadStatus.textContent = text || "";
  cadStatus.className = `status ${kind}`.trim();
}

function clearCadResult() {
  cadResult.className = "cad-result empty";
  cadResult.innerHTML = `
    <div class="cad-empty">
      <strong>等待生成 CAD</strong>
      <span>方案通过几何校验后，将在这里显示工程预览和下载文件。</span>
    </div>
  `;
  setCadStatus("");
}

function resetMessages() {
  const intro = document.createElement("div");
  intro.className = "assistant-intro";
  intro.innerHTML = `
    <div class="assistant-mark">✦</div>
    <strong>开始制作你的方案</strong>
    <span>我会结合当前资料库和 Skill 配置，生成多种可行方案并自我校核，同时给出置信度。</span>
  `;
  messages.replaceChildren(intro);
}

function fmtSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function api(path, options = {}) {
  const { timeoutMs = 30000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, { ...fetchOptions, signal: controller.signal });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.error || `请求失败 (${res.status})`);
    }
    return data;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(`请求超过 ${Math.round(timeoutMs / 1000)} 秒，请检查服务网络状态`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function loadHealth() {
  try {
    const data = await api("/api/health");
    const skill = data.skill?.name ? ` · ${data.skill.name}` : "";
    healthMeta.textContent = `${data.model} · ${data.embedding_model}${skill}`;
  } catch (err) {
    healthMeta.textContent = `未就绪：${err.message}`;
  }
}

function renderKnowledgeBases(data) {
  knowledgeBases = data.knowledge_bases || [];
  currentKnowledgeBaseId = data.current;
  knowledgeBaseSelect.replaceChildren(
    ...knowledgeBases.map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      option.selected = item.id === currentKnowledgeBaseId;
      return option;
    })
  );
  const current = knowledgeBases.find((item) => item.id === currentKnowledgeBaseId);
  knowledgeBaseName.value = current?.name || "";
  schemeTitle.textContent = current?.name || "未选择方案";
  deleteKnowledgeBaseBtn.disabled = !current || current.is_default;
  if (typeof populateStepManuals === "function") populateStepManuals();
}

async function loadKnowledgeBases() {
  const data = await api("/api/knowledge-bases");
  renderKnowledgeBases(data);
}

function renderSkills(data) {
  skills = data.skills || [];
  currentSkillId = data.current;
  skillSelect.replaceChildren(
    ...skills.map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      option.selected = item.id === currentSkillId;
      return option;
    })
  );
  const current = skills.find((item) => item.id === currentSkillId);
  skillName.value = current?.name || "";
  skillContent.value = current?.content || "";
  skillBadge.textContent = current?.name || "未选择";
  skillSummaryName.textContent = current?.name || "未选择";
  deleteSkillBtn.disabled = !current || current.is_default;
}

async function loadSkills() {
  renderSkills(await api("/api/skills"));
}

async function refreshAfterKnowledgeBaseChange(message) {
  resetMessages();
  clearCadResult();
  await Promise.all([loadDocuments(), loadHealth()]);
  setStatus(message, "ok");
}

const UPLOAD_OPTION_VALUE = "__upload_new__";

function populateStepManuals() {
  const selects = document.querySelectorAll(".manual-select");
  const currentName =
    knowledgeBases.find((item) => item.id === currentKnowledgeBaseId)?.name || "";
  selects.forEach((select) => {
    const step = select.getAttribute("data-step");
    const previous = select.dataset.previous || currentKnowledgeBaseId;
    select.replaceChildren();
    knowledgeBases.forEach((kb) => {
      const option = document.createElement("option");
      option.value = kb.id;
      option.textContent = kb.name;
      option.selected = kb.id === currentKnowledgeBaseId || kb.id === previous;
      select.append(option);
    });
    const upload = document.createElement("option");
    upload.value = UPLOAD_OPTION_VALUE;
    upload.textContent = "＋ 上传/新建说明书…";
    select.append(upload);
    select.dataset.previous = currentKnowledgeBaseId;
    select.dataset.stepTitle = step;
  });
}

async function selectKnowledgeBaseById(id) {
  const data = await api("/api/knowledge-bases/current", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
  renderKnowledgeBases(data);
  const current = knowledgeBases.find((item) => item.id === currentKnowledgeBaseId);
  await refreshAfterKnowledgeBaseChange(`已切换到「${current?.name || ""}」`);
}

document.querySelectorAll(".manual-select").forEach((select) => {
  select.addEventListener("change", async () => {
    const value = select.value;
    if (!value) return;
    if (value === UPLOAD_OPTION_VALUE) {
      fileInput.click();
      select.value = currentKnowledgeBaseId;
      return;
    }
    select.disabled = true;
    try {
      await selectKnowledgeBaseById(value);
    } catch (err) {
      setStatus(err.message, "error");
      await loadKnowledgeBases();
    } finally {
      populateStepManuals();
      select.disabled = false;
    }
  });
});

let draggedStep = null | 0;

function setupWorkflowReorder() {
  const strip = $("#workflowStrip");
  if (!strip) return;
  strip.addEventListener("dragstart", (e) => {
    const step = e.target.closest(".workflow-step");
    if (!step) return;
    draggedStep = step;
    step.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  strip.addEventListener("dragend", (e) => {
    e.target.closest(".workflow-step")?.classList.remove("dragging");
    draggedStep = null;
  });
  strip.addEventListener("dragover", (e) => {
    e.preventDefault();
    const after = getDragAfterElement(strip, e.clientX);
    const dragging = strip.querySelector(".dragging");
    if (!dragging) return;
    if (after == null) {
      strip.appendChild(dragging);
    } else {
      strip.insertBefore(dragging, after);
    }
    renumberSteps(strip);
  });
}

function getDragAfterElement(container, x) {
  const elements = [...container.querySelectorAll(".workflow-step:not(.dragging)")];
  return elements.reduce(
    (closest, child) => {
      const box = child.getBoundingClientRect();
      const offset = x - box.left - box.width / 2;
      if (offset < 0 && offset > closest.offset) {
        return { offset, element: child };
      }
      return closest;
    },
    { offset: Number.NEGATIVE_INFINITY, element: null }
  ).element;
}

function renumberSteps(strip) {
  const steps = [...strip.querySelectorAll(".workflow-step")];
  steps.forEach((step, index) => {
    const num = String(index + 1).padStart(2, "0");
    const badge = step.querySelector(":scope > span:nth-of-type(2)");
    if (badge) badge.textContent = num;
    step.setAttribute("data-step", String(index + 1));
  });
}


function renderCadResult(data) {
  const plan = data.plan;
  const artifact = data.artifact;
  const steps = (plan.manufacturing_steps || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const notes = (plan.notes || [])
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
  const sources = (data.sources || [])
    .map((item) => escapeHtml(item.source))
    .join("、");
  cadResult.className = "cad-result";
  cadResult.innerHTML = `
    <div class="cad-preview">
      <img src="${artifact.svg_url}" alt="${escapeAttr(plan.title)} CAD 预览" />
    </div>
    <div class="cad-plan">
      <h3>${escapeHtml(plan.title)}</h3>
      <p>${escapeHtml(plan.summary)}</p>
      <div class="cad-specs">
        <span>${escapeHtml(plan.material)}</span>
        <span>${plan.width} × ${plan.height} × ${plan.thickness} mm</span>
        <span>数量 ${plan.quantity}</span>
        <span>圆孔 ${plan.holes.length}</span>
        <span>矩形槽 ${plan.cutouts.length}</span>
      </div>
      <h4>制作步骤</h4>
      <ol>${steps}</ol>
      ${notes ? `<h4>工程备注</h4><ul>${notes}</ul>` : ""}
      ${sources ? `<p class="cad-sources">参考资料：${sources}</p>` : ""}
      <div class="cad-downloads">
        <a class="btn primary small" href="${artifact.dwg_url}" download>下载 DWG</a>
        <a class="btn secondary small" href="${artifact.dxf_url}" download>下载 DXF</a>
        <a class="btn secondary small" href="${artifact.svg_url}" download>下载 SVG</a>
        <a class="btn secondary small" href="${artifact.plan_url}" download>下载方案 JSON</a>
      </div>
    </div>
  `;
}

async function loadDocuments() {
  const data = await api("/api/documents");
  const docs = data.documents || [];
  documentMetric.textContent = String(docs.length);
  indexedMetric.textContent = String(docs.filter((doc) => doc.indexed).length);
  if (!docs.length) {
    docList.innerHTML = `
      <div class="empty-state">
        <strong>还没有方案资料</strong>
        <span>上传文档后即可开始制作方案</span>
      </div>
    `;
    return;
  }
  docList.innerHTML = docs
    .map(
      (doc) => `
      <article class="doc-item" data-name="${escapeAttr(doc.name)}">
        <div class="name">${escapeHtml(doc.name)}</div>
        <button class="btn danger" data-delete="${escapeAttr(doc.name)}">删除</button>
        <div class="meta-line">
          ${fmtSize(doc.size)} · ${doc.suffix}
          ·
          <span class="badge ${doc.indexed ? "" : "warn"}">
            ${doc.indexed ? `${doc.chunks} chunks` : "未索引"}
          </span>
        </div>
      </article>`
    )
    .join("");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function appendMessage(role, text, sources = []) {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  el.textContent = text;
  if (role === "assistant" && sources.length) {
    const box = document.createElement("div");
    box.className = "sources";
    box.innerHTML = `<div>引用 ${sources.length} 条</div>`;
    sources.forEach((item, i) => {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `[${i + 1}] ${item.source} · ${item.score}`;
      const body = document.createElement("div");
      body.textContent = item.text;
      details.append(summary, body);
      box.append(details);
    });
    el.append(box);
  }
  messages.append(el);
  messages.scrollTop = messages.scrollHeight;
}

knowledgeBaseSelect.addEventListener("change", async () => {
  const id = knowledgeBaseSelect.value;
  knowledgeBaseSelect.disabled = true;
  try {
    const data = await api("/api/knowledge-bases/current", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    renderKnowledgeBases(data);
    const current = knowledgeBases.find((item) => item.id === currentKnowledgeBaseId);
    await refreshAfterKnowledgeBaseChange(`已切换到「${current?.name || ""}」`);
  } catch (err) {
    setStatus(err.message, "error");
    await loadKnowledgeBases();
  } finally {
    knowledgeBaseSelect.disabled = false;
  }
});

newKnowledgeBaseBtn.addEventListener("click", () => {
  newSchemeName.value = "";
  schemeDialog.showModal();
  setTimeout(() => newSchemeName.focus(), 0);
});

$("#cancelSchemeBtn").addEventListener("click", () => schemeDialog.close());
$("#closeSchemeDialogBtn").addEventListener("click", () => schemeDialog.close());

schemeDialogForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = newSchemeName.value.trim();
  if (!name) return;
  confirmNewSchemeBtn.disabled = true;
  try {
    const data = await api("/api/knowledge-bases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    renderKnowledgeBases(data);
    schemeDialog.close();
    await refreshAfterKnowledgeBaseChange(`已新建并切换到「${name}」`);
  } catch (err) {
    setStatus(err.message, "error");
    schemeDialog.close();
  } finally {
    confirmNewSchemeBtn.disabled = false;
  }
});

saveKnowledgeBaseBtn.addEventListener("click", async () => {
  const name = knowledgeBaseName.value.trim();
  if (!name || !currentKnowledgeBaseId) {
    setStatus("方案名称不能为空", "error");
    return;
  }
  saveKnowledgeBaseBtn.disabled = true;
  try {
    const data = await api(
      `/api/knowledge-bases/${encodeURIComponent(currentKnowledgeBaseId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      }
    );
    renderKnowledgeBases(data);
    setStatus(`方案名称已保存为「${name}」`, "ok");
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    saveKnowledgeBaseBtn.disabled = false;
  }
});

deleteKnowledgeBaseBtn.addEventListener("click", async () => {
  const current = knowledgeBases.find((item) => item.id === currentKnowledgeBaseId);
  if (!current || current.is_default) return;
  if (!confirm(`删除知识库方案「${current.name}」及其中全部文档和索引？此操作不可恢复。`)) {
    return;
  }
  deleteKnowledgeBaseBtn.disabled = true;
  try {
    const data = await api(
      `/api/knowledge-bases/${encodeURIComponent(currentKnowledgeBaseId)}`,
      { method: "DELETE" }
    );
    renderKnowledgeBases(data);
    await refreshAfterKnowledgeBaseChange(`已删除「${current.name}」，并切换到默认知识库`);
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    const selected = knowledgeBases.find((item) => item.id === currentKnowledgeBaseId);
    deleteKnowledgeBaseBtn.disabled = !selected || selected.is_default;
  }
});

skillSelect.addEventListener("change", async () => {
  skillSelect.disabled = true;
  try {
    const data = await api("/api/skills/current", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: skillSelect.value }),
    });
    renderSkills(data);
    resetMessages();
    await loadHealth();
    setSkillStatus(`已启用「${skillName.value}」`, "ok");
  } catch (err) {
    setSkillStatus(err.message, "error");
    await loadSkills();
  } finally {
    skillSelect.disabled = false;
  }
});

newSkillBtn.addEventListener("click", () => {
  newSkillName.value = "";
  newSkillContent.value = "";
  skillDialog.showModal();
  setTimeout(() => newSkillName.focus(), 0);
});

$("#cancelSkillBtn").addEventListener("click", () => skillDialog.close());
$("#closeSkillDialogBtn").addEventListener("click", () => skillDialog.close());

skillDialogForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = newSkillName.value.trim();
  const content = newSkillContent.value.trim();
  if (!name || !content) return;
  confirmNewSkillBtn.disabled = true;
  try {
    const data = await api("/api/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content }),
    });
    renderSkills(data);
    resetMessages();
    skillDialog.close();
    await loadHealth();
    setSkillStatus(`已新建并启用「${name}」`, "ok");
  } catch (err) {
    setSkillStatus(err.message, "error");
    skillDialog.close();
  } finally {
    confirmNewSkillBtn.disabled = false;
  }
});

saveSkillBtn.addEventListener("click", async () => {
  const name = skillName.value.trim();
  const content = skillContent.value.trim();
  if (!name || !content || !currentSkillId) {
    setSkillStatus("Skill 名称和内容不能为空", "error");
    return;
  }
  saveSkillBtn.disabled = true;
  try {
    const data = await api(`/api/skills/${encodeURIComponent(currentSkillId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, content }),
    });
    renderSkills(data);
    resetMessages();
    await loadHealth();
    setSkillStatus(`已保存并启用「${name}」`, "ok");
  } catch (err) {
    setSkillStatus(err.message, "error");
  } finally {
    saveSkillBtn.disabled = false;
  }
});

deleteSkillBtn.addEventListener("click", async () => {
  const current = skills.find((item) => item.id === currentSkillId);
  if (!current || current.is_default) return;
  if (!confirm(`删除 Skill「${current.name}」？此操作不可恢复。`)) return;
  deleteSkillBtn.disabled = true;
  try {
    const data = await api(`/api/skills/${encodeURIComponent(currentSkillId)}`, {
      method: "DELETE",
    });
    renderSkills(data);
    resetMessages();
    await loadHealth();
    setSkillStatus(`已删除「${current.name}」，并启用默认 Skill`, "ok");
  } catch (err) {
    setSkillStatus(err.message, "error");
  } finally {
    const selected = skills.find((item) => item.id === currentSkillId);
    deleteSkillBtn.disabled = !selected || selected.is_default;
  }
});

dropzone.addEventListener("click", () => fileInput.click());

["dragenter", "dragover"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("active");
  });
});

["dragleave", "drop"].forEach((evt) => {
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("active");
  });
});

dropzone.addEventListener("drop", (e) => {
  fileInput.files = e.dataTransfer.files;
  setStatus(`已选择 ${fileInput.files.length} 个文件`);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files.length) {
    setStatus(`已选择 ${fileInput.files.length} 个文件`);
  }
});

uploadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!fileInput.files.length) {
    setStatus("请先选择文件", "error");
    return;
  }
  const form = new FormData();
  Array.from(fileInput.files).forEach((file) => form.append("files", file));
  uploadBtn.disabled = true;
  setStatus("上传中并建立检索索引…");
  try {
    const data = await api("/api/upload", {
      method: "POST",
      body: form,
      timeoutMs: 900000,
    });
    const total = (data.uploaded || []).reduce((n, item) => n + item.chunks, 0);
    setStatus(`完成：${data.uploaded.length} 个文件，共 ${total} 个检索片段`, "ok");
    fileInput.value = "";
    await loadDocuments();
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    uploadBtn.disabled = false;
  }
});

reindexBtn.addEventListener("click", async () => {
  reindexBtn.disabled = true;
  setStatus("正在重新建立检索索引…");
  try {
    const data = await api("/api/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: true }),
      timeoutMs: 900000,
    });
    setStatus(`索引完成，共 ${data.total_chunks} 个片段`, "ok");
    await loadDocuments();
  } catch (err) {
    setStatus(err.message, "error");
  } finally {
    reindexBtn.disabled = false;
  }
});

docList.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-delete]");
  if (!btn) return;
  const name = btn.getAttribute("data-delete");
  if (!confirm(`删除 ${name}？`)) return;
  try {
    await api("/api/documents", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    setStatus(`已删除 ${name}`, "ok");
    await loadDocuments();
  } catch (err) {
    setStatus(err.message, "error");
  }
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = chatInput.value.trim();
  if (!message) return;
  appendMessage("user", message);
  chatInput.value = "";
  sendBtn.disabled = true;
  const thinking = document.createElement("div");
  thinking.className = "bubble assistant";
  thinking.textContent = "检索、生成并自我校核方案…";
  messages.append(thinking);
  messages.scrollTop = messages.scrollHeight;
  try {
    const data = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, limit: 5 }),
      timeoutMs: 300000,
    });
    thinking.remove();
    appendMessage("assistant", data.answer, data.sources || []);
    if ((data.options || []).length) {
      appendOptions(data.options, data.recommendation || "");
    }
    if (data.reflection) {
      appendReflection(data.reflection);
    }
  } catch (err) {
    thinking.textContent = `错误：${err.message}`;
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
});

function appendOptions(options, recommendation) {
  const box = document.createElement("div");
  box.className = "bubble assistant";
  const cards = options
    .map((opt, i) => {
      const adv = (opt.advantages || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
      const dis = (opt.disadvantages || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
      return `
        <div class="option-card">
          <h4>方案 ${i + 1}：${escapeHtml(opt.title)}</h4>
          <p>${escapeHtml(opt.approach)}</p>
          ${opt.applicable_scenarios ? `<p class="opt-applicable">适用：${escapeHtml(opt.applicable_scenarios)}</p>` : ""}
          ${adv ? `<div class="opt-list adv"><strong>优点</strong><ul>${adv}</ul></div>` : ""}
          ${dis ? `<div class="opt-list dis"><strong>缺点 / 风险</strong><ul>${dis}</ul></div>` : ""}
        </div>`;
    })
    .join("");
  const rec = recommendation
    ? `<div class="option-recommend">${escapeHtml(recommendation)}</div>`
    : "";
  box.innerHTML = `<div class="options-block"><h3>多个可行方案</h3>${cards}${rec}</div>`;
  messages.append(box);
  messages.scrollTop = messages.scrollHeight;
}

function appendReflection(reflection) {
  const box = document.createElement("div");
  box.className = "bubble assistant";
  const pct = Math.round((reflection.confidence || 0) * 100);
  const level = pct >= 80 ? "高" : pct >= 50 ? "中" : "低";
  const gaps = (reflection.gaps || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("");
  const critique = reflection.self_critique
    ? `<div class="reflection-critique"><strong>自我校核</strong><p>${escapeHtml(reflection.self_critique)}</p></div>`
    : "";
  box.innerHTML = `
    <details class="reflection-box">
      <summary>置信度 ${level}（${pct}%） · 依据 ${reflection.grounded ? "已基于检索资料" : "资料不足"} · 自我校核 ${reflection.iterations || 1} 轮</summary>
      ${critique}
      ${gaps ? `<div class="reflection-gaps"><strong>不确定项 / 待确认</strong><ul>${gaps}</ul></div>` : ""}
    </details>
  `;
  messages.append(box);
  messages.scrollTop = messages.scrollHeight;
}

chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});

cadForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const description = cadDescription.value.trim();
  if (!description) return;
  cadGenerateBtn.disabled = true;
  setCadStatus("正在检索资料、生成制作方案并校验几何参数…");
  cadResult.className = "cad-result empty";
  cadResult.innerHTML = `
    <div class="cad-empty">
      <strong>正在参数化制图</strong>
      <span>完成后将生成 DXF、SVG 预览和结构化制作方案。</span>
    </div>
  `;
  try {
    const data = await api("/api/cad/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ description, limit: 5 }),
      timeoutMs: 300000,
    });
    renderCadResult(data);
    setCadStatus("制作方案和 CAD 图已生成，并通过几何边界校验。", "ok");
  } catch (err) {
    clearCadResult();
    setCadStatus(err.message, "error");
  } finally {
    cadGenerateBtn.disabled = false;
  }
});

(async function init() {
  await loadHealth();
  try {
    await loadKnowledgeBases();
    await loadSkills();
    await loadDocuments();
  } catch (err) {
    setStatus(err.message, "error");
  }
  setupWorkflowReorder();
})();
