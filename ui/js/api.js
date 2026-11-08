const listeners = new Set();
let socket;
let requestSequence = 0;

export function connect() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
  socket.addEventListener("message", (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch (error) {
      console.error("Invalid event received from LibraOS kernel", error);
      return;
    }
    for (const listener of listeners) listener(event);
  });
  socket.addEventListener("open", () => notify({ type: "connection", connected: true }));
  socket.addEventListener("close", () => notify({ type: "connection", connected: false }));
  socket.addEventListener("error", () => notify({ type: "connection", connected: false }));
}

export function onEvent(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function sendCommand(command) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `cmd-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "command", request_id: requestId, command }));
  return requestId;
}

export function sendPowerAction(action) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  socket.send(JSON.stringify({ type: "power", action }));
}

export function sendFileSystemRequest(operation, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `fs-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({
    type: "filesystem",
    request_id: requestId,
    operation,
    owner: "guest",
    ...fields,
  }));
  return requestId;
}

export function sendScheduleRequest(workload, options = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `sched-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({
    type: "schedule",
    request_id: requestId,
    workload,
    algorithm: options.algorithm || "fcfs",
    quantum: options.quantum || 3,
    cores: options.cores || 1,
  }));
  return requestId;
}

export function sendProcessRequest() {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `proc-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "processes", request_id: requestId }));
  return requestId;
}

export function sendProcessAction(operation, pid, priority) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `proc-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "process_action", request_id: requestId, operation, pid, priority }));
  return requestId;
}

export function sendSyncRequest(operation, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `sync-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "sync", request_id: requestId, operation, ...fields }));
  return requestId;
}

export function sendResourceRequest(operation, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `resource-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "resource", request_id: requestId, operation, ...fields }));
  return requestId;
}

export function sendSecurityRequest(operation, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `security-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "security", request_id: requestId, operation, ...fields }));
  return requestId;
}

export function sendLibraryRequest(operation, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `library-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "library", request_id: requestId, operation, ...fields }));
  return requestId;
}

export function sendObservabilityRequest(operation = "snapshot") {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `observe-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "observability", request_id: requestId, operation }));
  return requestId;
}

export function sendScenarioRequest(operation, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `scenario-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "scenario", request_id: requestId, operation, ...fields }));
  return requestId;
}

export function sendSyscallRequest(name, fields = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    throw new Error("Kernel connection is not available");
  }
  const requestId = `syscall-${Date.now()}-${++requestSequence}`;
  socket.send(JSON.stringify({ type: "syscall", request_id: requestId, syscall: name, ...fields }));
  return requestId;
}

function notify(event) {
  for (const listener of listeners) listener(event);
}
