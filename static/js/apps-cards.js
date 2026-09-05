(function () {
  const HOVER_MS = 1000;
  const HOLD_MS = 2000;

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function postOrder(order) {
    return fetch("/api/apps/reorder/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify({ order }),
    });
  }

  function snapshotPointer(event) {
    return {
      clientX: event.clientX,
      clientY: event.clientY,
      pointerId: event.pointerId,
      preventDefault() {},
    };
  }

  function collectOrder(grid) {
    return [...grid.querySelectorAll(".service-card-wrap[data-service-id]")].map(
      (wrap) => Number(wrap.dataset.serviceId),
    );
  }

  function initAppsGrid(grid) {
    const canReorder = grid.dataset.appsReorder === "1";
    const wraps = () => [...grid.querySelectorAll(".service-card-wrap[data-service-id]")];

    let hoverTimer = null;
    let hoverWrap = null;
    let holdTimer = null;
    let holdWrap = null;
    let holdPointerId = null;
    let lastPointer = null;
    let reorderMode = false;
    let draggingWrap = null;
    let dragOffsetX = 0;
    let dragOffsetY = 0;
    let placeholder = null;
    let originNext = null;
    let suppressClick = false;

    function isBusy() {
      return Boolean(holdWrap || holdTimer || reorderMode || grid.classList.contains("is-holding"));
    }

    function clearHover() {
      if (hoverTimer) window.clearTimeout(hoverTimer);
      hoverTimer = null;
      if (hoverWrap) {
        hoverWrap.classList.remove("is-hover-expanded");
        hoverWrap.querySelector(".service-card__expand")?.setAttribute("aria-hidden", "true");
      }
      hoverWrap = null;
    }

    function releaseHoldListeners() {
      window.removeEventListener("pointermove", onHoldMove);
      window.removeEventListener("pointerup", onHoldEnd);
      window.removeEventListener("pointercancel", onHoldEnd);
    }

    function releaseDragListeners() {
      window.removeEventListener("pointermove", onReorderMove);
      window.removeEventListener("pointerup", onReorderEnd);
      window.removeEventListener("pointercancel", onReorderEnd);
    }

    function resetDragStyles(wrap) {
      if (!wrap) return;
      wrap.classList.remove("is-dragging", "is-holding");
      wrap.style.position = "";
      wrap.style.left = "";
      wrap.style.top = "";
      wrap.style.width = "";
      wrap.style.height = "";
      wrap.style.zIndex = "";
      wrap.style.pointerEvents = "";
      wrap.style.margin = "";
    }

    function clearHold() {
      if (holdTimer) window.clearTimeout(holdTimer);
      holdTimer = null;
      if (holdWrap && holdPointerId != null) {
        try {
          holdWrap.releasePointerCapture(holdPointerId);
        } catch {
          /* ignore */
        }
      }
      if (holdWrap) holdWrap.classList.remove("is-holding");
      holdWrap = null;
      holdPointerId = null;
      lastPointer = null;
      grid.classList.remove("is-holding");
      releaseHoldListeners();
    }

    function removePlaceholder() {
      if (placeholder && placeholder.parentNode) placeholder.remove();
      placeholder = null;
    }

    function exitReorderMode(restore) {
      const wrap = draggingWrap;
      const next = originNext;
      releaseDragListeners();
      if (restore && wrap) {
        if (next && next.parentNode === grid) grid.insertBefore(wrap, next);
        else grid.appendChild(wrap);
      }
      resetDragStyles(wrap);
      removePlaceholder();
      wraps().forEach((item) => resetDragStyles(item));
      grid.classList.remove("is-reorder-mode", "is-holding");
      reorderMode = false;
      draggingWrap = null;
      originNext = null;
      dragOffsetX = 0;
      dragOffsetY = 0;
    }

    function movePlaceholder(clientX, clientY) {
      if (!placeholder || !grid.contains(placeholder)) return;
      const items = wraps().filter((item) => item !== draggingWrap);
      for (const item of items) {
        const rect = item.getBoundingClientRect();
        const before =
          clientY < rect.top + rect.height / 2 ||
          (clientY <= rect.bottom && clientX < rect.left + rect.width / 2);
        if (before) {
          if (placeholder.nextElementSibling !== item) grid.insertBefore(placeholder, item);
          return;
        }
      }
      if (grid.lastElementChild !== placeholder) grid.appendChild(placeholder);
    }

    function enterReorderMode(wrap, pointer) {
      clearHover();
      releaseHoldListeners();
      holdTimer = null;
      holdWrap = null;
      grid.classList.remove("is-holding");
      wrap.classList.remove("is-holding");

      const rect = wrap.getBoundingClientRect();
      originNext = wrap.nextSibling;
      placeholder = document.createElement("div");
      placeholder.className = "service-card-placeholder";
      placeholder.setAttribute("aria-hidden", "true");
      grid.insertBefore(placeholder, wrap);

      reorderMode = true;
      draggingWrap = wrap;
      dragOffsetX = pointer.clientX - rect.left;
      dragOffsetY = pointer.clientY - rect.top;
      grid.classList.add("is-reorder-mode");
      wrap.classList.add("is-dragging");
      wrap.style.width = `${rect.width}px`;
      wrap.style.height = `${rect.height}px`;
      wrap.style.left = `${rect.left}px`;
      wrap.style.top = `${rect.top}px`;

      window.addEventListener("pointermove", onReorderMove);
      window.addEventListener("pointerup", onReorderEnd);
      window.addEventListener("pointercancel", onReorderEnd);
      onReorderMove(pointer);
    }

    function onReorderMove(event) {
      if (!reorderMode || !draggingWrap) return;
      event.preventDefault();
      draggingWrap.style.left = `${event.clientX - dragOffsetX}px`;
      draggingWrap.style.top = `${event.clientY - dragOffsetY}px`;
      movePlaceholder(event.clientX, event.clientY);
    }

    async function onReorderEnd(event) {
      if (!reorderMode) return;
      event.preventDefault();
      suppressClick = true;
      window.setTimeout(() => {
        suppressClick = false;
      }, 300);

      const wrap = draggingWrap;
      if (wrap && placeholder) {
        grid.insertBefore(wrap, placeholder);
      }
      removePlaceholder();
      resetDragStyles(wrap);
      grid.classList.remove("is-reorder-mode", "is-holding");
      reorderMode = false;
      draggingWrap = null;
      originNext = null;
      releaseDragListeners();

      try {
        const resp = await postOrder(collectOrder(grid));
        if (!resp.ok) throw new Error("reorder failed");
      } catch (err) {
        console.warn(err);
        window.location.reload();
      }
    }

    function onPointerDown(event) {
      if (!canReorder || reorderMode) return;
      if (event.button !== 0) return;
      const wrap = event.currentTarget;
      if (event.target.closest(".service-card-menu, .service-card-dropdown")) return;

      clearHover();
      holdWrap = wrap;
      holdPointerId = event.pointerId;
      lastPointer = snapshotPointer(event);
      wrap.classList.add("is-holding");
      grid.classList.add("is-holding");

      try {
        wrap.setPointerCapture(event.pointerId);
      } catch {
        /* ignore */
      }

      holdTimer = window.setTimeout(() => {
        holdTimer = null;
        if (!holdWrap || !lastPointer) return;
        enterReorderMode(holdWrap, lastPointer);
      }, HOLD_MS);

      window.addEventListener("pointermove", onHoldMove);
      window.addEventListener("pointerup", onHoldEnd);
      window.addEventListener("pointercancel", onHoldEnd);
    }

    function onHoldMove(event) {
      if (!holdWrap || reorderMode) return;
      if (event.pointerId !== holdPointerId) return;
      lastPointer = snapshotPointer(event);
    }

    function onHoldEnd(event) {
      if (holdPointerId != null && event.pointerId !== holdPointerId) return;
      releaseHoldListeners();
      if (!reorderMode) clearHold();
    }

    function onMouseEnter(event) {
      if (isBusy()) return;
      const wrap = event.currentTarget;
      clearHover();
      hoverWrap = wrap;
      hoverTimer = window.setTimeout(() => {
        if (isBusy() || hoverWrap !== wrap) return;
        wrap.classList.add("is-hover-expanded");
        wrap.querySelector(".service-card__expand")?.setAttribute("aria-hidden", "false");
      }, HOVER_MS);
    }

    function onMouseLeave(event) {
      if (event.currentTarget === hoverWrap) clearHover();
    }

    function onClick(event) {
      if (suppressClick || reorderMode) {
        event.preventDefault();
        event.stopPropagation();
      }
    }

    wraps().forEach((wrap) => {
      const card = wrap.querySelector(".service-card--app");
      if (!card) return;
      wrap.addEventListener("mouseenter", onMouseEnter);
      wrap.addEventListener("mouseleave", onMouseLeave);
      if (canReorder) {
        wrap.addEventListener("pointerdown", onPointerDown, true);
        card.addEventListener("click", onClick, true);
        card.addEventListener("dragstart", (event) => event.preventDefault());
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (reorderMode) {
        event.preventDefault();
        exitReorderMode(true);
      } else if (isBusy()) {
        clearHold();
        clearHover();
      }
    });
  }

  document.querySelectorAll(".service-grid--apps").forEach(initAppsGrid);
})();
