import { onEvent, sendSecurityRequest, sendSyscallRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

let activePanel = null;

export function openSecurityPanel() {
  if (activePanel) {
    openWindow("security", activePanel, { width: 700, height: 430 });
    refreshSecurityState();
    return activePanel;
  }

  const panel = document.createElement("div");
  panel.className = "security-panel";
  panel.style.cssText = "display:flex; flex-direction:column; gap:12px; padding:12px; color:#e5eefb; font-family:Inter,Segoe UI,sans-serif;";

  const summary = document.createElement("div");
  summary.style.cssText = "display:flex; justify-content:space-between; align-items:center; gap:12px; padding:10px 12px; border:1px solid rgba(163,184,255,.28); border-radius:10px; background:rgba(12,20,39,.7);";
  const currentUser = document.createElement("div");
  currentUser.innerHTML = "<div style='font-size:12px; opacity:.7; text-transform:uppercase; letter-spacing:.12em;'>Current user</div><div id='security-current-user' style='font-size:1.3rem; font-weight:700; margin-top:4px;'>guest</div>";
  const statusPill = document.createElement("div");
  statusPill.id = "security-status-pill";
  statusPill.style.cssText = "padding:6px 10px; border-radius:999px; font-size:12px; font-weight:700; letter-spacing:.08em; background:rgba(88,166,92,.16); color:#9be4a5; border:1px solid rgba(88,166,92,.4);";
  statusPill.textContent = "AUTHORIZED";
  summary.append(currentUser, statusPill);

  const twoCol = document.createElement("div");
  twoCol.style.cssText = "display:grid; grid-template-columns:1.2fr .8fr; gap:12px;";

  const usersCard = document.createElement("div");
  usersCard.style.cssText = "padding:10px 12px; border:1px solid rgba(163,184,255,.28); border-radius:10px; background:rgba(12,20,39,.7);";
  const usersHeader = document.createElement("div");
  usersHeader.style.cssText = "font-size:12px; letter-spacing:.1em; text-transform:uppercase; opacity:.7; margin-bottom:8px;";
  usersHeader.textContent = "Known users";
  const usersTable = document.createElement("div");
  usersTable.id = "security-users-table";
  usersTable.style.cssText = "display:grid; gap:6px; font-size:13px;";
  usersCard.append(usersHeader, usersTable);

  const loginCard = document.createElement("div");
  loginCard.style.cssText = "padding:12px; border:1px solid rgba(163,184,255,.28); border-radius:10px; background:rgba(12,20,39,.7);";
  loginCard.innerHTML = `
    <div style="font-size:12px; letter-spacing:.1em; text-transform:uppercase; opacity:.7; margin-bottom:12px;">Switch demo account</div>
    <form id="security-login-form" style="display:grid; gap:10px;">
      <label style="display:grid; gap:6px; font-size:13px;">
        <span>Demo account</span>
        <select name="username" style="padding:8px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;">
          <option value="guest">guest · reader</option>
          <option value="librarian">librarian · circulation</option>
        </select>
      </label>
      <button type="submit" style="padding:9px 12px; border:0; border-radius:8px; background:#5a7cff; color:white; font-weight:700; cursor:pointer;">Switch user</button>
    </form>
  `;

  const authorizeCard = document.createElement("div");
  authorizeCard.style.cssText = "padding:12px; border:1px solid rgba(163,184,255,.28); border-radius:10px; background:rgba(12,20,39,.7);";
  authorizeCard.innerHTML = `
    <div style="font-size:12px; letter-spacing:.1em; text-transform:uppercase; opacity:.7; margin-bottom:12px;">Authorize</div>
    <form id="security-authorize-form" style="display:grid; gap:10px;">
      <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
        <label style="display:grid; gap:6px; font-size:13px;">
          <span>Action</span>
          <select name="action" style="padding:8px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;">
            <option value="read">read</option>
            <option value="write">write</option>
            <option value="create">create</option>
            <option value="delete">delete</option>
          </select>
        </label>
        <label style="display:grid; gap:6px; font-size:13px;">
          <span>User</span>
          <input name="user" value="guest" style="padding:8px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;" />
        </label>
      </div>
      <label style="display:grid; gap:6px; font-size:13px;">
        <span>Path</span>
        <input name="path" value="/home/guest/notes.txt" style="padding:8px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;" />
      </label>
      <label style="display:grid; gap:6px; font-size:13px;">
        <span>Owner</span>
        <input name="owner" value="guest" style="padding:8px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;" />
      </label>
      <button type="submit" style="padding:9px 12px; border:0; border-radius:8px; background:#2ea673; color:white; font-weight:700; cursor:pointer;">Check access</button>
    </form>
    <div id="security-authorization-result" style="margin-top:10px; padding:8px 10px; border-radius:8px; background:rgba(23,38,52,.9); min-height:36px; line-height:1.4; font-size:13px; color:#dfeaf9;">Ready.</div>
  `;

  const auditCard = document.createElement("div");
  auditCard.style.cssText = "padding:12px; border:1px solid rgba(163,184,255,.28); border-radius:10px; background:rgba(12,20,39,.7);";
  auditCard.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:12px;">
      <div style="font-size:12px; letter-spacing:.1em; text-transform:uppercase; opacity:.7;">System call audit</div>
      <div style="display:flex; gap:8px; align-items:center;">
        <button id="security-audit-clear" type="button" style="padding:7px 10px; border:1px solid rgba(163,184,255,.25); border-radius:8px; background:transparent; color:#dfeaf9; font-weight:700; cursor:pointer;">Clear</button>
        <button id="security-trace-demo" type="button" style="padding:7px 10px; border:0; border-radius:8px; background:#7c5cff; color:white; font-weight:700; cursor:pointer;">Trace demo read</button>
      </div>
    </div>
    <div id="security-audit-list" style="display:grid; gap:8px; min-height:120px;"></div>
  `;

  loginCard.querySelector("#security-login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const username = form.elements.namedItem("username").value;
    sendSecurityRequest("login", { username });
    refreshSecurityState();
  });

  authorizeCard.querySelector("#security-authorize-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const action = form.action.value;
    const user = form.user.value.trim();
    const path = form.path.value.trim();
    const owner = form.owner.value.trim();
    sendSecurityRequest("authorize", { action, user, path, owner });
    const result = authorizeCard.querySelector("#security-authorization-result");
    result.textContent = `Checking ${action} for ${user || "guest"} on ${path || "/"}...`;
  });

  auditCard.querySelector("#security-trace-demo").addEventListener("click", () => {
    const currentUser = panel.querySelector("#security-current-user")?.textContent || "guest";
    sendSyscallRequest("read", { path: "/books/B001.json", user: currentUser });
  });

  auditCard.querySelector("#security-audit-clear").addEventListener("click", () => {
    const host = panel.querySelector("#security-audit-list");
    if (!host) return;
    host.replaceChildren(renderAuditPlaceholder());
  });

  twoCol.append(usersCard, loginCard);
  panel.append(summary, twoCol, authorizeCard, auditCard);
  const auditHost = panel.querySelector("#security-audit-list");
  if (auditHost) {
    auditHost.append(renderAuditPlaceholder());
    hydrateAuditHistory(auditHost);
  }
  activePanel = panel;

  const unsubscribe = onEvent((event) => {
    if (!activePanel || activePanel !== panel) return;
    if (event.type === "security_result") {
      const payload = event.result || {};
      if (event.operation === "whoami") {
        const user = payload.username || "guest";
        panel.querySelector("#security-current-user").textContent = user;
        const pill = panel.querySelector("#security-status-pill");
        pill.textContent = event.ok ? "AUTHORIZED" : "DENIED";
        pill.style.background = event.ok ? "rgba(88,166,92,.16)" : "rgba(214,118,118,.16)";
        pill.style.color = event.ok ? "#9be4a5" : "#f3b8b8";
      }
      if (event.operation === "users") {
        const users = Array.isArray(payload.users) ? payload.users : [];
        renderUserList(panel.querySelector("#security-users-table"), users);
      }
      if (event.operation === "authorize") {
        const resolved = payload.authorized === true;
        const result = panel.querySelector("#security-authorization-result");
        result.textContent = resolved ? "Access granted." : "Access denied.";
        result.style.background = resolved ? "rgba(26,112,79,.27)" : "rgba(112,42,42,.3)";
        result.style.color = resolved ? "#bbf7d0" : "#ffd7d7";
      }
      if (event.operation === "login") {
        refreshSecurityState();
      }
    }
    if (event.type === "syscall" || event.type === "syscall_result") {
      updateAuditList(panel.querySelector("#security-audit-list"), event);
    }
  });
  panel.__unsubscribe = unsubscribe;
  openWindow("security", panel, { width: 700, height: 430 });
  refreshSecurityState();
  return panel;
}

function renderUserList(host, users) {
  host.replaceChildren();
  for (const user of users) {
    const row = document.createElement("div");
    row.style.cssText = "display:flex; justify-content:space-between; align-items:center; padding:6px 8px; border-radius:7px; background:rgba(17,30,50,.9);";
    const left = document.createElement("div");
    left.textContent = `${user.username} (${user.role})`;
    const tag = document.createElement("span");
    tag.style.cssText = "padding:2px 6px; border-radius:999px; font-size:10px; background:rgba(103,116,255,.18); color:#dbe4ff;";
    tag.textContent = user.active ? "ACTIVE" : "INACTIVE";
    row.append(left, tag);
    host.append(row);
  }
}

function renderAuditPlaceholder() {
  const placeholder = document.createElement("div");
  placeholder.style.cssText = "padding:10px 12px; border-radius:8px; border:1px dashed rgba(163,184,255,.2); background:rgba(17,30,50,.4); color:rgba(223,234,249,.72); font-size:12px;";
  placeholder.dataset.emptyState = "true";
  placeholder.textContent = "No traced system calls yet.";
  return placeholder;
}

function hydrateAuditHistory(host) {
  if (!host || !window.__libraOSRecentEvents) return;
  const pastEvents = window.__libraOSRecentEvents.filter((event) => event && (event.type === "syscall" || event.type === "syscall_result"));
  if (!pastEvents.length) return;
  host.replaceChildren();
  for (const event of [...pastEvents].reverse().slice(0, 8)) {
    updateAuditList(host, event);
  }
}

function updateAuditList(host, event) {
  if (!host) return;
  const existingPlaceholder = host.querySelector("[data-empty-state='true']");
  if (existingPlaceholder) existingPlaceholder.remove();

  const syscallName = event.syscall || event.result?.syscall || "syscall";
  const user = event.user || event.result?.user || "guest";
  const path = event.path || event.result?.path || event.result?.result?.path || "/";
  const ok = event.ok ?? event.result?.ok ?? true;
  const timestamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "now";
  const row = document.createElement("div");
  row.style.cssText = "padding:8px 10px; border-radius:8px; background:rgba(17,30,50,.9); border:1px solid rgba(163,184,255,.2); font-size:12px; line-height:1.4;";
  row.dataset.auditRow = "true";
  const statusColor = ok ? "rgba(88,166,92,.14)" : "rgba(214,118,118,.16)";
  row.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; gap:8px;">
      <div><strong>${syscallName}</strong> · ${user}</div>
      <span style="padding:2px 6px; border-radius:999px; font-size:10px; background:${statusColor}; color:${ok ? "#9be4a5" : "#f3b8b8"};">${ok ? "OK" : "DENIED"}</span>
    </div>
    <div style="opacity:.72; margin-top:2px;">${path}</div>
    <div style="opacity:.6; margin-top:3px; font-size:10px; letter-spacing:.05em; text-transform:uppercase;">${timestamp}</div>
  `;
  host.prepend(row);
  while (host.children.length > 8) host.removeChild(host.lastElementChild);
}

function refreshSecurityState() {
  sendSecurityRequest("whoami");
  sendSecurityRequest("users");
}
