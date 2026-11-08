import { connect, onEvent } from "./api.js";
import { handleDesktopEvent, initialize } from "./desktop.js?v=security-hardening-1";

let initialized = false;

onEvent((event) => {
  if (event.type === "snapshot") {
    if (initialized) return;
    initialized = true;
    initialize(event);
    return;
  }
  handleDesktopEvent(event);
});

connect();
