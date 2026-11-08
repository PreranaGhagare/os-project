import { onEvent, sendSyncRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

let host;
let currentState = { resources: [], wait_for: [], deadlocked_pids: [], processes: [] };

export function openSyncMonitor() {
  const panel = document.createElement("section");
  panel.className = "sync-monitor";
  panel.innerHTML = `
    <header class="sync-toolbar">
      <label>Process<select data-control="process"></select></label>
      <label>Resource<select data-control="resource"></select></label>
      <button data-action="acquire">Acquire</button>
      <button data-action="release">Release</button>
      <button data-action="refresh">Refresh</button>
    </header>
    <form class="sync-create-form">
      <label>Resource name<input data-control="resource-name" maxlength="32" value="demo-lock"></label>
      <label>Type<select data-control="resource-kind"><option value="mutex">Mutex</option><option value="semaphore">Semaphore</option></select></label>
      <label>Permits<input data-control="capacity" type="number" min="1" max="16" value="1" disabled></label>
      <button type="submit">Create resource</button>
    </form>
    <p class="sync-status" data-sync-status role="status" aria-live="polite">Loading synchronization state…</p>
    <section class="sync-resource-panel">
      <h3>Resources and ownership</h3>
      <div class="sync-table-wrap"><table class="sync-table">
        <thead><tr><th>Resource</th><th>Type</th><th>Available</th><th>Holders</th><th>Wait queue</th></tr></thead>
        <tbody data-resource-rows></tbody>
      </table></div>
    </section>
    <section class="sync-deadlock-panel">
      <div class="sync-section-heading"><h3>Deadlock manager</h3>
        <button data-action="deadlock-demo">Create deadlock demo</button>
        <button data-action="detect">Detect</button>
        <button data-action="recover" class="sync-recover">Recover one victim</button>
      </div>
      <p data-deadlock-status>No deadlock detected.</p>
      <h4>Wait-for relationships</h4><div class="sync-wait-graph" data-wait-graph></div>
    </section>
    <section class="sync-race-panel">
      <div class="sync-section-heading"><h3>Race-condition demo</h3>
        <button data-action="race-demo">Run comparison</button>
      </div>
      <div data-race-result class="sync-race-result">Run the demo to compare an interleaved counter with mutex-protected updates.</div>
    </section>`;

  host = openWindow("sync-monitor", panel, { width: 900, height: 600 });
  host.classList.add("sync-monitor-window");
  host.querySelector('[data-control="resource-kind"]').addEventListener("change", updateCapacityControl);
  host.querySelector(".sync-create-form").addEventListener("submit", (event) => {
    event.preventDefault();
    request("create", {
      name: host.querySelector('[data-control="resource-name"]').value.trim(),
      kind: host.querySelector('[data-control="resource-kind"]').value,
      capacity: Number(host.querySelector('[data-control="capacity"]').value),
    });
  });
  host.querySelector('[data-action="acquire"]').addEventListener("click", () => requestResourceAction("acquire"));
  host.querySelector('[data-action="release"]').addEventListener("click", () => requestResourceAction("release"));
  host.querySelector('[data-action="refresh"]').addEventListener("click", () => request("state"));
  host.querySelector('[data-action="detect"]').addEventListener("click", () => request("detect"));
  host.querySelector('[data-action="recover"]').addEventListener("click", () => request("recover"));
  host.querySelector('[data-action="deadlock-demo"]').addEventListener("click", () => request("deadlock_demo"));
  host.querySelector('[data-action="race-demo"]').addEventListener("click", () => request("race_demo"));
  renderState(currentState);
  request("state");
  return host;
}

onEvent((event) => {
  if ((event.type === "sync_result" || event.type === "sync_state") && host?.isConnected) {
    currentState = event;
    renderState(currentState);
    if (event.type === "sync_result") {
      renderOperationResult(event);
    }
  }
});

function request(operation, fields = {}) {
  try {
    sendSyncRequest(operation, fields);
    setStatus("Kernel synchronization request sent.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function requestResourceAction(operation) {
  const pid = Number(host.querySelector('[data-control="process"]').value);
  const name = host.querySelector('[data-control="resource"]').value;
  if (!Number.isInteger(pid) || !name) {
    setStatus("Choose an active process and a resource.", true);
    return;
  }
  request(operation, { pid, name });
}

function renderState(state) {
  if (!host?.isConnected) return;
  const activeProcesses = state.processes.filter((process) => process.state !== "TERMINATED");
  const processSelect = host.querySelector('[data-control="process"]');
  const selectedPid = processSelect.value;
  processSelect.replaceChildren();
  for (const process of activeProcesses) {
    const option = document.createElement("option");
    option.value = String(process.pid);
    option.textContent = `PID ${process.pid} · ${process.name} (${process.state})`;
    processSelect.append(option);
  }
  if (activeProcesses.some((process) => String(process.pid) === selectedPid)) {
    processSelect.value = selectedPid;
  }
  processSelect.disabled = activeProcesses.length === 0;

  const resourceSelect = host.querySelector('[data-control="resource"]');
  const selectedResource = resourceSelect.value;
  resourceSelect.replaceChildren();
  for (const resource of state.resources) {
    const option = document.createElement("option");
    option.value = resource.name;
    option.textContent = `${resource.name} · ${resource.kind}`;
    resourceSelect.append(option);
  }
  if (state.resources.some((resource) => resource.name === selectedResource)) {
    resourceSelect.value = selectedResource;
  }

  const rows = host.querySelector("[data-resource-rows]");
  rows.replaceChildren();
  for (const resource of state.resources) {
    const row = document.createElement("tr");
    appendCell(row, resource.name);
    appendCell(row, resource.kind);
    appendCell(row, `${resource.available} / ${resource.capacity}`);
    appendCell(row, formatPidList(resource.holders.map((holder) => `PID ${holder.pid} ×${holder.count}`)));
    appendCell(row, formatPidList(resource.waiters.map((waiter) => `PID ${waiter.pid}`)));
    rows.append(row);
  }
  if (!state.resources.length) {
    const row = document.createElement("tr");
    appendCell(row, "No synchronization resources", "sync-empty", 5);
    rows.append(row);
  }

  const deadlocked = state.deadlocked_pids || [];
  const deadlockStatus = host.querySelector("[data-deadlock-status]");
  deadlockStatus.textContent = deadlocked.length
    ? `Deadlock detected: ${deadlocked.map((pid) => `PID ${pid}`).join(", ")}`
    : "No deadlock detected.";
  deadlockStatus.classList.toggle("sync-deadlocked", deadlocked.length > 0);

  const processesByPid = new Map(state.processes.map((process) => [process.pid, process.name]));
  const graph = host.querySelector("[data-wait-graph]");
  graph.replaceChildren();
  if (!state.wait_for.length) {
    graph.textContent = "No processes are waiting on held resources.";
  } else {
    for (const edge of state.wait_for) {
      const line = document.createElement("div");
      line.textContent = `${processesByPid.get(edge.from_pid) || `PID ${edge.from_pid}`} → `
        + `${processesByPid.get(edge.to_pid) || `PID ${edge.to_pid}`} · ${edge.resource}`;
      graph.append(line);
    }
  }
}

function renderOperationResult(event) {
  if (!event.ok) {
    setStatus(event.error, true);
    return;
  }
  const result = event.result || {};
  if (event.operation === "state") {
    setStatus("Synchronization state refreshed.");
  } else if (event.operation === "acquire") {
    setStatus(
      result.acquired
        ? `PID ${result.pid} acquired ${result.resource}.`
        : `PID ${result.pid} is blocked on ${result.resource}.`,
      !result.acquired,
    );
  } else if (event.operation === "release") {
    setStatus(
      `PID ${result.pid} released ${result.resource}.`
      + (result.awakened_pids.length ? ` Woke PID ${result.awakened_pids.join(", ")}.` : ""),
    );
  } else if (event.operation === "detect") {
    setStatus(result.deadlocked_pids.length
      ? `Deadlock detected among PIDs ${result.deadlocked_pids.join(", ")}.`
      : "Deadlock scan complete: no deadlock detected.");
  } else if (event.operation === "recover") {
    setStatus(result.recovered
      ? `Terminated PID ${result.victim_pid} (${result.victim_name}) and released its resources.`
      : "Recovery complete: no deadlock to recover.");
  } else if (event.operation === "deadlock_demo") {
    setStatus(`Demo created for PIDs ${result.processes.join(" and ")}. Run detection, then recover.`);
  } else if (event.operation === "create") {
    setStatus("Synchronization resource created.");
  } else if (event.operation === "race_demo") {
    renderRaceResult(result);
    setStatus("Race-condition comparison complete.");
  }
}

function renderRaceResult(result) {
  const panel = host.querySelector("[data-race-result]");
  panel.replaceChildren();
  const summary = document.createElement("p");
  summary.textContent = `Without a mutex: ${result.unsafe_counter} (expected ${result.expected_counter}). `
    + `With a mutex: ${result.safe_counter}.`;
  panel.append(summary);
  const columns = document.createElement("div");
  columns.className = "sync-race-columns";
  columns.append(createTrace("Interleaved updates", result.unsafe_trace));
  columns.append(createTrace("Mutex-protected updates", result.safe_trace));
  panel.append(columns);
}

function createTrace(title, trace) {
  const section = document.createElement("section");
  const heading = document.createElement("h4");
  heading.textContent = title;
  const list = document.createElement("ol");
  for (const step of trace) {
    const item = document.createElement("li");
    item.textContent = `${step.process}: ${step.action} → ${step.value}`;
    list.append(item);
  }
  section.append(heading, list);
  return section;
}

function updateCapacityControl() {
  const kind = host.querySelector('[data-control="resource-kind"]').value;
  const capacity = host.querySelector('[data-control="capacity"]');
  capacity.disabled = kind === "mutex";
  capacity.value = kind === "mutex" ? "1" : "2";
}

function appendCell(row, text, className = "", colSpan = 1) {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) cell.className = className;
  cell.colSpan = colSpan;
  row.append(cell);
}

function formatPidList(items) {
  return items.length ? items.join(", ") : "—";
}

function setStatus(message, isError = false) {
  if (!host?.isConnected) return;
  const status = host.querySelector("[data-sync-status]");
  status.textContent = message;
  status.classList.toggle("error", isError);
}
