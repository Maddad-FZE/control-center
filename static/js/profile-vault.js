(function () {
  const pane = document.getElementById("profile-vault");
  if (!pane) return;

  const tbody = document.getElementById("vault-tbody");
  const form = document.getElementById("vault-form");
  const listWrap = document.getElementById("vault-list-wrap");
  const statusEl = document.getElementById("vault-status");
  const revealWrap = document.getElementById("vault-reveal");
  const revealOut = document.getElementById("vault-reveal-out");
  const serviceSelect = document.getElementById("vault-service");
  const presetService = pane.dataset.service || "";

  let entries = [];
  let revealId = "";

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || "";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  async function api(url, options) {
    const resp = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        ...(options?.headers || {}),
      },
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  function showForm(entry) {
    form.hidden = false;
    listWrap.hidden = true;
    revealWrap.hidden = true;
    document.getElementById("vault-id").value = entry?.id || "";
    document.getElementById("vault-label").value = entry?.label || "";
    document.getElementById("vault-username").value = entry?.username || "";
    document.getElementById("vault-secret").value = "";
    document.getElementById("vault-kind").value = entry?.kind || "password";
    document.getElementById("vault-notes").value = entry?.notes || "";
    serviceSelect.value = entry?.service_id ? String(entry.service_id) : presetService || "";
  }

  function hideForm() {
    form.hidden = true;
    listWrap.hidden = false;
    revealWrap.hidden = true;
  }

  function renderRows() {
    tbody.innerHTML = "";
    entries.forEach((entry) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(entry.label)}</td>
        <td>${escapeHtml(entry.username)}</td>
        <td>${escapeHtml(entry.kind)}</td>
        <td>${escapeHtml(entry.service_name || "—")}</td>
        <td class="library-repos-table__actions"></td>
      `;
      const actions = tr.querySelector(".library-repos-table__actions");
      const revealBtn = document.createElement("button");
      revealBtn.type = "button";
      revealBtn.className = "btn secondary";
      revealBtn.textContent = "Reveal";
      revealBtn.addEventListener("click", () => openReveal(entry));
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn secondary";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => showForm(entry));
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn secondary";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", async () => {
        if (
          !(await window.ccDialog.confirm(`Delete ${entry.label}?`, {
            title: "Delete credential",
            confirmLabel: "Delete",
            danger: true,
          }))
        ) {
          return;
        }
        await api(`/profile/api/vault/${entry.id}/`, { method: "DELETE" });
        await load();
      });
      actions.append(revealBtn, editBtn, delBtn);
      tbody.appendChild(tr);
    });
  }

  function openReveal(entry) {
    revealId = entry.id;
    revealWrap.hidden = false;
    listWrap.hidden = true;
    form.hidden = true;
    revealOut.hidden = true;
    revealOut.textContent = "";
    document.getElementById("vault-reveal-password").value = "";
  }

  async function load() {
    try {
      const data = await api("/profile/api/vault/");
      entries = data.entries || [];
      renderRows();
      setStatus(`${entries.length} saved`);
      if (presetService && !form.hidden === false) {
        const match = entries.find((row) => String(row.service_id) === String(presetService));
        if (!match) showForm({ service_id: Number(presetService) });
      }
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function loadServices() {
    try {
      const data = await api("/profile/api/vault/services/");
      serviceSelect.innerHTML = `<option value="">None</option>`;
      (data.services || []).forEach((row) => {
        const opt = document.createElement("option");
        opt.value = String(row.id);
        opt.textContent = row.name;
        serviceSelect.appendChild(opt);
      });
      if (presetService) serviceSelect.value = presetService;
    } catch {
      /* keep empty */
    }
  }

  document.getElementById("vault-add-btn")?.addEventListener("click", () => showForm(null));
  document.getElementById("vault-cancel-btn")?.addEventListener("click", hideForm);
  document.getElementById("vault-reveal-cancel")?.addEventListener("click", hideForm);

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = document.getElementById("vault-id").value;
    const payload = {
      label: document.getElementById("vault-label").value.trim(),
      username: document.getElementById("vault-username").value.trim(),
      secret: document.getElementById("vault-secret").value,
      kind: document.getElementById("vault-kind").value,
      notes: document.getElementById("vault-notes").value.trim(),
      service_id: serviceSelect.value ? Number(serviceSelect.value) : null,
    };
    try {
      if (id) {
        await api(`/profile/api/vault/${id}/`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        await api("/profile/api/vault/", { method: "POST", body: JSON.stringify(payload) });
      }
      hideForm();
      await load();
    } catch (err) {
      setStatus(err.message);
    }
  });

  document.getElementById("vault-reveal-btn")?.addEventListener("click", async () => {
    try {
      const data = await api(`/profile/api/vault/${revealId}/reveal/`, {
        method: "POST",
        body: JSON.stringify({
          password: document.getElementById("vault-reveal-password").value,
        }),
      });
      revealOut.hidden = false;
      revealOut.textContent = `${data.username || ""}\n${data.secret || ""}`;
    } catch (err) {
      setStatus(err.message);
    }
  });

  load().then(loadServices);
})();
