import { onEvent, sendFileSystemRequest } from "./api.js";
import { openWindow } from "./windowManager.js";

let host;
let currentPath = "/";
let selectedPath = null;
let selectedDetails = null;
let pending = new Map();
let entries = [];
let dialogMode = null;
let explorerInitialized = false;

export function openFileExplorer() {
  const panel = document.createElement("section");
  panel.className = "file-explorer";
  panel.innerHTML = `
    <header class="explorer-toolbar">
      <button data-action="up" title="Parent directory">↑</button>
      <span class="explorer-path" aria-live="polite">/</span>
      <label>New file allocation
        <select data-action="allocation" aria-label="Default file allocation">
          <option value="indexed">Indexed</option>
          <option value="linked">Linked</option>
          <option value="contiguous">Contiguous</option>
        </select>
      </label>
      <button data-action="refresh">Refresh</button>
      <button data-action="new-folder">New folder</button>
      <button data-action="new-file">New file</button>
      <button data-action="edit" disabled>Edit</button>
      <button data-action="delete" class="danger-button">Delete</button>
    </header>
    <div class="explorer-body">
      <nav class="explorer-tree" aria-label="Directory shortcuts"></nav>
      <section class="explorer-list" aria-label="Directory contents">
        <div class="explorer-columns"><span>Name</span><span>Type</span><span>Size</span><span>Owner</span></div>
        <div class="explorer-entries"></div>
      </section>
      <aside class="explorer-details"><div class="details-empty">Select a file or directory to inspect its inode and disk blocks.</div></aside>
    </div>
      <footer class="explorer-status" aria-live="polite">Connecting to simulated file system...</footer>
      <div class="explorer-dialog-backdrop hidden">
        <form class="explorer-dialog">
          <h3 data-dialog-title></h3>
          <label data-name-label>Name<input data-field="name" autocomplete="off"></label>
          <label data-content-label>Contents<textarea data-field="content" rows="5"></textarea></label>
          <p data-dialog-message></p>
          <div><button type="button" data-action="cancel-dialog">Cancel</button><button type="submit" class="dialog-confirm">Confirm</button></div>
        </form>
      </div>`;
  host = openWindow("file-explorer", panel, { width: 980, height: 590 });
  host.classList.add("file-explorer-window");
  if (explorerInitialized) {
    loadDirectory(currentPath);
    return host;
  }
  explorerInitialized = true;
  host.querySelector('[data-action="up"]').addEventListener("click", () => {
    if (currentPath !== "/") loadDirectory(parentPath(currentPath));
  });
  host.querySelector('[data-action="refresh"]').addEventListener("click", () => loadDirectory(currentPath));
  host.querySelector('[data-action="allocation"]').addEventListener("change", (event) => {
    request("set_allocation", { allocation: event.target.value }, (response) => {
      if (response.ok) setStatus(`New files will use ${response.result.allocation_method} allocation.`);
      else showError(response.error);
    });
  });
  host.querySelector('[data-action="new-folder"]').addEventListener("click", () => openDialog("folder"));
  host.querySelector('[data-action="new-file"]').addEventListener("click", () => openDialog("file"));
  host.querySelector('[data-action="edit"]').addEventListener("click", () => openDialog("edit"));
  host.querySelector('[data-action="delete"]').addEventListener("click", deleteSelection);
  host.querySelector('[data-action="cancel-dialog"]').addEventListener("click", closeDialog);
  host.querySelector(".explorer-dialog").addEventListener("submit", submitDialog);
  loadDirectory(currentPath);
  request("usage", {}, (response) => {
    if (response.ok) host.querySelector('[data-action="allocation"]').value = response.result.allocation_method;
    else showError(response.error);
  });
  return host;
}

onEvent((event) => {
  if (event.type !== "filesystem_result" || !pending.has(event.request_id)) return;
  const callback = pending.get(event.request_id);
  pending.delete(event.request_id);
  callback(event);
});

function request(operation, fields, callback) {
  try {
    const requestId = sendFileSystemRequest(operation, fields);
    pending.set(requestId, callback);
  } catch (error) {
    showError(error.message);
  }
}

function loadDirectory(path) {
  currentPath = path;
  selectedPath = null;
  selectedDetails = null;
  host.querySelector('[data-action="edit"]').disabled = true;
  renderPath();
  host.querySelector(".explorer-entries").replaceChildren();
  setStatus(`Reading ${path}...`);
  request("list", { path }, (response) => {
    if (!response.ok) {
      showError(response.error);
      return;
    }
    entries = response.result.entries;
    renderEntries();
    renderTree();
    renderDetails(null);
    setStatus(`${entries.length} item${entries.length === 1 ? "" : "s"} · ${path}`);
  });
}

function renderEntries() {
  const container = host.querySelector(".explorer-entries");
  container.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "explorer-empty";
    empty.textContent = "This directory is empty.";
    container.append(empty);
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("button");
    row.className = "explorer-row";
    row.dataset.path = entry.path;
    const name = document.createElement("span");
    name.className = "explorer-name";
    name.textContent = `${entry.type === "directory" ? "▰" : "▤"}  ${entry.name}`;
    const type = document.createElement("span");
    type.textContent = entry.type;
    const size = document.createElement("span");
    size.textContent = entry.type === "directory" ? "—" : `${entry.size} B`;
    const owner = document.createElement("span");
    owner.textContent = entry.owner;
    row.append(name, type, size, owner);
    row.addEventListener("click", () => selectEntry(entry));
    row.addEventListener("dblclick", () => {
      if (entry.type === "directory") loadDirectory(entry.path);
      else selectEntry(entry);
    });
    container.append(row);
  }
}

function renderTree() {
  const tree = host.querySelector(".explorer-tree");
  tree.replaceChildren();
  for (const path of ["/", "/books", "/members", "/issued", "/fines", "/logs", "/etc", "/home"]) {
    const button = document.createElement("button");
    button.className = "tree-item";
    button.classList.toggle("active", currentPath === path);
    button.textContent = path === "/" ? "▰  Root" : `▰  ${path.slice(1)}`;
    button.addEventListener("click", () => loadDirectory(path));
    tree.append(button);
  }
}

function selectEntry(entry) {
  selectedPath = entry.path;
  selectedDetails = null;
  host.querySelector('[data-action="edit"]').disabled = true;
  for (const row of host.querySelectorAll(".explorer-row")) {
    row.classList.toggle("selected", row.dataset.path === selectedPath);
  }
  request("stat", { path: entry.path }, (response) => {
    if (!response.ok) {
      showError(response.error);
      return;
    }
    selectedDetails = response.result;
    host.querySelector('[data-action="edit"]').disabled =
      selectedDetails.type !== "file" || selectedDetails.owner !== "guest";
    renderDetails(response.result);
  });
}

function renderDetails(details) {
  const panel = host.querySelector(".explorer-details");
  panel.replaceChildren();
  if (!details) {
    const empty = document.createElement("div");
    empty.className = "details-empty";
    empty.textContent = "Select a file or directory to inspect its inode and disk blocks.";
    panel.append(empty);
    return;
  }
  const heading = document.createElement("h3");
  heading.textContent = details.name;
  panel.append(heading);
  for (const [label, value] of [
    ["Path", details.path],
    ["Type", details.type],
    ["Inode", details.inode],
    ["Owner / mode", `${details.owner} · ${details.mode}`],
    ["Size", `${details.size} bytes`],
    ["Allocation", details.allocation || "directory"],
    ["Data blocks", details.blocks.length ? details.blocks.join(", ") : "none"],
    ["Index block", details.index_block ?? "none"],
  ]) {
    const row = document.createElement("div");
    row.className = "detail-row";
    const key = document.createElement("span");
    key.textContent = label;
    const valueElement = document.createElement("strong");
    valueElement.textContent = String(value);
    row.append(key, valueElement);
    panel.append(row);
  }
  if (details.type === "file") {
    const previewLabel = document.createElement("h4");
    previewLabel.textContent = "File contents";
    const preview = document.createElement("pre");
    preview.className = "file-preview";
    preview.textContent = details.content.slice(0, 1000) || "(empty file)";
    panel.append(previewLabel, preview);
  }
}

function deleteSelection() {
  if (!selectedPath) {
    setStatus("Select an item before deleting it.");
    return;
  }
  openDialog("delete");
}

function openDialog(mode) {
  dialogMode = mode;
  const overlay = host.querySelector(".explorer-dialog-backdrop");
  const form = host.querySelector(".explorer-dialog");
  const nameLabel = form.querySelector("[data-name-label]");
  const contentLabel = form.querySelector("[data-content-label]");
  const message = form.querySelector("[data-dialog-message]");
  const name = form.querySelector('[data-field="name"]');
  const title = form.querySelector("[data-dialog-title]");
  const confirm = form.querySelector(".dialog-confirm");
  nameLabel.classList.toggle("hidden", mode === "delete" || mode === "edit");
  contentLabel.classList.toggle("hidden", mode !== "file" && mode !== "edit");
  message.textContent = mode === "delete"
    ? `Delete ${selectedPath}? Directories must be empty.`
    : "";
  title.textContent = mode === "folder" ? "Create folder"
    : mode === "file" ? "Create file"
      : mode === "edit" ? "Edit file" : "Delete item";
  confirm.textContent = mode === "delete" ? "Delete" : mode === "edit" ? "Save" : "Create";
  confirm.classList.toggle("danger-button", mode === "delete");
  name.value = "";
  form.querySelector('[data-field="content"]').value = mode === "edit" ? selectedDetails?.content || "" : "";
  overlay.classList.remove("hidden");
  if (mode !== "delete") name.focus();
}

function closeDialog() {
  host.querySelector(".explorer-dialog-backdrop").classList.add("hidden");
  dialogMode = null;
}

function submitDialog(event) {
  event.preventDefault();
  const mode = dialogMode;
  if (!mode) return;
  if (mode === "delete") {
    const path = selectedPath;
    closeDialog();
    request("delete", { path }, (response) => {
      if (!response.ok) showError(response.error);
      else loadDirectory(currentPath);
    });
    return;
  }

  let path = selectedPath;
  let operation = "write";
  let fields;
  if (mode === "edit") {
    if (!selectedDetails || selectedDetails.type !== "file") return;
    fields = { path, content: host.querySelector('[data-field="content"]').value };
  } else {
    const name = host.querySelector('[data-field="name"]').value.trim();
    if (!name || name.includes("/") || name.includes("\\") || name === "." || name === "..") {
      setStatus("Enter a valid name without path separators.");
      return;
    }
    path = joinPath(currentPath, name);
    operation = mode === "file" ? "create" : "mkdir";
    fields = mode === "file"
      ? { path, content: host.querySelector('[data-field="content"]').value }
      : { path };
  }
  closeDialog();
  request(operation, fields, (response) => {
    if (!response.ok) showError(response.error);
    else loadDirectory(currentPath);
  });
}

function renderPath() {
  host.querySelector(".explorer-path").textContent = currentPath;
}

function setStatus(message) {
  host.querySelector(".explorer-status").textContent = message;
}

function showError(message) {
  setStatus(`File system error: ${message}`);
}

function joinPath(directory, name) {
  return `${directory === "/" ? "" : directory}/${name.trim()}`;
}

function parentPath(path) {
  const parent = path.slice(0, path.lastIndexOf("/"));
  return parent || "/";
}
