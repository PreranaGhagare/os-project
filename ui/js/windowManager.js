const windows = new Map();
let activeWindowId = null;
let zIndex = 10;
let presentationReturnFocus = null;

const icons = {
  terminal: '<span class="menu-app-icon terminal-icon">›_</span>',
  "kernel-log": '<span class="menu-app-icon log-icon">≋</span>',
  "file-explorer": '<span class="menu-app-icon files-icon">▰</span>',
  "task-manager": '<span class="menu-app-icon task-icon">▥</span>',
  "sync-monitor": '<span class="menu-app-icon sync-icon">⇄</span>',
  "system-monitor": '<span class="menu-app-icon system-icon">▤</span>',
  security: '<span class="menu-app-icon about-icon">⛨</span>',
  observability: '<span class="menu-app-icon log-icon">⌁</span>',
  scenarios: '<span class="menu-app-icon task-icon">⇆</span>',
  "session-studio": '<span class="menu-app-icon task-icon">▶</span>',
  about: '<span class="menu-app-icon about-icon">i</span>',
};

const titles = {
  terminal: "Terminal",
  "kernel-log": "Kernel Log",
  "file-explorer": "File Explorer",
  "task-manager": "Task Manager",
  "sync-monitor": "Sync Monitor",
  "system-monitor": "Resource Monitor",
  security: "Security",
  observability: "Trace & Journal",
  scenarios: "Scenario Lab",
  "session-studio": "Session Studio",
  about: "About LibraOS",
};

export function openWindow(id, content, options = {}) {
  const existing = windows.get(id);
  if (existing) {
    if (existing.minimized) restoreWindow(id);
    focusWindow(id);
    return existing.content;
  }

  const layer = document.querySelector("#window-layer");
  const frame = document.createElement("section");
  frame.className = "os-window";
  frame.dataset.windowId = id;
  frame.setAttribute("role", "region");
  frame.setAttribute("aria-label", titles[id] || id);
  frame.style.zIndex = String(++zIndex);
  const availableWidth = layer.clientWidth;
  const availableHeight = layer.clientHeight;
  const width = Math.min(options.width ?? 650, Math.max(300, availableWidth - 24));
  const height = Math.min(options.height ?? 430, Math.max(220, availableHeight - 16));
  frame.style.width = `${Math.max(300, width)}px`;
  frame.style.height = `${Math.max(220, height)}px`;
  const maxLeft = Math.max(8, availableWidth - width - 8);
  const maxTop = Math.max(8, availableHeight - height - 8);
  frame.style.left = `${Math.min(maxLeft, Math.max(8, (availableWidth - width) / 2 + windows.size * 22))}px`;
  frame.style.top = `${Math.min(maxTop, Math.max(8, (availableHeight - height) / 2 + windows.size * 18))}px`;
  frame.innerHTML = `
    <header class="window-titlebar" tabindex="-1">
      <div class="window-title">${icons[id]}<span>${titles[id]}</span></div>
      <div class="window-controls">
        <button class="minimize-window" aria-label="Minimize window">−</button>
        <button class="maximize-window" aria-label="Maximize window">□</button>
        <button class="close-window" aria-label="Close window">×</button>
      </div>
    </header>
    <div class="window-content"></div>`;
  const contentHost = frame.querySelector(".window-content");
  contentHost.append(content);
  layer.append(frame);

  const taskButton = document.createElement("button");
  taskButton.className = "taskbar-window";
  taskButton.innerHTML = `${icons[id]}<span>${titles[id]}</span>`;
  taskButton.addEventListener("click", () => {
    if (windows.get(id)?.minimized) restoreWindow(id);
    else if (activeWindowId === id) minimizeWindow(id);
    else focusWindow(id);
  });
  document.querySelector("#taskbar-windows").append(taskButton);

  const record = { frame, content: contentHost, taskButton, minimized: false, maximized: false };
  windows.set(id, record);
  frame.addEventListener("pointerdown", () => focusWindow(id));
  frame.querySelector(".close-window").addEventListener("click", () => closeWindow(id));
  frame.querySelector(".minimize-window").addEventListener("click", () => minimizeWindow(id));
  frame.querySelector(".maximize-window").addEventListener("click", () => toggleMaximize(id));
  enableDragging(frame, frame.querySelector(".window-titlebar"));
  focusWindow(id);
  return contentHost;
}

export function focusWindow(id) {
  const record = windows.get(id);
  if (!record) return;
  activeWindowId = id;
  record.frame.style.zIndex = String(++zIndex);
  for (const [windowId, item] of windows) {
    item.frame.classList.toggle(
      "presentation-window",
      document.body.classList.contains("presentation-mode") && windowId === id,
    );
    item.taskButton.classList.toggle("active", windowId === id && !item.minimized);
  }
}

export function closeWindow(id) {
  const record = windows.get(id);
  if (!record) return;
  record.frame.remove();
  record.taskButton.remove();
  windows.delete(id);
  if (activeWindowId === id) activeWindowId = null;
}

export function setPresentationMode(enabled) {
  if (enabled === document.body.classList.contains("presentation-mode")) return;
  if (enabled && !activeWindowId) return;
  if (enabled) {
    presentationReturnFocus = document.activeElement;
    document.querySelector("#start-menu").classList.add("hidden");
    document.querySelector("#power-menu").classList.add("hidden");
  }
  document.body.classList.toggle("presentation-mode", enabled);
  const toggle = document.querySelector("#presentation-toggle");
  toggle.setAttribute("aria-pressed", String(enabled));
  toggle.textContent = enabled ? "Exit presentation" : "Presentation";
  for (const [id, record] of windows) {
    record.frame.classList.toggle("presentation-window", enabled && id === activeWindowId);
  }
  if (enabled) {
    windows.get(activeWindowId)?.frame.querySelector(".window-titlebar").focus();
    return;
  }
  const returnFocus = presentationReturnFocus;
  presentationReturnFocus = null;
  if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
  else toggle.focus();
}

function minimizeWindow(id) {
  const record = windows.get(id);
  if (!record) return;
  record.frame.classList.add("hidden");
  record.minimized = true;
  record.taskButton.classList.remove("active");
  activeWindowId = null;
}

function restoreWindow(id) {
  const record = windows.get(id);
  if (!record) return;
  record.frame.classList.remove("hidden");
  record.minimized = false;
  focusWindow(id);
}

function toggleMaximize(id) {
  const record = windows.get(id);
  if (!record) return;
  record.maximized = !record.maximized;
  record.frame.classList.toggle("window-maximized", record.maximized);
  record.frame.querySelector(".maximize-window").textContent = record.maximized ? "❐" : "□";
}

function enableDragging(frame, handle) {
  let origin;
  handle.addEventListener("pointerdown", (event) => {
    if (event.target.closest(".window-controls") || frame.classList.contains("window-maximized")) return;
    origin = {
      x: event.clientX,
      y: event.clientY,
      left: frame.offsetLeft,
      top: frame.offsetTop,
    };
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", (event) => {
    if (!origin) return;
    const maxLeft = Math.max(0, window.innerWidth - 120);
    const maxTop = Math.max(45, window.innerHeight - 90);
    frame.style.left = `${Math.min(maxLeft, Math.max(0, origin.left + event.clientX - origin.x))}px`;
    frame.style.top = `${Math.min(maxTop, Math.max(45, origin.top + event.clientY - origin.y))}px`;
  });
  const stopDragging = () => { origin = null; };
  handle.addEventListener("pointerup", stopDragging);
  handle.addEventListener("pointercancel", stopDragging);
}
