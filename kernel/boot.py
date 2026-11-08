"""LibraOS boot sequence and top-level kernel state."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from kernel.disk import DiskImage, DiskImageError
from kernel.disk_scheduler import DiskScheduler
from kernel.events import EventHub
from kernel.filesystem import FileSystem, FileSystemError
from kernel.library import LibraryManager
from kernel.journal import DiskJournal, JournalError
from kernel.memory import MemoryManager
from kernel.process import ProcessManager
from kernel.request_trace import RequestTracer
from kernel.scenarios import SCENARIO_NAMES, compare_schedulers, run_scenario
from kernel.seed_data import seed_filesystem
from kernel.scheduler import SAMPLE_WORKLOAD, Scheduler
from kernel.security import SecurityError, SecurityManager, SyscallTracer
from kernel.synchronization import SynchronizationManager


class Kernel:
    """Coordinate boot, process-table access, terminal commands, and power state."""

    def __init__(self, disk_path: Path | None = None) -> None:
        self.events = EventHub()
        self.processes = ProcessManager()
        self.memory = MemoryManager(self.processes)
        self.scheduler = Scheduler()
        self.disk_scheduler = DiskScheduler()
        self.synchronization = SynchronizationManager(self.processes)
        self.security = SecurityManager(current_user="guest")
        self.syscall_tracer = SyscallTracer(self.security)
        self.request_tracer = RequestTracer()
        self.library: LibraryManager | None = None
        self.last_schedule: dict[str, Any] | None = None
        self.last_disk_schedule: dict[str, Any] | None = None
        self.status = "stopped"
        data_directory = os.environ.get("LIBRAOS_DATA_DIR")
        default_image_path = Path(__file__).resolve().parents[1] / "data" / "disk.img.json"
        image_path = disk_path or (
            Path(data_directory) / "disk.img.json" if data_directory else default_image_path
        )
        self.disk_image = DiskImage(image_path)
        self.journal = DiskJournal(image_path.with_suffix(image_path.suffix + ".journal.jsonl"))
        self.filesystem: FileSystem | None = None

    async def boot(self) -> None:
        self.status = "booting"
        recovered_transactions = self.journal.recover(self.disk_image)
        if self.disk_image.exists():
            self.filesystem = FileSystem.from_image(self.disk_image.load())
            filesystem_message = "Mounted simulated file system from disk image"
        else:
            self.filesystem = FileSystem()
            seed_filesystem(self.filesystem)
            self.disk_image.save(self.filesystem.to_image())
            filesystem_message = "Initialized disk image and seeded library files"
        self.library = LibraryManager(self.filesystem, self.security)
        if recovered_transactions:
            self.events.publish(
                "log",
                module="journal",
                severity="warning",
                message=f"Recovered {len(recovered_transactions)} pending disk transaction(s)",
            )
        messages = [
            ("bios", "info", "LibraOS BIOS v0.1 — simulated hardware check"),
            ("boot", "info", "Detecting CPU: 4 virtual cores available"),
            ("memory", "info", f"Initialized demand-paged memory ({self.memory.frame_count} frames)"),
            ("scheduler", "info", "Initializing discrete-time multi-core scheduler"),
            ("synchronization", "info", "Initializing mutexes, semaphores, and deadlock monitor"),
            ("filesystem", "info", filesystem_message),
            ("disk", "info", f"Mounted {self.disk_image.path.name} ({self.filesystem.disk_usage()['inode_count']} inodes)"),
            ("security", "info", "Loading security interface (demo guest session)"),
            ("library", "info", "Loading catalog and circulation services"),
            ("journal", "info", f"Mounted disk journal ({len(self.journal.snapshot())} records)"),
            ("process", "info", "Starting init process [PID 1]"),
            ("shell", "info", "Starting Libra shell [PID 2]"),
            ("desktop", "info", "Launching desktop and window manager"),
        ]
        for module, severity, message in messages:
            self.events.publish(
                "log",
                module=module,
                severity=severity,
                message=message,
            )
        self.status = "running"
        self.events.publish("system", status=self.status, message="LibraOS is ready")

    async def execute_command(self, command: str, request_id: str) -> None:
        from shell.commands import execute

        if self.filesystem is None:
            raise RuntimeError("file system is not mounted")
        trace_started = self.request_tracer.start()
        before_image = self.filesystem.to_image()
        result = execute(
            command,
            self.processes.list_processes(),
            self.events.snapshot(),
            self.filesystem,
            self.run_scheduler_command,
            self.processes,
            self.synchronization,
            self.memory,
        )
        command_name = command.strip().split(maxsplit=1)[0].lower() if command.strip() else ""
        if command_name == "mkdir" and result["exit_code"] == 0:
            try:
                self._commit_journal_transaction("terminal:mkdir", request_id)
            except (DiskImageError, JournalError) as error:
                self._restore_filesystem(before_image)
                result["output"] = [f"mkdir: journal commit failed: {error}"]
                result["exit_code"] = 2
        self._record_request_trace(
            request_id=request_id,
            request_type="command",
            operation=command_name or "empty",
            started_at=trace_started,
            ok=result["exit_code"] == 0,
            error=None if result["exit_code"] == 0 else "; ".join(result["output"]),
        )
        self.events.publish(
            "terminal",
            request_id=request_id,
            command=command,
            output=result["output"],
            exit_code=result["exit_code"],
            clear=result["clear"],
            action=result["action"],
        )
        if result["action"] in {"shutdown", "reboot"}:
            await self.power(result["action"])
        if result.get("sync_changed"):
            self.events.publish("sync_state", **self.synchronization.snapshot())
        if result.get("memory_changed"):
            self.events.publish("resource_state", **self.resource_snapshot())

    def run_scheduler_command(self, algorithm: str, quantum: int) -> dict[str, Any]:
        """Schedule the built-in demonstration workload from the shell."""
        return self.schedule_workload(
            list(SAMPLE_WORKLOAD),
            algorithm=algorithm,
            quantum=quantum,
            cores=1,
        )

    def process_snapshot(self) -> list[dict[str, Any]]:
        """Return all simulated PCBs for the Task Manager."""
        return [process.to_dict() for process in self.processes.list_processes()]

    def manage_process(self, request: dict[str, Any]) -> dict[str, Any]:
        """Apply one process-control operation and publish an updated process table."""
        trace_started = self.request_tracer.start()
        operation = request.get("operation")
        pid = request.get("pid")
        result: dict[str, Any] | None = None
        error = None
        if isinstance(pid, bool) or not isinstance(pid, int):
            error = "PID must be an integer"
        elif operation == "kill":
            try:
                process = self.processes.kill(pid)
                self.synchronization.terminate_process(pid)
                self.memory.terminate_process(pid)
                result = {"pid": process.pid, "state": process.state}
                self.events.publish("sync_state", **self.synchronization.snapshot())
                self.events.publish("resource_state", **self.resource_snapshot())
            except ValueError as exception:
                error = str(exception)
        elif operation == "nice":
            priority = request.get("priority")
            if isinstance(priority, bool) or not isinstance(priority, int):
                error = "priority must be an integer from 0 to 10"
            else:
                try:
                    process = self.processes.nice(pid, priority)
                    result = {"pid": process.pid, "priority": process.priority}
                except ValueError as exception:
                    error = str(exception)
        else:
            error = f"unsupported process operation: {operation}"

        payload = {
            "type": "process_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "result": result,
            "error": error,
            "processes": self.process_snapshot(),
        }
        self._record_request_trace(
            request_id=str(request.get("request_id", "")),
            request_type="process_action",
            operation=str(operation),
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        self.events.publish(
            "log",
            module="process",
            severity="info" if error is None else "warning",
            message=(
                f"{operation} PID {pid}" if error is None
                else f"Process operation failed: {error}"
            ),
        )
        self.events.publish("process_result", **{key: value for key, value in payload.items() if key != "type"})
        return payload

    def manage_security(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch user-session and authorization requests."""
        trace_started = self.request_tracer.start()
        operation = request.get("operation")
        result: dict[str, Any] | None = None
        error = None
        try:
            if operation == "whoami":
                result = self.security.whoami()
            elif operation == "users":
                result = {"users": self.security.list_users()}
            elif operation == "login":
                username = request.get("username")
                result = self.security.login(username, role=request.get("role"), home=request.get("home"))
            elif operation == "authorize":
                result = {
                    "authorized": self.security.authorize(
                        request.get("action", "read"),
                        path=request.get("path"),
                        owner=request.get("owner"),
                        user=request.get("user"),
                    )
                }
            else:
                raise ValueError(f"unsupported security operation: {operation}")
        except (SecurityError, TypeError, ValueError) as exception:
            error = str(exception)

        payload = {
            "type": "security_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "result": result,
            "error": error,
            "current_user": self.security.current_user,
        }
        self._record_request_trace(
            request_id=str(request.get("request_id", "")),
            request_type="security",
            operation=str(operation),
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        self.events.publish(
            "log",
            module="security",
            severity="info" if error is None else "warning",
            message=(
                f"Security operation completed: {operation}"
                if error is None
                else f"Security operation failed: {error}"
            ),
        )
        self.events.publish("security_result", **{key: value for key, value in payload.items() if key != "type"})
        return payload

    def manage_library(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch catalog and circulation operations."""
        trace_started = self.request_tracer.start()
        operation = request.get("operation")
        result: dict[str, Any] | None = None
        error = None
        before_image = (
            self.filesystem.to_image()
            if self.filesystem is not None and operation in {"checkout", "return"}
            else None
        )
        if self.library is None:
            error = "library service is not initialized"
        else:
            try:
                result = self.library.handle(request)
                if operation in {"checkout", "return"}:
                    self._commit_journal_transaction(
                        f"library:{operation}",
                        str(request.get("request_id", "")),
                    )
            except (FileSystemError, SecurityError, TypeError, ValueError) as exception:
                error = str(exception)
            except (DiskImageError, JournalError) as exception:
                if before_image is not None:
                    self._restore_filesystem(before_image)
                error = str(exception)

        payload = {
            "type": "library_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "result": result,
            "error": error,
            "current_user": self.security.current_user,
        }
        self._record_request_trace(
            request_id=str(request.get("request_id", "")),
            request_type="library",
            operation=str(operation),
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        self.events.publish(
            "log",
            module="library",
            severity="info" if error is None else "warning",
            message=(
                f"Library operation completed: {operation}"
                if error is None
                else f"Library operation failed: {error}"
            ),
        )
        self.events.publish(
            "library_result",
            **{key: value for key, value in payload.items() if key != "type"},
        )
        return payload

    def execute_syscall(self, syscall_name: str, **kwargs: Any) -> dict[str, Any]:
        """Run a modeled syscall and record the invocation in the tracer."""
        syscall = str(syscall_name).strip()
        if not syscall:
            raise ValueError("syscall name must not be empty")

        requested_user = kwargs.get("user")
        if isinstance(requested_user, str) and requested_user.strip():
            try:
                normalized_user = self.security._normalize_user(requested_user.strip())
            except ValueError:
                normalized_user = self.security.current_user
            user = normalized_user if normalized_user == self.security.current_user else self.security.current_user
        else:
            user = self.security.current_user
        trace_payload = {key: value for key, value in kwargs.items() if key != "user"}
        event = self.syscall_tracer.trace(syscall, user=user, **trace_payload)
        filesystem = kwargs.get("filesystem") or self.filesystem
        path = kwargs.get("path")
        trace_started = self.request_tracer.start()
        request_id = str(kwargs.get("request_id", ""))
        mutating = syscall in {"mkdir", "create", "write", "delete"} and filesystem is self.filesystem
        before_image = filesystem.to_image() if mutating and filesystem is not None else None
        result: dict[str, Any] | None = None
        error: str | None = None
        try:
            if syscall in {"read", "open", "stat", "list", "mkdir", "create", "write", "delete"} and filesystem is not None:
                if syscall in {"list", "read", "stat", "open"}:
                    self.security.require("read", path=path, owner=kwargs.get("owner"), user=user)
                if syscall in {"mkdir", "create", "write", "delete"}:
                    self.security.require("write", path=path, owner=kwargs.get("owner"), user=user)

                if syscall == "list":
                    result = {"path": path or "/", "entries": filesystem.list_directory(path or "/")}
                elif syscall == "read":
                    result = {"path": path, "content": filesystem.read_file(path)}
                elif syscall == "stat":
                    result = filesystem.stat(path)
                elif syscall == "mkdir":
                    result = filesystem.make_directory(path, owner=user)
                elif syscall == "create":
                    result = filesystem.create_file(path, kwargs.get("content", ""), owner=user, allocation=kwargs.get("allocation"))
                elif syscall == "write":
                    result = filesystem.write_file(path, kwargs.get("content", ""), owner=user, allocation=kwargs.get("allocation"))
                elif syscall == "delete":
                    filesystem.delete(path, owner=user)
                    result = {"path": path, "deleted": True}
                elif syscall == "open":
                    result = {"path": path, "flags": kwargs.get("flags", "r"), "owner": user}
                else:
                    result = {"path": path}
                if mutating:
                    self._commit_journal_transaction(f"syscall:{syscall}", request_id)
            else:
                result = {"path": path}

            event["result"] = result or {"path": path}
            event["ok"] = True
            self._record_request_trace(
                request_id=request_id,
                request_type="syscall",
                operation=syscall,
                started_at=trace_started,
                ok=True,
            )
            self.events.publish("syscall", syscall=syscall, user=user, result=event["result"])
            return event
        except (DiskImageError, JournalError) as exception:
            if before_image is not None:
                self._restore_filesystem(before_image)
            error = str(exception)
            event["ok"] = False
            event["error"] = error
            event["result"] = {"path": path}
            self._record_request_trace(
                request_id=request_id,
                request_type="syscall",
                operation=syscall,
                started_at=trace_started,
                ok=False,
                error=error,
            )
            self.events.publish("syscall", syscall=syscall, user=user, result=event["result"], error=error)
            return event
        except (FileSystemError, PermissionError, ValueError, TypeError) as exception:
            error = str(exception)
            event["ok"] = False
            event["error"] = error
            event["result"] = {"path": path}
            if before_image is not None:
                self._restore_filesystem(before_image)
            self._record_request_trace(
                request_id=request_id,
                request_type="syscall",
                operation=syscall,
                started_at=trace_started,
                ok=False,
                error=error,
            )
            self.events.publish("syscall", syscall=syscall, user=user, result=event["result"], error=error)
            return event

    def resource_snapshot(self) -> dict[str, Any]:
        """Return the current simulated memory and disk-scheduler state."""
        return {
            **self.memory.snapshot(),
            "disk_size": self.filesystem.block_count if self.filesystem is not None else None,
            "last_disk_schedule": self.last_disk_schedule,
            "processes": self.process_snapshot(),
        }

    def manage_scenarios(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run an isolated benchmark scenario or compare supplied workloads."""
        trace_started = self.request_tracer.start()
        operation = request.get("operation", "run")
        result: dict[str, Any] | None = None
        error = None
        try:
            if operation == "run":
                disk_size = self.filesystem.block_count if self.filesystem is not None else 0
                result = run_scenario(request.get("scenario"), disk_size, self.scheduler)
            elif operation == "compare":
                result = {
                    "comparison": compare_schedulers(
                        self.scheduler,
                        request.get("workload"),
                        algorithms=request.get("algorithms"),
                        quantum=request.get("quantum", 3),
                        cores=request.get("cores", 1),
                    )
                }
            elif operation == "list":
                result = {
                    "scenarios": [
                        {"id": scenario_id, "title": title}
                        for scenario_id, title in SCENARIO_NAMES.items()
                    ]
                }
            else:
                raise ValueError(f"unsupported scenario operation: {operation}")
        except (TypeError, ValueError) as exception:
            error = str(exception)

        payload = {
            "type": "scenario_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "result": result,
            "error": error,
        }
        self._record_request_trace(
            request_id=str(request.get("request_id", "")),
            request_type="scenario",
            operation=str(operation),
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        self.events.publish(
            "scenario_result",
            **{key: value for key, value in payload.items() if key != "type"},
        )
        return payload

    def manage_observability(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return recent disk-journal and request-trace data."""
        operation = request.get("operation", "snapshot")
        error = None
        if operation == "clear_traces":
            self.request_tracer.clear()
        elif operation != "snapshot":
            error = f"unsupported observability operation: {operation}"
        payload = {
            "type": "observability_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "error": error,
            "journal": self.journal.snapshot(),
            "traces": self.request_tracer.snapshot(),
        }
        self.events.publish(
            "observability_result",
            **{key: value for key, value in payload.items() if key != "type"},
        )
        return payload

    def manage_resources(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch memory-manager or disk-scheduler requests."""
        trace_started = self.request_tracer.start()
        operation = request.get("operation")
        result: dict[str, Any] | None = None
        error = None
        try:
            if operation == "state":
                pass
            elif operation == "memory_allocate":
                result = self.memory.allocate(request.get("pid"), request.get("pages"))
            elif operation == "memory_free":
                result = self.memory.release(request.get("pid"))
            elif operation == "memory_simulate":
                result = self.memory.simulate(
                    request.get("pid"),
                    request.get("references"),
                    algorithm=request.get("algorithm", "fifo"),
                )
            elif operation == "disk_schedule":
                if self.filesystem is None:
                    raise ValueError("simulated disk is not mounted")
                result = self.disk_scheduler.run(
                    request.get("requests"),
                    head=request.get("head"),
                    disk_size=self.filesystem.block_count,
                    algorithm=request.get("algorithm", "fcfs"),
                    direction=request.get("direction", "right"),
                )
                self.last_disk_schedule = result
            else:
                raise ValueError(f"unsupported resource operation: {operation}")
        except (TypeError, ValueError) as exception:
            error = str(exception)

        payload = {
            "type": "resource_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "result": result,
            "error": error,
            **self.resource_snapshot(),
        }
        self._record_request_trace(
            request_id=str(request.get("request_id", "")),
            request_type="resource",
            operation=str(operation),
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        self.events.publish(
            "log",
            module=(
                "memory" if isinstance(operation, str) and operation.startswith("memory_")
                else "disk" if operation == "disk_schedule"
                else "resource"
            ),
            severity="info" if error is None else "warning",
            message=(
                f"Resource operation completed: {operation}"
                if error is None
                else f"Resource operation failed: {error}"
            ),
        )
        self.events.publish(
            "resource_result",
            **{key: value for key, value in payload.items() if key != "type"},
        )
        return payload

    def manage_synchronization(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch one synchronization operation and publish a complete monitor snapshot."""
        trace_started = self.request_tracer.start()
        operation = request.get("operation")
        result: dict[str, Any] | None = None
        error = None
        try:
            if operation == "state":
                pass
            elif operation == "create":
                result = self.synchronization.create_resource(
                    request.get("name"),
                    request.get("kind"),
                    request.get("capacity", 1),
                )
            elif operation == "acquire":
                result = self.synchronization.acquire(request.get("pid"), request.get("name"))
            elif operation == "release":
                result = self.synchronization.release(request.get("pid"), request.get("name"))
            elif operation == "detect":
                result = {"deadlocked_pids": self.synchronization.detect_deadlock()}
            elif operation == "recover":
                result = self.synchronization.recover_deadlock()
            elif operation == "deadlock_demo":
                result = self.synchronization.create_deadlock_demo()
            elif operation == "race_demo":
                result = self.synchronization.run_race_demo()
            else:
                raise ValueError(f"unsupported synchronization operation: {operation}")
        except (TypeError, ValueError) as exception:
            error = str(exception)

        if operation == "recover" and error is None and result and result.get("victim_pid") is not None:
            self.memory.terminate_process(result["victim_pid"])
            self.events.publish("resource_state", **self.resource_snapshot())

        payload = {
            "type": "sync_result",
            "request_id": request.get("request_id", ""),
            "operation": operation,
            "ok": error is None,
            "result": result,
            "error": error,
            **self.synchronization.snapshot(),
        }
        self._record_request_trace(
            request_id=str(request.get("request_id", "")),
            request_type="sync",
            operation=str(operation),
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        self.events.publish(
            "log",
            module="synchronization",
            severity="info" if error is None else "warning",
            message=(
                f"Synchronization operation completed: {operation}"
                if error is None
                else f"Synchronization operation failed: {error}"
            ),
        )
        self.events.publish("sync_result", **{key: value for key, value in payload.items() if key != "type"})
        return payload

    def schedule_workload(
        self,
        workload: Any,
        *,
        algorithm: str = "fcfs",
        quantum: int = 3,
        cores: int = 1,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Validate, create PCBs, simulate, and publish one workload."""
        trace_started = self.request_tracer.start()
        if not isinstance(algorithm, str):
            raise ValueError("algorithm must be text")
        if not isinstance(workload, list) or not workload:
            raise ValueError("workload must be a non-empty list")
        probe = [
            {
                "pid": index + 1,
                "name": item.get("name", f"process-{index + 1}") if isinstance(item, dict) else "",
                "arrival_time": item.get("arrival_time", 0) if isinstance(item, dict) else 0,
                "burst_time": item.get("burst_time") if isinstance(item, dict) else None,
                "priority": item.get("priority", 5) if isinstance(item, dict) else 5,
            }
            for index, item in enumerate(workload)
        ]
        self.scheduler.run(probe, algorithm=algorithm, quantum=quantum, cores=cores)

        process_workload = []
        created = []
        for job in probe:
            process = self.processes.spawn(
                job["name"],
                owner="guest",
                ppid=1,
                priority=job["priority"],
                burst_time=job["burst_time"],
                arrival_time=job["arrival_time"],
                state="READY",
            )
            created.append(process)
            process_workload.append(
                {
                    "pid": process.pid,
                    "name": process.name,
                    "arrival_time": process.arrival_time,
                    "burst_time": process.burst_time,
                    "priority": process.priority,
                }
            )

        result = self.scheduler.run(
            process_workload,
            algorithm=algorithm,
            quantum=quantum,
            cores=cores,
        )
        self.processes.apply_schedule(result["processes"])
        self.last_schedule = result
        self.events.publish(
            "log",
            module="scheduler",
            severity="info",
            message=(
                f"Completed {result['algorithm']} scheduling: {len(created)} processes, "
                f"{cores} core(s), {result['metrics']['context_switches']} context switches"
            ),
        )
        self._record_request_trace(
            request_id=str(request_id or ""),
            request_type="schedule",
            operation=algorithm,
            started_at=trace_started,
            ok=True,
        )
        self.events.publish("scheduler_result", request_id=request_id, **result)
        return result

    def execute_filesystem_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a user-mode file request through the kernel file-system API."""
        if self.filesystem is None:
            raise RuntimeError("file system is not mounted")
        operation = request.get("operation")
        path = request.get("path", "/")
        owner = self.security.current_user
        request_id = request.get("request_id", "")
        result: dict[str, Any] | None = None
        error = None
        error_code = None
        trace_started = self.request_tracer.start()
        before_image = self.filesystem.to_image()
        try:
            if not isinstance(operation, str):
                raise FileSystemError("EINVAL", "operation must be text")
            if not isinstance(path, str):
                raise FileSystemError("EINVAL", "path must be text")
            if not isinstance(owner, str):
                raise FileSystemError("EINVAL", "owner must be text")
            if operation in {"list", "read", "stat"}:
                self.security.require("read", path=path, owner=owner, user=owner)
            elif operation in {"mkdir", "create", "write", "delete"}:
                self.security.require("write", path=path, owner=owner, user=owner)
            elif operation in {"set_allocation", "usage"}:
                self.security.require("read", path=path, owner=owner, user=owner)
            if operation == "list":
                result = {"path": path, "entries": self.filesystem.list_directory(path)}
            elif operation == "read":
                result = {"path": path, "content": self.filesystem.read_file(path)}
            elif operation == "stat":
                result = self.filesystem.stat(path)
            elif operation == "mkdir":
                result = self.filesystem.make_directory(path, owner=owner)
            elif operation == "create":
                content = request.get("content", "")
                allocation = request.get("allocation")
                if not isinstance(content, str) or (allocation is not None and not isinstance(allocation, str)):
                    raise FileSystemError("EINVAL", "content and allocation must be text")
                result = self.filesystem.create_file(path, content, owner=owner, allocation=allocation)
            elif operation == "write":
                content = request.get("content")
                allocation = request.get("allocation")
                if not isinstance(content, str) or (allocation is not None and not isinstance(allocation, str)):
                    raise FileSystemError("EINVAL", "content and allocation must be text")
                result = self.filesystem.write_file(path, content, owner=owner, allocation=allocation)
            elif operation == "delete":
                self.filesystem.delete(path, owner=owner)
                result = {"path": path, "deleted": True}
            elif operation == "set_allocation":
                method = request.get("allocation")
                if not isinstance(method, str):
                    raise FileSystemError("EINVAL", "allocation must be text")
                result = {"allocation_method": self.filesystem.set_allocation_method(method)}
            elif operation == "usage":
                result = self.filesystem.disk_usage()
            else:
                raise FileSystemError("ENOSYS", f"unsupported file-system operation: {operation}")
            if operation in {"mkdir", "create", "write", "delete", "set_allocation"}:
                self._commit_journal_transaction(
                    f"filesystem:{operation}",
                    str(request_id),
                )
        except (FileSystemError, PermissionError) as exception:
            if operation in {"mkdir", "create", "write", "delete", "set_allocation"}:
                self._restore_filesystem(before_image)
            error = str(exception)
            try:
                error_code = exception.code
            except AttributeError:
                error_code = "EACCES"
        except (DiskImageError, JournalError) as exception:
            self._restore_filesystem(before_image)
            error = str(exception)
            error_code = "EIO"

        operation_name = operation if isinstance(operation, str) else "request"
        self._record_request_trace(
            request_id=str(request_id),
            request_type="filesystem",
            operation=operation_name,
            started_at=trace_started,
            ok=error is None,
            error=error,
        )
        if operation_name in {"create", "write", "mkdir", "delete", "set_allocation"} and error is None:
            self.events.publish(
                "log",
                module="filesystem",
                severity="info",
                message=f"{operation_name} {path}",
            )
        elif error is not None:
            self.events.publish(
                "log",
                module="filesystem",
                severity="warning",
                message=f"{operation_name} failed ({error_code}): {error}",
            )

        return {
            "type": "filesystem_result",
            "request_id": request_id,
            "operation": operation_name,
            "ok": error is None,
            "result": result,
            "error": error,
            "error_code": error_code,
        }

    def save_disk_image(self) -> None:
        """Persist the mounted simulated disk image."""
        if self.filesystem is None:
            raise RuntimeError("cannot save before the file system is mounted")
        self.disk_image.save(self.filesystem.to_image())

    def _commit_journal_transaction(self, operation: str, request_id: str) -> None:
        if self.filesystem is None:
            raise RuntimeError("cannot journal before the file system is mounted")
        transaction_id = self.journal.begin(operation, request_id, self.filesystem.to_image())
        try:
            self.disk_image.save(self.filesystem.to_image())
        except DiskImageError as error:
            self.journal.abort(transaction_id, str(error))
            raise
        try:
            self.journal.commit(transaction_id)
        except JournalError as error:
            self.events.publish(
                "log",
                module="journal",
                severity="warning",
                message=f"Transaction {transaction_id} is durable and will be verified during recovery: {error}",
            )

    def _restore_filesystem(self, image: dict[str, Any]) -> None:
        if self.filesystem is None:
            return
        restored = FileSystem.from_image(image)
        self.filesystem.__dict__.clear()
        self.filesystem.__dict__.update(restored.__dict__)
        self.library = LibraryManager(self.filesystem, self.security)

    def _record_request_trace(
        self,
        *,
        request_id: str,
        request_type: str,
        operation: str,
        started_at: float,
        ok: bool,
        error: str | None = None,
    ) -> None:
        event = self.request_tracer.record(
            request_id=request_id,
            request_type=request_type,
            operation=operation,
            started_at=started_at,
            ok=ok,
            error=error,
        )
        self.events.publish("request_trace", **event)

    async def power(self, action: str) -> None:
        if action not in {"shutdown", "reboot"}:
            raise ValueError(f"unsupported power action: {action}")
        try:
            self.save_disk_image()
        except DiskImageError as error:
            self.events.publish(
                "log",
                module="disk",
                severity="error",
                message=f"Could not save disk image: {error}",
            )
            self.events.publish(
                "power",
                action="error",
                status=self.status,
                message=str(error),
            )
            return
        if action == "shutdown":
            self.status = "stopped"
            self.events.publish(
                "log",
                module="power",
                severity="warning",
                message="Disk image saved; LibraOS is shutting down",
            )
            self.events.publish("power", action="shutdown", status=self.status)
            return

        self.events.publish(
            "log",
            module="power",
            severity="warning",
            message="Restart requested",
        )
        self.status = "stopped"
        self.events.publish("power", action="reboot", status=self.status)
        await self.boot()
