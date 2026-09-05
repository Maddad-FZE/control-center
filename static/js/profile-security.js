(function () {
  const pane = document.getElementById("profile-security");
  if (!pane) return;

  const startBtn = document.getElementById("twofa-start-btn");
  const enroll = document.getElementById("twofa-enroll");
  const qr = document.getElementById("twofa-qr");
  const secretEl = document.getElementById("twofa-secret");
  const confirmBtn = document.getElementById("twofa-confirm-btn");
  const codeInput = document.getElementById("twofa-confirm-code");
  const recoveryWrap = document.getElementById("twofa-recovery");
  const recoveryList = document.getElementById("twofa-recovery-list");
  const statusEl = document.getElementById("twofa-status");
  const setupWrap = document.getElementById("twofa-setup");
  const disableWrap = document.getElementById("twofa-disable-wrap");

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }

  async function api(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "Request failed");
    return data;
  }

  startBtn?.addEventListener("click", async () => {
    try {
      const data = await api("/profile/api/2fa/start/");
      if (qr) qr.src = data.qr;
      if (secretEl) secretEl.textContent = data.secret;
      enroll.hidden = false;
    } catch (err) {
      statusEl.textContent = err.message;
    }
  });

  confirmBtn?.addEventListener("click", async () => {
    try {
      const data = await api("/profile/api/2fa/confirm/", { code: codeInput.value });
      recoveryWrap.hidden = false;
      recoveryList.textContent = (data.recovery_codes || []).join("\n");
      statusEl.textContent = "2FA is on. Save the recovery codes.";
      setupWrap.querySelector("#twofa-start-btn").hidden = true;
      enroll.hidden = true;
      disableWrap.hidden = false;
    } catch (err) {
      statusEl.textContent = err.message;
    }
  });

  document.getElementById("twofa-disable-btn")?.addEventListener("click", async () => {
    try {
      await api("/profile/api/2fa/disable/", {
        password: document.getElementById("twofa-disable-password").value,
        code: document.getElementById("twofa-disable-code").value,
      });
      statusEl.textContent = "2FA is off.";
      disableWrap.hidden = true;
      setupWrap.hidden = false;
      startBtn.hidden = false;
      enroll.hidden = true;
      recoveryWrap.hidden = true;
    } catch (err) {
      statusEl.textContent = err.message;
    }
  });
})();
