(function () {
  const modal = document.getElementById("library-repos-modal");
  const openBtn = document.getElementById("library-repos-edit-btn");
  if (!modal || !openBtn) return;

  const tbody = document.getElementById("library-repos-tbody");
  const form = document.getElementById("library-repos-form");
  const formTitle = document.getElementById("library-repos-form-title");
  const statusEl = document.getElementById("library-repos-status");
  const formError = document.getElementById("library-repos-form-error");
  const listWrap = document.querySelector(".library-repos-list-wrap");
  const closeActions = document.getElementById("library-repos-close-actions");
  const slugInput = document.getElementById("repos-slug");
  let items = [];
  let editingSlug = "";

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const cookie = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || "";
  }

  function field(id) {
    return document.getElementById(id);
  }

  function showForm(isNew, item) {
    if (!form || !listWrap || !closeActions) return;
    form.hidden = false;
    listWrap.hidden = true;
    closeActions.hidden = true;
    formTitle.textContent = isNew ? "Add app" : `Edit ${item?.name || ""}`;
    slugInput.readOnly = !isNew;
    slugInput.value = item?.slug || "";
    field("repos-name").value = item?.name || "";
    field("repos-category").value = item?.category || "";
    field("repos-tagline").value = item?.tagline || "";
    field("repos-description").value = item?.description || "";
    field("repos-repo").value = item?.repo || "";
    field("repos-icon").value = item?.icon || "";
    field("repos-default-port").value = item?.default_port || 8080;
    field("repos-path").value = item?.path || "/";
    field("repos-compose").value = item?.compose || "";
    if (formError) formError.hidden = true;
    editingSlug = isNew ? "" : item?.slug || "";
  }

  function hideForm() {
    if (!form || !listWrap || !closeActions) return;
    form.hidden = true;
    listWrap.hidden = false;
    closeActions.hidden = false;
    editingSlug = "";
  }

  function renderRows() {
    if (!tbody) return;
    tbody.innerHTML = "";
    items.forEach((item) => {
      const tr = document.createElement("tr");
      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "btn secondary library-repos-delete";
      deleteBtn.textContent = "Delete";
      deleteBtn.disabled = !item.can_delete;
      if (!item.can_delete && item.delete_block_reason) {
        deleteBtn.title = item.delete_block_reason;
      }
      deleteBtn.addEventListener("click", () => removeItem(item.slug));
      tr.innerHTML = `
        <td>${escapeHtml(item.name)}</td>
        <td><code>${escapeHtml(item.slug)}</code></td>
        <td>${escapeHtml(item.category)}</td>
        <td>${item.default_port}</td>
        <td class="library-repos-table__actions"></td>
      `;
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "btn secondary";
      editBtn.textContent = "Edit";
      editBtn.addEventListener("click", () => showForm(false, item));
      const actions = tr.querySelector(".library-repos-table__actions");
      actions.appendChild(editBtn);
      actions.appendChild(deleteBtn);
      tbody.appendChild(tr);
    });
  }

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function loadItems() {
    setStatus("Loading…");
    const resp = await fetch("/library/api/catalog/");
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Could not load catalog");
    items = data.items || [];
    renderRows();
    setStatus(`${items.length} entries`);
  }

  async function removeItem(slug) {
    if (!window.confirm(`Remove “${slug}” from the catalog?`)) return;
    setStatus("Deleting…");
    const resp = await fetch(`/library/api/catalog/${encodeURIComponent(slug)}/delete/`, {
      method: "POST",
      headers: { "X-CSRFToken": getCsrfToken() },
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Delete failed");
    await loadItems();
  }

  function formPayload() {
    return {
      slug: slugInput.value.trim().toLowerCase(),
      name: field("repos-name").value.trim(),
      category: field("repos-category").value.trim(),
      tagline: field("repos-tagline").value.trim(),
      description: field("repos-description").value.trim(),
      repo: field("repos-repo").value.trim(),
      icon: field("repos-icon").value.trim(),
      default_port: Number(field("repos-default-port").value) || 8080,
      path: field("repos-path").value.trim() || "/",
      compose: field("repos-compose").value.trim(),
    };
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (formError) formError.hidden = true;
    const payload = formPayload();
    const url = editingSlug
      ? `/library/api/catalog/${encodeURIComponent(editingSlug)}/`
      : "/library/api/catalog/create/";
    setStatus("Saving…");
    try {
      const resp = await fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || "Save failed");
      hideForm();
      await loadItems();
    } catch (err) {
      if (formError) {
        formError.textContent = err.message || "Save failed";
        formError.hidden = false;
      }
      setStatus("");
    }
  });

  document.getElementById("library-repos-add-btn")?.addEventListener("click", () => {
    showForm(true, null);
  });

  modal.querySelectorAll("[data-repos-close]").forEach((el) => {
    el.addEventListener("click", () => {
      modal.hidden = true;
      hideForm();
    });
  });

  form?.querySelectorAll("[data-repos-cancel]").forEach((el) => {
    el.addEventListener("click", hideForm);
  });

  openBtn.addEventListener("click", async () => {
    modal.hidden = false;
    hideForm();
    try {
      await loadItems();
    } catch (err) {
      setStatus(err.message || "Load failed");
    }
  });
})();
