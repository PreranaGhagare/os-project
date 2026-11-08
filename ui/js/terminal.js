import { onEvent, sendCommand } from "./api.js";
import { openWindow } from "./windowManager.js";

let outputElement;
let inputElement;
let history = [];
let historyIndex = 0;

export function openTerminal() {
  const terminal = document.createElement("div");
  terminal.className = "terminal";
  terminal.innerHTML = `
    <div class="terminal-output" aria-live="polite">
      <div class="terminal-line welcome">LibraOS Terminal · Stage 9</div>
      <div class="terminal-line muted">Kernel shell connected. Type <b>help</b> to see available commands.</div>
      <div class="terminal-line muted">Library records are stored on the simulated persistent disk.</div>
      <div class="terminal-line">&nbsp;</div>
    </div>
    <form class="terminal-form">
      <label for="terminal-input">guest@libraos:~$</label>
      <input id="terminal-input" autocomplete="off" spellcheck="false" aria-label="Terminal command">
      <span class="terminal-cursor"></span>
    </form>`;
  const host = openWindow("terminal", terminal, { width: 690, height: 440 });
  outputElement = host.querySelector(".terminal-output");
  inputElement = host.querySelector("#terminal-input");
  host.querySelector(".terminal-form").addEventListener("submit", submitCommand);
  inputElement.focus();
  return host;
}

export function handleTerminalEvent(event) {
  if (event.type !== "terminal" || !outputElement) return;
  if (event.clear) {
    outputElement.replaceChildren();
    return;
  }
  appendLine(`guest@libraos:~$ ${event.command}`, "command-line");
  for (const line of event.output) {
    appendLine(line, event.exit_code === 0 ? "" : "error");
  }
  if (event.action) {
    appendLine("Power control is available from the LibraOS Start menu.", "muted");
  }
}

export function terminalFocus() {
  inputElement?.focus();
}

function submitCommand(event) {
  event.preventDefault();
  const command = inputElement.value.trim();
  if (!command) return;
  history.push(command);
  historyIndex = history.length;
  try {
    sendCommand(command);
    inputElement.value = "";
  } catch (error) {
    appendLine(error.message, "error");
  }
}

function appendLine(text, className = "") {
  if (!outputElement) return;
  const line = document.createElement("div");
  line.className = `terminal-line ${className}`.trim();
  line.textContent = text || "\u00a0";
  outputElement.append(line);
  outputElement.scrollTop = outputElement.scrollHeight;
}

document.addEventListener("keydown", (event) => {
  if (document.activeElement !== inputElement || !inputElement) return;
  if (event.key === "ArrowUp") {
    event.preventDefault();
    historyIndex = Math.max(0, historyIndex - 1);
    inputElement.value = history[historyIndex] ?? "";
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    historyIndex = Math.min(history.length, historyIndex + 1);
    inputElement.value = history[historyIndex] ?? "";
  } else if (event.ctrlKey && event.key.toLowerCase() === "l") {
    event.preventDefault();
    outputElement.replaceChildren();
  }
});

onEvent(handleTerminalEvent);
