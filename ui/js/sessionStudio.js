import { openWindow } from "./windowManager.js";
import {
  MAX_SESSION_EVENTS,
  MAX_SESSION_FILE_BYTES,
  SESSION_ARCHIVE_FORMAT,
  SESSION_ARCHIVE_VERSION,
  normalizeEvent,
  validateArchive,
} from "./sessionArchive.mjs";

export function openSessionStudio() {
  const panel = document.createElement("section");
  panel.className = "session-studio";
  panel.innerHTML = `
    <header class="session-heading">
      <div>
        <h2>Session Studio</h2>
        <p>Export a sanitized event timeline or replay one as a visual walkthrough.</p>
      </div>
      <span class="session-count"></span>
    </header>
    <div class="session-actions">
      <button type="button" data-action="export">Export session</button>
      <button type="button" data-action="import">Import replay</button>
      <button type="button" data-action="play">Play</button>
      <button type="button" data-action="pause" disabled>Pause</button>
      <button type="button" data-action="step">Next event</button>
      <button type="button" data-action="stop">Stop</button>
      <label class="session-speed">Speed
        <select aria-label="Replay speed">
          <option value="1">1×</option>
          <option value="2">2×</option>
          <option value="4">4×</option>
        </select>
      </label>
      <input class="session-file-input" type="file" accept="application/json,.json" hidden>
    </div>
    <p class="session-notice" role="status" aria-live="polite"></p>
    <p class="session-privacy">Archives include event types and selected metrics only. Commands, file contents, and result payloads are excluded. Replay never sends requests to the kernel.</p>
    <ol class="session-timeline" aria-label="Session event timeline"></ol>`;

  const notice = panel.querySelector(".session-notice");
  const timeline = panel.querySelector(".session-timeline");
  const count = panel.querySelector(".session-count");
  const fileInput = panel.querySelector(".session-file-input");
  const pauseButton = panel.querySelector('[data-action="pause"]');
  const speedSelect = panel.querySelector(".session-speed select");
  let events = currentEvents();
  let cursor = -1;
  let timer = null;
  let playing = false;

  function setNotice(message, isError = false) {
    notice.textContent = message;
    notice.classList.toggle("error", isError);
  }

  function renderTimeline() {
    timeline.replaceChildren();
    count.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
    events.forEach((event, index) => {
      const item = document.createElement("li");
      item.className = "session-event";
      item.dataset.index = String(index);
      if (index === cursor) item.classList.add("current");
      const time = document.createElement("time");
      time.dateTime = event.timestamp;
      time.textContent = new Date(event.timestamp).toLocaleTimeString([], { hour12: false });
      const description = document.createElement("span");
      description.className = "session-event-description";
      description.textContent = describeEvent(event);
      item.append(time, description);
      timeline.append(item);
    });
    timeline.querySelector(".session-event.current")?.scrollIntoView({ block: "nearest" });
  }

  function stopPlayback() {
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
    playing = false;
    pauseButton.disabled = true;
  }

  function advance() {
    if (cursor + 1 >= events.length) {
      stopPlayback();
      setNotice("Replay finished.");
      return;
    }
    cursor += 1;
    renderTimeline();
    setNotice(`Replaying event ${cursor + 1} of ${events.length}.`);
    if (playing && cursor + 1 < events.length) {
      const currentTime = Date.parse(events[cursor].timestamp);
      const nextTime = Date.parse(events[cursor + 1].timestamp);
      const delay = Math.min(2000, Math.max(100, (nextTime - currentTime) / Number(speedSelect.value)));
      timer = window.setTimeout(advance, delay);
    } else if (playing) {
      stopPlayback();
      setNotice("Replay finished.");
    }
  }

  panel.querySelector('[data-action="export"]').addEventListener("click", () => {
    const source = currentEvents();
    const normalized = source.map(normalizeEvent).filter(Boolean).slice(-MAX_SESSION_EVENTS);
    const archive = {
      format: SESSION_ARCHIVE_FORMAT,
      version: SESSION_ARCHIVE_VERSION,
      created_at: new Date().toISOString(),
      events: normalized,
    };
    const blob = new Blob([`${JSON.stringify(archive, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "libraos-session.json";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    events = normalized;
    cursor = -1;
    renderTimeline();
    setNotice(`Exported ${events.length} sanitized events.`);
  });

  panel.querySelector('[data-action="import"]').addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const [file] = fileInput.files || [];
    fileInput.value = "";
    if (!file) return;
    stopPlayback();
    if (file.size > MAX_SESSION_FILE_BYTES) {
      setNotice("Replay file is too large (maximum 1 MB).", true);
      return;
    }
    try {
      const archive = JSON.parse(await file.text());
      events = validateArchive(archive);
      cursor = -1;
      renderTimeline();
      setNotice(`Loaded ${events.length} sanitized events. Replay is visual-only.`);
    } catch (error) {
      setNotice(`Could not load replay: ${error.message}`, true);
    }
  });

  panel.querySelector('[data-action="play"]').addEventListener("click", () => {
    if (!events.length) {
      setNotice("There are no timestamped events to replay.", true);
      return;
    }
    if (cursor >= events.length - 1) cursor = -1;
    playing = true;
    pauseButton.disabled = false;
    advance();
  });

  pauseButton.addEventListener("click", () => {
    stopPlayback();
    setNotice(cursor >= 0 ? `Paused at event ${cursor + 1} of ${events.length}.` : "Replay paused.");
  });

  panel.querySelector('[data-action="step"]').addEventListener("click", () => {
    stopPlayback();
    advance();
  });

  panel.querySelector('[data-action="stop"]').addEventListener("click", () => {
    stopPlayback();
    cursor = -1;
    renderTimeline();
    setNotice("Replay stopped.");
  });

  renderTimeline();
  setNotice(events.length
    ? `Current session loaded. Export includes up to ${MAX_SESSION_EVENTS} recent events.`
    : "No timestamped events are available yet.");
  return openWindow("session-studio", panel, { width: 820, height: 560 });
}

function currentEvents() {
  const source = window.__libraOSRecentEvents;
  return Array.isArray(source) ? source : [];
}

export function describeEvent(event) {
  const details = [event.type];
  if (event.operation) details.push(event.operation);
  if (event.algorithm) details.push(event.algorithm);
  if (typeof event.ok === "boolean") details.push(event.ok ? "success" : "failed");
  if (Number.isFinite(event.duration_ms)) details.push(`${event.duration_ms.toFixed(1)} ms`);
  return details.join(" · ");
}
