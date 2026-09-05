(function () {
  const pane = document.getElementById("settings-users");
  if (!pane) return;

  const tbody = document.getElementById("users-tbody");
  const form = document.getElementById("users-form");
  const listWrap = document.getElementById("users-list-wrap");
  const statusEl = document.getElementById("users-status");
  const formError = document.getElementById("users-form-error");
  const formTitle = document.getElementById("users-form-title");
  const servicesBox = document.getElementById("user-services");
  const servicesGroup = document.getElementById("user-services-group");
  const generatedWrap = document.getElementById("users-generated");
  const generatedValue = document.getElementById("users-generated-value");
  const roleSelect = document.getElementById("user-role");

  let users = [];
  let services = [];
  let editingId = "";

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || "";
  }

  function setError(text) {
    if (!formError) return;
    formError.hidden = !text;
    formError.textContent = text || "";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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

  function showForm(isNew, user) {
    form.hidden = false;
    listWrap.hidden = true;
    formTitle.textContent = isNew ? "Add user" : `Edit ${user?.username || ""}`;
    document.getElementById("user-id").value = user?.id || "";
    document.getElementById("user-username").value = user?.username || "";
    document.getElementById("user-email").value = user?.email || "";
    roleSelect.value = user?.role || "member";
    document.getElementById("user-password").value = "";
    document.getElementById("user-password-group").hidden = !isNew;
    document.getElementById("user-active").checked = user ? Boolean(user.is_active) : true;
    document.getElementById("user-must-change").checked = Boolean(user?.must_change_password);
    generatedWrap.hidden = true;
    setError("");
    editingId = user?.id ? String(user.id) : "";
    renderServiceChecks(user?.allowed_service_ids || []);
    toggleServices();
  }

  function hideForm() {
    form.hidden = true;
    listWrap.hidden = false;
    editingId = "";
  }

  function toggleServices() {
    servicesGroup.hidden = roleSelect.value === "admin";
  }

  function renderServiceChecks(selected) {
    const picked = new Set((selected || []).map(String));
    servicesBox.innerHTML = services
      .map(
        (row) =>
          `<label class="checkbox-label"><input type="checkbox" value="${row.id}" ${
            picked.has(String(row.id)) ? "checked" : ""
          }><span>${escapeHtml(row.name)}</span></label>`
      )
      .join("");
  }

  function selectedServiceIds() {
    return [...servicesBox.querySelectorAll("input:checked")].map((el) => Number(el.value));
  }

  function renderRows() {
    tbody.innerHTML = "";
    users.forEach((user) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(user.username)}</td>
        <td>${escapeHtml(user.role)}</td>
        <td>${user.twofa_enabled ? "On" : "Off"}</td>
        <td>${user.is_active ? "Yes" : "No"}</td>
        <td>${escapeHtml(user.last_login || "—")}</td>
        <td class="library-repos-table__actions"></td>
      `;
      const actions = tr.querySelector(".library-repos-table__actions");
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn secondary";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => showForm(false, user));
      const passBtn = document.createElement("button");
      passBtn.type = "button";
      passBtn.className = "btn secondary";
      passBtn.textContent = "Reset password";
      passBtn.addEventListener("click", () => resetPassword(user));
      const twofaBtn = document.createElement("button");
      twofaBtn.type = "button";
      twofaBtn.className = "btn secondary";
      twofaBtn.textContent = "Reset 2FA";
      twofaBtn.disabled = !user.twofa_enabled;
      twofaBtn.addEventListener("click", () => resetTwofa(user));
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "btn secondary";
      delBtn.textContent = "Delete";
      delBtn.disabled = Boolean(user.is_self);
      delBtn.addEventListener("click", () => removeUser(user));
      actions.append(editBtn, passBtn, twofaBtn, delBtn);
      tbody.appendChild(tr);
    });
  }

  async function loadAll() {
    setStatus("Loading…");
    try {
      const [userPayload, servicePayload] = await Promise.all([
        api("/settings/api/users/"),
        api("/settings/api/users/services/"),
      ]);
      users = userPayload.users || [];
      services = servicePayload.services || [];
      renderRows();
      setStatus(`${users.length} account(s)`);
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function resetPassword(user) {
    if (!confirm(`Generate a new password for ${user.username}?`)) return;
    try {
      const data = await api(`/settings/api/users/${user.id}/password/`, {
        method: "POST",
        body: JSON.stringify({ generate: true }),
      });
      generatedWrap.hidden = false;
      generatedValue.textContent = data.generated_password || "";
      setStatus(`Password reset for ${user.username}`);
      await loadAll();
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function resetTwofa(user) {
    if (!confirm(`Reset 2FA for ${user.username}? They will need to enrol again.`)) return;
    try {
      await api(`/settings/api/users/${user.id}/2fa/reset/`, { method: "POST", body: "{}" });
      setStatus(`2FA reset for ${user.username}`);
      await loadAll();
    } catch (err) {
      setStatus(err.message);
    }
  }

  async function removeUser(user) {
    const typed = window.prompt(`Type ${user.username} to delete this account:`);
    if (!typed) return;
    try {
      await api(`/settings/api/users/${user.id}/`, {
        method: "DELETE",
        body: JSON.stringify({ username: typed }),
      });
      setStatus(`Deleted ${user.username}`);
      hideForm();
      await loadAll();
    } catch (err) {
      setStatus(err.message);
    }
  }

  document.getElementById("users-add-btn")?.addEventListener("click", () => showForm(true, null));
  document.getElementById("users-cancel-btn")?.addEventListener("click", hideForm);
  roleSelect?.addEventListener("change", toggleServices);

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      username: document.getElementById("user-username").value.trim(),
      email: document.getElementById("user-email").value.trim(),
      role: roleSelect.value,
      is_active: document.getElementById("user-active").checked,
      must_change_password: document.getElementById("user-must-change").checked,
      allowed_service_ids: selectedServiceIds(),
    };
    const password = document.getElementById("user-password").value;
    if (!editingId && password) payload.password = password;
    try {
      let data;
      if (editingId) {
        data = await api(`/settings/api/users/${editingId}/`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        data = await api("/settings/api/users/", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      if (data.generated_password) {
        generatedWrap.hidden = false;
        generatedValue.textContent = data.generated_password;
      } else {
        generatedWrap.hidden = true;
        hideForm();
      }
      setError("");
      await loadAll();
      setStatus("Saved.");
    } catch (err) {
      setError(err.message);
    }
  });

  window.addEventListener("cc-wizard-section", () => {
    if (pane.classList.contains("is-active")) loadAll();
  });

  if (pane.classList.contains("is-active")) loadAll();
})();
