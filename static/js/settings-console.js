(function () {
  const pane = document.getElementById("settings-console");
  if (!pane) return;

  const connectBtn = document.getElementById("console-connect-btn");
  const statusEl = document.getElementById("console-status");
  const terminalWrap = document.getElementById("console-terminal");
  const tabs = pane.querySelectorAll(".settings-console-tab");

  let target = "app";
  let term = null;
  let fitAddon = null;
  let socket = null;
  let resizeObserver = null;

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  function setStatus(text) {
    if (statusEl) {
      statusEl.hidden = Boolean(term);
      statusEl.textContent = text || "";
    }
  }

  function paneActive() {
    return pane.classList.contains("is-active");
  }

  function selectTarget(next) {
    target = next;
    tabs.forEach((tab) => {
      const active = tab.dataset.consoleTarget === next;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      if (socket) return;
      selectTarget(tab.dataset.consoleTarget || "app");
    });
  });

  function teardown() {
    if (socket) {
      try {
        socket.close();
      } catch {
        /* ignore */
      }
    }
    socket = null;
    if (resizeObserver) resizeObserver.disconnect();
    resizeObserver = null;
    if (term) {
      term.dispose();
      term = null;
      fitAddon = null;
    }
    if (terminalWrap) {
      terminalWrap.innerHTML = "";
      terminalWrap.hidden = true;
    }
    if (connectBtn) connectBtn.disabled = false;
  }

  function fitTerminal() {
    if (!term || !fitAddon) return;
    requestAnimationFrame(() => {
      fitAddon.fit();
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({
            type: "resize",
            rows: term.rows,
            cols: term.cols,
          })
        );
      }
    });
  }

  function initTerminal() {
    if (!window.Terminal || !window.FitAddon) {
      setStatus("Terminal library failed to load.");
      return null;
    }
    terminalWrap.hidden = false;
    term = new window.Terminal({
      cursorBlink: true,
      fontFamily: '"IBM Plex Mono", monospace',
      fontSize: 13,
      theme: {
        background: "#1a120c",
        foreground: "#f3e6c8",
        cursor: "#e87722",
      },
    });
    fitAddon = new window.FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalWrap);
    fitTerminal();
    term.onData((data) => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(data);
      }
    });
    resizeObserver = new ResizeObserver(() => fitTerminal());
    const consoleBody = pane.querySelector(".settings-console-body");
    resizeObserver.observe(consoleBody || terminalWrap);
    resizeObserver.observe(terminalWrap);
    return term;
  }

  async function connect() {
    if (socket) return;
    const password = window.prompt("Confirm your password to open the console:");
    if (!password) return;
    let totp = "";
    if (pane.dataset.twofa === "1") {
      totp = window.prompt("Authenticator code:") || "";
      if (!totp) return;
    }
    connectBtn.disabled = true;
    setStatus("Requesting session…");
    try {
      const resp = await fetch("/settings/api/console/ticket/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({ target, password, totp }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        setStatus(data.error || "Could not open console.");
        connectBtn.disabled = false;
        return;
      }
      if (!initTerminal()) {
        connectBtn.disabled = false;
        return;
      }
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(
        `${proto}//${window.location.host}/ws/console/?ticket=${encodeURIComponent(data.ticket)}`
      );
      socket.binaryType = "arraybuffer";
      socket.addEventListener("open", () => {
        setStatus("");
        fitTerminal();
      });
      socket.addEventListener("message", (event) => {
        if (!term) return;
        if (typeof event.data === "string") {
          term.write(event.data);
        } else {
          term.write(new Uint8Array(event.data));
        }
      });
      socket.addEventListener("close", () => {
        term?.writeln("\r\n[Session ended]");
        connectBtn.disabled = false;
        socket = null;
        setStatus("Session ended. Connect again to start a new shell.");
      });
      socket.addEventListener("error", () => {
        setStatus("Console connection failed.");
        connectBtn.disabled = false;
      });
    } catch (err) {
      setStatus("Console connection failed.");
      connectBtn.disabled = false;
    }
  }

  connectBtn?.addEventListener("click", connect);

  window.addEventListener("cc-wizard-section", () => {
    if (!paneActive()) {
      teardown();
      return;
    }
    if (term) fitTerminal();
  });

  window.addEventListener("beforeunload", teardown);
})();
