import assert from "node:assert/strict";
import test from "node:test";

import { normalizeEvent, validateArchive } from "../ui/js/sessionArchive.mjs";

const archive = (events) => ({
  format: "libraos-session",
  version: 1,
  events,
});

test("session exports retain only allowlisted event metadata and metrics", () => {
  const event = normalizeEvent({
    type: "filesystem_result",
    timestamp: "2026-11-01T10:00:00.000Z",
    request_id: "private-request-id",
    operation: "/home/secret.txt",
    message: "private message",
    command: "cat /home/secret.txt",
    result: { content: "private file contents" },
    ok: true,
    duration_ms: 2.5,
  });

  assert.deepEqual(event, {
    timestamp: "2026-11-01T10:00:00.000Z",
    type: "filesystem_result",
    ok: true,
    duration_ms: 2.5,
  });
});

test("session imports accept supported archives and sanitize event fields", () => {
  const events = validateArchive(archive([{
    type: "scheduler_result",
    timestamp: "2026-11-01T10:00:00.000Z",
    operation: "secret-operation",
    algorithm: "rr",
    ok: true,
  }]));

  assert.deepEqual(events, [{
    timestamp: "2026-11-01T10:00:00.000Z",
    type: "scheduler_result",
    ok: true,
  }]);
});

test("session imports reject unknown event types and unsupported archive versions", () => {
  assert.throws(() => validateArchive(archive([{
    type: "arbitrary-user-data",
    timestamp: "2026-11-01T10:00:00.000Z",
  }])), /invalid event/);
  assert.throws(() => validateArchive({
    ...archive([]),
    version: 2,
  }), /unsupported archive format/);
});

test("session imports reject oversized and out-of-order event lists", () => {
  const event = { type: "log", timestamp: "2026-11-01T10:00:00.000Z" };
  assert.throws(() => validateArchive(archive(Array(201).fill(event))), /unsupported archive format/);
  assert.throws(() => validateArchive(archive([
    event,
    { type: "system", timestamp: "2026-10-31T10:00:00.000Z" },
  ])), /ordered by timestamp/);
});
