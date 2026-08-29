(function () {
  const form = document.getElementById("service-form");
  if (!form) return;

  const linkSelect = document.getElementById("id_linked_service");
  const combo = document.getElementById("service-combo");
  const comboInput = document.getElementById("service-combo-input");
  const comboToggle = document.getElementById("service-combo-toggle");
  const comboList = document.getElementById("service-combo-list");
  const customWrap = document.getElementById("custom-url-wrap");
  const nameInput = document.getElementById("id_name");
  const descInput = document.getElementById("id_description");
  const categoryInput = document.getElementById("id_category");
  const iconInput = document.getElementById("id_icon");
  const iconSlugInput = document.getElementById("id_icon_slug");
  const portInput = document.getElementById("id_port");
  const pathInput = document.getElementById("id_path");
  const catalogInput = document.getElementById("id_catalog_slug");
  const preset = document.getElementById("id_preset");
  const metricsSection = document.getElementById("metrics-section");
  const keyWrap = document.getElementById("widget-key-wrap");
  const addBtn = document.getElementById("add-metric-row");
  const rowsContainer = document.getElementById("metric-rows");
  const totalFormsInput = document.querySelector("input[name='metrics-TOTAL_FORMS']");
  const iconSearch = document.getElementById("icon-search");
  const iconGrid = document.getElementById("icon-grid");
  const iconCount = document.getElementById("icon-count");
  const iconPreview = document.getElementById("icon-preview");
  const iconPreviewLabel = document.getElementById("icon-preview-label");
  const esc = (value) =>
    String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");

  let comboBrowseAll = false;
  let comboActive = -1;

  let linkMeta = {};
  const metaEl = document.getElementById("link-meta");
  if (metaEl) {
    try {
      linkMeta = JSON.parse(metaEl.textContent);
    } catch {
      linkMeta = {};
    }
  }

  const linkItems = [];
  if (linkSelect) {
    Array.from(linkSelect.children).forEach((child) => {
      if (child.tagName === "OPTGROUP") {
        const group = child.label || "";
        Array.from(child.children).forEach((opt) => {
          linkItems.push({
            value: opt.value,
            label: opt.textContent.trim(),
            group,
          });
        });
      } else if (child.tagName === "OPTION") {
        linkItems.push({
          value: child.value,
          label: child.textContent.trim(),
          group: "",
        });
      }
    });
  }

  function selectedLabel() {
    const item = linkItems.find((row) => row.value === (linkSelect && linkSelect.value));
    return item ? item.label : "";
  }

  function toggleCustom() {
    if (!linkSelect || !customWrap) return;
    customWrap.hidden = linkSelect.value !== "__custom__";
  }

  function applyLink() {
    if (!linkSelect) return;
    const meta = linkMeta[linkSelect.value];
    toggleCustom();
    if (!meta || meta.custom) {
      if (catalogInput) catalogInput.value = "";
      return;
    }
    if (catalogInput) catalogInput.value = meta.slug || "";
    if (portInput && meta.port) portInput.value = meta.port;
    if (pathInput && meta.path) pathInput.value = meta.path;
    if (nameInput && meta.name) nameInput.value = meta.name;
    if (descInput && meta.description) descInput.value = meta.description;
    if (categoryInput && meta.category_id) categoryInput.value = String(meta.category_id);
    if (meta.icon && iconInput) {
      iconInput.value = meta.icon;
      const slug = (meta.icon.split("simpleicons.org/")[1] || "").split("/")[0];
      if (iconSlugInput) iconSlugInput.value = slug;
      setIconPreview(meta.icon, slug || meta.name);
    }
    if (preset && meta.preset && meta.preset !== "none") preset.value = meta.preset;
    toggleStats();
  }

  function setLinkValue(value, apply) {
    if (!linkSelect) return;
    linkSelect.value = value;
    if (comboInput) comboInput.value = selectedLabel();
    closeCombo();
    if (apply) applyLink();
  }

  function filteredItems() {
    if (comboBrowseAll) return linkItems;
    const q = comboInput ? comboInput.value.trim().toLowerCase() : "";
    if (!q) return linkItems;
    return linkItems.filter(
      (row) => row.label.toLowerCase().includes(q) || row.value.toLowerCase().includes(q)
    );
  }

  function renderComboList() {
    if (!comboList) return;
    const rows = filteredItems();
    comboActive = -1;
    if (!rows.length) {
      comboList.innerHTML = `<div class="combo__empty">No matches</div>`;
      return;
    }
    let html = "";
    let lastGroup = null;
    rows.forEach((row) => {
      if (row.group && row.group !== lastGroup) {
        html += `<div class="combo__group">${esc(row.group)}</div>`;
        lastGroup = row.group;
      }
      const selected = linkSelect && row.value === linkSelect.value ? " is-selected" : "";
      html += `<button type="button" class="combo__option${selected}" role="option" data-value="${esc(
        row.value
      )}">${esc(row.label)}</button>`;
    });
    comboList.innerHTML = html;
  }

  function openCombo(browseAll) {
    if (!comboList || !combo) return;
    comboBrowseAll = Boolean(browseAll);
    renderComboList();
    comboList.hidden = false;
    combo.classList.add("is-open");
    if (comboInput) comboInput.setAttribute("aria-expanded", "true");
  }

  function closeCombo() {
    if (!comboList || !combo) return;
    comboList.hidden = true;
    combo.classList.remove("is-open");
    comboBrowseAll = false;
    comboActive = -1;
    if (comboInput) {
      comboInput.setAttribute("aria-expanded", "false");
      comboInput.value = selectedLabel();
    }
  }

  function toggleCombo() {
    if (comboList && comboList.hidden) openCombo(true);
    else closeCombo();
  }

  function moveCombo(delta) {
    const opts = comboList ? Array.from(comboList.querySelectorAll(".combo__option")) : [];
    if (!opts.length) return;
    comboActive = (comboActive + delta + opts.length) % opts.length;
    opts.forEach((el, i) => el.classList.toggle("is-active", i === comboActive));
    opts[comboActive].scrollIntoView({ block: "nearest" });
  }

  if (comboInput) {
    comboInput.value = selectedLabel();
    comboInput.addEventListener("focus", () => {
      if (comboInput.value === selectedLabel()) openCombo(true);
      else openCombo(false);
    });
    comboInput.addEventListener("input", () => {
      openCombo(false);
    });
    comboInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeCombo();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (comboList && comboList.hidden) openCombo(true);
        else moveCombo(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        if (comboList && comboList.hidden) openCombo(true);
        else moveCombo(-1);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const opts = comboList ? comboList.querySelectorAll(".combo__option") : [];
        const active = opts[comboActive] || opts[0];
        if (active) setLinkValue(active.dataset.value, true);
      }
    });
  }
  comboToggle?.addEventListener("click", (event) => {
    event.preventDefault();
    toggleCombo();
  });
  comboList?.addEventListener("click", (event) => {
    const opt = event.target.closest(".combo__option");
    if (!opt) return;
    setLinkValue(opt.dataset.value, true);
  });
  document.addEventListener("click", (event) => {
    if (combo && !combo.contains(event.target)) closeCombo();
  });

  toggleCustom();

  function toggleStats() {
    const value = preset ? preset.value : "none";
    if (metricsSection) metricsSection.hidden = value !== "custom";
    if (keyWrap) keyWrap.hidden = value !== "pihole";
  }

  function setIconPreview(url, label) {
    if (iconPreview) iconPreview.src = url;
    if (iconPreviewLabel) iconPreviewLabel.textContent = label || "Icon";
  }

  function selectIcon(slug, url, title) {
    if (iconInput) iconInput.value = url;
    if (iconSlugInput) iconSlugInput.value = slug;
    setIconPreview(url, title || slug);
    if (iconGrid) {
      iconGrid.querySelectorAll(".icon-picker__item").forEach((btn) => {
        btn.classList.toggle("is-selected", btn.dataset.slug === slug);
      });
    }
  }

  let iconTimer = null;
  async function loadIcons(query) {
    if (!iconGrid) return;
    iconGrid.innerHTML = `<p class="settings-hint">Loading icons…</p>`;
    try {
      const resp = await fetch(`/api/icons/?q=${encodeURIComponent(query || "")}`);
      const data = await resp.json();
      const icons = data.icons || [];
      if (!icons.length) {
        if (iconCount) iconCount.textContent = "(0)";
        iconGrid.innerHTML = `<p class="settings-hint">No icons match.</p>`;
        return;
      }
      const selected = iconSlugInput ? iconSlugInput.value : "";
      if (iconCount) iconCount.textContent = `(${icons.length})`;
      iconGrid.innerHTML = icons
        .map(
          (icon) =>
            `<button type="button" class="icon-picker__item${
              icon.slug === selected ? " is-selected" : ""
            }" data-slug="${esc(icon.slug)}" data-url="${esc(icon.url)}" title="${esc(icon.title)}">` +
            `<img src="${esc(icon.url)}" alt="">` +
            `<span>${esc(icon.title)}</span>` +
            `</button>`
        )
        .join("");
    } catch (e) {
      iconGrid.innerHTML = `<p class="settings-hint">Could not load icons.</p>`;
    }
  }

  if (preset) {
    preset.addEventListener("change", toggleStats);
    toggleStats();
  }

  iconGrid?.addEventListener("click", (event) => {
    const btn = event.target.closest(".icon-picker__item");
    if (!btn) return;
    selectIcon(btn.dataset.slug, btn.dataset.url, btn.title);
  });

  iconSearch?.addEventListener("input", () => {
    clearTimeout(iconTimer);
    iconTimer = setTimeout(() => loadIcons(iconSearch.value), 180);
  });

  loadIcons("");

  if (addBtn && rowsContainer && totalFormsInput) {
    addBtn.addEventListener("click", () => {
      const index = parseInt(totalFormsInput.value, 10);
      const template = rowsContainer.querySelector(".metric-row");
      if (!template) return;
      const clone = template.cloneNode(true);
      clone.dataset.formIndex = String(index);
      clone.querySelectorAll("input, select, textarea").forEach((el) => {
        if (el.name) {
          el.name = el.name.replace(/metrics-\d+-/, `metrics-${index}-`);
          el.id = el.id.replace(/metrics-\d+-/, `metrics-${index}-`);
        }
        if (el.type === "checkbox") el.checked = false;
        else if (el.type !== "hidden") el.value = "";
      });
      rowsContainer.appendChild(clone);
      totalFormsInput.value = String(index + 1);
    });
  }
})();
