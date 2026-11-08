import { onEvent, sendResourceRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

const DISK_SAMPLE = [98, 183, 37, 122, 14, 124, 65, 67];
const PAGE_SAMPLE = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 8, 9, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9];

let host;
let latestMemory = null;
let latestDiskResult = null;

export function openSystemMonitor() {
  const panel = document.createElement("section");
  panel.className = "system-monitor";
  panel.innerHTML = `
    <section class="memory-view">
      <header class="resource-section-heading">
        <div><h2>Memory Manager</h2><p>Demand paging · ${PAGE_SAMPLE.length} sample references</p></div>
        <button data-action="refresh">Refresh</button>
      </header>
      <div class="memory-toolbar">
        <label>Process<select data-control="memory-process"></select></label>
        <label>Virtual pages<input data-control="memory-pages" type="number" min="1" max="64" value="10"></label>
        <button data-action="allocate">Allocate address space</button>
        <button data-action="free">Free address space</button>
      </div>
      <form class="memory-simulation-form">
        <label>Replacement policy<select data-control="pager">
          <option value="fifo">FIFO</option><option value="lru">LRU</option><option value="optimal">Optimal (offline)</option>
        </select></label>
        <label class="reference-string-label">Page reference string<input data-control="references" value="${PAGE_SAMPLE.join(", ")}"></label>
        <button type="submit">Run page simulation</button>
      </form>
      <p class="resource-status" data-resource-status role="status" aria-live="polite">Loading memory and disk state…</p>
      <div class="memory-metrics"></div>
      <section class="frame-section"><h3>Physical frames</h3><div class="frame-grid"></div></section>
      <section class="page-table-section"><h3>Process page tables</h3><div class="resource-table-wrap">
        <table class="resource-table"><thead><tr><th>PID</th><th>Process</th><th>Virtual pages</th><th>Resident pages → frame</th></tr></thead><tbody data-page-tables></tbody></table>
      </div></section>
      <section class="page-trace-section"><h3>Page reference trace</h3><div class="resource-table-wrap">
        <table class="resource-table"><thead><tr><th>Step</th><th>Page</th><th>Result</th><th>Frame</th><th>Evicted</th><th>Resident set</th></tr></thead><tbody data-page-trace></tbody></table>
      </div></section>
    </section>
    <section class="disk-view">
      <header class="resource-section-heading">
        <div><h2>Disk Scheduler</h2><p>Virtual disk tracks · 0–<span data-disk-max>511</span></p></div>
      </header>
      <form class="disk-simulation-form">
        <label>Algorithm<select data-control="disk-algorithm">
          <option value="fcfs">FCFS</option><option value="sstf">SSTF</option>
          <option value="scan">SCAN</option><option value="c-scan">C-SCAN</option>
          <option value="look">LOOK</option><option value="c-look">C-LOOK</option>
        </select></label>
        <label>Initial head<input data-control="disk-head" type="number" min="0" max="511" value="53"></label>
        <label>Direction<select data-control="disk-direction"><option value="right">Toward higher tracks</option><option value="left">Toward lower tracks</option></select></label>
        <label class="request-queue-label">Request queue<input data-control="disk-requests" value="${DISK_SAMPLE.join(", ")}"></label>
        <button type="submit">Run disk schedule</button>
      </form>
      <div class="disk-metrics"></div>
      <section class="disk-path-section"><h3>Head movement path</h3><div class="disk-path-chart"></div></section>
      <section class="disk-steps-section"><h3>Service and seek order</h3><div class="resource-table-wrap">
        <table class="resource-table"><thead><tr><th>Step</th><th>From</th><th>To</th><th>Movement</th><th>Action</th></tr></thead><tbody data-disk-steps></tbody></table>
      </div></section>
    </section>`;

  host = openWindow("system-monitor", panel, { width: 1040, height: 720 });
  host.classList.add("system-monitor-window");
  host.querySelector('[data-action="refresh"]').addEventListener("click", () => request("state"));
  host.querySelector('[data-action="allocate"]').addEventListener("click", () => {
    const pid = selectedPid();
    if (pid === null) return;
    request("memory_allocate", {
      pid,
      pages: Number(host.querySelector('[data-control="memory-pages"]').value),
    });
  });
  host.querySelector('[data-action="free"]').addEventListener("click", () => {
    const pid = selectedPid();
    if (pid !== null) request("memory_free", { pid });
  });
  host.querySelector(".memory-simulation-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const references = parseNumberList(host.querySelector('[data-control="references"]').value);
    if (!references) {
      setStatus("Page references must be comma-separated integers.", true);
      return;
    }
    const pid = selectedPid();
    if (pid === null) return;
    request("memory_simulate", {
      pid,
      algorithm: host.querySelector('[data-control="pager"]').value,
      references,
    });
  });
  host.querySelector(".disk-simulation-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const requests = parseNumberList(host.querySelector('[data-control="disk-requests"]').value);
    if (!requests) {
      setStatus("Disk requests must be comma-separated integers.", true);
      return;
    }
    request("disk_schedule", {
      requests,
      head: Number(host.querySelector('[data-control="disk-head"]').value),
      algorithm: host.querySelector('[data-control="disk-algorithm"]').value,
      direction: host.querySelector('[data-control="disk-direction"]').value,
    });
  });
  renderMemory(latestMemory);
  renderDisk(latestDiskResult, 512);
  request("state");
  return host;
}

onEvent((event) => {
  if (event.type !== "resource_result" && event.type !== "resource_state") return;
  if (!host?.isConnected) return;
  latestMemory = event.memory || latestMemory;
  latestDiskResult = event.last_disk_schedule || latestDiskResult;
  renderMemory(latestMemory, event.processes);
  renderDisk(latestDiskResult, event.disk_size || 512);
  if (event.type === "resource_result") renderOperationResult(event);
});

function request(operation, fields = {}) {
  try {
    sendResourceRequest(operation, fields);
    setStatus("Kernel resource request sent.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function selectedPid() {
  const value = host.querySelector('[data-control="memory-process"]').value;
  const pid = Number(value);
  if (!value || !Number.isInteger(pid)) {
    setStatus("Choose a process first.", true);
    return null;
  }
  return pid;
}

function renderMemory(memory, processes = []) {
  if (!host?.isConnected || !memory) return;
  updateProcessOptions(processes);
  host.querySelector(".memory-metrics").replaceChildren(
    metricCard("Physical frames", `${memory.used_frames} / ${memory.frame_count}`),
    metricCard("Free frames", String(memory.free_frames)),
    metricCard("Page size", `${memory.page_size} bytes`),
    metricCard("Last policy", memory.last_run
      ? `${memory.last_run.algorithm.toUpperCase()} · ${memory.last_run.page_faults} faults`
      : "Not run"),
  );
  const frames = host.querySelector(".frame-grid");
  frames.replaceChildren();
  for (const frame of memory.frames) {
    const cell = document.createElement("div");
    cell.className = `frame-cell${frame.pid === null ? " frame-free" : ""}`;
    const number = document.createElement("strong");
    number.textContent = `F${frame.frame}`;
    const contents = document.createElement("span");
    contents.textContent = frame.pid === null ? "Free" : `PID ${frame.pid} · P${frame.page}`;
    cell.append(number, contents);
    frames.append(cell);
  }
  const pageTables = host.querySelector("[data-page-tables]");
  pageTables.replaceChildren();
  for (const table of memory.page_tables) {
    const row = document.createElement("tr");
    appendCell(row, String(table.pid));
    appendCell(row, table.process);
    appendCell(row, String(table.virtual_pages));
    appendCell(row, table.resident_pages.length
      ? table.resident_pages.map((page) => `${page.page} → F${page.frame}`).join(", ")
      : "No resident pages");
    pageTables.append(row);
  }
  if (!memory.page_tables.length) {
    const row = document.createElement("tr");
    appendCell(row, "No allocated address spaces", 4);
    pageTables.append(row);
  }
  renderPageTrace(memory.last_run);
}

function updateProcessOptions(processes) {
  if (!Array.isArray(processes)) return;
  const select = host.querySelector('[data-control="memory-process"]');
  const selected = select.value;
  select.replaceChildren();
  for (const process of processes.filter((item) => item.state !== "TERMINATED")) {
    const option = document.createElement("option");
    option.value = String(process.pid);
    option.textContent = `PID ${process.pid} · ${process.name} (${process.state})`;
    select.append(option);
  }
  if (Array.from(select.options).some((option) => option.value === selected)) {
    select.value = selected;
  }
}

function renderPageTrace(run) {
  const rows = host.querySelector("[data-page-trace]");
  rows.replaceChildren();
  if (!run) {
    const row = document.createElement("tr");
    appendCell(row, "Allocate an address space and run a page reference simulation.", 6);
    rows.append(row);
    return;
  }
  for (const step of run.trace) {
    const row = document.createElement("tr");
    appendCell(row, String(step.step));
    appendCell(row, `P${step.page}`);
    appendCell(row, step.hit ? "Hit" : "Fault", step.hit ? "hit-cell" : "fault-cell");
    appendCell(row, `F${step.frame}`);
    appendCell(row, step.evicted ? `PID ${step.evicted.pid} · P${step.evicted.page}` : "—");
    appendCell(row, step.resident_pages.map((page) => `P${page.page}→F${page.frame}`).join(", "));
    rows.append(row);
  }
}

function renderDisk(result, diskSize) {
  if (!host?.isConnected) return;
  const maxTrack = Math.max(0, diskSize - 1);
  host.querySelector("[data-disk-max]").textContent = String(maxTrack);
  const head = host.querySelector('[data-control="disk-head"]');
  head.max = String(maxTrack);
  if (Number(head.value) > maxTrack) head.value = String(Math.floor(maxTrack / 2));
  const requestField = host.querySelector('[data-control="disk-requests"]');
  requestField.maxLength = 1000;
  if (!result) {
    host.querySelector(".disk-metrics").replaceChildren();
    host.querySelector(".disk-path-chart").textContent = "Run a disk schedule to view the head path.";
    const rows = host.querySelector("[data-disk-steps]");
    rows.replaceChildren();
    const row = document.createElement("tr");
    appendCell(row, "No schedule has been run.", 5);
    rows.append(row);
    return;
  }
  host.querySelector(".disk-metrics").replaceChildren(
    metricCard("Algorithm", result.algorithm.toUpperCase()),
    metricCard("Total movement", `${result.total_movement} tracks`),
    metricCard("Average / request", `${result.average_movement} tracks`),
    metricCard("Service order", result.service_order.join(" → ")),
  );
  renderDiskChart(result);
  const rows = host.querySelector("[data-disk-steps]");
  rows.replaceChildren();
  for (const [index, step] of result.steps.entries()) {
    const row = document.createElement("tr");
    appendCell(row, String(index + 1));
    appendCell(row, String(step.from));
    appendCell(row, String(step.to));
    appendCell(row, String(step.movement));
    appendCell(row, step.kind === "request" ? "Service request" : step.kind);
    rows.append(row);
  }
}

function renderDiskChart(result) {
  const chart = host.querySelector(".disk-path-chart");
  chart.replaceChildren();
  const width = 760;
  const height = 220;
  const margin = { left: 36, right: 24, top: 22, bottom: 24 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const path = result.path;
  const maxTrack = Math.max(1, result.disk_size - 1);
  const x = (track) => margin.left + (track / maxTrack) * innerWidth;
  const y = (index) => margin.top + (path.length <= 1 ? 0 : (index / (path.length - 1)) * innerHeight);
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Disk head path using ${result.algorithm}`);
  const axis = document.createElementNS(svg.namespaceURI, "line");
  axis.setAttribute("x1", String(margin.left));
  axis.setAttribute("x2", String(width - margin.right));
  axis.setAttribute("y1", String(height - margin.bottom));
  axis.setAttribute("y2", String(height - margin.bottom));
  axis.setAttribute("class", "disk-chart-axis");
  svg.append(axis);
  const axisStart = svgText(svg, margin.left, height - 5, "0");
  const axisEnd = svgText(svg, width - margin.right - 20, height - 5, String(maxTrack));
  svg.append(axisStart, axisEnd);
  if (path.length > 1) {
    const polyline = document.createElementNS(svg.namespaceURI, "polyline");
    polyline.setAttribute(
      "points",
      path.map((track, index) => `${x(track)},${y(index)}`).join(" "),
    );
    polyline.setAttribute("class", "disk-chart-path");
    svg.append(polyline);
  }
  path.forEach((track, index) => {
    const point = document.createElementNS(svg.namespaceURI, "circle");
    point.setAttribute("cx", String(x(track)));
    point.setAttribute("cy", String(y(index)));
    point.setAttribute("r", "4");
    point.setAttribute("class", index === 0 ? "disk-chart-head" : "disk-chart-request");
    const label = svgText(svg, x(track) + 6, Math.max(12, y(index) - 5), String(track));
    svg.append(point, label);
  });
  chart.append(svg);
}

function svgText(svg, x, y, text) {
  const label = document.createElementNS(svg.namespaceURI, "text");
  label.setAttribute("x", String(x));
  label.setAttribute("y", String(y));
  label.setAttribute("class", "disk-chart-label");
  label.textContent = text;
  return label;
}

function renderOperationResult(event) {
  if (!event.ok) {
    setStatus(event.error, true);
    return;
  }
  if (event.operation === "state") {
    setStatus("Memory and disk state refreshed.");
  } else if (event.operation === "memory_allocate") {
    setStatus("Process address space allocated.");
  } else if (event.operation === "memory_free") {
    setStatus("Process address space and resident pages freed.");
  } else if (event.operation === "memory_simulate") {
    const run = event.memory.last_run;
    setStatus(
      `${run.algorithm.toUpperCase()} completed: ${run.page_faults} page faults, `
      + `${run.hits} hits (${run.fault_rate}% faults).`,
    );
  } else if (event.operation === "disk_schedule") {
    setStatus(
      `${event.result.algorithm.toUpperCase()} serviced ${event.result.request_count} requests `
      + `with ${event.result.total_movement} tracks of movement.`,
    );
  }
}

function parseNumberList(value) {
  if (!value.trim()) return null;
  const parts = value.split(",").map((part) => part.trim());
  if (parts.some((part) => !/^\d+$/.test(part))) return null;
  const numbers = parts.map(Number);
  return numbers.every(Number.isSafeInteger) ? numbers : null;
}

function metricCard(label, value) {
  const card = document.createElement("div");
  card.className = "resource-metric";
  const heading = document.createElement("span");
  heading.textContent = label;
  const content = document.createElement("strong");
  content.textContent = value;
  card.append(heading, content);
  return card;
}

function appendCell(row, text, className = "", colSpan = 1) {
  const cell = document.createElement("td");
  cell.textContent = text;
  cell.colSpan = colSpan;
  if (className) cell.className = className;
  row.append(cell);
}

function setStatus(message, isError = false) {
  if (!host?.isConnected) return;
  const status = host.querySelector("[data-resource-status]");
  status.textContent = message;
  status.classList.toggle("error", isError);
}
