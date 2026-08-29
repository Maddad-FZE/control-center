(function () {
  const clock = document.getElementById("tva-clock");
  if (!clock) return;

  const WEEKDAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function tick() {
    const now = new Date();
    const weekday = WEEKDAYS[now.getDay()];
    const day = pad(now.getDate());
    const month = MONTHS[now.getMonth()];
    const year = now.getFullYear();
    const h = pad(now.getHours());
    const m = pad(now.getMinutes());
    const s = pad(now.getSeconds());
    clock.innerHTML =
      `<span class="tva-clock__date">` +
      `<span class="tva-clock__weekday">${weekday}</span>` +
      `<span class="tva-clock__day">${day} ${month} ${year}</span>` +
      `</span>` +
      `<span class="tva-clock__sep" aria-hidden="true"></span>` +
      `<span class="tva-clock__time">` +
      `<span class="tva-clock__digits">${h}</span>` +
      `<span class="clock-colon">:</span>` +
      `<span class="tva-clock__digits">${m}</span>` +
      `<span class="clock-colon">:</span>` +
      `<span class="tva-clock__digits">${s}</span>` +
      `</span>`;
    clock.setAttribute("datetime", now.toISOString());
  }

  tick();
  setInterval(tick, 1000);
})();
