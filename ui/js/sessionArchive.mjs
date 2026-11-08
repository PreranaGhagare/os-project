export const SESSION_ARCHIVE_FORMAT = "libraos-session";
export const SESSION_ARCHIVE_VERSION = 1;
export const MAX_SESSION_EVENTS = 200;
export const MAX_SESSION_FILE_BYTES = 1_000_000;

const EVENT_TYPES = new Set([
  "filesystem_result",
  "library_result",
  "log",
  "observability_result",
  "power",
  "process_result",
  "request_trace",
  "resource_result",
  "resource_state",
  "scenario_result",
  "scheduler_result",
  "security_result",
  "sync_result",
  "sync_state",
  "system",
]);

export function normalizeEvent(event) {
  if (!event || typeof event !== "object" || !EVENT_TYPES.has(event.type)) return null;
  const timestamp = typeof event.timestamp === "string" ? event.timestamp : "";
  if (!Number.isFinite(Date.parse(timestamp))) return null;
  const normalized = { timestamp, type: event.type };
  if (typeof event.ok === "boolean") normalized.ok = event.ok;
  if (Number.isFinite(event.duration_ms) && event.duration_ms >= 0) {
    normalized.duration_ms = event.duration_ms;
  }
  return normalized;
}

export function validateArchive(archive) {
  if (!archive || typeof archive !== "object" ||
      archive.format !== SESSION_ARCHIVE_FORMAT || archive.version !== SESSION_ARCHIVE_VERSION ||
      !Array.isArray(archive.events) || archive.events.length > MAX_SESSION_EVENTS) {
    throw new Error("unsupported archive format or event count");
  }
  let previousTimestamp = -Infinity;
  return archive.events.map((event, index) => {
    const normalized = normalizeEvent(event);
    if (!normalized) throw new Error(`invalid event at position ${index + 1}`);
    const timestamp = Date.parse(normalized.timestamp);
    if (timestamp < previousTimestamp) throw new Error("events must be ordered by timestamp");
    previousTimestamp = timestamp;
    return normalized;
  });
}
