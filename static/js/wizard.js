const GREETED_KEY = "cc-wizard-greeted";
const POS_KEY = "cc-wizard-pos";

const TIPS = {
  dashboard: [
    { text: "This strip is the live status of the lab. It updates on its own.", target: "#status-strip" },
    { text: "The sync chip shows whether checks are live, syncing, or paused, and when the last check ran.", target: "#refresh-indicator" },
    { text: "Click the up count to show only services that are responding. Click again to clear.", target: "#stat-up" },
    { text: "Click the down count to show only services that are not responding. Click again to clear.", target: "#stat-down" },
    { text: "This opens the alerts list on the right. Unacknowledged alerts also show a badge there.", target: "#stat-alerts" },
    { text: "24H is recent uptime for your cards, not the host itself.", target: "#stat-uptime-24h" },
    { text: "Host uptime is how long this machine has been running.", target: "#stat-host-uptime" },
    { text: "Type here to filter cards by name. Empty sections still stay on the page.", target: "#service-filter" },
    { text: "Add card creates a new dashboard tile. Admins only.", target: ".status-strip__add" },
    { text: "Tracked is for the services you watch most closely. Those cards are larger.", target: ".service-grid--tracked, .services-group .group-title" },
    { text: "Apps is the main catalog of everyday services.", target: ".service-grid--apps" },
    { text: "Misc is for leftovers and simple links that do not need a full card.", target: ".services-group--misc .group-title" },
    { text: "Open a card to go to that service.", target: ".service-card, .bookmark--service" },
    { text: "The menu on a card lets you edit it, change who can see it, or delete it.", target: ".service-card-menu" },
    { text: "System shows CPU, memory, and disk for this host.", target: '[data-panel-id="system"]' },
    { text: "Alerts lists recent problems. ACK ALL marks them as seen.", target: "#alerts-panel-section" },
    { text: "Use ACK ALL when you have read the current alerts.", target: "#ack-all-btn" },
    { text: "Containers lists Docker services running on this host.", target: '[data-panel-id="containers"]' },
    { text: "Uptime (24h) is a short history of which cards stayed up.", target: '[data-panel-id="uptime"]' },
  ],
  library: [
    { text: "This panel explains how install, uninstall, and addons work.", target: ".library-info" },
    { text: "The catalog is every addon and service you can put on this host.", target: "#library-grid" },
    { text: "Filter by addon or service if the list is getting long.", target: "#library-type-filter" },
    { text: "Category groups apps, like media or networking.", target: "#library-category-filter" },
    { text: "Status shows only installed apps, or only ones you have not installed yet.", target: "#library-installed-filter" },
    { text: "Install pulls the image, starts the container, and can add a dashboard card.", target: ".library-install-btn, #library-grid" },
    { text: "Uninstall stops the container. You can also delete its data volumes.", target: ".library-uninstall-btn, #library-grid" },
    { text: "Detected means the app was already running on the host. It was not installed from here.", target: ".library-badge--detected, #library-grid" },
    { text: "Add card pins an installed service onto the dashboard.", target: ".library-card .btn.secondary, .library-apps-head" },
    { text: "The GitHub button opens the project page for that app.", target: ".library-github-btn" },
    { text: "Notes on the right save as you type. Use them for ports, passwords reminders, or setup steps.", target: "#library-notes-editor" },
    { text: "These buttons format the notes: bold, lists, headings.", target: ".library-notes-toolbar" },
  ],
  settings: [
    { text: "Appearance only changes your account. Site settings apply to everyone.", target: '[data-section="appearance"]' },
    { text: "I am turned on under Site. Uncheck Call in the Wizard to hide me.", target: '[data-section="site"]' },
    { text: "If you turn on wizard notifications, I will read site messages instead of the toast popups.", target: "#id_wizard_notify, [data-section=\"site\"]" },
  ],
  settings_updates: [
    { text: "This page checks GitHub for new versions, including prereleases.", target: "#update-latest" },
    { text: "Check now looks for a newer release. Install only shows up when you are behind.", target: "#update-check-btn" },
  ],
  settings_site: [
    { text: "Title, tagline, logo, and weather are set here. So is the wizard.", target: "#id_title" },
    { text: "Services host should be the LAN address you use in the browser, not a Docker bridge IP.", target: "#id_services_host" },
    { text: "Call in the Wizard is this checkbox. The one under it controls notifications.", target: "#id_wizard_enabled" },
  ],
  service_create: [
    { text: "Fill in the details on the left, pick icons in the middle, and check the preview on the right.", target: ".card-form-opens" },
    { text: "The right pane shows how the card will look on the dashboard.", target: ".card-form-stats" },
    { text: "Save and Cancel stay in the footer so they stay easy to reach.", target: ".footer-actions" },
  ],
  service_edit: [
    { text: "You are editing an existing card. Changes show up in the preview as you go.", target: ".card-form-card" },
    { text: "Use the search box on the left to link a service.", target: "#service-combo" },
  ],
  profile: [
    { text: "This page is for your name, email, and password. Theme is under Settings, Appearance.", target: ".settings-panel, #id_email" },
  ],
  default: [
    { text: "Click me if you want a tip about this page." },
    { text: "You can drag me out of the way if I am covering something." },
  ],
};

function pageKey() {
  const page = document.body.dataset.wizardPage || "";
  const section = new URL(window.location.href).searchParams.get("section") || "";
  if (page === "settings" && section) {
    const specific = `settings_${section}`;
    if (TIPS[specific]) return specific;
  }
  if (TIPS[page]) return page;
  return "default";
}

function tipsForPage() {
  const key = pageKey();
  const extra = key === "default" ? [] : TIPS.default;
  return [...TIPS[key], ...extra].filter((tip) => !tip.target || resolveTarget(tip.target));
}

function homePos() {
  return {
    x: window.innerWidth - 148,
    y: window.innerHeight - 188,
  };
}

function savedPos() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(POS_KEY) || "null");
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
      return {
        x: Math.min(Math.max(16, saved.x), window.innerWidth - 140),
        y: Math.min(Math.max(72, saved.y), window.innerHeight - 140),
      };
    }
  } catch {
    /* use home */
  }
  return homePos();
}

let walkToken = 0;

function stopIdle(agent) {
  if (agent._idleResolve) {
    agent._idleResolve();
    agent._idlePromise = null;
    agent._idleResolve = null;
  }
  agent._queue?.clear();
  agent._animator?.exitAnimation();
}

function playAnim(agent, name) {
  if (!name || !agent.hasAnimation(name)) return;
  stopIdle(agent);
  agent._animator.showAnimation(name, () => {});
}

function isVisible(node) {
  if (!node) return false;
  const box = node.getClientRects()[0];
  return Boolean(box && box.width > 2 && box.height > 2);
}

function resolveTarget(selector) {
  if (!selector) return null;
  return selector
    .split(",")
    .map((part) => document.querySelector(part.trim()))
    .find(isVisible) || null;
}

function standBeside(node) {
  const box = node.getBoundingClientRect();
  const size = 128;
  let x = box.right + 10;
  let y = box.top + box.height / 2 - size / 2;
  if (x + size > window.innerWidth - 8) x = box.left - size - 10;
  if (x < 8) x = 8;
  if (y < 64) y = 64;
  if (y + size > window.innerHeight - 8) y = window.innerHeight - size - 8;
  return {
    x,
    y,
    pointX: box.left + box.width / 2,
    pointY: box.top + box.height / 2,
  };
}

function walkTo(agent, x, y, duration) {
  const el = agent._el;
  const dest = agent._clampXY(x, y);
  const here = el.getBoundingClientRect();
  const fromX = here.left;
  const fromY = here.top;
  const dx = dest.x - fromX;
  const dy = dest.y - fromY;
  if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return Promise.resolve();

  stopIdle(agent);
  const anim = `Move${agent._getDirection(dest.x, dest.y)}`;
  if (agent.hasAnimation(anim)) agent._animator.showAnimation(anim, () => {});

  const token = ++walkToken;
  const dist = Math.hypot(dx, dy);
  const ms = duration ?? Math.min(1600, Math.max(380, dist * 1.15));
  const started = performance.now();
  const swing = (progress) => 0.5 - Math.cos(progress * Math.PI) / 2;
  return new Promise((resolve) => {
    const step = (now) => {
      if (token !== walkToken) {
        resolve();
        return;
      }
      const progress = Math.min(1, (now - started) / ms);
      const eased = swing(progress);
      el.style.left = `${fromX + dx * eased}px`;
      el.style.top = `${fromY + dy * eased}px`;
      agent._balloon?.reposition();
      if (progress < 1) {
        requestAnimationFrame(step);
        return;
      }
      agent._animator.exitAnimation();
      agent.reposition();
      resolve();
    };
    requestAnimationFrame(step);
  });
}

function walkIn(agent) {
  const dest = savedPos();
  agent._el.style.left = `${window.innerWidth + 24}px`;
  agent._el.style.top = `${dest.y}px`;
  walkTo(agent, dest.x, dest.y, 1400);
}

function savePos(agent) {
  const box = agent._el?.getBoundingClientRect();
  if (!box) return;
  sessionStorage.setItem(POS_KEY, JSON.stringify({ x: box.left, y: box.top }));
}

function styleChrome(agent) {
  agent._el?.classList.add("cc-wizard");
  agent._balloon?._balloon?.classList.add("cc-wizard-balloon");
  agent._balloon?._tip?.classList.add("cc-wizard-balloon__tip");
  agent._balloon?._content?.classList.add("cc-wizard-balloon__text");
  if (agent._balloon) {
    agent._balloon.WORD_SPEAK_TIME = 45;
    agent._balloon.CLOSE_BALLOON_DELAY = 4500;
  }
}

function clampBalloon(balloon) {
  const el = balloon?._balloon;
  if (!el || el.style.display === "none") return;
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const margin = 8;
  let top = box.top;
  let left = box.left;
  if (top < margin) top = margin;
  if (left < margin) left = margin;
  if (top + box.height > window.innerHeight - margin) {
    top = Math.max(margin, window.innerHeight - box.height - margin);
  }
  if (left + box.width > window.innerWidth - margin) {
    left = Math.max(margin, window.innerWidth - box.width - margin);
  }
  el.style.top = `${top}px`;
  el.style.left = `${left}px`;
}

function noticeTexts() {
  return [...document.querySelectorAll("#toast-stack .toast__text")]
    .map((node) => (node.textContent || "").trim())
    .filter(Boolean);
}

function noticeLevel(index) {
  const toast = document.querySelectorAll("#toast-stack .toast")[index];
  return toast ? toast.className : "";
}

async function boot() {
  const body = document.body;
  if (body.dataset.wizard !== "1") return;

  const indexUrl = body.dataset.clippyIndex;
  const merlinUrl = body.dataset.clippyMerlin;
  if (!indexUrl || !merlinUrl) return;

  const [{ initAgent }, merlinMod] = await Promise.all([
    import(indexUrl),
    import(merlinUrl),
  ]);
  const Merlin = merlinMod.default || merlinMod.Merlin;
  const agent = await initAgent(Merlin);
  styleChrome(agent);
  agent._onQueueEmpty = () => {};
  if (agent._mouseDownHandle) {
    agent._el.removeEventListener("mousedown", agent._mouseDownHandle);
  }
  if (agent._dblClickHandle) {
    agent._el.removeEventListener("dblclick", agent._dblClickHandle);
  }
  agent.show(true);
  stopIdle(agent);
  walkIn(agent);

  let tipIndex = 0;
  let tipToken = 0;
  const speak = (text, animation) => {
    const balloon = agent._balloon;
    if (balloon._hiding) {
      window.clearTimeout(balloon._hiding);
      balloon._hiding = null;
    }
    if (balloon._loop) {
      window.clearTimeout(balloon._loop);
      balloon._loop = null;
    }
    balloon.speak(() => {}, text);
    requestAnimationFrame(() => clampBalloon(balloon));
    playAnim(agent, animation);
  };

  const offerTip = async () => {
    const tips = tipsForPage();
    const tip = tips[tipIndex % tips.length];
    tipIndex += 1;
    const myTip = ++tipToken;
    const target = resolveTarget(tip.target);
    if (target) {
      target.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
      await new Promise((resolve) => window.setTimeout(resolve, 180));
      if (myTip !== tipToken) return;
      const dest = standBeside(target);
      await walkTo(agent, dest.x, dest.y);
      if (myTip !== tipToken) return;
    }
    speak(tip.text, "Acknowledge");
  };

  const notify = (text, level = "") => {
    if (body.dataset.wizardNotify !== "1") return false;
    let animation = "Announce";
    if (level.includes("error")) animation = "Sad";
    else if (level.includes("success")) animation = "Congratulate";
    else if (level.includes("warning")) animation = "GetAttention";
    speak(text, animation);
    return true;
  };

  window.ccWizard = {
    speak: (text) => speak(text),
    notify,
    offerTip,
  };

  const notices = noticeTexts();
  const greeted = sessionStorage.getItem(GREETED_KEY) === "1";
  if (notices.length) {
    notices.forEach((text, index) => notify(text, noticeLevel(index)));
    sessionStorage.setItem(GREETED_KEY, "1");
  } else if (!greeted) {
    sessionStorage.setItem(GREETED_KEY, "1");
    speak("Hi, I am Merlin. Click me if you want a tip.", "Wave");
  }

  let press = null;
  agent._el.addEventListener("mousedown", (event) => {
    event.preventDefault();
    walkToken += 1;
    const box = agent._el.getBoundingClientRect();
    press = {
      x: event.clientX,
      y: event.clientY,
      ox: event.clientX - box.left,
      oy: event.clientY - box.top,
      dragged: false,
    };
    const onMove = (moveEvent) => {
      if (!press) return;
      const dx = moveEvent.clientX - press.x;
      const dy = moveEvent.clientY - press.y;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) press.dragged = true;
      const next = agent._clampXY(moveEvent.clientX - press.ox, moveEvent.clientY - press.oy);
      agent._el.style.left = `${next.x}px`;
      agent._el.style.top = `${next.y}px`;
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (!press) return;
      const wasDrag = press.dragged;
      press = null;
      savePos(agent);
      if (!wasDrag) offerTip();
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });

  window.addEventListener("cc-wizard-section", () => {
    tipIndex = 0;
  });
}

boot().catch((error) => {
  console.warn("Wizard failed to load.", error);
});
