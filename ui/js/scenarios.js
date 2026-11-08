import { onEvent, sendScenarioRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

const SCENARIOS = [
  ["library-rush", "Library rush · CPU scheduling"],
  ["disk-queue", "Disk queue · seek algorithms"],
  ["page-pressure", "Page pressure · replacement policies"],
];
let panel = null;
let pendingRequest = null;

export function openScenarioLab() {
  if (panel) {
    openWindow("scenarios", panel, { width: 850, height: 560 });
    return panel;
  }
  panel = document.createElement("section");
  panel.style.cssText = "display:flex; flex-direction:column; gap:14px; padding:14px; height:100%; overflow:auto; color:#e5eefb; font-family:Inter,Segoe UI,sans-serif;";
  panel.innerHTML = `
    <header><h2 style="margin:0;">Scenario Lab</h2><p style="margin:4px 0 0; opacity:.72;">Run isolated, repeatable workloads and compare algorithms side by side.</p></header>
    <form data-scenario-form style="display:flex; gap:10px; align-items:end;">
      <label style="display:grid; gap:6px; flex:1;">Scenario
        <select data-scenario style="padding:9px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;"></select>
      </label>
      <button type="submit" style="padding:9px 12px; border:0; border-radius:8px; background:#5a7cff; color:white; font-weight:700; cursor:pointer;">Run scenario</button>
    </form>
    <p data-scenario-status role="status" aria-live="polite" style="margin:0; color:#b8c8e2;">Choose a scenario to compare.</p>
    <section style="padding:12px; border:1px solid rgba(163,184,255,.25); border-radius:10px; background:rgba(12,20,39,.7); overflow:auto;">
      <h3 data-scenario-title style="margin:0 0 10px;">Comparison results</h3>
      <table style="width:100%; border-collapse:collapse; font-size:13px;"><thead data-scenario-head></thead><tbody data-scenario-rows></tbody></table>
    </section>`;
  const select = panel.querySelector("[data-scenario]");
  for (const [id, title] of SCENARIOS) {
    const option = document.createElement("option");
    option.value = id;
    option.textContent = title;
    select.append(option);
  }
  openWindow("scenarios", panel, { width: 850, height: 560 });
  panel.querySelector("[data-scenario-form]").addEventListener("submit", (event) => {
    event.preventDefault();
    try {
      pendingRequest = sendScenarioRequest("run", { scenario: select.value });
      setStatus("Running isolated scenario…");
    } catch (error) {
      setStatus(error.message, true);
    }
  });
  return panel;
}

onEvent((event) => {
  if (event.type !== "scenario_result" || event.request_id !== pendingRequest) return;
  pendingRequest = null;
  if (!event.ok) {
    setStatus(event.error || "Scenario failed.", true);
    return;
  }
  const result = event.result;
  const comparison = result.comparison;
  panel.querySelector("[data-scenario-title]").textContent = result.title;
  renderComparison(comparison);
  setStatus(`Completed ${comparison.results.length} comparison runs.`);
});

function renderComparison(comparison) {
  const headers = comparison.kind === "scheduler"
    ? ["Algorithm", "Elapsed", "Avg wait", "Avg turnaround", "CPU utilization"]
    : comparison.kind === "disk"
      ? ["Algorithm", "Requests", "Total movement", "Average movement"]
      : ["Policy", "References", "Page faults", "Hits", "Fault rate"];
  const head = panel.querySelector("[data-scenario-head]");
  head.replaceChildren();
  const headerRow = document.createElement("tr");
  for (const label of headers) {
    const cell = document.createElement("th");
    cell.style.cssText = "padding:8px; text-align:left; border-bottom:1px solid rgba(163,184,255,.25);";
    cell.textContent = label;
    headerRow.append(cell);
  }
  head.append(headerRow);
  const body = panel.querySelector("[data-scenario-rows]");
  body.replaceChildren();
  for (const item of comparison.results) {
    let values;
    if (comparison.kind === "scheduler") {
      const metrics = item.metrics;
      values = [
        item.algorithm.toUpperCase(),
        metrics.elapsed_time,
        metrics.average_waiting_time,
        metrics.average_turnaround_time,
        `${metrics.cpu_utilization}%`,
      ];
    } else if (comparison.kind === "disk") {
      values = [
        item.algorithm.toUpperCase(),
        item.request_count,
        item.total_movement,
        item.average_movement,
      ];
    } else {
      values = [
        item.algorithm.toUpperCase(),
        item.references,
        item.page_faults,
        item.hits,
        `${item.fault_rate}%`,
      ];
    }
    const row = document.createElement("tr");
    for (const value of values) {
      const cell = document.createElement("td");
      cell.style.cssText = "padding:8px; border-bottom:1px solid rgba(163,184,255,.12);";
      cell.textContent = String(value);
      row.append(cell);
    }
    body.append(row);
  }
}

function setStatus(message, isError = false) {
  if (!panel) return;
  const status = panel.querySelector("[data-scenario-status]");
  status.textContent = message;
  status.style.color = isError ? "#ff9c9c" : "#b8c8e2";
}
