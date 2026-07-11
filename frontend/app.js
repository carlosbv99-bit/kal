// kal — frontend vanilla, sin build step. Habla con la API FastAPI del
// propio proceso (mismo origen, sin CORS que configurar).

const API = "";

// Token administrativo (self-modification, aprobación/rollback de
// herramientas, autorreparación) — ver utils/admin_token.py y
// agent_core/orchestrator.py. Se toma una vez de la URL
// (?admin_token=... impresa en el log del backend al arrancar) y se
// guarda en localStorage para no tener que repetirlo en cada visita.
const ADMIN_TOKEN_STORAGE_KEY = "kal_admin_token";
(function persistAdminTokenFromUrl() {
  const fromUrl = new URLSearchParams(window.location.search).get("admin_token");
  if (fromUrl) localStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, fromUrl);
})();

// ---------- Utilidades ----------

async function api(path, options = {}) {
  const adminToken = localStorage.getItem(ADMIN_TOKEN_STORAGE_KEY);
  const res = await fetch(API + path, {
    headers: {
      "Content-Type": "application/json",
      ...(adminToken ? { "X-Kal-Admin-Token": adminToken } : {}),
    },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString();
}

// ---------- Franja de estado (el elemento distintivo) ----------

async function refreshStatus() {
  const strip = document.getElementById("status-strip");
  let status;
  try {
    status = await api("/status");
  } catch (e) {
    strip.querySelectorAll(".lamp").forEach((l) => (l.className = "lamp critical"));
    return;
  }

  setLamp("audit_chain_verified", status.audit_chain_verified ? "ok" : "critical");
  setLamp("sandbox_network_mode", status.sandbox_network_mode === "none" ? "ok" : "warn");
  setLamp("open_circuit_breakers", status.open_circuit_breakers === 0 ? "ok" : "critical");

  const pendingTotal = (status.pending_tool_approvals || 0) + (status.pending_self_modification_approvals || 0);
  setLamp("pending_approvals", pendingTotal === 0 ? "ok" : "warn");

  setLamp("llm_available", status.llm_available ? "ok" : "critical");
}

function setLamp(key, state) {
  const node = document.querySelector(`.status-lamp[data-key="${key}"] .lamp`);
  if (node) node.className = `lamp ${state}`;
}

// ---------- Modelos ----------

async function loadModels() {
  const select = document.getElementById("model-select");
  try {
    const data = await api("/models");
    select.innerHTML = "";
    for (const name of data.models) {
      const opt = el("option", null, name);
      opt.value = name;
      if (name === data.default) opt.selected = true;
      select.appendChild(opt);
    }
    if (data.models.length === 0) {
      select.appendChild(el("option", null, "sin modelos"));
    }
  } catch (e) {
    select.innerHTML = "";
    select.appendChild(el("option", null, "ollama no disponible"));
  }
}

// ---------- Chat ----------

const chatScroll = document.getElementById("chat-scroll");
const chatEmpty = document.getElementById("chat-empty");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");

// Continuidad conversacional (ver agent_core/sessions.py): null hasta el
// primer /chat, el backend crea la sesión y devuelve su id — a partir de
// ahí se reusa mientras dure esta pestaña (recargar la página = chat
// nuevo, comportamiento esperable).
let sessionId = null;

function appendUserMessage(text) {
  chatEmpty.style.display = "none";
  const msg = el("div", "msg msg-user", text);
  chatScroll.appendChild(msg);
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

// El indicador de "trabajando" es un único elemento fijo, pegado arriba
// del botón de modelo — no un mensaje más del historial del chat.
const pendingIndicator = document.getElementById("pending-indicator");
const pendingCancelBtn = document.getElementById("pending-cancel-btn");
let currentAbortController = null;

function showPending(controller) {
  currentAbortController = controller;
  pendingIndicator.hidden = false;
}

function hidePending() {
  currentAbortController = null;
  pendingIndicator.hidden = true;
}

pendingCancelBtn.addEventListener("click", () => {
  if (currentAbortController) currentAbortController.abort();
});

// ---------- Imágenes en el chat ----------
// Toda imagen subida, generada, o editada/corregida aparece como un
// mensaje más del chat, en el orden en que ocurrió.

function appendImageMessage(url, altText) {
  chatEmpty.style.display = "none";
  const wrapper = el("div", "msg msg-agent");
  const img = document.createElement("img");
  img.className = "chat-image-message";
  img.src = url;
  img.alt = altText || "Imagen";
  wrapper.appendChild(img);
  chatScroll.appendChild(wrapper);
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function appendAgentResult(result) {
  if (result.plan && result.plan.length > 1) {
    const planBox = el("div", "msg-steps");
    const title = el("div", "msg-step-tool", "Plan:");
    planBox.appendChild(title);
    result.plan.forEach((step, i) => {
      planBox.appendChild(el("div", "msg-step-line", `${i + 1}. ${step}`));
    });
    chatScroll.appendChild(planBox);
  }

  if (result.steps && result.steps.length > 0) {
    const stepsBox = el("div", "msg-steps");
    for (const step of result.steps) {
      const line = el("div", "msg-step-line");
      const toolSpan = el("span", "msg-step-tool", `${step.tool}`);
      line.appendChild(toolSpan);
      line.appendChild(document.createTextNode(`(${JSON.stringify(step.arguments)}) → ${truncate(step.observation, 200)}`));
      stepsBox.appendChild(line);

      // Toda imagen generada/editada/compuesta aparece como un
      // mensaje más del chat, sin que el usuario tenga que hacer nada.
      if (step.artifact && step.artifact.modality === "image") {
        appendImageMessage(step.artifact.url, "Imagen generada por kal");
      }
    }
    chatScroll.appendChild(stepsBox);
  }

  if (result.status === "llm_error") {
    chatScroll.appendChild(el("div", "msg-error", `No pude contactar a Ollama: ${result.final_answer}`));
  } else {
    const msg = el("div", "msg msg-agent", result.final_answer);
    if (result.status === "max_steps_exceeded") {
      msg.appendChild(el("div", "dash-item-meta", "(se agotó el límite de pasos antes de una respuesta final)"));
    }
    chatScroll.appendChild(msg);
  }
  chatScroll.scrollTop = chatScroll.scrollHeight;
}

function truncate(text, n) {
  if (!text) return "";
  return text.length > n ? text.slice(0, n) + "…" : text;
}

// Auto-crece con el contenido (p.ej. pegar código) hasta el límite de
// max-height del CSS (160px, ahí ya sigue con scroll interno normal),
// y vuelve a su tamaño de una línea después de enviar.
function autoResizeChatInput() {
  chatInput.style.height = "auto";
  chatInput.style.height = `${chatInput.scrollHeight}px`;
}

chatInput.addEventListener("input", autoResizeChatInput);

chatForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const goal = chatInput.value.trim();
  if (!goal) return;

  appendUserMessage(goal);
  chatInput.value = "";
  autoResizeChatInput(); // vuelve a una línea
  sendBtn.disabled = true;

  // Cancelar solo corta la ESPERA del lado del navegador — /chat es un
  // endpoint sincrónico (ver README), así que kal puede seguir
  // trabajando un rato más del lado del servidor aunque cancelemos acá;
  // no hay forma barata de interrumpir a mitad una llamada al modelo o
  // una generación de imagen ya en curso.
  const controller = new AbortController();
  showPending(controller);

  const model = document.getElementById("model-select").value;

  try {
    const result = await api("/chat", {
      method: "POST",
      body: JSON.stringify({ goal, model: model || null, session_id: sessionId }),
      signal: controller.signal,
    });
    sessionId = result.session_id;
    hidePending();
    appendAgentResult(result);
  } catch (e) {
    hidePending();
    if (e.name === "AbortError") {
      chatScroll.appendChild(el("div", "msg-error", "Cancelado. Kal puede seguir trabajando en el fondo un rato más, pero ya no esperamos esa respuesta."));
    } else {
      chatScroll.appendChild(el("div", "msg-error", `Error: ${e.message}`));
    }
  } finally {
    sendBtn.disabled = false;
    refreshDashTab(currentTab); // lo que kal hizo probablemente cambió algo en el panel
    refreshStatus();
  }
});

// ---------- Subir una imagen propia ----------

const imageUploadInput = document.getElementById("image-upload-input");

function appendUploadedImage(url, path) {
  appendImageMessage(url, "Imagen subida");
}

imageUploadInput.addEventListener("change", async () => {
  const file = imageUploadInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("file", file);
  formData.append("session_id", sessionId || "");

  const controller = new AbortController();
  showPending(controller);
  try {
    const res = await fetch(API + "/uploads", { method: "POST", body: formData, signal: controller.signal });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.statusText);
    }
    const result = await res.json();
    sessionId = result.session_id;
    hidePending();
    appendUploadedImage(result.url, result.path);
  } catch (e) {
    hidePending();
    if (e.name === "AbortError") {
      chatScroll.appendChild(el("div", "msg-error", "Subida cancelada."));
    } else {
      chatScroll.appendChild(el("div", "msg-error", `Error subiendo imagen: ${e.message}`));
    }
  } finally {
    imageUploadInput.value = ""; // permite volver a subir el mismo archivo
  }
});

chatInput.addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && !ev.shiftKey) {
    ev.preventDefault();
    chatForm.requestSubmit();
  }
});

// ---------- Dashboard: tabs ----------

let currentTab = "tasks";

document.getElementById("dash-tabs").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".dash-tab");
  if (!btn) return;
  const tab = btn.dataset.tab;
  currentTab = tab;

  document.querySelectorAll(".dash-tab").forEach((t) => t.classList.toggle("active", t === btn));
  document.querySelectorAll(".dash-view").forEach((v) => v.classList.toggle("active", v.dataset.view === tab));

  refreshDashTab(tab);
});

document.querySelectorAll("[data-refresh]").forEach((btn) => {
  btn.addEventListener("click", () => refreshDashTab(btn.dataset.refresh));
});

function refreshDashTab(tab) {
  if (tab === "tasks") return refreshTasks();
  if (tab === "tools") return refreshTools();
  if (tab === "selfmod") return refreshSelfMod();
  if (tab === "audit") return refreshAudit();
}

// ---------- Tareas ----------

async function refreshTasks() {
  const list = document.getElementById("tasks-list");
  list.innerHTML = "";
  let tasks;
  try {
    tasks = await api("/tasks");
  } catch (e) {
    list.appendChild(el("div", "dash-empty", "No se pudo cargar tareas."));
    return;
  }
  if (tasks.length === 0) {
    list.appendChild(el("div", "dash-empty", "Sin tareas todavía."));
    return;
  }
  for (const t of tasks.slice(0, 30)) {
    const item = el("div", "dash-item");
    const title = el("div", "dash-item-title");
    title.appendChild(el("span", null, truncate(t.description, 40)));
    title.appendChild(statusBadge(t.status));
    item.appendChild(title);
    item.appendChild(el("div", "dash-item-meta", formatTime(t.created_at) + (t.error ? " · " + truncate(t.error, 60) : "")));
    list.appendChild(item);
  }
}

function statusBadge(status) {
  const map = { success: "badge-success", failed: "badge-critical", escalated: "badge-critical", running: "badge-warn", pending: "" };
  return el("span", `badge ${map[status] || ""}`, status);
}

// ---------- Memoria ----------

document.getElementById("memory-search-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = document.getElementById("memory-query").value.trim();
  const results = document.getElementById("memory-results");
  results.innerHTML = "";
  if (!q) return;

  let data;
  try {
    data = await api(`/memory/search?q=${encodeURIComponent(q)}&top_k=5`);
  } catch (e) {
    results.appendChild(el("div", "dash-empty", "Error al buscar."));
    return;
  }

  let any = false;
  for (const [tier, items] of Object.entries(data)) {
    for (const item of items) {
      any = true;
      const box = el("div", "dash-item");
      box.appendChild(el("div", "dash-item-title", truncate(item.content, 80)));
      box.appendChild(el("div", "dash-item-meta", tier));
      results.appendChild(box);
    }
  }
  if (!any) results.appendChild(el("div", "dash-empty", "Sin resultados."));
});

// ---------- Herramientas ----------

async function refreshTools() {
  const activeList = document.getElementById("tools-active-list");
  const pendingList = document.getElementById("tools-pending-list");
  activeList.innerHTML = "";
  pendingList.innerHTML = "";

  let data;
  try {
    data = await api("/tools");
  } catch (e) {
    activeList.appendChild(el("div", "dash-empty", "No se pudo cargar herramientas."));
    return;
  }

  if (data.active.length === 0) activeList.appendChild(el("div", "dash-empty", "Ninguna."));
  for (const tool of data.active) {
    const item = el("div", "dash-item");
    item.appendChild(el("div", "dash-item-title", tool.name));
    item.appendChild(el("div", "dash-item-meta", tool.description));
    activeList.appendChild(item);
  }

  if (data.pending.length === 0) pendingList.appendChild(el("div", "dash-empty", "Ninguna pendiente."));
  for (const tool of data.pending) {
    const item = el("div", "dash-item");
    const title = el("div", "dash-item-title");
    title.appendChild(el("span", null, tool.name));
    title.appendChild(el("span", "badge badge-warn", "pendiente"));
    item.appendChild(title);
    item.appendChild(el("div", "dash-item-meta", tool.description));

    const approveBtn = el("button", "mini-btn", "Aprobar");
    approveBtn.style.marginTop = "6px";
    approveBtn.addEventListener("click", async () => {
      approveBtn.disabled = true;
      try {
        await api(`/tools/${encodeURIComponent(tool.name)}/approve`, {
          method: "POST",
          body: JSON.stringify({ approved_by: "kalin (frontend)" }),
        });
        refreshTools();
        refreshStatus();
      } catch (e) {
        approveBtn.disabled = false;
        alert("No se pudo aprobar: " + e.message);
      }
    });
    item.appendChild(approveBtn);
    pendingList.appendChild(item);
  }
}

// ---------- Self-modification ----------

async function refreshSelfMod() {
  const list = document.getElementById("selfmod-list");
  list.innerHTML = "";
  let proposals;
  try {
    proposals = await api("/self-modification");
  } catch (e) {
    list.appendChild(el("div", "dash-empty", "No se pudo cargar propuestas."));
    return;
  }
  if (proposals.length === 0) {
    list.appendChild(el("div", "dash-empty", "Sin propuestas todavía."));
    return;
  }
  for (const p of proposals) {
    const item = el("div", "dash-item");
    const title = el("div", "dash-item-title");
    title.appendChild(el("span", null, p.target_path));
    title.appendChild(selfModBadge(p.status));
    item.appendChild(title);
    item.appendChild(el("div", "dash-item-meta", truncate(p.justification, 70)));
    if (p.detail) item.appendChild(el("div", "dash-item-meta", truncate(p.detail, 90)));

    if (p.status === "pending_human_approval") {
      const applyBtn = el("button", "mini-btn", "Aplicar");
      applyBtn.style.marginTop = "6px";
      applyBtn.addEventListener("click", async () => {
        if (!confirm(`¿Aplicar el cambio propuesto a ${p.target_path}?`)) return;
        applyBtn.disabled = true;
        try {
          await api("/self-modification/apply", {
            method: "POST",
            body: JSON.stringify({ proposal_id: p.id, approved_by: "kalin (frontend)" }),
          });
          refreshSelfMod();
        } catch (e) {
          applyBtn.disabled = false;
          alert("No se pudo aplicar: " + e.message);
        }
      });
      item.appendChild(applyBtn);
    }
    list.appendChild(item);
  }
}

function selfModBadge(status) {
  const map = {
    applied: "badge-success",
    pending_human_approval: "badge-warn",
    blocked_core: "badge-critical",
    rejected_unsafe: "badge-critical",
    regression_detected: "badge-critical",
    rolled_back: "",
  };
  return el("span", `badge ${map[status] || ""}`, status);
}

// ---------- Auditoría ----------

async function refreshAudit() {
  const list = document.getElementById("audit-list");
  list.innerHTML = "";
  let data;
  try {
    data = await api("/audit/tail?n=40");
  } catch (e) {
    list.appendChild(el("div", "dash-empty", "No se pudo cargar auditoría."));
    return;
  }

  const header = el("div", "dash-item-meta", data.verified ? "cadena íntegra ✓" : "¡CADENA ROTA!");
  header.style.color = data.verified ? "var(--accent)" : "var(--critical)";
  list.appendChild(header);

  for (const entry of data.entries) {
    const item = el("div", "dash-item");
    const title = el("div", "dash-item-title");
    title.appendChild(el("span", null, entry.event_type));
    title.appendChild(el("span", `badge ${entry.outcome === "success" ? "badge-success" : entry.outcome === "failure" ? "badge-critical" : "badge-warn"}`, entry.outcome));
    item.appendChild(title);
    item.appendChild(el("div", "dash-item-meta", truncate(entry.summary, 90)));
    list.appendChild(item);
  }
}

// ---------- Arranque ----------

refreshStatus();
loadModels();
refreshTasks();
setInterval(refreshStatus, 6000);
