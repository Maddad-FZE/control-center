import { matchHelpIntent } from "./wizard-help.js";

const GREETED_KEY = "cc-wizard-greeted";
const POS_KEY = "cc-wizard-pos";
const MUTE_KEY = "cc-wizard-muted";
const DOCK_KEY = "cc-wizard-docked";

window.ccWizardMuted = localStorage.getItem(MUTE_KEY) === "1";
let merlinDocked = false;

function prefersDocked() {
  try {
    const raw = localStorage.getItem(DOCK_KEY);
    if (raw === null) return true;
    return raw === "1";
  } catch {
    return true;
  }
}

function setDockPref(value) {
  try {
    localStorage.setItem(DOCK_KEY, value ? "1" : "0");
  } catch {
    /* ignore quota */
  }
}

function showDockSection() {
  const section = document.getElementById("merlin-dock-section");
  const wrap = document.getElementById("dashboard-merlin");
  if (section) section.hidden = false;
  if (wrap) wrap.hidden = false;
}

function hideDockSection() {
  const section = document.getElementById("merlin-dock-section");
  const wrap = document.getElementById("dashboard-merlin");
  if (section) section.hidden = true;
  if (wrap) wrap.hidden = true;
}

const TIPS = {
  dashboard: [
    { text: "This strip is the live status of the lab. It updates on its own.", target: "#status-strip" },
    { text: "The sync chip shows whether checks are live, syncing, or paused, and when the last check ran.", target: "#refresh-indicator" },
    { text: "Click the up count to show only services that are responding. Click again to clear.", target: "#stat-up" },
    { text: "Click the down count to show only services that are not responding. Click again to clear.", target: "#stat-down" },
    { text: "The bell next to your name holds alerts. Unacknowledged ones show a badge.", target: "#alerts-bell" },
    { text: "24H is recent uptime for your cards, not the host itself.", target: "#stat-uptime-24h" },
    { text: "Host uptime is how long this machine has been running.", target: "#stat-host-uptime" },
    { text: "Type here to filter cards by name. Empty sections still stay on the page.", target: "#service-filter" },
    { text: "Add card creates a new dashboard tile. Admins only.", target: ".status-strip__add" },
    { text: "Tracked is for the services you watch most closely. Those cards are larger.", target: ".service-grid--tracked, .services-group .group-title" },
    { text: "Apps cards are compact. Hover for details. Admins press and hold for 2 seconds to reorder.", target: ".service-grid--apps" },
    { text: "Misc is for leftovers and simple links that do not need a full card.", target: ".services-group--misc .group-title" },
    { text: "Stats is host load, USB, containers, and Monitor.", target: ".services-group--stats .group-title" },
    { text: "Open a card to go to that service.", target: ".service-card, .bookmark--service" },
    { text: "The menu on a card lets you edit it, change who can see it, or delete it.", target: ".service-card-menu" },
    { text: "System shows CPU, memory, and disk for this host. Restart Server reboots the machine.", target: '[data-panel-id="system"]' },
    { text: "USB lists devices plugged into this host. Storage sticks can be unmounted from here.", target: '[data-panel-id="usb"]' },
    { text: "Alerts are in the bell next to your name. ACK ALL marks them as seen.", target: "#alerts-bell" },
    { text: "Use ACK ALL when you have read the current alerts.", target: "#ack-all-btn" },
    { text: "Containers lists Docker services. Restart a container from the row if you are an admin.", target: '[data-panel-id="containers"]' },
    { text: "Monitor is a short history of which cards stayed up.", target: '[data-panel-id="uptime"]' },
  ],
  library: [
    { text: "This panel explains how install, uninstall, and addons work.", target: ".library-info" },
    { text: "The catalog is every addon and service you can put on this host.", target: "#library-grid" },
    { text: "Type here to search the catalog by name, description, or slug.", target: "#library-search" },
    { text: "Filter by addon or service if the list is getting long.", target: "#library-type-filter" },
    { text: "Category groups apps, like media or networking.", target: "#library-category-filter" },
    { text: "Status shows only installed apps, or only ones you have not installed yet.", target: "#library-installed-filter" },
    { text: "Install pulls the image, starts the container, and can add a dashboard card.", target: ".library-install-btn, #library-grid" },
    { text: "Uninstall stops the container. You can also delete its data volumes.", target: ".library-uninstall-btn, #library-grid" },
    { text: "Restart reloads an installed container without uninstalling it.", target: ".library-restart-btn, #library-grid" },
    { text: "Detected means the app was already running on the host. It was not installed from here.", target: ".library-badge--detected, #library-grid" },
    { text: "Add card pins an installed service onto the dashboard.", target: ".library-add-card-btn, .library-apps-head" },
    { text: "The GitHub button opens the project page for that app.", target: ".library-github-btn" },
    { text: "Notes on the right save as you type. Use them for ports, passwords reminders, or setup steps.", target: "#library-notes-editor" },
    { text: "These buttons format the notes: bold, lists, headings.", target: ".library-notes-toolbar" },
  ],
  settings: [
    { text: "Categories on the left pick which settings you are editing.", target: ".settings-group--nav" },
    { text: "Information explains the category you selected.", target: ".settings-group--info" },
    { text: "Section 4 Notes save as you type.", target: "#settings-notes-editor" },
    { text: "Merlin lives in section 2 under Categories. He cannot be dragged there.", target: "#settings-merlin-dock" },
  ],
  settings_updates: [
    { text: "This page checks GitHub for new versions, including prereleases.", target: "#update-latest" },
    { text: "Check now looks for a newer release. Install downloads it from GitHub — no git checkout needed.", target: "#update-check-btn" },
  ],
  settings_site: [
    { text: "Title, tagline, logo, and weather are set here.", target: "#id_title" },
    { text: "Services host should be the LAN address you use in the browser, not a Docker bridge IP.", target: "#id_services_host" },
    { text: "Monitor login is generated for Uptime Kuma. Show or copy it here if you already created your own admin.", target: "#id_kuma_username" },
    { text: "CRT scanlines are this checkbox. They apply to everyone.", target: "#id_crt_enabled" },
    { text: "Call in the Wizard turns me on for signed-in pages. The nested box is notifications.", target: "#id_wizard_enabled" },
  ],
  settings_users: [
    { text: "Add user creates an account. Members only see the cards you tick under Allowed services.", target: "#users-add-btn" },
    { text: "Admin, Member, and Viewer are the three roles. Viewer cannot acknowledge alerts.", target: "#settings-users" },
  ],
  settings_tunnel: [
    { text: "Cloudflare Tunnel is a Library install. If it is missing, use the button to go install it.", target: "#tunnel-install-cta" },
    { text: "Tunnel links Cloudflare with an API token. Create one from the button, paste it, click Connect, then Link account. Nothing goes online until you publish a service.", target: "#tunnel-installed-settings" },
    { text: "Control Center cannot be published. It stays on the LAN.", target: "#settings-tunnel" },
  ],
  settings_logs: [
    { text: "Pick a log source, filter by keyword, and turn on Live to tail new lines.", target: "#settings-logs" },
    { text: "Download saves the current tail as a text file.", target: "#logs-download-btn" },
  ],
  settings_console: [
    { text: "App opens a shell inside Control Center. Host opens on the machine running it.", target: "#settings-console" },
    { text: "You must confirm your password before a session starts.", target: "#console-connect-btn" },
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
    { text: "Categories on the left pick Account, Security, or Vault.", target: ".settings-group--nav" },
    { text: "Information explains the category you selected.", target: ".settings-group--info" },
    { text: "Identity is your username, role, and last login.", target: ".settings-group--identity" },
    { text: "Merlin lives in section 2 under Categories. He cannot be dragged there.", target: "#settings-merlin-dock" },
  ],
  profile_account: [
    { text: "Save your email and name here. Username is set by an admin.", target: "#profile-account" },
  ],
  profile_security: [
    { text: "Change your password in this panel. An admin can require a new password on next login.", target: "#profile-security" },
    { text: "Two-factor adds a six-digit code after sign-in. Save recovery codes when you turn it on.", target: "#twofa-start-btn, #twofa-disable-btn" },
  ],
  profile_vault: [
    { text: "Store passwords for other services here. They are encrypted for your account only.", target: "#vault-add-btn" },
    { text: "Reveal asks for your Control Center password before showing a secret.", target: "#vault-table, #vault-reveal" },
  ],
  default: [
    { text: "Click me once for my menu. Double-click me if you want a tip about this page." },
    { text: "You can drag me out of the way if I am covering something." },
  ],
};

function pageKey() {
  const page = document.body.dataset.wizardPage || "";
  const section = new URL(window.location.href).searchParams.get("section") || "";
  if ((page === "settings" || page === "profile") && section) {
    const specific = `${page}_${section}`;
    if (TIPS[specific]) return specific;
  }
  if (TIPS[page]) return page;
  return "default";
}

function tipsForPage() {
  const key = pageKey();
  const extra = key === "default" ? [] : TIPS.default;
  const tips = [...TIPS[key], ...extra].filter((tip) => !tip.target || resolveTarget(tip.target));
  return tips.filter((tip) => {
    const text = tip.text || "";
    if (merlinDocked && /drag me/i.test(text)) return false;
    if (!merlinDocked && /cannot be dragged/i.test(text)) return false;
    return true;
  });
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
let merlinMoving = false;
let merlinMoveHook = null;
let animGen = 0;

function bumpAnim() {
  animGen += 1;
  return animGen;
}

function hasUnackedAlerts() {
  const badge = document.getElementById("alerts-badge");
  if (!badge || badge.hidden) return false;
  const n = Number.parseInt(String(badge.textContent || "").trim(), 10);
  if (Number.isFinite(n)) return n > 0;
  return Boolean(String(badge.textContent || "").trim());
}

function pick(names) {
  return names[Math.floor(Math.random() * names.length)];
}

function gestureName(agent, pointX, pointY) {
  let dir = agent._getDirection(pointX, pointY);
  if (dir === "Top") dir = "Up";
  const named = `Gesture${dir}`;
  return agent.hasAnimation(named) ? named : "GestureUp";
}

const SAFE_ANIMS = new Set([
  "Acknowledge",
  "Alert",
  "Announce",
  "Blink",
  "Confused",
  "Congratulate",
  "Explain",
  "GestureDown",
  "GestureLeft",
  "GestureRight",
  "GestureUp",
  "GetAttention",
  "Greet",
  "Pleased",
  "Sad",
  "Suggest",
  "Surprised",
  "Think",
  "Uncertain",
  "Wave",
  "Show",
]);

function restPose(agent) {
  if (!agent?.hasAnimation("RestPose")) return;
  agent._animator.showAnimation("RestPose", () => {});
}

function stopIdle(agent) {
  if (agent._idleResolve) {
    agent._idleResolve();
    agent._idlePromise = null;
    agent._idleResolve = null;
  }
  agent._queue?.clear();
}

function playAnim(agent, name) {
  if (name === "Wave" && !hasUnackedAlerts()) {
    name = "Pleased";
  }
  const gen = bumpAnim();
  return new Promise((resolve) => {
    let settled = false;
    const settle = (pose) => {
      if (settled) return;
      settled = true;
      if (gen === animGen && pose) restPose(agent);
      resolve();
    };
    if (!name || !SAFE_ANIMS.has(name) || !agent.hasAnimation(name)) {
      settle(gen === animGen);
      return;
    }
    stopIdle(agent);
    const started = agent._animator.showAnimation(name, (_anim, state) => {
      if (gen !== animGen) {
        settle(false);
        return;
      }
      if (state === 0) {
        settle(true);
        return;
      }
      if (state === 1) agent._animator.exitAnimation();
    });
    if (!started) {
      settle(true);
      return;
    }
    window.setTimeout(() => {
      if (settled) return;
      if (gen !== animGen) {
        settle(false);
        return;
      }
      if (agent._animator?.currentAnimationName === name) {
        agent._animator.exitAnimation();
        window.setTimeout(() => settle(true), 2500);
        return;
      }
      settle(false);
    }, 20000);
  });
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
  if (!el || el.classList.contains("cc-wizard--docked")) return Promise.resolve();
  const dest = agent._clampXY(x, y);
  const here = el.getBoundingClientRect();
  const fromX = here.left;
  const fromY = here.top;
  const dx = dest.x - fromX;
  const dy = dest.y - fromY;
  if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return Promise.resolve();

  merlinMoving = true;
  merlinMoveHook?.();
  bumpAnim();
  stopIdle(agent);
  const anim = `Move${agent._getDirection(dest.x, dest.y)}`;
  const token = ++walkToken;
  const replayMove = () => {
    if (token !== walkToken || !agent.hasAnimation(anim)) return;
    agent._animator.showAnimation(anim, (_name, state) => {
      if (token !== walkToken) return;
      if (state === 1 && merlinMoving) replayMove();
    });
  };
  replayMove();

  const dist = Math.hypot(dx, dy);
  const ms = duration ?? Math.max(1100, Math.min(2600, dist * 3.6));
  const started = performance.now();
  const swing = (progress) => 0.5 - Math.cos(progress * Math.PI) / 2;
  return new Promise((resolve) => {
    const finishWalk = () => {
      if (token === walkToken) merlinMoving = false;
      const animator = agent._animator;
      const waitExit = new Promise((done) => {
        if (token !== walkToken || !animator || animator.currentAnimationName !== anim) {
          done();
          return;
        }
        let ended = false;
        const end = () => {
          if (ended) return;
          ended = true;
          done();
        };
        animator._endCallback = (_name, state) => {
          if (state === 1) animator.exitAnimation();
          if (state === 0) end();
        };
        animator.exitAnimation();
        window.setTimeout(end, 2500);
      });
      waitExit.then(() => {
        if (token === walkToken) restPose(agent);
        agent.reposition();
        resolve();
      });
    };
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
      finishWalk();
    };
    requestAnimationFrame(step);
  });
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
  agent._el.style.visibility = "hidden";
  agent.show(true);
  stopIdle(agent);

  const settingsDock = document.getElementById("settings-merlin-dock");
  let docked = Boolean(settingsDock) && prefersDocked();
  merlinDocked = docked;
  const MERLIN_FRAME = 128;
  let dockObserver = null;
  const scaleDockedMerlin = () => {
    if (!merlinDocked || !settingsDock || !agent._el) return;
    const box = settingsDock.getBoundingClientRect();
    const pad = 12;
    const scale = Math.min(
      (box.width - pad) / MERLIN_FRAME,
      (box.height - pad) / MERLIN_FRAME,
      2.75,
    );
    agent._el.style.setProperty("--cc-wizard-dock-scale", String(Math.max(scale, 0.5)));
  };
  const applyDocked = () => {
    if (!settingsDock || !agent._el) return;
    showDockSection();
    settingsDock.appendChild(agent._el);
    agent._el.classList.add("cc-wizard--docked");
    agent._el.style.position = "relative";
    agent._el.style.left = "";
    agent._el.style.top = "";
    agent._el.style.visibility = "visible";
    scaleDockedMerlin();
    if (!dockObserver) {
      dockObserver = new ResizeObserver(scaleDockedMerlin);
      dockObserver.observe(settingsDock);
    }
  };
  const applyFloating = () => {
    const el = agent._el;
    const box = el.getBoundingClientRect();
    const cx = box.left + box.width / 2;
    const cy = box.top + box.height / 2;
    hideDockSection();
    el.classList.remove("cc-wizard--docked");
    el.style.removeProperty("--cc-wizard-dock-scale");
    el.style.position = "fixed";
    document.body.appendChild(el);
    const w = el.offsetWidth || MERLIN_FRAME;
    const h = el.offsetHeight || MERLIN_FRAME;
    const dest =
      box.width > 2 && box.height > 2
        ? agent._clampXY(cx - w / 2, cy - h / 2)
        : savedPos();
    el.style.left = `${dest.x}px`;
    el.style.top = `${dest.y}px`;
    el.style.visibility = "visible";
    savePos(agent);
  };
  const dockMerlin = () => {
    if (!settingsDock) return;
    docked = true;
    merlinDocked = true;
    setDockPref(true);
    applyDocked();
    placeHelp();
    speak("I am back in my section.", "Wave");
  };
  const undockMerlin = () => {
    docked = false;
    merlinDocked = false;
    setDockPref(false);
    applyFloating();
    placeHelp();
    speak("I can float now. Drag me if I am in the way.", "Pleased");
  };
  if (docked) {
    applyDocked();
  } else if (settingsDock) {
    hideDockSection();
  }

  let tipIndex = 0;
  let tipToken = 0;
  let idleTimer = null;
  let idleGen = 0;
  let helpPanel = null;
  let orbWrap = null;
  let helpMuteBtn = null;
  let muteOrbBtn = null;
  let helpLog = null;
  let helpInput = null;

  const pauseIdle = () => {
    idleGen += 1;
    window.clearTimeout(idleTimer);
    idleTimer = null;
  };

  const idlePool = () => {
    const page = pageKey();
    const common = ["Blink", "Blink", "Pleased"];
    if (hasUnackedAlerts()) common.push("Wave");
    if (page.startsWith("settings") || page.startsWith("profile")) {
      return [...common, "Uncertain", "Explain"];
    }
    if (page === "library") {
      return [...common, "Acknowledge", "Explain"];
    }
    if (page === "service_create" || page === "service_edit") {
      return [...common, "Explain", "Think"];
    }
    return [...common, "Acknowledge", "Uncertain"];
  };

  const resumeIdle = () => {
    const gen = ++idleGen;
    window.clearTimeout(idleTimer);
    idleTimer = window.setTimeout(async () => {
      if (gen !== idleGen || merlinMoving || orbWrap || press || helpPanel) {
        if (gen === idleGen) resumeIdle();
        return;
      }
      await playAnim(agent, pick(idlePool()));
      if (gen === idleGen) resumeIdle();
    }, 1800 + Math.random() * 3200);
  };

  const speak = (text, animation) => {
    pauseIdle();
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
    playAnim(agent, animation).then(() => {
      if (!merlinMoving && !orbWrap && !helpPanel) resumeIdle();
    });
  };

  const offerTip = async () => {
    pauseIdle();
    const tips = tipsForPage();
    const tip = tips[tipIndex % tips.length];
    tipIndex += 1;
    const myTip = ++tipToken;
    await playAnim(agent, pick(["Think", "Uncertain"]));
    if (myTip !== tipToken) return;
    const target = resolveTarget(tip.target);
    if (target) {
      target.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
      await new Promise((resolve) => window.setTimeout(resolve, 80));
      if (myTip !== tipToken) return;
      if (!docked) {
        const dest = standBeside(target);
        await walkTo(agent, dest.x, dest.y);
        if (myTip !== tipToken) return;
        await playAnim(agent, gestureName(agent, dest.pointX, dest.pointY));
        if (myTip !== tipToken) return;
      }
    }
    speak(tip.text, pick(["Explain", "Suggest", "Acknowledge", "Announce", "Pleased"]));
  };

  const notify = (text, level = "") => {
    if (body.dataset.wizardNotify !== "1") return false;
    let animation = pick(["Announce", "Explain"]);
    if (level.includes("error")) animation = pick(["Sad", "Confused", "Decline"]);
    else if (level.includes("success")) animation = pick(["Congratulate", "Pleased", "Wave"]);
    else if (level.includes("warning")) animation = pick(["GetAttention", "Uncertain", "Alert"]);
    speak(text, animation);
    return true;
  };

  const isAdmin = document.body.dataset.admin === "1";

  const isMuted = () => localStorage.getItem(MUTE_KEY) === "1";

  const setMuted = (value) => {
    localStorage.setItem(MUTE_KEY, value ? "1" : "0");
    window.ccWizardMuted = value;
    if (muteOrbBtn) muteOrbBtn.textContent = value ? "Unmute" : "Mute";
    if (helpMuteBtn) {
      helpMuteBtn.textContent = value ? "Unmute" : "Mute";
      helpMuteBtn.setAttribute("aria-pressed", value ? "true" : "false");
    }
  };

  const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  const postJson = async (url, body) => {
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
  };

  const runningContainers = async () => {
    try {
      const resp = await fetch("/api/docker/");
      if (!resp.ok) return [];
      const data = await resp.json();
      return (data.containers || [])
        .filter((row) => (row.state || row.status) === "running")
        .map((row) => row.name);
    } catch {
      return [];
    }
  };

  const hideHelp = () => {
    helpPanel?.remove();
    helpPanel = null;
    helpMuteBtn = null;
    helpLog = null;
    helpInput = null;
  };

  const placeHelp = () => {
    if (!helpPanel) return;
    const box = agent._el.getBoundingClientRect();
    const width = Math.min(320, window.innerWidth - 16);
    let left = box.left - width - 8;
    if (left < 8) left = Math.min(window.innerWidth - width - 8, box.right + 8);
    let top = box.top - 24;
    if (top < 72) top = 72;
    if (top + 280 > window.innerHeight) top = Math.max(72, window.innerHeight - 288);
    helpPanel.style.left = `${left}px`;
    helpPanel.style.top = `${top}px`;
    helpPanel.style.width = `${width}px`;
  };

  const appendHelpLine = (who, text) => {
    if (!helpLog) return;
    const line = document.createElement("p");
    line.className = `cc-wizard-help__line cc-wizard-help__line--${who}`;
    line.textContent = text;
    helpLog.appendChild(line);
    helpLog.scrollTop = helpLog.scrollHeight;
  };

  const appendHelpButtons = (buttons) => {
    if (!helpLog || !buttons?.length) return;
    const row = document.createElement("div");
    row.className = "cc-wizard-help__actions";
    buttons.forEach((item) => {
      const btn = document.createElement(item.href ? "a" : "button");
      if (item.href) {
        btn.href = item.href;
        btn.className = "cc-wizard-help__btn";
      } else {
        btn.type = "button";
        btn.className = "cc-wizard-help__btn";
      }
      btn.textContent = item.label;
      btn.addEventListener("click", (event) => {
        if (item.href) return;
        event.preventDefault();
        runHelpButton(item);
      });
      row.appendChild(btn);
    });
    helpLog.appendChild(row);
    helpLog.scrollTop = helpLog.scrollHeight;
  };

  const runHelpButton = async (item) => {
    if (item.suggest) {
      if (helpInput) helpInput.value = item.suggest;
      submitHelp(item.suggest);
      return;
    }
    if (item.action === "mute") {
      setMuted(true);
      appendHelpLine("merlin", "Muted.");
      return;
    }
    if (item.action === "unmute") {
      setMuted(false);
      appendHelpLine("merlin", "Sound is back.");
      return;
    }
    if (item.action === "alerts") {
      document.getElementById("alerts-bell")?.click();
      return;
    }
    if (item.action === "usb") {
      document.querySelector('[data-panel-id="usb"]')?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    if (item.action === "containers") {
      document.querySelector('[data-panel-id="containers"]')?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      return;
    }
    if (item.action === "reboot") {
      hideHelp();
      const openBtn = document.getElementById("host-reboot-btn");
      if (openBtn) {
        openBtn.click();
        return;
      }
      appendHelpLine("merlin", "Open the dashboard to restart the host.");
      return;
    }
    if (item.action === "ack") {
      try {
        await postJson("/api/alerts/ack/", {});
        appendHelpLine("merlin", "Alerts acknowledged.");
        window.dispatchEvent(new Event("cc-alerts-refresh"));
      } catch (err) {
        appendHelpLine("merlin", err.message || "Could not acknowledge alerts.");
      }
      return;
    }
    if (item.action === "restart-container") {
      const name = item.name;
      if (!name) return;
      if (
        !(await window.ccDialog.confirm(`Restart ${name}? It will be briefly offline.`, {
          title: "Restart",
          confirmLabel: "Restart",
        }))
      ) {
        return;
      }
      try {
        await postJson("/api/docker/restart/", { name });
        appendHelpLine("merlin", `Restarted ${name}.`);
      } catch (err) {
        appendHelpLine("merlin", err.message || `Could not restart ${name}.`);
      }
    }
  };

  const submitHelp = async (raw) => {
    const text = String(raw || helpInput?.value || "").trim();
    if (!text) return;
    if (helpInput) helpInput.value = "";
    appendHelpLine("user", text);
    const reply = matchHelpIntent(text, {
      isAdmin,
      muted: isMuted(),
      page: document.body.dataset.wizardPage || "",
      containers: text.toLowerCase().includes("restart") ? await runningContainers() : [],
    });
    appendHelpLine("merlin", reply.text);
    appendHelpButtons(reply.buttons);
    speak(reply.text, reply.animation || "Explain");
  };

  const showHelp = () => {
    hideOrbs();
    hideHelp();
    pauseIdle();
    playAnim(agent, pick(["Explain", "Suggest", "Wave"]));
    helpPanel = document.createElement("div");
    helpPanel.className = "cc-wizard-help";
    helpPanel.innerHTML = `
      <div class="cc-wizard-help__head">
        <span>Merlin Help</span>
        <div class="cc-wizard-help__head-actions">
          <button type="button" class="cc-wizard-help__icon" id="cc-help-mute" aria-pressed="${isMuted() ? "true" : "false"}">${isMuted() ? "Unmute" : "Mute"}</button>
          <button type="button" class="cc-wizard-help__icon" id="cc-help-close" aria-label="Close help">Close</button>
        </div>
      </div>
      <div class="cc-wizard-help__log" id="cc-help-log"></div>
      <form class="cc-wizard-help__form" id="cc-help-form">
        <input type="text" id="cc-help-input" class="cc-wizard-help__input" placeholder="Ask for help" autocomplete="off" spellcheck="false">
        <button type="submit" class="cc-wizard-help__send">Send</button>
      </form>
    `;
    document.body.appendChild(helpPanel);
    helpLog = helpPanel.querySelector("#cc-help-log");
    helpInput = helpPanel.querySelector("#cc-help-input");
    helpMuteBtn = helpPanel.querySelector("#cc-help-mute");
    helpPanel.querySelector("#cc-help-close").addEventListener("click", () => {
      hideHelp();
      resumeIdle();
    });
    helpMuteBtn.addEventListener("click", () => {
      const next = !isMuted();
      setMuted(next);
      appendHelpLine("merlin", next ? "Muted." : "Sound is back.");
    });
    helpPanel.querySelector("#cc-help-form").addEventListener("submit", (event) => {
      event.preventDefault();
      submitHelp();
    });
    appendHelpLine("merlin", "Hello, how can I help?");
    placeHelp();
    helpInput?.focus();
  };

  const availableActions = () => {
    const actions = [];
    const targeted = tipsForPage().filter((tip) => tip.target && resolveTarget(tip.target));
    if (targeted.length) {
      actions.push({ id: "tips", label: "Tips", run: () => offerTip() });
    }
    const alerts = document.querySelector("#alerts-bell");
    if (isVisible(alerts)) {
      actions.push({
        id: "alerts",
        label: "Alerts",
        run: async () => {
          pauseIdle();
          await playAnim(agent, pick(["Alert", "GetAttention", "Surprised"]));
          alerts.click();
          resumeIdle();
        },
      });
    }
    const updateBtn = [...document.querySelectorAll("#header-update-btn, #footer-update-btn")].find(
      (node) => isVisible(node) && !node.hidden
    );
    if (updateBtn) {
      actions.push({
        id: "update",
        label: "Update",
        run: async () => {
          pauseIdle();
          await playAnim(agent, pick(["Announce", "Suggest", "Congratulate"]));
          updateBtn.click();
          resumeIdle();
        },
      });
    }
    actions.push({
      id: "help",
      label: "Help",
      run: () => showHelp(),
    });
    if (settingsDock) {
      if (docked) {
        actions.push({ id: "undock", label: "Undock", run: () => undockMerlin() });
      } else {
        actions.push({ id: "dock", label: "Dock", run: () => dockMerlin() });
      }
    }
    actions.push({
      id: "mute",
      label: isMuted() ? "Unmute" : "Mute",
      run: () => {
        const next = !isMuted();
        setMuted(next);
        speak(next ? "I will keep quiet." : "Sound is back.", next ? "Acknowledge" : "Wave");
      },
    });
    return actions;
  };

  const hideOrbs = () => {
    orbWrap?.remove();
    orbWrap = null;
  };

  merlinMoveHook = () => {
    hideOrbs();
    placeHelp();
  };

  const showOrbs = () => {
    if (merlinMoving) return;
    const actions = availableActions();
    hideOrbs();
    if (!actions.length) {
      playAnim(agent, pick(["Confused", "Uncertain"]));
      return;
    }
    pauseIdle();
    playAnim(agent, pick(["GetAttention", "Pleased", "Surprised", "Wave"]));
    const box = agent._el.getBoundingClientRect();
    const cx = box.left + box.width / 2;
    const cy = box.top + box.height / 3;
    orbWrap = document.createElement("div");
    orbWrap.className = "cc-wizard-orbs";
    const start = Math.PI * 1.08;
    const end = Math.PI * 1.92;
    const radius = actions.length > 3 ? 96 : 86;
    actions.forEach((item, index) => {
      const t = actions.length === 1 ? 0.5 : index / (actions.length - 1);
      const angle = start + (end - start) * t;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `cc-wizard-orb cc-wizard-orb--${item.id}`;
      btn.textContent = item.label;
      if (item.id === "mute") muteOrbBtn = btn;
      btn.style.left = `${cx + Math.cos(angle) * radius - 32}px`;
      btn.style.top = `${cy + Math.sin(angle) * radius - 14}px`;
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        hideOrbs();
        item.run();
      });
      orbWrap.appendChild(btn);
    });
    document.body.appendChild(orbWrap);
  };

  window.ccWizard = {
    speak: (text) => speak(text),
    notify,
    offerTip,
    availableActions,
    showHelp,
    setMuted,
    isMuted,
  };

  const notices = noticeTexts();
  const greeted = sessionStorage.getItem(GREETED_KEY) === "1";

  const finishDocked = async () => {
    agent._el.style.visibility = "visible";
    if (notices.length) {
      notices.forEach((text, index) => notify(text, noticeLevel(index)));
      sessionStorage.setItem(GREETED_KEY, "1");
    } else if (!greeted) {
      sessionStorage.setItem(GREETED_KEY, "1");
      await playAnim(agent, "Greet");
      speak("Hi, I am Merlin. I stay in this section when docked. Click me for Tips, Help, or Undock.", "Wave");
    } else {
      await playAnim(agent, pick(["Acknowledge", "Blink", "Pleased"]));
      resumeIdle();
    }
  };

  const finishEntrance = async () => {
    await walkTo(agent, savedPos().x, savedPos().y, 1400);
    if (notices.length) {
      notices.forEach((text, index) => notify(text, noticeLevel(index)));
      sessionStorage.setItem(GREETED_KEY, "1");
    } else if (!greeted) {
      sessionStorage.setItem(GREETED_KEY, "1");
      await playAnim(agent, "Greet");
      speak(
        settingsDock
          ? "Hi, I am Merlin. Click me for Tips, Help, Dock, or Mute. Double-click for a tip."
          : "Hi, I am Merlin. Click me for Tips, Help, or Mute. Double-click for a tip.",
        "Wave",
      );
    } else {
      await playAnim(agent, pick(["Acknowledge", "Blink", "Pleased"]));
      resumeIdle();
    }
  };

  if (docked) {
    finishDocked();
  } else if (!greeted) {
    const dest = savedPos();
    agent._el.style.left = `${window.innerWidth + 24}px`;
    agent._el.style.top = `${dest.y}px`;
    agent._el.style.visibility = "visible";
    finishEntrance();
  } else {
    const dest = savedPos();
    agent._el.style.left = `${dest.x}px`;
    agent._el.style.top = `${dest.y}px`;
    const finishReturn = async () => {
      const entrance = pick(["Show", "Surprised", "Congratulate"]);
      agent._el.classList.add("cc-wizard--teleport");
      agent._el.style.visibility = "visible";
      await playAnim(agent, entrance);
      agent._el.classList.remove("cc-wizard--teleport");
      if (notices.length) {
        notices.forEach((text, index) => notify(text, noticeLevel(index)));
      } else {
        resumeIdle();
      }
    };
    finishReturn();
  }

  let press = null;
  let clickTimer = null;
  agent._el.addEventListener("mousedown", (event) => {
    event.preventDefault();
    walkToken += 1;
    merlinMoving = false;
    bumpAnim();
    restPose(agent);
    const box = agent._el.getBoundingClientRect();
    press = {
      x: event.clientX,
      y: event.clientY,
      ox: event.clientX - box.left,
      oy: event.clientY - box.top,
      dragged: false,
    };
    const onMove = (moveEvent) => {
      if (!press || docked) return;
      const dx = moveEvent.clientX - press.x;
      const dy = moveEvent.clientY - press.y;
      if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
        press.dragged = true;
        hideOrbs();
      }
      const next = agent._clampXY(moveEvent.clientX - press.ox, moveEvent.clientY - press.oy);
      agent._el.style.left = `${next.x}px`;
      agent._el.style.top = `${next.y}px`;
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      if (!press) return;
      const wasDrag = !docked && press.dragged;
      press = null;
      if (!docked) savePos(agent);
      if (wasDrag) {
        playAnim(agent, pick(["Pleased", "Acknowledge", "RestPose"])).then(resumeIdle);
        return;
      }
      if (merlinMoving) return;
      if (clickTimer) {
        window.clearTimeout(clickTimer);
        clickTimer = null;
        hideOrbs();
        hideHelp();
        offerTip();
        return;
      }
      clickTimer = window.setTimeout(() => {
        clickTimer = null;
        if (orbWrap) {
          hideOrbs();
          playAnim(agent, pick(["Blink", "Acknowledge"])).then(resumeIdle);
        } else {
          showOrbs();
        }
      }, 280);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  });

  document.addEventListener("mousedown", (event) => {
    if (helpPanel && !helpPanel.contains(event.target) && !agent._el.contains(event.target)) {
      hideHelp();
      resumeIdle();
    }
    if (!orbWrap) return;
    if (agent._el.contains(event.target) || orbWrap.contains(event.target)) return;
    if (helpPanel?.contains(event.target)) return;
    hideOrbs();
    if (!helpPanel) playAnim(agent, "Blink").then(resumeIdle);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (orbWrap) hideOrbs();
    if (helpPanel) {
      hideHelp();
      resumeIdle();
    }
  });

  window.addEventListener("resize", placeHelp);

  window.addEventListener("cc-wizard-section", () => {
    tipIndex = 0;
    hideOrbs();
    hideHelp();
    pauseIdle();
    playAnim(agent, pick(["Blink", "Confused"])).then(resumeIdle);
  });
}

boot().catch((error) => {
  console.warn("Wizard failed to load.", error);
});
