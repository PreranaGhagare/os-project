"""Simulated mutexes, semaphores, deadlock handling, and race demonstrations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from kernel.process import Process, ProcessManager


@dataclass
class Resource:
    name: str
    kind: str
    capacity: int
    available: int
    allocations: dict[int, int] = field(default_factory=dict)
    requests: dict[int, int] = field(default_factory=dict)
    wait_queue: list[int] = field(default_factory=list)


class SynchronizationManager:
    """Manage simulated synchronization resources for kernel processes."""

    def __init__(self, processes: ProcessManager) -> None:
        self.processes = processes
        self._resources: dict[str, Resource] = {}
        self.create_resource("catalog-lock", "mutex")
        self.create_resource("circulation-slots", "semaphore", capacity=2)

    def create_resource(self, name: str, kind: str, capacity: int = 1) -> dict[str, Any]:
        if not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}", name):
            raise ValueError("resource name must be 1-32 letters, numbers, underscores, or hyphens")
        if name in self._resources:
            raise ValueError(f"resource already exists: {name}")
        if not isinstance(kind, str) or kind not in {"mutex", "semaphore"}:
            raise ValueError("resource type must be mutex or semaphore")
        if isinstance(capacity, bool) or not isinstance(capacity, int):
            raise ValueError("capacity must be an integer from 1 to 16")
        if kind == "mutex" and capacity != 1:
            raise ValueError("mutex capacity must be 1")
        if not 1 <= capacity <= 16:
            raise ValueError("capacity must be between 1 and 16")
        resource = Resource(name, kind, capacity, capacity)
        self._resources[name] = resource
        return self.snapshot()

    def acquire(self, pid: int, name: str) -> dict[str, Any]:
        process = self._active_process(pid)
        resource = self._resource(name)
        if pid in resource.requests:
            raise ValueError(f"PID {pid} is already waiting for {name}")
        if resource.kind == "mutex" and pid in resource.allocations:
            raise ValueError(f"mutex {name} is not reentrant")

        if resource.available > 0 and not resource.wait_queue:
            resource.available -= 1
            resource.allocations[pid] = resource.allocations.get(pid, 0) + 1
            self._record_lock(process.pid, name, True)
            return {"acquired": True, "pid": pid, "resource": name}

        resource.requests[pid] = 1
        resource.wait_queue.append(pid)
        process.state = "BLOCKED"
        return {
            "acquired": False,
            "pid": pid,
            "resource": name,
            "deadlocked_pids": self.detect_deadlock(),
        }

    def release(self, pid: int, name: str) -> dict[str, Any]:
        self._active_process(pid)
        resource = self._resource(name)
        allocated = resource.allocations.get(pid, 0)
        if allocated == 0:
            raise ValueError(f"PID {pid} does not hold {name}")
        if allocated == 1:
            del resource.allocations[pid]
            self._record_lock(pid, name, False)
        else:
            resource.allocations[pid] = allocated - 1
        resource.available += 1
        awakened = self._grant_waiters(resource)
        return {"released": True, "pid": pid, "resource": name, "awakened_pids": awakened}

    def detect_deadlock(self) -> list[int]:
        """Return PIDs that cannot complete under the current resource requests."""
        active = {
            process.pid: process
            for process in self.processes.list_processes()
            if process.state != "TERMINATED"
        }
        resource_names = list(self._resources)
        work = {name: resource.available for name, resource in self._resources.items()}
        allocation = {
            pid: {name: self._resources[name].allocations.get(pid, 0) for name in resource_names}
            for pid in active
        }
        requests = {
            pid: {name: self._resources[name].requests.get(pid, 0) for name in resource_names}
            for pid in active
        }
        finish = {
            pid: not any(allocation[pid].values())
            for pid in active
        }

        progress = True
        while progress:
            progress = False
            for pid in active:
                if finish[pid]:
                    continue
                if all(requests[pid][name] <= work[name] for name in resource_names):
                    for name in resource_names:
                        work[name] += allocation[pid][name]
                    finish[pid] = True
                    progress = True
        return sorted(pid for pid, can_finish in finish.items() if not can_finish)

    def recover_deadlock(self) -> dict[str, Any]:
        deadlocked = self.detect_deadlock()
        if not deadlocked:
            return {"recovered": False, "deadlocked_pids": [], "victim_pid": None}

        victim_pid = max(deadlocked)
        victim = self.processes.kill(victim_pid)
        awakened = self._release_process_resources(victim_pid)
        return {
            "recovered": True,
            "deadlocked_pids": deadlocked,
            "victim_pid": victim_pid,
            "victim_name": victim.name,
            "awakened_pids": awakened,
        }

    def terminate_process(self, pid: int) -> list[int]:
        """Release resources and cancel pending requests after process termination."""
        return self._release_process_resources(pid)

    def create_deadlock_demo(self) -> dict[str, Any]:
        first = self.processes.spawn("deadlock-worker-a", ppid=1, state="READY")
        second = self.processes.spawn("deadlock-worker-b", ppid=1, state="READY")
        first_lock = f"demo-a-{first.pid}"
        second_lock = f"demo-b-{first.pid}"
        self.create_resource(first_lock, "mutex")
        self.create_resource(second_lock, "mutex")
        self.acquire(first.pid, first_lock)
        self.acquire(second.pid, second_lock)
        self.acquire(first.pid, second_lock)
        self.acquire(second.pid, first_lock)
        return {
            "processes": [first.pid, second.pid],
            "resources": [first_lock, second_lock],
            "deadlocked_pids": self.detect_deadlock(),
        }

    @staticmethod
    def run_race_demo() -> dict[str, Any]:
        """Show a lost update and its mutex-protected serial equivalent."""
        unsafe_trace = [
            {"process": "worker-a", "action": "read", "value": 0},
            {"process": "worker-b", "action": "read", "value": 0},
            {"process": "worker-a", "action": "write", "value": 1},
            {"process": "worker-b", "action": "write", "value": 1},
        ]
        safe_trace = [
            {"process": "worker-a", "action": "read", "value": 0},
            {"process": "worker-a", "action": "write", "value": 1},
            {"process": "worker-b", "action": "read", "value": 1},
            {"process": "worker-b", "action": "write", "value": 2},
        ]
        return {
            "unsafe_counter": unsafe_trace[-1]["value"],
            "safe_counter": safe_trace[-1]["value"],
            "expected_counter": 2,
            "unsafe_trace": unsafe_trace,
            "safe_trace": safe_trace,
        }

    def snapshot(self) -> dict[str, Any]:
        resources = []
        wait_for = []
        for resource in self._resources.values():
            holders = [
                {"pid": pid, "count": count}
                for pid, count in sorted(resource.allocations.items())
            ]
            waiters = [
                {"pid": pid, "requested": resource.requests[pid]}
                for pid in resource.wait_queue
                if pid in resource.requests
            ]
            for waiter in waiters:
                wait_for.extend(
                    {
                        "from_pid": waiter["pid"],
                        "to_pid": holder["pid"],
                        "resource": resource.name,
                    }
                    for holder in holders
                )
            resources.append(
                {
                    "name": resource.name,
                    "kind": resource.kind,
                    "capacity": resource.capacity,
                    "available": resource.available,
                    "holders": holders,
                    "waiters": waiters,
                }
            )
        return {
            "resources": resources,
            "wait_for": wait_for,
            "deadlocked_pids": self.detect_deadlock(),
            "processes": [process.to_dict() for process in self.processes.list_processes()],
        }

    def _active_process(self, pid: int) -> Process:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise ValueError("PID must be an integer")
        process = self.processes.get(pid)
        if process.state == "TERMINATED":
            raise ValueError(f"PID {pid} is already terminated")
        if process.state == "BLOCKED":
            raise ValueError(f"PID {pid} is blocked waiting for a resource")
        return process

    def _resource(self, name: str) -> Resource:
        if not isinstance(name, str):
            raise ValueError("resource name must be text")
        try:
            return self._resources[name]
        except KeyError as error:
            raise ValueError(f"no such resource: {name}") from error

    def _release_process_resources(self, pid: int) -> list[int]:
        for resource in self._resources.values():
            resource.requests.pop(pid, None)
            resource.wait_queue = [waiter for waiter in resource.wait_queue if waiter != pid]
            allocated = resource.allocations.pop(pid, 0)
            if allocated:
                resource.available += allocated
                self._record_lock(pid, resource.name, False)
        return self._grant_all_waiters()

    def _grant_all_waiters(self) -> list[int]:
        awakened = []
        for resource in self._resources.values():
            awakened.extend(self._grant_waiters(resource))
        return awakened

    def _grant_waiters(self, resource: Resource) -> list[int]:
        awakened = []
        while resource.wait_queue and resource.available:
            pid = resource.wait_queue[0]
            requested = resource.requests.get(pid)
            if requested is None:
                resource.wait_queue.pop(0)
                continue
            if requested > resource.available:
                break
            resource.wait_queue.pop(0)
            del resource.requests[pid]
            resource.available -= requested
            resource.allocations[pid] = resource.allocations.get(pid, 0) + requested
            process = self.processes.get(pid)
            process.state = "READY"
            self._record_lock(pid, resource.name, True)
            awakened.append(pid)
        return awakened

    def _record_lock(self, pid: int, name: str, held: bool) -> None:
        process = self.processes.get(pid)
        if held:
            if name not in process.held_locks:
                process.held_locks.append(name)
        elif not any(
            resource.allocations.get(pid, 0)
            for resource in self._resources.values()
            if resource.name == name
        ):
            process.held_locks = [lock for lock in process.held_locks if lock != name]
