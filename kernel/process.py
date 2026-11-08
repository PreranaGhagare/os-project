"""Process control blocks and basic process lifecycle operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Process:
    """Simulated PCB with lifecycle, scheduling, and resource metadata."""

    pid: int
    ppid: int
    name: str
    owner: str
    state: str
    priority: int = 5
    burst_time: int = 0
    remaining_time: int = 0
    arrival_time: int = 0
    start_time: int | None = None
    finish_time: int | None = None
    waiting_time: int = 0
    turnaround_time: int | None = None
    response_time: int | None = None
    memory_pages: list[int] = field(default_factory=list)
    open_file_table: list[str] = field(default_factory=list)
    held_locks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable process snapshot."""
        return asdict(self)


class ProcessManager:
    """Own process identifiers, lifecycle transitions, and process snapshots."""

    def __init__(self) -> None:
        self._next_pid = 4
        self._processes = [
            Process(pid=1, ppid=0, name="init", owner="root", state="RUNNING", priority=0),
            Process(pid=2, ppid=1, name="libra-shell", owner="guest", state="WAITING", priority=3),
            Process(pid=3, ppid=1, name="desktop", owner="guest", state="RUNNING", priority=2),
        ]

    def list_processes(self) -> list[Process]:
        """Return a stable snapshot of process records."""
        return list(self._processes)

    def get(self, pid: int) -> Process:
        """Return a process by PID."""
        for process in self._processes:
            if process.pid == pid:
                return process
        raise ValueError(f"no such process: {pid}")

    def fork(self, parent_pid: int, name: str | None = None) -> Process:
        """Create a READY child process from an existing process."""
        parent = self.get(parent_pid)
        return self.spawn(
            name or parent.name,
            owner=parent.owner,
            ppid=parent.pid,
            priority=parent.priority,
            state="READY",
        )

    def spawn(
        self,
        name: str,
        *,
        owner: str = "guest",
        ppid: int = 1,
        priority: int = 5,
        burst_time: int = 0,
        arrival_time: int = 0,
        state: str = "NEW",
    ) -> Process:
        """Allocate a PCB with validated initial fields."""
        if not name.strip():
            raise ValueError("process name must not be empty")
        if priority < 0 or priority > 10:
            raise ValueError("priority must be between 0 and 10")
        self.get(ppid)
        process = Process(
            pid=self._next_pid,
            ppid=ppid,
            name=name.strip(),
            owner=owner,
            state=state,
            priority=priority,
            burst_time=burst_time,
            remaining_time=burst_time,
            arrival_time=arrival_time,
        )
        self._next_pid += 1
        self._processes.append(process)
        return process

    def exec(self, pid: int, name: str) -> Process:
        """Replace a process image by changing its simulated program name."""
        process = self.get(pid)
        self._require_active(process)
        if not name.strip():
            raise ValueError("process name must not be empty")
        process.name = name.strip()
        process.state = "READY"
        return process

    def exit(self, pid: int) -> Process:
        """Terminate a process and mark its remaining time as zero."""
        if pid == 1:
            raise ValueError("cannot exit init (PID 1)")
        process = self.get(pid)
        self._require_active(process)
        process.state = "TERMINATED"
        process.remaining_time = 0
        return process

    def kill(self, pid: int) -> Process:
        """Terminate a process unless it is the init process."""
        if pid == 1:
            raise ValueError("cannot terminate init (PID 1)")
        return self.exit(pid)

    def wait(self, parent_pid: int, child_pid: int) -> Process:
        """Wait for a direct child; return only when it has terminated."""
        parent = self.get(parent_pid)
        child = self.get(child_pid)
        if child.ppid != parent.pid:
            raise ValueError(f"PID {child_pid} is not a child of PID {parent_pid}")
        if child.state != "TERMINATED":
            raise ValueError(f"PID {child_pid} has not terminated")
        return child

    def nice(self, pid: int, priority: int) -> Process:
        """Change a process priority within the supported 0-10 range."""
        process = self.get(pid)
        self._require_active(process)
        if priority < 0 or priority > 10:
            raise ValueError("priority must be between 0 and 10")
        process.priority = priority
        return process

    def apply_schedule(self, scheduled: list[dict[str, Any]]) -> None:
        """Copy final scheduler state and metrics into the owning PCBs."""
        for result in scheduled:
            process = self.get(int(result["pid"]))
            process.state = str(result["state"])
            process.remaining_time = int(result["remaining_time"])
            process.start_time = result["start_time"]
            process.finish_time = result["finish_time"]
            process.waiting_time = int(result["waiting_time"])
            process.turnaround_time = result["turnaround_time"]
            process.response_time = result["response_time"]

    @staticmethod
    def _require_active(process: Process) -> None:
        if process.state == "TERMINATED":
            raise ValueError(f"PID {process.pid} is already terminated")
