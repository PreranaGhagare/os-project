import {
  onEvent,
  sendProcessAction,
  sendProcessRequest,
  sendScenarioRequest,
  sendScheduleRequest,
} from "./api.js";
import { openWindow } from "./windowManager.js";

const COLORS = ["#67c7a2", "#7ea5f5", "#e7b866", "#ca91ef", "#eb8294", "#63c9d2", "#f39866", "#9aa7bc"];
const SAMPLE = [
  { name: "catalog-search", arrival_time: 0, burst_time: 7, priority: 3 },
  { name: "issue-request", arrival_time: 1, burst_time: 4, priority: 1 },
  { name: "member-lookup", arrival_time: 2, burst_time: 2, priority: 5 },
  { name: "book-import", arrival_time: 3, burst_time: 6, priority: 4 },
  { name: "fine-payment", arrival_time: 4, burst_time: 3, priority: 2 },
  { name: "report-build", arrival_time: 5, burst_time: 5, priority: 6 },
];

let host;
let pendingRequest = null;
let latestResult = null;
let pendingComparison = null;
let selectedPid = null;

export function openTaskManager() {
  const panel = document.createElement("section");
  panel.className = "task-manager";
  panel.innerHTML = `
    <header class="scheduler-toolbar">
      <label>Algorithm<select data-control="algorithm">
        <option value="fcfs">FCFS</option>
        <option value="sjf">SJF · non-preemptive</option>
        <option value="srtf">SRTF · preemptive</option>
        <option value="rr">Round Robin</option>
        <option value="priority-preemptive">Priority · preemptive + aging</option>
        <option value="priority-nonpreemptive">Priority · non-preemptive</option>
        <option value="mlfq">Multilevel feedback queue</option>
      </select></label>
      <label>CPU cores<select data-control="cores">
        <option value="1">1 core</option><option value="2">2 cores</option>
        <option value="3">3 cores</option><option value="4">4 cores</option>
      </select></label>
      <label>Quantum <output data-quantum-output>3</output>
        <input data-control="quantum" type="range" min="1" max="20" value="3">
      </label>
      <button class="scheduler-run">Run simulation</button>
      <button class="scheduler-compare">Compare algorithms</button>
    </header>
    <section class="workload-editor">
      <label>Workload · JSON rows with name, arrival_time, burst_time, priority
        <textarea data-control="workload" spellcheck="false" rows="3"></textarea>
      </label>
      <span data-scheduler-status role="status">Choose an algorithm and run the sample workload.</span>
    </section>
    <section class="scheduler-comparison" hidden><h3>Algorithm comparison</h3><div class="comparison-table-wrap"></div></section>
    <section class="metric-cards" aria-label="Scheduler metrics"></section>
    <section class="cpu-core-panel"></section>
    <section class="scheduler-columns">
      <div class="scheduler-table-wrap">
        <div class="process-table-heading"><h3>Process table</h3>
          <label>Priority<select data-control="priority">${Array.from({ length: 11 }, (_, i) => `<option value="${i}">${i}</option>`).join("")}</select></label>
          <button data-action="set-priority" disabled>Nice</button>
          <button data-action="kill" class="process-kill" disabled>Kill</button>
          <button data-action="refresh-processes">Refresh</button>
        </div>
        <table class="process-table">
          <thead><tr><th>PID</th><th>PPID</th><th>Process</th><th>State</th><th>Priority</th><th>Burst</th><th>Remaining</th><th>Wait</th><th>Turnaround</th><th>Response</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <aside class="ready-queue-panel">
        <h3>Ready queue</h3><div class="ready-queue">Run a workload to view the queue.</div>
        <h3>Process tree</h3><div class="process-tree">Refresh to load processes.</div>
      </aside>
    </section>
    <section class="gantt-panel"><h3>CPU Gantt chart</h3><div class="gantt-chart"></div></section>
    <section class="schedule-timeline-panel"><h3>Simulation timeline</h3><div class="schedule-timeline"></div></section>`;
  host = openWindow("task-manager", panel, { width: 1100, height: 720 });
  host.classList.add("task-manager-window");
  const workload = host.querySelector('[data-control="workload"]');
  workload.value = JSON.stringify(SAMPLE, null, 2);
  host.querySelector('[data-control="quantum"]').addEventListener("input", (event) => {
    host.querySelector("[data-quantum-output]").value = event.target.value;
  });
  host.querySelector(".scheduler-run").addEventListener("click", runSimulation);
  host.querySelector(".scheduler-compare").addEventListener("click", compareWorkload);
  host.querySelector('[data-action="refresh-processes"]').addEventListener("click", refreshProcesses);
  host.querySelector('[data-action="kill"]').addEventListener("click", () => manageSelected("kill"));
  host.querySelector('[data-action="set-priority"]').addEventListener("click", () => manageSelected("nice"));
  if (latestResult) renderResult(latestResult);
  refreshProcesses();
  return host;
}

onEvent((event) => {
  if (event.type === "scheduler_result") {
    latestResult = event;
    if (pendingRequest && event.request_id === pendingRequest) {
      pendingRequest = null;
      renderResult(event);
    } else if (host) {
      renderResult(event);
    }
    refreshProcesses();
  } else if (event.type === "process_snapshot" && host) {
    renderProcesses(event.processes);
    renderProcessTree(event.processes);
  } else if (event.type === "process_result" && host) {
    if (!event.ok) setStatus(event.error, true);
    else setStatus(`${event.operation} completed for PID ${event.result.pid}.`);
    renderProcesses(event.processes);
    renderProcessTree(event.processes);
  } else if (
    event.type === "scheduler_error"
    && pendingRequest
    && event.request_id === pendingRequest
  ) {
    pendingRequest = null;
    setStatus(event.message, true);
  } else if (
    event.type === "scenario_result"
    && pendingComparison
    && event.request_id === pendingComparison
  ) {
    pendingComparison = null;
    if (!event.ok) {
      setStatus(event.error || "Comparison failed.", true);
    } else {
      renderComparison(event.result.comparison.results);
      setStatus(`Compared ${event.result.comparison.results.length} scheduling algorithms.`);
    }
  }
});

function runSimulation() {
  let workload;
  try {
    workload = JSON.parse(host.querySelector('[data-control="workload"]').value);
    if (!Array.isArray(workload)) throw new Error("Workload must be a JSON array.");
  } catch (error) {
    setStatus(`Invalid workload: ${error.message}`, true);
    return;
  }
  const options = {
    algorithm: host.querySelector('[data-control="algorithm"]').value,
    quantum: Number(host.querySelector('[data-control="quantum"]').value),
    cores: Number(host.querySelector('[data-control="cores"]').value),
  };
  try {
    pendingRequest = sendScheduleRequest(workload, options);
    setStatus("Kernel scheduling simulation running…");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function compareWorkload() {
  let workload;
  try {
    workload = JSON.parse(host.querySelector('[data-control="workload"]').value);
    if (!Array.isArray(workload)) throw new Error("Workload must be a JSON array.");
  } catch (error) {
    setStatus(`Invalid workload: ${error.message}`, true);
    return;
  }
  try {
    pendingComparison = sendScenarioRequest("compare", {
      workload,
      algorithms: ["fcfs", "sjf", "srtf", "rr", "priority-preemptive", "priority-nonpreemptive", "mlfq"],
      quantum: Number(host.querySelector('[data-control="quantum"]').value),
      cores: Number(host.querySelector('[data-control="cores"]').value),
    });
    setStatus("Comparing all scheduling algorithms against the same workload…");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderComparison(results) {
  const section = host.querySelector(".scheduler-comparison");
  const container = section.querySelector(".comparison-table-wrap");
  const table = document.createElement("table");
  table.className = "process-table";
  const head = document.createElement("thead");
  const header = document.createElement("tr");
  for (const label of ["Algorithm", "Elapsed", "Avg. waiting", "Avg. turnaround", "CPU utilization"]) {
    const cell = document.createElement("th");
    cell.textContent = label;
    header.append(cell);
  }
  head.append(header);
  const body = document.createElement("tbody");
  for (const result of results) {
    const row = document.createElement("tr");
    const metrics = result.metrics;
    for (const value of [
      result.algorithm.toUpperCase(),
      metrics.elapsed_time,
      metrics.average_waiting_time,
      metrics.average_turnaround_time,
      `${metrics.cpu_utilization}%`,
    ]) {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  container.replaceChildren(table);
  section.hidden = false;
}

function renderResult(result) {
  if (!host?.isConnected) return;
  host.querySelector('[data-control="algorithm"]').value = result.algorithm;
  host.querySelector('[data-control="cores"]').value = String(result.cores);
  host.querySelector('[data-control="quantum"]').value = String(result.quantum);
  host.querySelector("[data-quantum-output]").value = String(result.quantum);
  setStatus(
    `${result.algorithm.toUpperCase()} finished in ${result.metrics.elapsed_time} time units · `
    + `${result.metrics.completed_processes} processes`,
  );
  renderMetrics(result.metrics);
  renderCores(result);
  renderProcesses(result.processes);
  renderReadyQueue(result.timeline, result.processes);
  renderGantt(result.gantt, result.metrics.elapsed_time);
  renderTimeline(result.timeline, result.processes);
}

function renderMetrics(metrics) {
  const container = host.querySelector(".metric-cards");
  container.replaceChildren();
  for (const [label, value] of [
    ["Avg. waiting", `${metrics.average_waiting_time} units`],
    ["Avg. turnaround", `${metrics.average_turnaround_time} units`],
    ["Avg. response", `${metrics.average_response_time} units`],
    ["CPU utilization", `${metrics.cpu_utilization}%`],
    ["Throughput", `${metrics.throughput} proc/unit`],
    ["Context switches", metrics.context_switches],
  ]) {
    const card = document.createElement("div");
    card.className = "metric-card";
    const caption = document.createElement("span");
    caption.textContent = label;
    const number = document.createElement("strong");
    number.textContent = String(value);
    card.append(caption, number);
    container.append(card);
  }
}

function renderCores(result) {
  const container = host.querySelector(".cpu-core-panel");
  container.replaceChildren();
  const last = result.timeline.at(-1);
  for (let core = 0; core < result.cores; core += 1) {
    const box = document.createElement("div");
    box.className = "cpu-core-box";
    const label = document.createElement("span");
    label.textContent = `CPU ${core + 1}`;
    const active = result.gantt[core].at(-1);
    const name = document.createElement("strong");
    name.textContent = active ? active.name : "Idle";
    const detail = document.createElement("small");
    detail.textContent = last?.cores[core]?.pid ? `Last PID ${last.cores[core].pid}` : "Simulation complete";
    box.append(label, name, detail);
    container.append(box);
  }
}

function renderProcesses(processes) {
  const body = host.querySelector(".process-table tbody");
  body.replaceChildren();
  for (const process of processes) {
    const row = document.createElement("tr");
    row.dataset.pid = String(process.pid);
    for (const value of [
      process.pid,
      process.ppid ?? "—",
      process.name,
      process.state,
      process.priority,
      process.burst_time,
      process.remaining_time,
      process.waiting_time,
      process.turnaround_time,
      process.response_time,
    ]) {
      const cell = document.createElement("td");
      cell.textContent = String(value ?? "—");
      row.append(cell);
    }
    row.querySelector("td:nth-child(4)").className = `process-state state-${process.state.toLowerCase()}`;
    row.classList.toggle("selected", process.pid === selectedPid);
    row.addEventListener("click", () => {
      selectedPid = process.pid;
      for (const item of body.querySelectorAll("tr")) {
        item.classList.toggle("selected", Number(item.dataset.pid) === selectedPid);
      }
      updateProcessActions(process);
    });
    body.append(row);
  }
  updateProcessActions(processes.find((process) => process.pid === selectedPid));
}

function updateProcessActions(process) {
  const active = process?.state !== "TERMINATED";
  host.querySelector('[data-action="kill"]').disabled = !process || process.pid === 1 || !active;
  host.querySelector('[data-action="set-priority"]').disabled = !process || !active;
  if (process?.priority !== undefined) host.querySelector('[data-control="priority"]').value = String(process.priority);
}

function renderProcessTree(processes) {
  const container = host.querySelector(".process-tree");
  container.replaceChildren();
  const children = new Map();
  for (const process of processes) {
    if (!children.has(process.ppid)) children.set(process.ppid, []);
    children.get(process.ppid).push(process);
  }
  const addBranch = (parentPid, depth, visited) => {
    for (const process of children.get(parentPid) || []) {
      if (visited.has(process.pid)) continue;
      visited.add(process.pid);
      const row = document.createElement("div");
      row.className = "process-tree-row";
      row.style.paddingLeft = `${depth * 12}px`;
      row.textContent = `↳ ${process.pid} ${process.name} · ${process.state}`;
      container.append(row);
      addBranch(process.pid, depth + 1, visited);
    }
  };
  const root = processes.find((process) => process.pid === 1);
  if (root) {
    const rootRow = document.createElement("div");
    rootRow.className = "process-tree-row root";
    rootRow.textContent = `1 ${root.name} · ${root.state}`;
    container.append(rootRow);
    addBranch(root.pid, 1, new Set([root.pid]));
  }
  if (!container.childElementCount) container.textContent = "No processes.";
}

function refreshProcesses() {
  try {
    sendProcessRequest();
  } catch (error) {
    if (host) setStatus(error.message, true);
  }
}

function manageSelected(operation) {
  if (!selectedPid) {
    setStatus("Select a process first.", true);
    return;
  }
  const priority = Number(host.querySelector('[data-control="priority"]').value);
  try {
    sendProcessAction(operation, selectedPid, priority);
    setStatus(`${operation} request sent for PID ${selectedPid}.`);
  } catch (error) {
    setStatus(error.message, true);
  }
}

function renderReadyQueue(timeline, processes) {
  const finalQueue = timeline.at(-1)?.ready_queue || [];
  const names = new Map(processes.map((process) => [process.pid, process.name]));
  const container = host.querySelector(".ready-queue");
  container.replaceChildren();
  if (!finalQueue.length) {
    container.textContent = "Queue empty · all processes completed";
    return;
  }
  for (const pid of finalQueue) {
    const item = document.createElement("span");
    item.className = "queue-process";
    item.textContent = `${pid} · ${names.get(pid)}`;
    container.append(item);
  }
}

function renderGantt(lanes, elapsed) {
  const chart = host.querySelector(".gantt-chart");
  chart.replaceChildren();
  for (const [core, segments] of lanes.entries()) {
    const lane = document.createElement("div");
    lane.className = "gantt-lane";
    const label = document.createElement("span");
    label.className = "gantt-core-label";
    label.textContent = `CPU ${core + 1}`;
    const track = document.createElement("div");
    track.className = "gantt-track";
    track.style.setProperty("--elapsed", String(elapsed));
    for (const segment of segments) {
      const bar = document.createElement("div");
      bar.className = "gantt-segment";
      bar.style.left = `${(segment.start / elapsed) * 100}%`;
      bar.style.width = `${((segment.end - segment.start) / elapsed) * 100}%`;
      bar.style.backgroundColor = colorForPid(segment.pid);
      bar.title = `${segment.name} · PID ${segment.pid} · ${segment.start}–${segment.end}`;
      const name = document.createElement("span");
      name.textContent = segment.name;
      const duration = document.createElement("small");
      duration.textContent = `${segment.start}–${segment.end}`;
      bar.append(name, duration);
      track.append(bar);
    }
    lane.append(label, track);
    chart.append(lane);
  }
  const axis = document.createElement("div");
  axis.className = "gantt-axis";
  axis.textContent = `Time units 0 → ${elapsed}`;
  chart.append(axis);
}

function renderTimeline(timeline, processes) {
  const container = host.querySelector(".schedule-timeline");
  container.replaceChildren();
  const names = new Map(processes.map((process) => [process.pid, process.name]));
  const rows = timeline.length > 100 ? timeline.filter((_, index) => index % Math.ceil(timeline.length / 100) === 0) : timeline;
  for (const tick of rows) {
    const row = document.createElement("div");
    row.className = "timeline-tick";
    const time = document.createElement("span");
    time.textContent = `t=${tick.time}`;
    const cores = document.createElement("span");
    cores.textContent = tick.cores.map((core, index) => `CPU ${index + 1}: ${core.pid ? names.get(core.pid) : "Idle"}`).join(" · ");
    const ready = document.createElement("small");
    ready.textContent = `Ready: ${tick.ready_queue.length ? tick.ready_queue.map((pid) => names.get(pid)).join(", ") : "—"}`;
    row.append(time, cores, ready);
    container.append(row);
  }
}

function colorForPid(pid) {
  return COLORS[pid % COLORS.length];
}

function setStatus(message, isError = false) {
  const status = host.querySelector("[data-scheduler-status]");
  status.textContent = message;
  status.classList.toggle("error", isError);
}
