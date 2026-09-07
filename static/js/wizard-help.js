function topicMenu(ctx) {
  const page = ctx?.page || "";
  const isAdmin = Boolean(ctx?.isAdmin);
  const items = [
    { label: "Dashboard", suggest: "tell me about the dashboard" },
    { label: "Settings", suggest: "tell me about settings" },
    { label: "Library", suggest: "tell me about the library" },
    { label: "Alerts", suggest: "show alerts" },
  ];
  if (page === "dashboard") {
    return [
      { label: "Tracked vs Apps", suggest: "what is tracked vs apps vs misc" },
      { label: "Add card", suggest: "how do I add a card" },
      { label: "Stats", suggest: "what is in stats" },
      { label: "Alerts", suggest: "show alerts" },
    ];
  }
  if (page === "settings") {
    return [
      { label: "Appearance", suggest: "tell me about appearance" },
      { label: "Site", suggest: "tell me about site settings" },
      { label: "Updates", suggest: "how do updates work" },
      isAdmin ? { label: "Users", suggest: "tell me about users" } : { label: "Merlin", suggest: "how do I turn Merlin off" },
    ];
  }
  if (page === "profile") {
    return [
      { label: "Password", suggest: "how do I change my password" },
      { label: "Two-factor", suggest: "how do I set up 2FA" },
      { label: "Vault", suggest: "tell me about the vault" },
      { label: "Alerts", suggest: "show alerts" },
    ];
  }
  if (page === "library") {
    return [
      { label: "Install", suggest: "how do I install an app" },
      { label: "Uninstall", suggest: "how do I uninstall an app" },
      { label: "Publish", suggest: "how do I publish a service" },
      { label: "Dashboard", suggest: "tell me about the dashboard" },
    ];
  }
  return items;
}

function withMenu(text, animation, extraButtons, ctx) {
  const extra = extraButtons || [];
  const seen = new Set(extra.map((btn) => btn.label));
  const fill = topicMenu(ctx).filter((btn) => !seen.has(btn.label));
  return {
    text,
    animation,
    buttons: [...extra, ...fill].slice(0, 4),
  };
}

export function matchHelpIntent(query, ctx) {
  const q = String(query || "").trim().toLowerCase();
  const isAdmin = Boolean(ctx?.isAdmin);
  const muted = Boolean(ctx?.muted);
  const page = ctx?.page || "";
  const containers = Array.isArray(ctx?.containers) ? ctx.containers : [];

  if (!q) {
    return unknownReply(ctx);
  }

  if (/\b(unmute|sound on|turn on sound)\b/.test(q)) {
    return {
      text: muted ? "I will speak up again." : "I am not muted.",
      animation: "Wave",
      buttons: muted
        ? [{ label: "Unmute", action: "unmute" }]
        : topicMenu(ctx).slice(0, 3),
    };
  }
  if (/\b(mute|quiet|silence|be quiet|sound off)\b/.test(q)) {
    return {
      text: muted ? "I am already muted." : "I can keep quiet. Use Mute when you want silence.",
      animation: "Acknowledge",
      buttons: muted ? topicMenu(ctx).slice(0, 3) : [{ label: "Mute", action: "mute" }],
    };
  }

  if (/\b(help|what can you|what do you do|commands|who are you)\b/.test(q)) {
    return withMenu(
      "I can walk you through this Control Center. Pick a topic, or type a question.",
      "Wave",
      [],
      ctx,
    );
  }

  if (/\b(notif|toast|wizard notify|normal setting|normal notification|popup)\b/.test(q)) {
    return withMenu(
      "That's under Site on Settings. Uncheck “Let the wizard notify me” for the normal toasts.",
      "Explain",
      [{ label: "Open Site settings", href: "/settings/?section=site" }],
      ctx,
    );
  }

  if (/\b(crt|scanline)\b/.test(q)) {
    return withMenu(
      "CRT scanlines are a Site setting. They apply to everyone on this board.",
      "Suggest",
      [{ label: "Open Site", href: "/settings/?section=site" }],
      ctx,
    );
  }

  if (/\b(theme|appearance)\b/.test(q)) {
    return withMenu(
      "Appearance is per account. Color theme only changes your login. CRT scanlines are under Site.",
      "Suggest",
      [
        { label: "Open Appearance", href: "/settings/?section=appearance" },
        { label: "Site", suggest: "tell me about site settings" },
      ],
      ctx,
    );
  }

  if (/\b(weather|city|location|forecast)\b/.test(q)) {
    return withMenu(
      "Weather city is under Settings → Site. The chip in the header uses that location.",
      "Explain",
      [{ label: "Open Site", href: "/settings/?section=site" }],
      ctx,
    );
  }

  if (/\b(merlin|wizard|clippy)\b/.test(q) && /\b(off|on|enable|disable|hide|show|turn)\b/.test(q)) {
    return withMenu(
      "Call in the Wizard is under Settings → Site. That turns me on or off for every signed-in user.",
      "Explain",
      [
        { label: "Open Site", href: "/settings/?section=site" },
        { label: "Dock me", suggest: "how do I dock Merlin" },
      ],
      ctx,
    );
  }

  if (
    /\b(dock|undock)\b/.test(q) ||
    (/\bfloat\b/.test(q) && /\b(merlin|wizard|you)\b/.test(q))
  ) {
    return withMenu(
      "Click me and pick Dock or Undock. Dock parks me in the Merlin section. Undock lets you drag me. That choice stays in this browser.",
      "Pleased",
      [
        { label: "Turn Merlin off", suggest: "how do I turn Merlin off" },
        { label: "Dashboard", suggest: "tell me about the dashboard" },
      ],
      ctx,
    );
  }

  if (/\b(2fa|two.?factor|authenticator|recovery code)\b/.test(q)) {
    return withMenu(
      "Two-factor is on your profile under Security. Save the recovery codes when you turn it on.",
      "Explain",
      [
        { label: "Open Security", href: "/profile/?section=security" },
        { label: "Password", suggest: "how do I change my password" },
      ],
      ctx,
    );
  }

  if (/\b(password)\b/.test(q)) {
    return withMenu(
      "Change your Control Center password on Profile → Security. Service passwords belong in Vault.",
      "Explain",
      [
        { label: "Open Security", href: "/profile/?section=security" },
        { label: "Vault", suggest: "tell me about the vault" },
      ],
      ctx,
    );
  }

  if (/\bvault\b/.test(q)) {
    return withMenu(
      "Vault stores passwords and tokens for other services. They are encrypted for your account. Reveal asks for your Control Center password.",
      "Explain",
      [
        { label: "Open Vault", href: "/profile/?section=vault" },
        { label: "Password", suggest: "how do I change my password" },
      ],
      ctx,
    );
  }

  if (/\b(profile|account|email|my name)\b/.test(q)) {
    return withMenu(
      "Name, email, password, 2FA, and Vault are on your profile.",
      "Explain",
      [
        { label: "Open Profile", href: "/profile/" },
        { label: "Security", href: "/profile/?section=security" },
        { label: "Vault", suggest: "tell me about the vault" },
      ],
      ctx,
    );
  }

  if (/\b(pi-?hole|pihole)\b/.test(q)) {
    return withMenu(
      isAdmin
        ? "Pi-hole is a Library install. After it is running, open it from a dashboard card."
        : "Pi-hole is installed by an admin. If it has a card on the dashboard, you can open it from there.",
      "Suggest",
      isAdmin
        ? [
            { label: "Open Library", href: "/library/" },
            { label: "Dashboard", suggest: "tell me about the dashboard" },
          ]
        : [{ label: "Dashboard", suggest: "tell me about the dashboard" }],
      ctx,
    );
  }

  if (/\b(tunnel|publish|cloudflare)\b/.test(q)) {
    return withMenu(
      "Cloudflare Tunnel is a Library install. Connect it under Settings → Tunnel. Nothing goes online until you publish a service. Control Center stays on the LAN.",
      "Explain",
      [
        { label: "Open Tunnel", href: "/settings/?section=tunnel" },
        { label: "Library", suggest: "tell me about the library" },
      ],
      ctx,
    );
  }

  if (/\buninstall\b/.test(q)) {
    return withMenu(
      isAdmin
        ? "Uninstall is on the Library card. You can also delete its data volumes."
        : "Uninstall is an admin action. Ask one if an app should come off this host.",
      "Explain",
      isAdmin
        ? [
            { label: "Open Library", href: "/library/" },
            { label: "Install", suggest: "how do I install an app" },
          ]
        : [],
      ctx,
    );
  }

  if (/\b(library|install|catalog|addon)\b/.test(q)) {
    return withMenu(
      isAdmin
        ? "Library is the catalog. Install pulls the image and can add a dashboard card. Restart reloads a container without uninstalling it."
        : "Library is for admins. Ask one if you need an app installed.",
      "Suggest",
      isAdmin
        ? [
            { label: "Open Library", href: "/library/" },
            { label: "Uninstall", suggest: "how do I uninstall an app" },
            { label: "Publish", suggest: "how do I publish a service" },
          ]
        : [],
      ctx,
    );
  }

  if (/\b(tracked|apps vs|misc vs|vs apps|vs misc)\b/.test(q) || /\bwhat is (tracked|apps|misc)\b/.test(q)) {
    return withMenu(
      "Tracked is the services you watch most closely. Apps are compact cards. Misc is leftovers and simple links.",
      "Explain",
      [
        { label: "Add card", suggest: "how do I add a card" },
        { label: "Open a service", suggest: "how do I open a service" },
        { label: "Stats", suggest: "what is in stats" },
      ],
      ctx,
    );
  }

  if (/\b(add card|new card|create card|new service|pin a service)\b/.test(q)) {
    return withMenu(
      isAdmin ? "Use Add card on the dashboard to pin a service. You can also add a card from Library after an install." : "Only admins can add cards.",
      "Suggest",
      isAdmin
        ? [
            { label: "Add card", href: "/cards/new/" },
            { label: "Library", suggest: "tell me about the library" },
          ]
        : [],
      ctx,
    );
  }

  if (/\b(open a service|open a card|launch)\b/.test(q)) {
    return withMenu(
      "Click a card to open that service. Some cards open in a new tab. The card menu lets admins edit or hide it.",
      "GestureUp",
      [
        { label: "Tracked vs Apps", suggest: "what is tracked vs apps vs misc" },
        { label: "Add card", suggest: "how do I add a card" },
      ],
      ctx,
    );
  }

  if (/\b(stats|system panel|host load)\b/.test(q) || /\bwhat is in stats\b/.test(q)) {
    return withMenu(
      "Stats is host load, USB, containers, and Monitor. Restart Server reboots the machine.",
      "Explain",
      [
        { label: "USB", suggest: "show usb" },
        { label: "Containers", suggest: "how do I restart a container" },
        { label: "Dashboard", suggest: "tell me about the dashboard" },
      ],
      ctx,
    );
  }

  if (/\b(dashboard|home board|home page)\b/.test(q) || /\btell me about the dashboard\b/.test(q)) {
    return withMenu(
      "Home has Tracked, Apps, and Misc. Stats sits on the right. Filter cards from the strip at the top.",
      "Explain",
      [
        { label: "Tracked vs Apps", suggest: "what is tracked vs apps vs misc" },
        { label: "Add card", suggest: "how do I add a card" },
        { label: "Stats", suggest: "what is in stats" },
      ],
      ctx,
    );
  }

  if (/\b(site settings|under site|weather city|call in the wizard)\b/.test(q) || /\btell me about site\b/.test(q)) {
    return withMenu(
      "Site holds the title, weather city, CRT, and Merlin’s on/off switch. Those apply to everyone.",
      "Explain",
      [
        { label: "Open Site", href: "/settings/?section=site" },
        { label: "Merlin on/off", suggest: "how do I turn Merlin off" },
        { label: "Weather", suggest: "how do I set the weather city" },
      ],
      ctx,
    );
  }

  if (/\b(users|members|viewers|invite)\b/.test(q) || /\btell me about users\b/.test(q)) {
    return withMenu(
      isAdmin
        ? "Users is under Settings. Admin, Member, and Viewer are the three roles. Members only see the cards you allow."
        : "Only an admin can add or change users.",
      "Explain",
      isAdmin ? [{ label: "Open Users", href: "/settings/?section=users" }] : [],
      ctx,
    );
  }

  if (/\btell me about settings\b/.test(q) || (/\bsettings\b/.test(q) && !/\b(site|update|user|tunnel|appearance)\b/.test(q))) {
    return withMenu(
      "Settings is split into categories on the left. Appearance is yours. Site, Updates, and Users are shared.",
      "Explain",
      [
        { label: "Appearance", suggest: "tell me about appearance" },
        { label: "Site", suggest: "tell me about site settings" },
        { label: "Updates", suggest: "how do updates work" },
      ],
      ctx,
    );
  }

  if (/\b(ack|acknowledge)\b/.test(q) && /\balert/.test(q)) {
    return {
      text: "That marks current alerts as seen.",
      animation: "Acknowledge",
      buttons: [
        { label: "ACK ALL", action: "ack" },
        { label: "Open alerts", action: "alerts" },
        { label: "Dashboard", suggest: "tell me about the dashboard" },
      ],
    };
  }

  if (/\balert/.test(q)) {
    return withMenu(
      "Alerts are in the bell next to your name.",
      "Alert",
      [{ label: "Open alerts", action: "alerts" }],
      ctx,
    );
  }

  if (/\busb\b/.test(q)) {
    return withMenu(
      "USB devices are listed in Stats on the dashboard. Storage sticks can be unmounted from there.",
      "GestureLeft",
      [{ label: "Show USB", action: "usb" }],
      ctx,
    );
  }

  if (/\b(reboot|restart)\b/.test(q) && /\b(pi|server|host|machine)\b/.test(q)) {
    if (!isAdmin) {
      return withMenu("Restarting the host is an admin action.", "Decline", [], ctx);
    }
    return {
      text: "This reboots the whole machine. Every service goes offline until it comes back.",
      animation: "GetAttention",
      buttons: [
        { label: "Restart Server", action: "reboot" },
        { label: "Restart a container", suggest: "restart a container" },
        { label: "Dashboard", suggest: "tell me about the dashboard" },
      ],
    };
  }

  if (/\brestart\b/.test(q)) {
    if (!isAdmin) {
      return withMenu("Restarting containers is an admin action.", "Decline", [], ctx);
    }
    const named = q.replace(/.*\brestart\b/, "").replace(/\b(the|a|an|container|service|docker)\b/g, "").trim();
    if (named) {
      const match = containers.find((name) => name.toLowerCase().includes(named.replace(/\s+/g, "-")));
      const target = match || named.replace(/\s+/g, "-");
      return {
        text: `I can restart ${target}. It will be briefly offline.`,
        animation: "Uncertain",
        buttons: [
          { label: `Restart ${target}`, action: "restart-container", name: target },
          { label: "Show containers", action: "containers" },
        ],
      };
    }
    const top = containers.slice(0, 6);
    if (!top.length) {
      return withMenu(
        "Name a container, or open the Containers panel and use Restart on its row.",
        "Think",
        [{ label: "Show containers", action: "containers" }],
        ctx,
      );
    }
    return {
      text: "Which container should I restart?",
      animation: "Explain",
      buttons: top.map((name) => ({ label: name, action: "restart-container", name })),
    };
  }

  if (/\b(update|upgrade)\b/.test(q) || /\bhow do updates work\b/.test(q)) {
    return withMenu(
      "Updates are under Settings, or the Update chip when one is ready.",
      "Announce",
      [{ label: "Open Updates", href: "/settings/?section=updates" }],
      ctx,
    );
  }

  if (page === "dashboard" && /\b(here|this page|this board)\b/.test(q)) {
    return matchHelpIntent("tell me about the dashboard", ctx);
  }
  if (page === "settings" && /\b(here|this page)\b/.test(q)) {
    return matchHelpIntent("tell me about settings", ctx);
  }
  if (page === "library" && /\b(here|this page)\b/.test(q)) {
    return matchHelpIntent("tell me about the library", ctx);
  }
  if (page === "profile" && /\b(here|this page)\b/.test(q)) {
    return matchHelpIntent("tell me about my profile", ctx);
  }

  return unknownReply(ctx);
}

function unknownReply(ctx) {
  return {
    text: "I am not sure. What do you want to know about?",
    animation: "Confused",
    buttons: topicMenu(ctx),
  };
}
