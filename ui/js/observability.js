import { onEvent, sendObservabilityRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

let panel = null;
let pendingSnapshot = null;

export function openObservability() {
  if (panel) {
    openWindow("observability", panel, { width: 900, height: 620 });
    refresh();
    return panel;
  }
  panel = document.createElement("section");
  panel.style.cssText = "display:flex; flex-direction:column; gap:12px; padding:14px; height:100%; overflow:auto; color:#e5eefb; font-family:Inter,Segoe UI,sans-serif;";
  panel.innerHTML = `
    <header style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
      <div><h2 style="margin:0;">Trace &amp; Journal</h2><p style="margin:4px 0 0; opacity:.72;">Request outcomes and durable simulated-disk transactions.</p></div>
      <div style="display:flex; gap:8px;"><button data-action="refresh">Refresh</button><button data-action="clear">Clear traces</button></div>
    </header>
    <p data-observe-status role="status" aria-live="polite" style="margin:0; color:#b8c8e2;">Loading observability data…</p>
    <section style="padding:12px; border:1px solid rgba(163,184,255,.25); border-radius:10px; background:rgba(12,20,39,.7);">
      <h3 style="margin:0 0 8px;">Recent requests</h3>
      <div style="overflow:auto;"><table style="width:100%; border-collapse:collapse; font-size:12px;"><thead><tr><th>Time</th><th>Request ID</th><th>Type</th><th>Operation</th><th>Result</th><th>Duration</th></tr></thead><tbody data-trace-rows></tbody></table></div>
    </section>
    <section style="padding:12px; border:1px solid rgba(163,184,255,.25); border-radius:10px; background:rgba(12,20,39,.7);">
      <h3 style="margin:0 0 8px;">Disk journal</h3>
      <div style="overflow:auto;"><table style="width:100%; border-collapse:collapse; font-size:12px;"><thead><tr><th>Time</th><th>Transaction</th><th>Operation</th><th>Request</th><th>State</th></tr></thead><tbody data-journal-rows></tbody></table></div>
    </section>`;
  openWindow("observability", panel, { width: 900, height: 620 });
  panel.querySelector('[data-action="refresh"]').addEventListener("click", refresh);
  panel.querySelector('[data-action="clear"]').addEventListener("click", () => {
    try {
      pendingSnapshot = sendObservabilityRequest("clear_traces");
      setStatus("Clearing request traces…");
    } catch (error) {
      setStatus(error.message, true);
    }
  });
  refresh();
  return panel;
}

function refresh() {
  try {
    pendingSnapshot = sendObservabilityRequest("snapshot");
    setStatus("Refreshing journal and request traces…");
  } catch (error) {
    setStatus(error.message, true);
  }
}

onEvent((event) => {
  if (event.type === "request_trace" && panel?.isConnected) {
    appendTrace(event);
    return;
  }
  if (event.type !== "observability_result" || event.request_id !== pendingSnapshot) return;
  pendingSnapshot = null;
  if (!event.ok) {
    setStatus(event.error || "Could not load observability data.", true);
    return;
  }
  renderRows(panel.querySelector("[data-trace-rows]"), event.traces || [], [
    (item) => new Date(item.timestamp).toLocaleTimeString(),
    (item) => item.request_id,
    (item) => item.request_type,
    (item) => item.operation,
    (item) => item.ok ? "OK" : `FAILED${item.error ? ` · ${item.error}` : ""}`,
    (item) => `${item.duration_ms} ms`,
  ]);
  const states = new Map();
  for (const item of event.journal || []) {
    if (item.kind === "begin") states.set(item.transaction_id, item);
    else if (states.has(item.transaction_id)) states.get(item.transaction_id).outcome = item.kind;
  }
  renderRows(panel.querySelector("[data-journal-rows]"), [...states.values()], [
    (item) => new Date(item.timestamp).toLocaleTimeString(),
    (item) => item.transaction_id.slice(0, 12),
    (item) => item.operation,
    (item) => item.request_id || "—",
    (item) => item.outcome || "PENDING",
  ]);
  setStatus(`${(event.traces || []).length} request traces · ${states.size} journal transactions.`);
});

function appendTrace(trace) {
  const body = panel.querySelector("[data-trace-rows]");
  const row = buildRow([
    new Date(trace.timestamp).toLocaleTimeString(),
    trace.request_id,
    trace.request_type,
    trace.operation,
    trace.ok ? "OK" : `FAILED${trace.error ? ` · ${trace.error}` : ""}`,
    `${trace.duration_ms} ms`,
  ]);
  body.prepend(row);
  while (body.children.length > 100) body.lastElementChild.remove();
}

function renderRows(body, records, columns) {
  body.replaceChildren();
  if (!records.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columns.length;
    cell.textContent = "No records yet.";
    row.append(cell);
    body.append(row);
    return;
  }
  for (const record of [...records].reverse()) {
    body.append(buildRow(columns.map((column) => column(record))));
  }
}

function buildRow(values) {
  const row = document.createElement("tr");
  for (const value of values) {
    const cell = document.createElement("td");
    cell.style.cssText = "padding:7px; border-bottom:1px solid rgba(163,184,255,.12); text-align:left; vertical-align:top;";
    cell.textContent = String(value ?? "—");
    row.append(cell);
  }
  return row;
}

function setStatus(message, isError = false) {
  if (!panel) return;
  const status = panel.querySelector("[data-observe-status]");
  status.textContent = message;
  status.style.color = isError ? "#ff9c9c" : "#b8c8e2";
}
