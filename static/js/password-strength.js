(function () {
  const input = document.getElementById("id_password1");
  const meter = document.getElementById("password-strength");
  const fill = document.getElementById("password-strength-fill");
  const label = document.getElementById("password-strength-label");
  if (!input || !meter || !fill || !label) return;

  function scorePassword(pw) {
    let score = 0;
    if (!pw) return 0;
    if (pw.length >= 8) score += 1;
    if (pw.length >= 12) score += 1;
    if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score += 1;
    if (/\d/.test(pw)) score += 1;
    if (/[^a-zA-Z0-9]/.test(pw)) score += 1;
    return Math.min(score, 4);
  }

  function update() {
    const pw = input.value;
    if (!pw) {
      meter.hidden = true;
      return;
    }
    meter.hidden = false;
    const score = scorePassword(pw);
    const pct = (score / 4) * 100;
    fill.style.width = `${pct}%`;
    const levels = ["Weak", "Fair", "Good", "Strong", "Excellent"];
    label.textContent = levels[score];
    fill.className = "password-strength__fill";
    if (score <= 1) fill.classList.add("is-weak");
    else if (score === 2) fill.classList.add("is-fair");
    else if (score === 3) fill.classList.add("is-good");
    else fill.classList.add("is-strong");
  }

  input.addEventListener("input", update);
  update();
})();
