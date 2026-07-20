// Lado webview: nunca llama a la API de kal directamente (evita CSP/red
// desde el webview) — le manda postMessage al extension host, que es
// quien hace el HTTP real (ver src/chatPanel.ts).
(function () {
  const vscode = acquireVsCodeApi();
  const messagesEl = document.getElementById("messages");
  const inputEl = document.getElementById("input");
  const sendBtn = document.getElementById("send");
  const contextIndicatorEl = document.getElementById("context-indicator");
  const contextLabelEl = document.getElementById("context-label");
  const contextDismissBtn = document.getElementById("context-dismiss");

  contextDismissBtn.addEventListener("click", () => {
    contextIndicatorEl.style.display = "none";
    vscode.postMessage({ type: "dismiss-context" });
  });

  function appendMessage(text, className) {
    const div = document.createElement("div");
    div.className = "msg " + className;
    div.textContent = text;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function send() {
    const text = inputEl.value.trim();
    if (!text) return;
    appendMessage(text, "msg-user");
    inputEl.value = "";
    contextIndicatorEl.style.display = "none"; // adjunto de un solo uso, ver chatPanel.ts
    const pending = appendMessage("kal está pensando...", "msg-pending");
    pending.dataset.pending = "true";
    // BUG REAL ENCONTRADO EN USO: sin deshabilitar el envío acá, el
    // usuario podía mandar un pedido nuevo mientras la vista previa de
    // archivos (propose_project_files, ver projectFiles.ts) de un
    // pedido ANTERIOR todavía estaba esperando su decisión — VS Code
    // encola los diálogos nativos, así que el usuario seguía viendo la
    // propuesta VIEJA (a veces de varios mensajes atrás) sin importar
    // cuántos pedidos nuevos hiciera después. Se vuelve a habilitar
    // recién con "ready", que el extension host manda cuando TODO el
    // flujo del pedido (incluida esa vista previa, si la hubo) terminó.
    inputEl.disabled = true;
    sendBtn.disabled = true;
    vscode.setState({ lastQuestion: text });
    vscode.postMessage({ type: "ask", text: text });
  }

  sendBtn.addEventListener("click", send);
  inputEl.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      send();
    }
  });

  function removePending() {
    const pending = messagesEl.querySelector('[data-pending="true"]');
    if (pending) pending.remove();
  }

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (message.type === "context-attached") {
      const label = message.isSelection ? "selección" : "archivo completo";
      contextLabelEl.textContent = `📎 ${message.relativePath} (${label})`;
      contextIndicatorEl.style.display = "flex";
      inputEl.focus();
    } else if (message.type === "answer") {
      removePending();
      const result = message.result;
      if (result.plan && result.plan.length > 1) {
        appendMessage("Plan:\n" + result.plan.map((s, i) => `${i + 1}. ${s}`).join("\n"), "msg-plan");
      }
      appendMessage(result.final_answer, "msg-agent");
    } else if (message.type === "error") {
      removePending();
      appendMessage(message.message, "msg-error");
    } else if (message.type === "ready") {
      inputEl.disabled = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  });
})();
