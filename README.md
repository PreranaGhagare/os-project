# LibraOS

LibraOS is a simulated desktop operating system for demonstrating OS concepts through a library-management use case. It is being built in the nine stages in the project brief; **this checkout implements Stages 1–9**.

## Project tree

```text
os project/
  kernel/
    boot.py              Kernel startup, file-system, process, and sync requests
    disk.py              Atomic disk-image JSON persistence
    events.py            Kernel event history and broadcast
    filesystem.py        Inodes, virtual blocks, and allocation policies
    memory.py            Demand paging and FIFO/LRU/Optimal page replacement
    disk_scheduler.py    FCFS, SSTF, SCAN, C-SCAN, LOOK, and C-LOOK
    security.py          Demo roles, authorization rules, and syscall tracing
    syscalls.py           Modeled syscall dispatcher
    library.py            Catalog and circulation operations
    journal.py            Write-ahead redo journal for virtual-disk transactions
    request_trace.py      Bounded, correlated kernel request traces
    scenarios.py          Reproducible algorithm comparisons and workloads
    process.py           Process control blocks and lifecycle operations
    scheduler.py         Multi-core CPU scheduling simulations
    synchronization.py   Mutexes, semaphores, and deadlock management
    seed_data.py         Deterministic library records
  shell/
    commands.py          Allow-listed simulated shell commands
  server/
    main.py              FastAPI app and lifecycle
    websocket.py         Commands, filesystem, scheduling, sync, and events
  ui/
    index.html
    css/style.css        Desktop, window manager, and File Explorer styles
    js/api.js            WebSocket client
    js/app.js            Browser entry point
    js/desktop.js        Boot screen and desktop apps
    js/fileExplorer.js   Simulated file-system viewer
    js/taskManager.js    Workload editor, scheduler, and performance views
    js/syncMonitor.js    Resource monitor, deadlock tools, and race demo
    js/systemMonitor.js  Physical frames, page tables, and disk seek viewer
    js/security.js       Demo user, authorization, and syscall-trace panel
    js/library.js        Catalog, member lookup, checkout, and returns
    js/observability.js  Request trace and disk journal viewer
    js/scenarios.js      Scenario runner and resource comparisons
    js/sessionStudio.js  Privacy-minimized session export and visual replay
    js/terminal.js
    js/windowManager.js
  data/
    disk.img.json        Created on first boot and saved on shutdown
  tests/test_stage2_filesystem.py
  tests/test_stage3_scheduler.py
  tests/test_stage4_synchronization.py
  tests/test_stage5_resources.py
  tests/test_stage7_library.py
  tests/test_stage8_observability.py
  docs/design.md
  Dockerfile
  compose.yaml
  .dockerignore
  requirements.txt
  run.bat
```

## Architecture

```text
Browser desktop (HTML/CSS/ES modules)
      │ WebSocket commands and kernel events
      ▼
FastAPI server → terminal / File Explorer / Task Manager / Sync Monitor / Resource Monitor
      │
      ├→ Kernel → simulated inode/block file system → data/disk.img.json
      ├→ Process manager → discrete-time scheduler
      ├→ Synchronization manager → mutex/semaphore wait queues
      ├→ Resource manager → demand-paged memory / disk-head scheduler
      ├→ Security manager → demo role checks / syscall tracer
      └→ Library manager → catalog, members, circulation, and fines
      └→ Journal / request tracer / benchmark scenarios
```

The UI renders kernel events and sends structured requests over WebSocket; it does not access the host file system for library data. The simulated disk image is JSON, and its block contents are base64 encoded.

## Setup and run

Requirements: Python 3.11 or newer.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\run.bat
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The server also exposes `GET /health` and the live event/command WebSocket at `/ws`.

## Container deployment

Requirements: Docker Desktop with Docker Compose v2.

```powershell
docker compose up --build -d
docker compose ps
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000); check readiness at [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health). The container runs as a non-root user, uses a read-only application filesystem, and stores the simulated disk image and redo journal in the `libraos-data` named volume. `LIBRAOS_DATA_DIR` can point to another writable data directory when running outside Compose.

Stop with `docker compose down`; persisted data remains in the named volume. To permanently remove it, run `docker compose down --volumes` (this deletes the simulated disk image and journal).

LibraOS uses demo roles, has no real authentication, and is intended for local teaching/demo use. The Compose port binds to `127.0.0.1`; do not expose this service to an untrusted network without adding real authentication and deployment-specific protections.

## Implemented features

- BIOS-style boot screen with timestamped kernel messages, progress indicator, and skip control.
- Dark desktop with light-theme toggle, clock, guest demo identity, kernel connection status, start menu, desktop shortcuts, and taskbar.
- Draggable, resizable, minimizable, maximizable, focusable, and closable application windows.
- Terminal commands: `help`, `clear`, `ps`, `top`, `ls`, `cat`, `mkdir`, `df`, `pwd`, `whoami`, `uname`, `date`, `dmesg`, `echo`, `shutdown`, `reboot`.
- Kernel Log window, process-table snapshot, WebSocket event history, keyboard terminal shortcut (`T`), command history (Up/Down), and clear shortcut (Ctrl+L).
- File Explorer with directory navigation, inode and permissions metadata, file previews, block maps, create/delete operations, and contiguous/linked/indexed allocation selection.
- Virtual directories for books, members, issues, fines, logs, configuration, and home files.
- Deterministic seed records: 60 books, 25 members, 20 issue records, and 8 unpaid overdue fines.
- Simulated disk block bitmap, inode table, block allocation, and atomic JSON disk-image saves on shutdown, restart, and server exit.
- Process control blocks with fork, exec, exit, kill, wait, and priority-change operations.
- FCFS, SJF, SRTF, Round Robin, preemptive/non-preemptive Priority with aging, and MLFQ scheduling.
- Configurable 1–4 simulated CPU cores, quantum control, Gantt lanes, ready-queue snapshots, process metrics, context switches, utilization, and throughput.
- Task Manager workload editor and live scheduler-result stream; terminal commands include `sched`, `fork-test`, `fork`, `exec`, `exit`, `kill`, `nice`, and `wait`.
- Sync Monitor with mutex and counting-semaphore resources, FIFO wait queues, process blocking/wakeup, resource-allocation snapshots, deadlock detection/recovery, and a deterministic lost-update comparison with mutex protection.
- Resource Monitor with per-process virtual address spaces, an eight-frame memory viewer, FIFO/LRU/Optimal page replacement and fault metrics, and six disk-scheduling algorithms with track paths and seek-movement metrics.
- Security panel with demo user roles, authorization checks, and syscall audit traces. Accounts are simulated and have no passwords.
- Library app with searchable catalog, member lookup, availability derived from active loans, role-restricted checkout/return, due dates, and overdue fines.
- Write-ahead redo journal for filesystem, terminal, syscall, and circulation mutations; commits are persisted atomically and pending transactions are recovered on boot.
- Trace & Journal viewer with correlated request IDs, outcomes, processing durations, and transaction history.
- Scenario Lab for repeatable scheduler, disk-seek, and page-replacement comparisons; Task Manager can compare all CPU algorithms against a custom workload without creating processes.
- Presentation mode focuses the active application in a distraction-free layout; Session Studio exports a sanitized event timeline and imports it for visual-only replay.
- Keyboard-visible focus indicators, presentation focus restoration, and reduced-motion support improve accessibility across interactive windows.

## Demo account and seeded files

The desktop starts as `guest` in a demo session. Stage 6 provides simulated role-based authorization and syscall tracing, not real authentication; accounts have no passwords. Demo identities have fixed roles, and the administrator account is reserved. Switch to `librarian` in the Security app to use circulation operations; librarian file access is limited to the simulated library data directories. Seeded library files are readable from File Explorer. The guest account may create, edit, and delete its own files.

## Known limitations

The terminal process table reflects actual process records, but CPU and memory figures in the top bar remain illustrative. Task Manager, Sync Monitor, Resource Monitor, security, journaling, scenarios, and library operations are deterministic simulations, not host resource primitives or real authentication. Session exports include only a bounded set of event metadata; commands, file contents, and result payloads are excluded. Imported replay is visual-only and does not execute saved actions.

Run all tests with `python -m unittest discover -s tests -v`.
Run the Stage 9 session archive tests with `node --test tests/test_stage9_session.mjs`.
Run the browser integration tests locally with `npm ci`, `npx playwright install chromium firefox webkit`, and `npm run test:browser` (with Python and the project dependencies installed).
The HTTP and WebSocket integration tests run with the Python suite; install `requirements-dev.txt` to include its test-client dependency.
For local Python coverage, install `requirements-dev.txt`, run `coverage run --branch --source=kernel,server,shell -m unittest discover -s tests -v`, then run `coverage report --show-missing`.
GitHub Actions runs the Python suite with coverage on Python 3.11–3.13 on Linux and Python 3.13 on Windows. Coverage reports are retained as workflow artifacts for seven days. CI also checks frontend JavaScript syntax, session archives, and the security and library browser flows on Chromium, Firefox, and WebKit with Node.js 22. CI runs on pushes, pull requests, and a weekly schedule, supports manual runs from the Actions tab, and cancels superseded runs on the same branch. Dependabot opens grouped weekly dependency update pull requests for Python, npm, and GitHub Actions.

## Roadmap

1. Kernel skeleton, boot screen, kernel log, desktop shell, terminal (**implemented**).
2. Simulated file system, disk image, seed data, File Explorer (**implemented**).
3. Process manager, CPU scheduler, Task Manager, Gantt chart (**implemented**).
4. Synchronization, deadlock manager, Sync Monitor, race demo (**implemented**).
5. Memory manager, disk scheduler, viewers (**implemented**).
6. Security module, syscall layer, Syscall Tracer (**implemented**).
7. Library applications (**implemented**).
8. Journaling, request tracing, scenarios, comparison mode (**implemented**).
9. Presentation mode, export/replay, tests, and complete documentation (**implemented**).
