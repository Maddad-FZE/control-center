(function () {
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const cookie = document.cookie.split("; ").find((row) => row.startsWith("csrftoken="));
    return cookie ? decodeURIComponent(cookie.split("=")[1]) : "";
  }

  document.querySelectorAll("[data-notes-save]").forEach((notesEditor) => {
    const url = notesEditor.dataset.notesSave;
    const notesStatus = document.getElementById(notesEditor.dataset.notesStatus || "");
    const panel = notesEditor.closest("[data-notes-panel]") || notesEditor.parentElement;
    let notesTimer = null;
    let notesInFlight = false;
    let notesQueued = false;
    let lastSaved = notesEditor.innerHTML;

    function setNotesStatus(text) {
      if (notesStatus) notesStatus.textContent = text;
    }

    function notesBody() {
      return notesEditor.innerHTML;
    }

    async function saveNotes(opts) {
      const immediate = opts && opts.immediate;
      const body = notesBody();
      if (body === lastSaved) {
        if (!notesInFlight) setNotesStatus(lastSaved ? "Saved" : "");
        return;
      }
      if (notesInFlight) {
        notesQueued = true;
        return;
      }
      notesInFlight = true;
      setNotesStatus("Saving…");
      try {
        const resp = await fetch(url, {
          method: "POST",
          headers: {
            "X-CSRFToken": getCsrfToken(),
            "Content-Type": "application/json",
          },
          keepalive: !!immediate,
          body: JSON.stringify({ body }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || "Save failed");
        lastSaved = body;
        setNotesStatus("Saved");
      } catch (e) {
        console.warn("notes save failed", e);
        setNotesStatus("Save failed");
      } finally {
        notesInFlight = false;
        if (notesQueued) {
          notesQueued = false;
          saveNotes();
        }
      }
    }

    function scheduleNotesSave() {
      setNotesStatus("Saving…");
      clearTimeout(notesTimer);
      notesTimer = setTimeout(() => saveNotes(), 180);
    }

    panel?.querySelectorAll(".library-notes-fmt, .notes-fmt").forEach((btn) => {
      btn.addEventListener("mousedown", (event) => event.preventDefault());
      btn.addEventListener("click", () => {
        notesEditor.focus();
        document.execCommand(btn.dataset.cmd, false, btn.dataset.value || null);
        scheduleNotesSave();
      });
    });

    ["input", "paste", "keyup"].forEach((eventName) => {
      notesEditor.addEventListener(eventName, scheduleNotesSave);
    });
    notesEditor.addEventListener("blur", () => saveNotes({ immediate: true }));
    window.addEventListener("pagehide", () => saveNotes({ immediate: true }));
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") saveNotes({ immediate: true });
    });
  });
})();
