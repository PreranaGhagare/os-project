import { onEvent, sendLibraryRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

let panel = null;
let latestCatalogRequest = null;
const pendingRequests = new Map();

export function openLibrary() {
  if (panel) {
    openWindow("library", panel, { width: 1060, height: 680 });
    refreshDashboard();
    return panel;
  }

  panel = document.createElement("section");
  panel.className = "library-app";
  panel.style.cssText = "display:flex; flex-direction:column; gap:12px; padding:14px; height:100%; overflow:auto; color:#e5eefb; font-family:Inter,Segoe UI,sans-serif;";
  panel.innerHTML = `
    <header style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
      <div><h2 style="margin:0;">Library</h2><p style="margin:4px 0 0; opacity:.72;">Search the catalog and manage circulation.</p></div>
      <form data-catalog-search style="display:flex; gap:8px;">
        <input name="query" aria-label="Search books" placeholder="Title, author, ISBN…" style="min-width:220px; padding:9px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;">
        <button type="submit" style="padding:9px 12px; border:0; border-radius:8px; background:#5a7cff; color:white; font-weight:700; cursor:pointer;">Search</button>
      </form>
    </header>
    <div data-library-status role="status" aria-live="polite" style="min-height:20px; color:#b8c8e2;">Loading library records…</div>
    <div style="display:grid; grid-template-columns:minmax(0,1.5fr) minmax(280px,1fr); gap:12px; min-height:0;">
      <section style="padding:12px; border:1px solid rgba(163,184,255,.25); border-radius:10px; background:rgba(12,20,39,.7);">
        <h3 style="margin:0 0 10px;">Catalog</h3>
        <div data-library-books style="display:grid; gap:8px;"></div>
      </section>
      <aside style="display:grid; align-content:start; gap:12px;">
        <section style="padding:12px; border:1px solid rgba(163,184,255,.25); border-radius:10px; background:rgba(12,20,39,.7);">
          <h3 style="margin:0 0 10px;">Circulation desk</h3>
          <label style="display:grid; gap:6px; font-size:13px;">Member
            <select data-library-member style="padding:8px 10px; border-radius:8px; border:1px solid rgba(163,184,255,.3); background:#0a1220; color:#edf4ff;"></select>
          </label>
          <div data-library-member-info style="margin-top:8px; font-size:13px; opacity:.8;"></div>
          <h3 style="margin:16px 0 8px;">Active loans</h3>
          <div data-library-loans style="display:grid; gap:8px;"></div>
        </section>
      </aside>
    </div>`;
  openWindow("library", panel, { width: 1060, height: 680 });

  panel.querySelector("[data-catalog-search]").addEventListener("submit", (event) => {
    event.preventDefault();
    request("catalog", { query: panel.querySelector('[name="query"]').value });
  });
  panel.querySelector("[data-library-member]").addEventListener("change", renderMemberInfo);
  panel.querySelector("[data-library-loans]").addEventListener("click", (event) => {
    const button = event.target.closest("[data-return-issue]");
    if (button) request("return", { issue_id: button.dataset.returnIssue });
  });
  refreshDashboard();
  return panel;
}

function request(operation, fields = {}) {
  try {
    const requestId = sendLibraryRequest(operation, fields);
    pendingRequests.set(requestId, operation);
    if (operation === "catalog") latestCatalogRequest = requestId;
    setStatus(operation === "catalog" ? "Searching catalog…" : `${operation} request sent…`);
    return requestId;
  } catch (error) {
    setStatus(error.message, true);
    return null;
  }
}

function refreshDashboard() {
  request("dashboard");
}

function handleLibraryEvent(event) {
  if (event.type !== "library_result") return;
  const operation = pendingRequests.get(event.request_id);
  if (!operation) return;
  pendingRequests.delete(event.request_id);
  if (!event.ok) {
    setStatus(event.error || "Library request failed.", true);
    return;
  }

  const result = event.result || {};
  if (operation === "dashboard") {
    renderDashboard(result);
    setStatus(`Signed in as ${event.current_user || "guest"}.`);
  } else if (operation === "catalog") {
    if (event.request_id === latestCatalogRequest) renderBooks(result.books || []);
    setStatus(`Found ${(result.books || []).length} matching books.`);
  } else if (operation === "members") {
    renderMembers(result.members || []);
  } else if (operation === "checkout" || operation === "return") {
    const issue = result.issue || {};
    setStatus(
      operation === "checkout"
        ? `Checked out ${issue.book_id} to ${issue.member_id}; due ${issue.due_date}.`
        : `Returned ${issue.book_id}${issue.fine ? `; fine assessed: $${Number(issue.fine).toFixed(2)}` : ""}.`,
    );
    refreshDashboard();
  }
}

function renderDashboard(result) {
  window.__libraOSBooks = result.books || [];
  window.__libraOSMembers = result.members || [];
  renderBooks(result.books || []);
  renderMembers(result.members || []);
  renderLoans(result.loans || []);
}

function renderBooks(books) {
  if (!panel) return;
  window.__libraOSBooks = books;
  const list = panel.querySelector("[data-library-books]");
  list.replaceChildren();
  if (!books.length) {
    list.textContent = "No matching books.";
    return;
  }
  for (const book of books) {
    const card = document.createElement("article");
    card.style.cssText = "display:flex; justify-content:space-between; align-items:center; gap:12px; padding:10px; border-radius:8px; background:rgba(23,38,52,.75);";
    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = book.title || book.id;
    const metadata = document.createElement("div");
    metadata.style.cssText = "margin-top:4px; font-size:12px; opacity:.75;";
    metadata.textContent = `${book.id} · ${book.author || "Unknown author"} · ${book.category || "Uncategorized"} · ${book.available_copies} available`;
    details.append(title, metadata);
    const checkout = document.createElement("button");
    checkout.type = "button";
    checkout.textContent = book.available_copies > 0 ? "Check out" : "Unavailable";
    checkout.disabled = book.available_copies <= 0;
    checkout.style.cssText = "padding:7px 10px; border:0; border-radius:7px; background:#2ea673; color:white; font-weight:700; cursor:pointer;";
    checkout.addEventListener("click", () => {
      const memberId = panel.querySelector("[data-library-member]").value;
      if (!memberId) {
        setStatus("Choose a member before checking out a book.", true);
        return;
      }
      request("checkout", { book_id: book.id, member_id: memberId });
    });
    card.append(details, checkout);
    list.append(card);
  }
}

function renderMembers(members) {
  if (!panel) return;
  const select = panel.querySelector("[data-library-member]");
  const selectedMember = select.value;
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Select a member";
  select.append(placeholder);
  for (const member of members) {
    const option = document.createElement("option");
    option.value = member.id;
    option.textContent = `${member.id} · ${member.name}`;
    select.append(option);
  }
  if (members.some((member) => member.id === selectedMember)) select.value = selectedMember;
  renderMemberInfo();
}

function renderMemberInfo() {
  if (!panel) return;
  const member = (window.__libraOSMembers || []).find(
    (item) => item.id === panel.querySelector("[data-library-member]").value,
  );
  const info = panel.querySelector("[data-library-member-info]");
  info.textContent = member
    ? `${member.role} · ${member.status} · ${member.fines_due > 0 ? `$${Number(member.fines_due).toFixed(2)} in fines` : "No fines due"}`
    : "Select a member to view their status.";
}

function renderLoans(loans) {
  if (!panel) return;
  const list = panel.querySelector("[data-library-loans]");
  list.replaceChildren();
  const books = new Map((window.__libraOSBooks || []).map((book) => [book.id, book.title]));
  const members = new Map((window.__libraOSMembers || []).map((member) => [member.id, member.name]));
  if (!loans.length) {
    list.textContent = "No active loans.";
    return;
  }
  for (const issue of loans) {
    const row = document.createElement("div");
    row.style.cssText = "display:grid; grid-template-columns:1fr auto; gap:8px; align-items:center; padding:8px; border-radius:8px; background:rgba(23,38,52,.75); font-size:12px;";
    const label = document.createElement("span");
    label.textContent = `${books.get(issue.book_id) || issue.book_id} · ${members.get(issue.member_id) || issue.member_id} · due ${issue.due_date}`;
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.returnIssue = issue.id;
    button.textContent = "Return";
    button.style.cssText = "padding:6px 8px; border:0; border-radius:6px; background:#5a7cff; color:white; font-weight:700; cursor:pointer;";
    row.append(label, button);
    list.append(row);
  }
}

function setStatus(message, isError = false) {
  if (!panel) return;
  const status = panel.querySelector("[data-library-status]");
  status.textContent = message;
  status.style.color = isError ? "#ff9c9c" : "#b8c8e2";
}

onEvent(handleLibraryEvent);
