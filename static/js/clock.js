(function () {
  const clock = document.getElementById("tva-clock");
  if (!clock) return;

  const timeZone = clock.dataset.timezone || undefined;

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function partsInZone(date) {
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone,
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const bag = {};
    fmt.formatToParts(date).forEach((part) => {
      if (part.type !== "literal") bag[part.type] = part.value;
    });
    return {
      weekday: (bag.weekday || "").slice(0, 3).toUpperCase(),
      day: pad(parseInt(bag.day, 10) || 0),
      month: (bag.month || "").slice(0, 3).toUpperCase(),
      year: bag.year,
      hour: pad(parseInt(bag.hour, 10) || 0),
      minute: pad(parseInt(bag.minute, 10) || 0),
      second: pad(parseInt(bag.second, 10) || 0),
    };
  }

  function tick() {
    const now = new Date();
    const p = partsInZone(now);
    clock.innerHTML =
      `<span class="tva-clock__date">` +
      `<span class="tva-clock__weekday">${p.weekday}</span>` +
      `<span class="tva-clock__day">${p.day} ${p.month} ${p.year}</span>` +
      `</span>` +
      `<span class="tva-clock__sep" aria-hidden="true"></span>` +
      `<span class="tva-clock__time">` +
      `<span class="tva-clock__digits">${p.hour}</span>` +
      `<span class="clock-colon">:</span>` +
      `<span class="tva-clock__digits">${p.minute}</span>` +
      `<span class="clock-colon">:</span>` +
      `<span class="tva-clock__digits">${p.second}</span>` +
      `</span>`;
    clock.setAttribute("datetime", now.toISOString());
  }

  tick();
  setInterval(tick, 1000);
})();
