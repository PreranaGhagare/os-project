"""Allow-listed Stage 1 terminal commands."""

from __future__ import annotations

import shlex
from datetime import datetime
from typing import Any, Callable

from kernel.filesystem import FileSystemError
from kernel.memory import MemoryManager
from kernel.process import ProcessManager
from kernel.synchronization import SynchronizationManager


HELP = [
    "LibraOS Stage 1 commands:",
    "  help                 Show available commands",
    "  clear                Clear this terminal",
    "  ps                   List simulated processes",
    "  top                  Show a system status snapshot",
    "  ls [path]            List a simulated directory",
    "  cat <path>           Read a simulated file",
    "  mkdir <path>         Create a simulated directory",
    "  df                   Show simulated disk usage",
    "  sched <algo> [q]     Schedule the demo workload (q is the RR quantum)",
    "  fork-test            Spawn three demonstration worker processes",
    "  fork <pid> [name]    Fork a simulated child process",
    "  exec <pid> <name>    Replace a process image",
    "  exit <pid>           Exit a simulated process",
    "  kill <pid>           Terminate a simulated process",
    "  nice <pid> <0-10>    Change simulated process priority",
    "  wait <parent> <child> Wait for a terminated child",
    "  pwd                  Print the current virtual directory",
    "  whoami               Show the demo user",
    "  uname                Show system information",
    "  date                 Show the server's local time",
    "  dmesg                Show recent kernel log entries",
    "  echo <text>          Print text",
    "  shutdown             Power off the simulated desktop",
    "  reboot               Restart the simulated kernel",
]


def execute(
    command: str,
    processes: list[Any],
    events: list[dict[str, Any]],
    filesystem: Any = None,
    scheduler: Callable[[str, int], dict[str, Any]] | None = None,
    process_manager: ProcessManager | None = None,
    sync_manager: SynchronizationManager | None = None,
    memory_manager: MemoryManager | None = None,
) -> dict[str, Any]:
    """Parse and execute one built-in command without invoking the host shell."""
    try:
        parts = shlex.split(command)
    except ValueError as error:
        return _result([f"parse error: {error}"], exit_code=2)

    if not parts:
        return _result([])

    name, args = parts[0].lower(), parts[1:]
    if name == "help":
        return _result(HELP)
    if name == "clear":
        return _result([], clear=True)
    if name == "ps":
        lines = ["PID  PPID  STATE      OWNER  NAME"]
        lines.extend(
            f"{process.pid:<4} {process.ppid:<5} {process.state:<10} "
            f"{process.owner:<6} {process.name}"
            for process in processes
        )
        return _result(lines)
    if name == "top":
        return _result(
            [
                "LibraOS system snapshot",
                f"Processes: {len(processes)}",
                "Memory: 18% (illustrative)   CPU scheduling: simulated",
                "Open Task Manager to run workloads and inspect CPU metrics.",
            ]
        )
    if name == "ls":
        path = args[0] if args else "/"
        if filesystem is not None:
            try:
                entries = filesystem.list_directory(path)
            except FileSystemError as error:
                return _result([f"ls: {error}"], exit_code=2)
            return _result(
                [
                    f"{entry['name']}{'/' if entry['type'] == 'directory' else ''}"
                    for entry in entries
                ]
                or ["(empty directory)"]
            )
        if path not in {"/", ".", "/etc", "/home", "/var"}:
            return _result([f"ls: {path}: no such directory"], exit_code=2)
        entries = {
            "/": ["etc/", "home/", "var/"],
            ".": ["etc/", "home/", "var/"],
            "/etc": ["libraos.conf"],
            "/home": ["guest/"],
            "/var": ["log/"],
        }
        return _result(entries[path])
    if name == "cat":
        if len(args) != 1:
            return _result(["usage: cat <path>"], exit_code=2)
        if filesystem is None:
            return _result(["cat: simulated file system is unavailable"], exit_code=2)
        try:
            return _result(filesystem.read_file(args[0]).splitlines() or [""])
        except FileSystemError as error:
            return _result([f"cat: {error}"], exit_code=2)
    if name == "mkdir":
        if len(args) != 1:
            return _result(["usage: mkdir <path>"], exit_code=2)
        if filesystem is None:
            return _result(["mkdir: simulated file system is unavailable"], exit_code=2)
        try:
            filesystem.make_directory(args[0], owner="guest")
            return _result([f"created directory {args[0]}"])
        except FileSystemError as error:
            return _result([f"mkdir: {error}"], exit_code=2)
    if name == "df":
        if filesystem is None:
            return _result(["df: simulated file system is unavailable"], exit_code=2)
        usage = filesystem.disk_usage()
        return _result(
            [
                "Filesystem  Blocks  Used  Available  Size",
                f"libra-disk  {usage['block_count']}  {usage['used_blocks']}  "
                f"{usage['free_blocks']}  {usage['block_count'] * usage['block_size']} bytes",
            ]
        )
    if name == "sched":
        if len(args) > 2:
            return _result(["usage: sched <fcfs|sjf|srtf|rr|priority-preemptive|priority-nonpreemptive|mlfq> [quantum]"], exit_code=2)
        if scheduler is None:
            return _result(["scheduler is unavailable"], exit_code=2)
        algorithm = args[0] if args else "fcfs"
        try:
            quantum = int(args[1]) if len(args) == 2 else 3
            result = scheduler(algorithm, quantum)
        except (ValueError, TypeError) as error:
            return _result([f"sched: {error}"], exit_code=2)
        metrics = result["metrics"]
        return _result(
            [
                f"Algorithm: {result['algorithm']} · processes: {metrics['completed_processes']} · "
                f"cores: {result['cores']} · elapsed: {metrics['elapsed_time']} units",
                f"Average waiting: {metrics['average_waiting_time']} · "
                f"turnaround: {metrics['average_turnaround_time']} · "
                f"response: {metrics['average_response_time']}",
                f"CPU utilization: {metrics['cpu_utilization']}% · "
                f"context switches: {metrics['context_switches']}",
            ]
        )
    if name == "fork-test":
        if process_manager is None:
            return _result(["process manager is unavailable"], exit_code=2)
        children = [
            process_manager.spawn(
                f"demo-worker-{index}",
                owner="guest",
                ppid=2,
                priority=index + 2,
                burst_time=index + 2,
                state="READY",
            )
            for index in range(1, 4)
        ]
        return _result([f"Created READY processes: {', '.join(str(child.pid) for child in children)}"])
    if name == "fork":
        if not 1 <= len(args) <= 2 or process_manager is None:
            return _result(["usage: fork <parent-pid> [name]"], exit_code=2)
        try:
            child = process_manager.fork(int(args[0]), args[1] if len(args) == 2 else None)
        except (ValueError, TypeError) as error:
            return _result([f"fork: {error}"], exit_code=2)
        return _result([f"created READY child PID {child.pid} of PID {child.ppid}"])
    if name == "exec":
        if len(args) != 2 or process_manager is None:
            return _result(["usage: exec <pid> <program-name>"], exit_code=2)
        try:
            process = process_manager.exec(int(args[0]), args[1])
        except (ValueError, TypeError) as error:
            return _result([f"exec: {error}"], exit_code=2)
        return _result([f"PID {process.pid} now runs {process.name}"])
    if name == "exit":
        if len(args) != 1 or process_manager is None:
            return _result(["usage: exit <pid>"], exit_code=2)
        try:
            process = process_manager.exit(int(args[0]))
        except (ValueError, TypeError) as error:
            return _result([f"exit: {error}"], exit_code=2)
        if sync_manager is not None:
            sync_manager.terminate_process(process.pid)
        if memory_manager is not None:
            memory_manager.terminate_process(process.pid)
        return _result(
            [f"PID {process.pid} exited"],
            sync_changed=sync_manager is not None,
            memory_changed=memory_manager is not None,
        )
    if name == "kill":
        if len(args) != 1 or process_manager is None:
            return _result(["usage: kill <pid>"], exit_code=2)
        try:
            process = process_manager.kill(int(args[0]))
        except (ValueError, TypeError) as error:
            return _result([f"kill: {error}"], exit_code=2)
        if sync_manager is not None:
            sync_manager.terminate_process(process.pid)
        if memory_manager is not None:
            memory_manager.terminate_process(process.pid)
        return _result(
            [f"terminated PID {process.pid} ({process.name})"],
            sync_changed=sync_manager is not None,
            memory_changed=memory_manager is not None,
        )
    if name == "nice":
        if len(args) != 2 or process_manager is None:
            return _result(["usage: nice <pid> <priority 0-10>"], exit_code=2)
        try:
            process = process_manager.nice(int(args[0]), int(args[1]))
        except (ValueError, TypeError) as error:
            return _result([f"nice: {error}"], exit_code=2)
        return _result([f"PID {process.pid} priority set to {process.priority}"])
    if name == "wait":
        if len(args) != 2 or process_manager is None:
            return _result(["usage: wait <parent-pid> <child-pid>"], exit_code=2)
        try:
            process = process_manager.wait(int(args[0]), int(args[1]))
        except (ValueError, TypeError) as error:
            return _result([f"wait: {error}"], exit_code=2)
        return _result([f"PID {args[0]} collected terminated child PID {process.pid}"])
    if name == "pwd":
        return _result(["/home/guest"])
    if name == "whoami":
        return _result(["guest (demo session)"])
    if name == "uname":
        return _result(["LibraOS 0.1.0-stage1 simulated-kernel x86_64"])
    if name == "date":
        return _result([datetime.now().astimezone().isoformat(timespec="seconds")])
    if name == "dmesg":
        log_lines = [
            f"[{event['timestamp']}] [{event.get('module', 'kernel')}] "
            f"{event.get('severity', 'info').upper()}: {event.get('message', '')}"
            for event in events
            if event["type"] == "log"
        ]
        return _result(log_lines[-30:] or ["No kernel messages"])
    if name == "echo":
        return _result([" ".join(args)])
    if name == "shutdown":
        return _result(["Powering off LibraOS..."], action="shutdown")
    if name in {"reboot", "restart"}:
        return _result(["Restarting LibraOS..."], action="reboot")
    return _result([f"{name}: command not found (try 'help')"], exit_code=127)


def _result(
    output: list[str],
    *,
    exit_code: int = 0,
    clear: bool = False,
    action: str | None = None,
    sync_changed: bool = False,
    memory_changed: bool = False,
) -> dict[str, Any]:
    return {
        "output": output,
        "exit_code": exit_code,
        "clear": clear,
        "action": action,
        "sync_changed": sync_changed,
        "memory_changed": memory_changed,
    }
