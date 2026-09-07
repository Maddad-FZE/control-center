(function () {
  document.querySelectorAll("[data-image-upload]").forEach((root) => {
    const input = root.querySelector(".image-upload__input");
    const preview = root.querySelector(".image-upload__preview");
    const empty = root.querySelector(".image-upload__empty");
    const editBtn = root.querySelector("[data-image-edit]");
    const clearBtn = root.querySelector("[data-image-clear]");
    const clearBox = root.querySelector(".image-upload__clear");
    const originalSrc = preview?.getAttribute("src") || "";
    let objectUrl = "";

    function revoke() {
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = "";
      }
    }

    function show(url) {
      if (!preview || !empty) return;
      if (url) {
        preview.src = url;
        preview.hidden = false;
        empty.hidden = true;
        root.classList.add("is-filled");
        if (clearBtn) clearBtn.hidden = false;
      } else {
        preview.removeAttribute("src");
        preview.hidden = true;
        empty.hidden = false;
        root.classList.remove("is-filled");
        if (clearBtn) clearBtn.hidden = true;
      }
    }

    editBtn?.addEventListener("click", () => input?.click());

    input?.addEventListener("change", () => {
      const file = input.files && input.files[0];
      if (!file) return;
      revoke();
      if (clearBox) clearBox.checked = false;
      const reader = new FileReader();
      reader.onload = () => show(reader.result);
      reader.readAsDataURL(file);
    });

    clearBtn?.addEventListener("click", () => {
      const pending = Boolean(input?.files && input.files.length);
      if (pending) {
        input.value = "";
        revoke();
        if (clearBox) clearBox.checked = false;
        show(originalSrc);
        return;
      }
      if (clearBox) clearBox.checked = true;
      input.value = "";
      revoke();
      show("");
    });
  });
})();
