(function () {
  const chip = document.getElementById("weather-chip");
  if (!chip) return;

  const WEATHER_ICONS = {
    day: { clear: "☀", cloudy: "⛅", rain: "🌧", snow: "❄", storm: "⚡", fog: "🌫" },
    night: { clear: "🌙", cloudy: "☁", rain: "🌧", snow: "❄", storm: "⚡", fog: "🌫" },
  };

  function iconFor(code, isDay) {
    const set = isDay ? WEATHER_ICONS.day : WEATHER_ICONS.night;
    if (code === 0) return set.clear;
    if (code <= 3) return set.cloudy;
    if (code <= 48) return set.fog;
    if (code <= 57) return set.rain;
    if (code <= 77) return set.snow;
    if (code <= 82) return set.rain;
    return set.storm;
  }

  async function loadWeather() {
    try {
      const resp = await fetch("/api/weather/");
      if (!resp.ok) return;
      const data = await resp.json();
      if (!data.configured || data.error) {
        chip.hidden = true;
        return;
      }
      const icon = iconFor(data.weather_code || 0, data.is_day !== 0);
      const temp =
        data.temperature_c != null ? `${Math.round(data.temperature_c)}°C` : "—";
      chip.innerHTML = `<span class="weather-icon" aria-hidden="true">${icon}</span><span class="weather-temp">${temp}</span><span class="weather-city">${data.location || ""}</span>`;
      chip.hidden = false;
    } catch (e) {
      console.warn("weather fetch failed", e);
    }
  }

  loadWeather();
  setInterval(loadWeather, 900000);
})();
