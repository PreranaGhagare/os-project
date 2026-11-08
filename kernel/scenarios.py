"""Repeatable benchmark scenarios for scheduling and resource algorithms."""

from __future__ import annotations

from typing import Any

from kernel.disk_scheduler import DISK_ALGORITHMS, DiskScheduler
from kernel.memory import MemoryManager
from kernel.process import ProcessManager
from kernel.scheduler import ALGORITHMS, Scheduler


SCHEDULER_SCENARIO = [
    {"name": "catalog-search", "arrival_time": 0, "burst_time": 7, "priority": 3},
    {"name": "issue-request", "arrival_time": 1, "burst_time": 4, "priority": 1},
    {"name": "member-lookup", "arrival_time": 2, "burst_time": 2, "priority": 5},
    {"name": "book-import", "arrival_time": 3, "burst_time": 6, "priority": 4},
    {"name": "fine-payment", "arrival_time": 4, "burst_time": 3, "priority": 2},
    {"name": "report-build", "arrival_time": 5, "burst_time": 5, "priority": 6},
]
DISK_SCENARIO = [98, 183, 37, 122, 14, 124, 65, 67]
PAGE_SCENARIO = [0, 1, 2, 3, 0, 4, 5, 1, 2, 6, 0, 4, 7, 1, 5, 2, 6, 3]
SCENARIO_NAMES = {
    "library-rush": "Library rush · CPU scheduling",
    "disk-queue": "Disk queue · seek algorithms",
    "page-pressure": "Page pressure · replacement policies",
}


def compare_schedulers(
    scheduler: Scheduler,
    workload: Any,
    *,
    algorithms: Any = None,
    quantum: Any = 3,
    cores: Any = 1,
) -> dict[str, Any]:
    if not isinstance(algorithms, list) or not algorithms:
        raise ValueError("algorithms must be a non-empty list")
    if len(algorithms) > len(ALGORITHMS):
        raise ValueError(f"choose at most {len(ALGORITHMS)} algorithms")
    normalized = []
    for algorithm in algorithms:
        if not isinstance(algorithm, str):
            raise ValueError("each algorithm name must be text")
        key = algorithm.strip().lower().replace("_", "-")
        if key == "priority":
            key = "priority-preemptive"
        if key not in ALGORITHMS:
            raise ValueError(f"unknown scheduling algorithm: {key}")
        if key not in normalized:
            normalized.append(key)
    if not isinstance(workload, list):
        raise ValueError("workload must be a list")
    results = []
    for algorithm in normalized:
        result = scheduler.run(workload, algorithm=algorithm, quantum=quantum, cores=cores)
        results.append({
            "algorithm": algorithm,
            "metrics": result["metrics"],
            "processes": result["processes"],
            "gantt": result["gantt"],
        })
    return {"kind": "scheduler", "results": results}


def run_scenario(name: Any, disk_size: int, scheduler: Scheduler) -> dict[str, Any]:
    if not isinstance(name, str) or name not in SCENARIO_NAMES:
        raise ValueError(f"unknown scenario: {name}")
    if name == "library-rush":
        comparison = compare_schedulers(
            scheduler,
            SCHEDULER_SCENARIO,
            algorithms=sorted(ALGORITHMS),
        )
        return {
            "scenario": name,
            "title": SCENARIO_NAMES[name],
            "comparison": comparison,
        }
    if name == "disk-queue":
        disk_scheduler = DiskScheduler()
        results = [
            disk_scheduler.run(
                DISK_SCENARIO,
                head=53,
                disk_size=disk_size,
                algorithm=algorithm,
                direction="right",
            )
            for algorithm in sorted(DISK_ALGORITHMS)
        ]
        return {
            "scenario": name,
            "title": SCENARIO_NAMES[name],
            "comparison": {"kind": "disk", "results": results},
        }

    results = []
    for algorithm in ("fifo", "lru", "optimal"):
        processes = ProcessManager()
        process = processes.spawn("page-pressure", state="READY")
        memory = MemoryManager(processes, frame_count=4)
        memory.allocate(process.pid, 8)
        snapshot = memory.simulate(process.pid, PAGE_SCENARIO, algorithm=algorithm)
        results.append({
            "algorithm": algorithm,
            "page_faults": snapshot["memory"]["last_run"]["page_faults"],
            "hits": snapshot["memory"]["last_run"]["hits"],
            "fault_rate": snapshot["memory"]["last_run"]["fault_rate"],
            "references": len(PAGE_SCENARIO),
        })
    return {
        "scenario": name,
        "title": SCENARIO_NAMES[name],
        "comparison": {"kind": "memory", "results": results},
    }
