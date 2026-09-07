(function () {
  const root = document.createElement("div");
  root.className = "library-modal cc-dialog";
  root.hidden = true;
  root.innerHTML = `
    <div class="library-modal__backdrop" data-cc-dialog-dismiss></div>
    <div class="library-modal__panel" role="dialog" aria-modal="true" aria-labelledby="cc-dialog-title">
      <h2 class="library-modal__title" id="cc-dialog-title"></h2>
      <p class="settings-hint" id="cc-dialog-body"></p>
      <p class="cc-dialog__error" id="cc-dialog-error" hidden></p>
      <div class="form-group" id="cc-dialog-field-wrap" hidden>
        <label class="cc-dialog__label" id="cc-dialog-field-label" for="cc-dialog-field"></label>
        <input id="cc-dialog-field" class="cc-dialog__input" autocomplete="off" spellcheck="false">
      </div>
      <div class="library-modal__actions">
        <button type="button" class="btn secondary" id="cc-dialog-cancel">Cancel</button>
        <button type="button" class="btn" id="cc-dialog-ok">OK</button>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  const titleEl = root.querySelector("#cc-dialog-title");
  const bodyEl = root.querySelector("#cc-dialog-body");
  const errorEl = root.querySelector("#cc-dialog-error");
  const fieldWrap = root.querySelector("#cc-dialog-field-wrap");
  const fieldLabel = root.querySelector("#cc-dialog-field-label");
  const field = root.querySelector("#cc-dialog-field");
  const cancelBtn = root.querySelector("#cc-dialog-cancel");
  const okBtn = root.querySelector("#cc-dialog-ok");
  let active = null;
  let chain = Promise.resolve();

  function setError(text) {
    if (!text) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = text;
  }

  function close(result) {
    if (!active) return;
    const resolve = active.resolve;
    active = null;
    root.hidden = true;
    field.type = "text";
    field.value = "";
    field.autocomplete = "off";
    setError("");
    resolve(result);
  }

  function onKey(event) {
    if (!active || root.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      close(active.mode === "alert" ? true : active.mode === "prompt" ? null : false);
    }
    if (event.key === "Enter" && event.target === field) {
      event.preventDefault();
      okBtn.click();
    }
  }

  document.addEventListener("keydown", onKey, true);

  root.querySelector("[data-cc-dialog-dismiss]").addEventListener("click", () => {
    if (!active) return;
    close(active.mode === "alert" ? true : active.mode === "prompt" ? null : false);
  });

  cancelBtn.addEventListener("click", () => {
    if (!active) return;
    close(active.mode === "prompt" ? null : false);
  });

  okBtn.addEventListener("click", () => {
    if (!active) return;
    if (active.mode === "prompt") {
      const value = field.value;
      if (active.expected && value !== active.expected) {
        setError(`Type ${active.expected} to confirm.`);
        field.focus();
        return;
      }
      close(value);
      return;
    }
    close(true);
  });

  function open(mode, message, options) {
    const opts = options || {};
    return new Promise((resolve) => {
      active = { mode, resolve, expected: opts.expected || "" };
      titleEl.textContent = opts.title || (mode === "alert" ? "Notice" : mode === "prompt" ? "Confirm" : "Confirm");
      bodyEl.textContent = message || "";
      bodyEl.hidden = !message;
      cancelBtn.hidden = mode === "alert";
      cancelBtn.textContent = opts.cancelLabel || "Cancel";
      okBtn.textContent = opts.confirmLabel || (mode === "alert" ? "OK" : mode === "prompt" ? "Continue" : "OK");
      okBtn.className = opts.danger ? "btn danger" : "btn";
      if (mode === "prompt") {
        fieldWrap.hidden = false;
        fieldLabel.textContent = opts.fieldLabel || "";
        fieldLabel.hidden = !opts.fieldLabel;
        field.type = opts.inputType || "text";
        field.placeholder = opts.placeholder || "";
        field.autocomplete = opts.autocomplete || "off";
        field.value = opts.value || "";
      } else {
        fieldWrap.hidden = true;
      }
      setError("");
      root.hidden = false;
      requestAnimationFrame(() => {
        if (mode === "prompt") field.focus();
        else okBtn.focus();
      });
    });
  }

  function enqueue(mode, message, options) {
    const run = () => open(mode, message, options);
    const next = chain.then(run, run);
    chain = next.catch(() => {});
    return next;
  }

  window.ccDialog = {
    alert(message, options) {
      return enqueue("alert", message, options);
    },
    confirm(message, options) {
      return enqueue("confirm", message, options);
    },
    prompt(message, options) {
      return enqueue("prompt", message, options);
    },
  };
})();
