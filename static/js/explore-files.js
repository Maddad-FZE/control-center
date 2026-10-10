(function () {
  const desk = document.createElement("div");
  desk.className = "cc-explore-desk";
  desk.id = "cc-explore-desk";
  document.body.appendChild(desk);

  let zIndex = 80;
  let offset = 0;
  const explorers = new Map();

  function bringToFront(win) {
    zIndex += 1;
    win.style.zIndex = String(zIndex);
  }

  function dragWindow(win, handle) {
    let active = false;
    let startX = 0;
    let startY = 0;
    let originX = 0;
    let originY = 0;

    handle.addEventListener("mousedown", (event) => {
      if (event.button !== 0 || event.target.closest("button")) return;
      active = true;
      const rect = win.getBoundingClientRect();
      startX = event.clientX;
      startY = event.clientY;
      originX = rect.left;
      originY = rect.top;
      event.preventDefault();
    });

    window.addEventListener("mousemove", (event) => {
      if (!active) return;
      const maxLeft = Math.max(0, window.innerWidth - 80);
      const maxTop = Math.max(0, window.innerHeight - 36);
      const left = Math.min(maxLeft, Math.max(0, originX + event.clientX - startX));
      const top = Math.min(maxTop, Math.max(0, originY + event.clientY - startY));
      win.style.left = `${left}px`;
      win.style.top = `${top}px`;
    });

    window.addEventListener("mouseup", () => {
      active = false;
    });
  }

  function makeWindow(title, extraClass) {
    const win = document.createElement("section");
    win.className = `cc-win${extraClass ? ` ${extraClass}` : ""}`;
    win.setAttribute("role", "dialog");
    const bar = document.createElement("header");
    bar.className = "cc-win__bar";
    const titleEl = document.createElement("h2");
    titleEl.className = "cc-win__title";
    titleEl.textContent = title;
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cc-win__close";
    close.setAttribute("aria-label", "Close");
    close.textContent = "×";
    bar.append(titleEl, close);
    const body = document.createElement("div");
    body.className = "cc-win__body";
    win.append(bar, body);
    desk.appendChild(win);
    const slot = offset % 8;
    offset += 1;
    win.style.left = `${24 + slot * 28}px`;
    win.style.top = `${72 + slot * 24}px`;
    bringToFront(win);
    win.addEventListener("mousedown", () => bringToFront(win));
    close.addEventListener("click", () => win.remove());
    dragWindow(win, bar);
    return { win, titleEl, body };
  }

  function note(parent, message) {
    parent.replaceChildren();
    const p = document.createElement("p");
    p.className = "cc-explore-note";
    p.textContent = message;
    parent.appendChild(p);
  }

  async function readError(resp) {
    const data = await resp.json().catch(() => ({}));
    return data.error || "Could not open that file.";
  }

  function openViewer(serviceId, filePath, fileName, kind) {
    const view = makeWindow(fileName, "cc-win--viewer");
    note(view.body, "Opening…");
    const url = `/api/services/${serviceId}/files/content/?path=${encodeURIComponent(filePath)}`;
    if (kind === "image") {
      const img = document.createElement("img");
      img.className = "cc-win__img";
      img.alt = fileName;
      img.addEventListener("error", () => note(view.body, "Could not open that image."));
      img.addEventListener("load", () => {
        view.body.replaceChildren(img);
      });
      img.src = url;
      return;
    }
    fetch(url)
      .then(async (resp) => {
        if (!resp.ok) throw new Error(await readError(resp));
        return resp.json();
      })
      .then((data) => {
        const pre = document.createElement("pre");
        pre.className = "cc-win__pre";
        pre.textContent = data.text || "";
        view.body.replaceChildren(pre);
      })
      .catch((err) => note(view.body, err.message || "Could not open that file."));
  }

  function joinPath(dir, name) {
    if (!dir || dir === "/") return `/${name}`;
    return `${dir.replace(/\/$/, "")}/${name}`;
  }

  function renderList(serviceId, body, tools, data) {
    tools.replaceChildren();
    if (data.parent) {
      const up = document.createElement("button");
      up.type = "button";
      up.className = "cc-explore-chip";
      up.textContent = "Up";
      up.addEventListener("click", () => load(serviceId, data.parent, body, tools));
      tools.appendChild(up);
    }
    (data.mounts || []).forEach((mount) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "cc-explore-chip";
      chip.textContent = mount;
      chip.addEventListener("click", () => load(serviceId, mount, body, tools));
      tools.appendChild(chip);
    });
    const path = document.createElement("span");
    path.className = "cc-explore-path";
    path.textContent = data.path || "/";
    tools.appendChild(path);

    body.replaceChildren();
    const entries = data.entries || [];
    if (!entries.length) {
      note(body, "This folder is empty.");
      return;
    }
    entries.forEach((entry) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "cc-explore-row";
      row.textContent = entry.kind === "dir" ? `${entry.name}/` : entry.name;
      row.addEventListener("click", () => {
        const next = joinPath(data.path, entry.name);
        if (entry.kind === "dir") {
          load(serviceId, next, body, tools);
          return;
        }
        if (entry.preview === "text" || entry.preview === "image") {
          openViewer(serviceId, next, entry.name, entry.preview);
          return;
        }
      });
      body.appendChild(row);
    });
  }

  function load(serviceId, path, body, tools) {
    note(body, "Looking…");
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    fetch(`/api/services/${serviceId}/files/${query}`)
      .then(async (resp) => {
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || "Could not list files.");
        return data;
      })
      .then((data) => renderList(serviceId, body, tools, data))
      .catch((err) => note(body, err.message || "Could not list files."));
  }

  window.ccOpenExplore = function ccOpenExplore(opts) {
    const serviceId = String((opts && opts.serviceId) || "");
    const name = (opts && opts.name) || "Files";
    if (!serviceId) return;
    const existing = explorers.get(serviceId);
    if (existing && existing.isConnected) {
      bringToFront(existing);
      return;
    }
    const explorer = makeWindow(`Files — ${name}`, "");
    explorers.set(serviceId, explorer.win);
    const close = explorer.win.querySelector(".cc-win__close");
    close.addEventListener("click", () => explorers.delete(serviceId));
    const tools = document.createElement("div");
    tools.className = "cc-explore-tools";
    explorer.win.insertBefore(tools, explorer.body);
    load(serviceId, "", explorer.body, tools);
  };
})();
