# LibraOS design notes — Stages 1–9

## Layering

```text
Browser UI → WebSocket command/event protocol → FastAPI adapter
           ├→ shell command dispatcher → kernel state
           └→ file-system request handler → inode/block file system → disk image
           └→ scheduler request → process table → discrete-time CPU simulation
           └→ synchronization request → mutex/semaphore manager → process wait queues
           └→ resource request → demand-paged memory / disk-head scheduler
           ├→ security request → demo role manager / syscall tracer
           └→ library request → catalog / member / circulation operations
           ├→ request trace → bounded correlated request history
           ├→ journal → redo recovery for virtual-disk transactions
           └→ scenario request → isolated algorithm comparisons
```

The browser sends structured JSON commands and displays structured JSON events. The server does not accept or execute arbitrary host-shell commands. File Explorer, scheduler, synchronization, memory, and disk-scheduling requests also use the WebSocket and return structured result events. The kernel event hub retains a bounded history for reconnecting clients and broadcasts new events to active WebSocket subscribers.

The container image serves only the application and runs as an unprivileged user. The disk image and redo journal are written under `LIBRAOS_DATA_DIR`; Compose mounts a named persistent volume there while keeping the application filesystem read-only.

## Modules and OS concepts

| Module | Responsibility | OS topic |
|---|---|---|
| `kernel/boot.py` | Mounts the disk image, emits startup messages, and coordinates kernel operations | Boot and initialization |
| `kernel/events.py` | Timestamped event history and asynchronous subscribers | Kernel event delivery |
| `kernel/process.py` | Initial PID/PPID table for init, shell, and desktop | Process control block basics |
| `shell/commands.py` | Parses and executes a fixed set of user-mode commands | User/kernel boundary and command interpreter |
| `kernel/filesystem.py` | Maintains directories, inodes, blocks, and allocation policies | File systems and disk allocation |
| `kernel/disk.py` | Atomically loads and saves a JSON disk image | Persistent storage |
| `kernel/seed_data.py` | Creates deterministic book, member, issue, and fine files | Data represented by files |
| `kernel/scheduler.py` | Validates workloads and simulates FCFS, SJF, SRTF, RR, Priority, and MLFQ | CPU scheduling |
| `kernel/memory.py` | Tracks address spaces, resident frames, page faults, and FIFO/LRU/Optimal eviction | Virtual memory |
| `kernel/disk_scheduler.py` | Orders disk requests and computes track-by-track head movement | Disk scheduling |
| `kernel/synchronization.py` | Tracks mutex/semaphore ownership, blocked requests, deadlocks, and recovery | Process synchronization |
| `kernel/security.py` | Tracks demo accounts, roles, authorization decisions, and syscall events | Access control and syscall tracing |
| `kernel/syscalls.py` | Dispatches modeled syscalls through the tracer | System-call interface |
| `kernel/library.py` | Searches records and performs checkout/return against simulated files | Catalog and circulation |
| `kernel/journal.py` | Records durable transaction intents and replays pending disk-image snapshots on boot | File-system recovery |
| `kernel/request_trace.py` | Captures request IDs, outcomes, and processing durations | Request observability |
| `kernel/scenarios.py` | Runs repeatable scheduler, disk, and memory comparisons | Experiments and comparison mode |
| `kernel/process.py` | Stores PCB state and implements lifecycle operations | Process management |
| `server/websocket.py` | Adapts shell and file-system requests to kernel calls and streams events | System interface boundary |
| `server/main.py` | Hosts the app, static UI, health endpoint, and startup lifecycle | Service initialization |
| `ui/js/windowManager.js` | Manages window focus, geometry, taskbar state, and lifecycle | Desktop shell / user interface |
| `ui/js/fileExplorer.js` | Renders directory contents and inode/block metadata | File-system user interface |
| `ui/js/taskManager.js` | Sends workloads and renders queues, CPU lanes, Gantt chart, and metrics | Scheduler visualization |
| `ui/js/syncMonitor.js` | Sends resource operations and renders ownership, wait relationships, deadlocks, and race traces | Synchronization visualization |
| `ui/js/systemMonitor.js` | Renders physical frames, page tables, replacement traces, and disk-head paths | Memory and disk visualization |
| `ui/js/security.js` | Displays demo accounts, access checks, and syscall audit events | Security user interface |
| `ui/js/library.js` | Searches the catalog and provides member checkout/return workflows | Library application interface |
| `ui/js/observability.js` | Displays recent request traces and journal transactions | Request and disk observability |
| `ui/js/scenarios.js` | Runs built-in scenarios and compares algorithm results | Scenario interface |
| `ui/js/sessionStudio.js` | Exports bounded, sanitized event archives and replays them visually | Presentation and replay |

## File-system data structures and decisions

- A simulated disk image contains a superblock, inode table, free-block bitmap, and base64-encoded block payloads. File bytes are UTF-8 encoded and split at the configured block size.
- Inodes record path, owner, mode, size, timestamps, allocation method, data blocks, and an optional index block. Directories do not consume data blocks.
- Contiguous allocation requires adjacent free blocks and reports `ENOSPC` when fragmentation prevents a large enough run. Linked allocation records an ordered block chain in the inode. Indexed allocation reserves an additional index block.
- Updating an existing file treats its old blocks as reusable while finding a replacement allocation, so a failed allocation leaves old contents intact.
- Disk image writes use a temporary file followed by atomic replacement. The image is initialized on first boot and saved on simulated shutdown/restart and server exit.
- The seed generator writes 60 book files, 25 member files, 20 issue files, and 8 overdue fine files under `/books`, `/members`, `/issued`, and `/fines`.
- The guest session is fixed by the kernel for file operations; clients cannot choose an owner to impersonate.
- A process is currently an immutable record with PID, parent PID, name, owner, and state. Lifecycle operations and scheduling arrive in Stage 3.
- The event hub uses a bounded in-memory deque (500 events) plus a queue per connected client.
- Boot runs as part of FastAPI's application lifespan. The UI receives the boot events as a snapshot and animates them locally.
- Shutdown and restart are simulated kernel transitions that save the disk image; they do not stop the actual web server.
- Scheduler simulations operate on discrete integer time units. A workload is validated before its PCBs are created, and every simulated job is reflected in the process table after completion.
- The scheduler supports 1–4 cores. FCFS/SJF/non-preemptive Priority preserve running jobs; SRTF/preemptive Priority/MLFQ can preempt according to their ranking; RR rotates processes at the configured quantum.
- Priority uses lower numbers for higher priority; waiting processes gain one effective priority level per aging interval. MLFQ starts jobs in level zero and demotes them when they consume a full queue quantum.
- Gantt chart data is merged into per-core intervals; the timeline retains per-unit core assignments and ready queues. Metrics use arrival-adjusted turnaround/waiting/response times and aggregate CPU capacity across the configured cores.
- Sample task-manager workloads are deterministic. CPU and memory header percentages remain presentation placeholders rather than host measurements.
- Mutexes have one permit; counting semaphores have 1–16 permits. Requests that cannot proceed enter a FIFO queue and block the owning PCB; releasing permits wakes eligible waiters.
- Deadlock detection uses the multi-instance resource-allocation reduction algorithm. Recovery terminates the highest-PID process in the detected set and releases its allocations and pending requests.
- The race demonstration replays a fixed interleaving that loses one counter update, then compares it with mutex-serialized updates. It is a deterministic teaching simulation, not a host-thread race.
- Each process can own a 1–64-page virtual address space. Eight physical frames are shared by all processes; a page-fault run starts that process's pages nonresident, and global replacement updates the evicted process's PCB frame list.
- FIFO evicts the oldest resident page, LRU the least recently used page, and Optimal the page whose next use is farthest away in the supplied offline reference string. Process termination frees its address space and resident frames.
- Disk scheduling operates on the mounted simulated disk's block range. FCFS, SSTF, SCAN, C-SCAN, LOOK, and C-LOOK expose service order, boundary/wrap steps, total head movement, and average movement per request.
- Security accounts and role checks are simulated; there are no passwords or external identity provider. Demo account roles and home paths cannot be changed through login requests, the administrator identity is reserved, and syscall identity always comes from kernel session state. Home and library permissions compare normalized path segments; librarian file access is limited to `/books`, `/members`, `/issued`, and `/fines`. `SecurityManager` gates filesystem syscalls, while `SyscallTracer` records modeled calls for the Security panel.
- Library records remain JSON files on the simulated disk. Catalog availability is calculated from active `/issued` records instead of trusting the stored `available_copies` seed value. Checkout enforces active-member and per-member/per-book limits; returns update issue status and create unpaid fine records for overdue loans.
- Mutating filesystem, terminal `mkdir`, syscall, and circulation requests write a redo intent containing the next disk image to a sidecar journal, atomically save the disk image, then append a commit marker. Boot replays intents without a commit marker and records recovery. The journal keeps summaries after commit and retains the full image only for pending recovery.
- Request traces are bounded in-memory records correlated by request ID and include operation type, success/failure, and elapsed processing time. They are intentionally separate from persisted filesystem journal data.
- Built-in scenarios use isolated scheduler, memory-manager, and disk-scheduler instances. Custom scheduler comparisons run the same validated workload once per algorithm without changing the live process table.

## Stage boundary and known limitations

Process records, scheduling, synchronization, memory, disk head movement, security, journaling, scenarios, and library operations are simulated; status indicators are not measurements from host resources, and demo accounts do not provide real authentication. Presentation mode hides desktop chrome, expands the focused application, and transfers keyboard focus into the presentation window before restoring focus on exit. Session archives are capped at 200 chronologically ordered events and contain only timestamps, allowlisted event types, and optional success/duration metrics; imported archives are validated and replayed locally without sending kernel requests. Interactive controls have visible keyboard focus indicators, and decorative transitions honor reduced-motion preferences.
