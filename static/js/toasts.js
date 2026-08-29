(function () {
  const HOLD_MS = 5000;
  const stack = document.getElementById("toast-stack");
  if (!stack) return;

  stack.querySelectorAll(".toast").forEach((toast) => {
    let remaining = HOLD_MS;
    let started = 0;
    let timer = null;
    let pinned = false;

    function clearTimer() {
      if (!timer) return;
      remaining -= Date.now() - started;
      clearTimeout(timer);
      timer = null;
    }

    function startTimer() {
      if (pinned || remaining <= 0) {
        if (!pinned && remaining <= 0) dismiss();
        return;
      }
      started = Date.now();
      timer = setTimeout(dismiss, remaining);
    }

    function dismiss() {
      clearTimer();
      if (toast.classList.contains("is-leaving")) return;
      toast.classList.add("is-leaving");
      const remove = () => toast.remove();
      toast.addEventListener("transitionend", remove, { once: true });
      setTimeout(remove, 400);
    }

    function hold() {
      toast.classList.remove("is-leaving");
      clearTimer();
    }

    toast.addEventListener("mouseenter", hold);
    toast.addEventListener("mouseleave", () => {
      if (!pinned) startTimer();
    });
    toast.addEventListener("click", (event) => {
      if (event.target.closest(".toast__close")) return;
      pinned = true;
      toast.classList.add("is-pinned");
      hold();
    });
    toast.querySelector(".toast__close")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      pinned = false;
      remaining = 0;
      dismiss();
    });

    startTimer();
  });
})();
