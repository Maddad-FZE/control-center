export function matchHelpIntent(query, ctx) {
  const q = String(query || "").trim().toLowerCase();
  const isAdmin = Boolean(ctx?.isAdmin);
  const muted = Boolean(ctx?.muted);
  const containers = Array.isArray(ctx?.containers) ? ctx.containers : [];

  if (!q) {
    return unknownReply();
  }

  if (/\b(unmute|sound on|turn on sound)\b/.test(q)) {
    return {
      text: muted ? "I will speak up again." : "I am not muted.",
      animation: "Wave",
      buttons: muted ? [{ label: "Unmute", action: "unmute" }] : [],
    };
  }
  if (/\b(mute|quiet|silence|be quiet|sound off)\b/.test(q)) {
    return {
      text: muted ? "I am already muted." : "I can keep quiet. Use Mute when you want silence.",
      animation: "Acknowledge",
      buttons: muted ? [] : [{ label: "Mute", action: "mute" }],
    };
  }

  if (
    /\b(notif|toast|wizard notify|normal setting|normal notification|popup)\b/.test(q)
  ) {
    return {
      text: "That's under Site on Settings. Uncheck “Let the wizard notify me” for the normal toasts.",
      animation: "Explain",
      buttons: [{ label: "Open Site settings", href: "/settings/?section=site" }],
    };
  }

  if (/\b(theme|appearance|crt|scanline)\b/.test(q)) {
    return {
      text: "Appearance is per account. CRT scanlines are under Site.",
      animation: "Suggest",
      buttons: [{ label: "Open Appearance", href: "/settings/?section=appearance" }],
    };
  }

  if (/\b(profile|password|account|email)\b/.test(q)) {
    return {
      text: "Name, email, and password are on your profile.",
      animation: "Explain",
      buttons: [{ label: "Open Profile", href: "/profile/" }],
    };
  }

  if (/\b(library|install|catalog|addon)\b/.test(q)) {
    return {
      text: isAdmin
        ? "Library is where you install and restart addons."
        : "Library is for admins. Ask one if you need an app installed.",
      animation: "Suggest",
      buttons: isAdmin ? [{ label: "Open Library", href: "/library/" }] : [],
    };
  }

  if (/\b(add card|new card|create card|new service)\b/.test(q)) {
    return {
      text: isAdmin ? "Use Add card to pin a service on the dashboard." : "Only admins can add cards.",
      animation: "Suggest",
      buttons: isAdmin ? [{ label: "Add card", href: "/cards/new/" }] : [],
    };
  }

  if (/\b(ack|acknowledge)\b/.test(q) && /\balert/.test(q)) {
    return {
      text: "That marks current alerts as seen.",
      animation: "Acknowledge",
      buttons: [{ label: "ACK ALL", action: "ack" }],
    };
  }

  if (/\balert/.test(q)) {
    return {
      text: "Alerts are in the bell next to your name.",
      animation: "Alert",
      buttons: [{ label: "Open alerts", action: "alerts" }],
    };
  }

  if (/\busb\b/.test(q)) {
    return {
      text: "USB devices are listed in the sidebar. Storage sticks can be unmounted from there.",
      animation: "GestureLeft",
      buttons: [{ label: "Show USB", action: "usb" }],
    };
  }

  if (/\b(reboot|restart)\b/.test(q) && /\b(pi|server|host|machine)\b/.test(q)) {
    if (!isAdmin) {
      return {
        text: "Restarting the host is an admin action.",
        animation: "Decline",
        buttons: [],
      };
    }
    return {
      text: "This reboots the whole machine. Every service goes offline until it comes back.",
      animation: "GetAttention",
      buttons: [{ label: "Restart Server", action: "reboot" }],
    };
  }

  if (/\brestart\b/.test(q)) {
    if (!isAdmin) {
      return {
        text: "Restarting containers is an admin action.",
        animation: "Decline",
        buttons: [],
      };
    }
    const named = q.replace(/.*\brestart\b/, "").replace(/\b(the|a|an|container|service|docker)\b/g, "").trim();
    if (named) {
      const match = containers.find((name) => name.toLowerCase().includes(named.replace(/\s+/g, "-")));
      const target = match || named.replace(/\s+/g, "-");
      return {
        text: `I can restart ${target}. It will be briefly offline.`,
        animation: "Uncertain",
        buttons: [{ label: `Restart ${target}`, action: "restart-container", name: target }],
      };
    }
    const top = containers.slice(0, 6);
    if (!top.length) {
      return {
        text: "Name a container, or open the Containers panel and use Restart on its row.",
        animation: "Think",
        buttons: [{ label: "Show containers", action: "containers" }],
      };
    }
    return {
      text: "Which container should I restart?",
      animation: "Explain",
      buttons: top.map((name) => ({ label: name, action: "restart-container", name })),
    };
  }

  if (/\b(update|upgrade)\b/.test(q)) {
    return {
      text: "Updates are under Settings, or the Update chip when one is ready.",
      animation: "Announce",
      buttons: [{ label: "Open Updates", href: "/settings/?section=updates" }],
    };
  }

  if (/\b(help|what can you|commands)\b/.test(q)) {
    return unknownReply();
  }

  return unknownReply();
}

function unknownReply() {
  return {
    text: "I can help with settings, alerts, USB, and restarts. Try one of these.",
    animation: "Confused",
    buttons: [
      { label: "Notifications", suggest: "change the notification to the normal setting" },
      { label: "Alerts", suggest: "show alerts" },
      { label: "Restart Server", suggest: "restart the pi" },
    ],
  };
}
