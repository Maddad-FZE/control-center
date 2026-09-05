(function () {
  const helpTips = [];

  function tipLayer() {
    let layer = document.getElementById("help-tip-layer");
    if (!layer) {
      layer = document.createElement("div");
      layer.id = "help-tip-layer";
      document.body.appendChild(layer);
    }
    return layer;
  }

  function parkBubble(wrap) {
    const bubble = wrap._bubble;
    if (!bubble) return;
    bubble.classList.remove("is-shown");
    bubble.style.left = "";
    bubble.style.top = "";
    if (bubble.parentElement !== wrap) wrap.appendChild(bubble);
  }

  function placeBubble(wrap) {
    const btn = wrap._btn;
    const bubble = wrap._bubble;
    if (!btn || !bubble) return;
    const layer = tipLayer();
    if (bubble.parentElement !== layer) layer.appendChild(bubble);
    bubble.classList.add("is-shown");
    const gap = 6;
    const pad = 8;
    const r = btn.getBoundingClientRect();
    const bw = bubble.offsetWidth;
    const bh = bubble.offsetHeight;
    let left = r.left;
    let top = r.top - gap - bh;
    if (top < pad) top = r.bottom + gap;
    if (left + bw > window.innerWidth - pad) left = window.innerWidth - pad - bw;
    if (left < pad) left = pad;
    if (top + bh > window.innerHeight - pad) top = Math.max(pad, window.innerHeight - pad - bh);
    bubble.style.left = `${Math.round(left)}px`;
    bubble.style.top = `${Math.round(top)}px`;
  }

  function hideTip(wrap) {
    wrap._pinned = false;
    wrap.classList.remove("is-open");
    wrap._btn?.setAttribute("aria-expanded", "false");
    parkBubble(wrap);
  }

  function closeHelpTips(except) {
    helpTips.forEach((wrap) => {
      if (wrap === except) return;
      hideTip(wrap);
    });
  }

  document.querySelectorAll(".help-tip").forEach((btn) => {
    const wrap = btn.closest(".help-tip-wrap");
    const bubble = wrap?.querySelector(".help-tip__bubble");
    if (!wrap || !bubble) return;
    wrap._btn = btn;
    wrap._bubble = bubble;
    helpTips.push(wrap);

    const show = () => {
      closeHelpTips(wrap);
      wrap.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      placeBubble(wrap);
    };

    wrap.addEventListener("mouseenter", show);
    wrap.addEventListener("mouseleave", () => {
      if (wrap._pinned || document.activeElement === btn) return;
      hideTip(wrap);
    });
    wrap.addEventListener("focusin", show);
    wrap.addEventListener("focusout", (e) => {
      if (wrap._pinned || wrap.contains(e.relatedTarget)) return;
      hideTip(wrap);
    });
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (wrap._pinned) {
        hideTip(wrap);
        return;
      }
      wrap._pinned = true;
      show();
    });
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".help-tip-wrap")) closeHelpTips();
  });

  document.addEventListener(
    "scroll",
    () => {
      helpTips.forEach((wrap) => {
        if (wrap.classList.contains("is-open")) placeBubble(wrap);
      });
    },
    true
  );

  window.addEventListener("resize", () => {
    helpTips.forEach((wrap) => {
      if (wrap.classList.contains("is-open")) placeBubble(wrap);
    });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const focused = document.activeElement?.closest?.(".help-tip-wrap");
    closeHelpTips();
    focused?.querySelector(".help-tip")?.blur();
  });
})();
