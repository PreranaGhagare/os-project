import { onEvent, sendPowerAction } from "./api.js";
import { openWindow, setPresentationMode } from "./windowManager.js";
import { openTerminal, terminalFocus } from "./terminal.js?v=stage9-1";
import { openFileExplorer } from "./fileExplorer.js";
import { openTaskManager } from "./taskManager.js?v=stage8-1";
import { openSyncMonitor } from "./syncMonitor.js?v=stage8-1";
import { openSystemMonitor } from "./systemMonitor.js?v=stage8-1";
import { openSecurityPanel } from "./security.js?v=security-hardening-1";
import { openLibrary } from "./library.js";
import { openObservability } from "./observability.js";
import { openScenarioLab } from "./scenarios.js";
import { openSessionStudio } from "./sessionStudio.js";

const bootScreen = document.querySelector("#boot-screen");
const desktop = document.querySelector("#desktop");
const bootLog = document.querySelector("#boot-log");
const bootProgress = document.querySelector("#boot-progress");
const bootStatus = document.querySelector("#boot-status");
const powerScreen = document.querySelector("#power-screen");
const seenLogs = new Set();
const kernelLogs = [];
let bootFinished = false;
let rebootPending = false;
let rebootEvents = [];
window.__libraOSRecentEvents = [];

export function initialize(snapshot) {
  const bootEvents = snapshot.events.filter((event) => event.type === "log");
  bootEvents.forEach((event) => addKernelLog(event, false));
  window.__libraOSRecentEvents = snapshot.events || [];
  updateUserStatus({ result: { username: "guest", role: "guest" } });
  playBoot(bootEvents);
}

export function handleDesktopEvent(event) {
  if (!event || !event.type) return;
  window.__libraOSRecentEvents = [...(window.__libraOSRecentEvents || []), event].slice(-200);
  if (event.type === "log") {
    if (rebootPending && event.module !== "power") rebootEvents.push(event);
    addKernelLog(event, true);
  } else if (event.type === "system" && event.status === "running") {
    bootStatus.textContent = event.message;
    if (rebootPending) {
      rebootPending = false;
      powerScreen.classList.add("hidden");
      desktop.classList.add("hidden");
      bootScreen.classList.remove("hidden");
      bootFinished = false;
      bootLog.replaceChildren();
      bootProgress.style.width = "0%";
      playBoot(rebootEvents);
      rebootEvents = [];
    }
  } else if (event.type === "connection") {
    document.querySelector("#connection-dot").classList.toggle("disconnected", !event.connected);
    document.querySelector("#connection-label").textContent = event.connected ? "Kernel connected" : "Kernel disconnected";
  } else if (event.type === "security_result") {
    updateUserStatus(event);
  } else if (event.type === "power") {
    if (event.action === "error") {
      document.querySelector("#connection-label").textContent = event.message;
    } else {
      showPowerScreen(event.action);
    }
  }
}

function updateUserStatus(event) {
  const result = event.result || {};
  const username = result.username || result.current_user || event.current_user || "guest";
  const role = (result.role || event.role || "guest").toString().toUpperCase();
  const userLabel = document.querySelector(".top-system b");
  const rolePill = document.querySelector(".role-pill");
  const startUser = document.querySelector("#start-user");
  if (userLabel) userLabel.textContent = username;
  if (rolePill) rolePill.textContent = role;
  if (startUser) startUser.textContent = `${username} · ${role.toLowerCase()} session`;
}

export function openApp(id) {
  if (id === "terminal") return openTerminal();
  if (id === "kernel-log") return openKernelLog();
  if (id === "file-explorer") return openFileExplorer();
  if (id === "task-manager") return openTaskManager();
  if (id === "sync-monitor") return openSyncMonitor();
  if (id === "system-monitor") return openSystemMonitor();
  if (id === "security") return openSecurityPanel();
  if (id === "library") return openLibrary();
  if (id === "observability") return openObservability();
  if (id === "scenarios") return openScenarioLab();
  if (id === "session-studio") return openSessionStudio();
  if (id === "about") return openAbout();
  return null;
}

function playBoot(events) {
  if (!events.length) {
    finishBoot();
    return;
  }
  bootLog.replaceChildren();
  let index = 0;
  const next = () => {
    if (bootFinished) return;
    const event = events[index];
    if (!event) {
      finishBoot();
      return;
    }
    appendBootLine(event);
    index += 1;
    bootProgress.style.width = `${Math.round((index / events.length) * 100)}%`;
    bootStatus.textContent = index === events.length ? "Starting desktop..." : "Initializing system...";
    window.setTimeout(next, 230);
  };
  next();
}

function finishBoot() {
  if (bootFinished) return;
  bootFinished = true;
  bootProgress.style.width = "100%";
  bootScreen.classList.add("hidden");
  desktop.classList.remove("hidden");
  openTerminal();
}

function appendBootLine(event) {
  const row = document.createElement("div");
  row.className = "boot-line";
  const time = document.createElement("span");
  time.className = "boot-time";
  time.textContent = `[${formatTime(event.timestamp)}] `;
  const status = document.createElement("span");
  status.className = "boot-ok";
  status.textContent = " OK ";
  const message = document.createElement("span");
  message.textContent = event.message;
  row.append(time, status, message);
  bootLog.append(row);
  bootLog.scrollTop = bootLog.scrollHeight;
}

function addKernelLog(event, appendToWindow) {
  const key = `${event.timestamp}:${event.module}:${event.message}`;
  if (seenLogs.has(key)) return;
  seenLogs.add(key);
  kernelLogs.push(event);
  if (!appendToWindow) return;
  const body = document.querySelector("#kernel-log-body");
  if (body) body.append(createLogRow(event));
}

function openKernelLog() {
  const container = document.createElement("div");
  container.className = "kernel-log";
  container.id = "kernel-log-body";
  kernelLogs.forEach((event) => container.append(createLogRow(event)));
  return openWindow("kernel-log", container, { width: 800, height: 420 });
}

function createLogRow(event) {
  const row = document.createElement("div");
  row.className = `kernel-log-row ${event.severity}`;
  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = formatTime(event.timestamp);
  const module = document.createElement("span");
  module.className = "log-module";
  module.textContent = event.module;
  const severity = document.createElement("span");
  severity.className = "log-severity";
  severity.textContent = event.severity.toUpperCase();
  const message = document.createElement("span");
  message.textContent = event.message;
  row.append(time, module, severity, message);
  return row;
}

function openAbout() {
  const panel = document.createElement("div");
  panel.className = "about-panel";
  panel.innerHTML = `
    <span class="brand-mark">L</span>
    <p class="about-version">LIBRAOS · VERSION 0.1.0 · STAGE 9</p>
    <h2>A library system with an operating system at its core.</h2>
    <p>LibraOS is a teaching simulation for exploring operating-system concepts through a desktop environment for a library management system.</p>
    <p class="stage-note"><b>Current stage:</b> presentation mode, session export/replay, and simulated operating-system services.</p>`;
  return openWindow("about", panel, { width: 490, height: 370 });
}

function showPowerScreen(action) {
  powerScreen.classList.remove("hidden");
  const rebooting = action === "reboot";
  document.querySelector("#power-title").textContent = rebooting ? "LibraOS is restarting" : "LibraOS is shut down";
  document.querySelector("#power-message").textContent = rebooting ? "The kernel is restarting..." : "The simulated kernel is stopped.";
  document.querySelector("#power-on").classList.toggle("hidden", rebooting);
  if (rebooting) {
    rebootPending = true;
    rebootEvents = [];
    bootStatus.textContent = "Restarting...";
  }
}

document.querySelectorAll("[data-open]").forEach((button) => {
  button.addEventListener("click", () => {
    openApp(button.dataset.open);
    document.querySelector("#start-menu").classList.add("hidden");
  });
});

document.querySelectorAll("#top-start, #taskbar-start").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#start-menu").classList.toggle("hidden");
    document.querySelector("#power-menu").classList.add("hidden");
  });
});

document.querySelector("#power-button").addEventListener("click", () => {
  document.querySelector("#power-menu").classList.toggle("hidden");
});

document.querySelectorAll("[data-power]").forEach((button) => {
  button.addEventListener("click", () => {
    try {
      sendPowerAction(button.dataset.power);
    } catch (error) {
      document.querySelector("#connection-label").textContent = error.message;
    }
    document.querySelector("#power-menu").classList.add("hidden");
  });
});

document.querySelector("#power-on").addEventListener("click", () => {
  try {
    sendPowerAction("reboot");
    document.querySelector("#power-message").textContent = "The kernel is restarting...";
    document.querySelector("#power-on").classList.add("hidden");
  } catch (error) {
    document.querySelector("#power-message").textContent = error.message;
  }
});

document.querySelector("#skip-boot").addEventListener("click", finishBoot);
document.querySelector("#theme-toggle").addEventListener("click", () => document.body.classList.toggle("light-theme"));
document.querySelector("#presentation-toggle").addEventListener("click", () => setPresentationMode(true));
document.querySelector("#presentation-exit").addEventListener("click", () => setPresentationMode(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("presentation-mode")) {
    setPresentationMode(false);
  } else if (event.code === "Space" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    event.preventDefault();
    terminalFocus();
  } else if (event.key.toLowerCase() === "t" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    openTerminal();
    terminalFocus();
  } else if (event.key === "Escape") {
    document.querySelector("#start-menu").classList.add("hidden");
    document.querySelector("#power-menu").classList.add("hidden");
  }
});

function formatTime(timestamp) {
  return new Date(timestamp).toLocaleTimeString([], { hour12: false });
}

function updateClock() {
  const now = new Date();
  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  document.querySelector("#clock").textContent = time;
  document.querySelector("#tray-clock").textContent = time;
}

updateClock();
window.setInterval(updateClock, 15_000);
onEvent(handleDesktopEvent);
