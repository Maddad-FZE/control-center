(function () {
  const preset = document.getElementById("id_preset");
  const metricsSection = document.getElementById("metrics-section");
  const addBtn = document.getElementById("add-metric-row");
  const rowsContainer = document.getElementById("metric-rows");
  const totalFormsInput = document.querySelector("input[name='metrics-TOTAL_FORMS']");

  function toggleMetricsSection() {
    if (!preset || !metricsSection) return;
    const usePreset = preset.value && preset.value !== "none";
    metricsSection.hidden = usePreset;
  }

  if (preset) {
    preset.addEventListener("change", toggleMetricsSection);
    toggleMetricsSection();
  }

  if (!addBtn || !rowsContainer || !totalFormsInput) return;

  addBtn.addEventListener("click", () => {
    const index = parseInt(totalFormsInput.value, 10);
    const template = rowsContainer.querySelector(".metric-row");
    if (!template) return;
    const clone = template.cloneNode(true);
    clone.dataset.formIndex = String(index);
    clone.querySelectorAll("input, select, textarea").forEach((el) => {
      if (el.name) {
        el.name = el.name.replace(/metrics-\d+-/, `metrics-${index}-`);
        el.id = el.id.replace(/metrics-\d+-/, `metrics-${index}-`);
      }
      if (el.type === "checkbox") el.checked = false;
      else if (el.type !== "hidden") el.value = "";
    });
    rowsContainer.appendChild(clone);
    totalFormsInput.value = String(index + 1);
  });
})();
