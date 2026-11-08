"""Deterministic multi-core CPU scheduling simulations."""

from __future__ import annotations

from typing import Any


ALGORITHMS = {
    "fcfs",
    "sjf",
    "srtf",
    "rr",
    "priority-preemptive",
    "priority-nonpreemptive",
    "mlfq",
}

SAMPLE_WORKLOAD = (
    {"name": "catalog-search", "arrival_time": 0, "burst_time": 7, "priority": 3},
    {"name": "issue-request", "arrival_time": 1, "burst_time": 4, "priority": 1},
    {"name": "member-lookup", "arrival_time": 2, "burst_time": 2, "priority": 5},
    {"name": "book-import", "arrival_time": 3, "burst_time": 6, "priority": 4},
    {"name": "fine-payment", "arrival_time": 4, "burst_time": 3, "priority": 2},
    {"name": "report-build", "arrival_time": 5, "burst_time": 5, "priority": 6},
)


class Scheduler:
    """Run reproducible scheduling algorithms over discrete time units."""

    def run(
        self,
        workload: list[dict[str, Any]],
        *,
        algorithm: str = "fcfs",
        quantum: int = 3,
        cores: int = 1,
        aging_interval: int = 5,
    ) -> dict[str, Any]:
        """Simulate a workload and return per-process metrics and Gantt data."""
        if not isinstance(algorithm, str):
            raise ValueError("scheduling algorithm must be text")
        algorithm = algorithm.strip().lower().replace("_", "-")
        if algorithm == "priority":
            algorithm = "priority-preemptive"
        if algorithm not in ALGORITHMS:
            raise ValueError(f"unknown scheduling algorithm: {algorithm}")
        if isinstance(cores, bool) or not isinstance(cores, int) or not 1 <= cores <= 4:
            raise ValueError("CPU core count must be between 1 and 4")
        if isinstance(quantum, bool) or not isinstance(quantum, int) or not 1 <= quantum <= 20:
            raise ValueError("round-robin quantum must be between 1 and 20")
        if (
            isinstance(aging_interval, bool)
            or not isinstance(aging_interval, int)
            or not 1 <= aging_interval <= 100
        ):
            raise ValueError("aging interval must be between 1 and 100")
        if not workload or len(workload) > 40:
            raise ValueError("workload must contain between 1 and 40 processes")
        if any(not isinstance(source, dict) for source in workload):
            raise ValueError("each workload process must be a JSON object")

        jobs: list[dict[str, Any]] = []
        seen_pids: set[int] = set()
        for index, source in enumerate(workload):
            pid = source.get("pid", index + 1)
            name = source.get("name", f"process-{pid}")
            arrival = source.get("arrival_time", 0)
            burst = source.get("burst_time")
            priority = source.get("priority", 5)
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or pid in seen_pids:
                raise ValueError("each process must have a unique positive integer pid")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("each process must have a non-empty name")
            if isinstance(arrival, bool) or not isinstance(arrival, int) or not 0 <= arrival <= 1000:
                raise ValueError("arrival time must be an integer between 0 and 1000")
            if isinstance(burst, bool) or not isinstance(burst, int) or not 1 <= burst <= 1000:
                raise ValueError("burst time must be an integer between 1 and 1000")
            if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 10:
                raise ValueError("priority must be an integer between 0 and 10")
            seen_pids.add(pid)
            jobs.append(
                {
                    "pid": pid,
                    "name": name.strip(),
                    "arrival_time": arrival,
                    "burst_time": burst,
                    "priority": priority,
                    "remaining_time": burst,
                    "state": "NEW",
                    "start_time": None,
                    "finish_time": None,
                    "waiting_time": 0,
                    "turnaround_time": None,
                    "response_time": None,
                    "ready_since": None,
                    "ready_order": None,
                    "quantum_left": 0,
                    "level": 0,
                }
            )

        by_pid = {job["pid"]: job for job in jobs}
        current: list[int | None] = [None] * cores
        last_running: list[int | None] = [None] * cores
        gantt: list[list[dict[str, Any]]] = [[] for _ in range(cores)]
        timeline: list[dict[str, Any]] = []
        sequence = 0
        elapsed = 0
        busy_units = 0
        context_switches = 0

        while any(job["remaining_time"] > 0 for job in jobs):
            if elapsed >= 10000:
                raise ValueError("workload exceeds the 10000-unit simulation limit")

            for job in jobs:
                if (
                    job["remaining_time"] > 0
                    and job["arrival_time"] <= elapsed
                    and job["pid"] not in current
                    and job["ready_since"] is None
                ):
                    job["state"] = "READY"
                    job["ready_since"] = elapsed
                    job["ready_order"] = sequence
                    sequence += 1

            candidates = [
                job for job in jobs
                if job["arrival_time"] <= elapsed and job["remaining_time"] > 0
            ]
            selected = self._select(
                candidates,
                current,
                algorithm,
                aging_interval,
                cores,
                elapsed,
            )
            assignments = [job["pid"] if job else None for job in selected]

            for core, job in enumerate(selected):
                if job is None:
                    current[core] = None
                    continue
                pid = job["pid"]
                if last_running[core] is not None and last_running[core] != pid:
                    context_switches += 1
                last_running[core] = pid
                if job["start_time"] is None:
                    job["start_time"] = elapsed
                    job["response_time"] = elapsed - job["arrival_time"]
                job["state"] = "RUNNING"
                job["ready_since"] = None
                current[core] = pid
                if algorithm in {"rr", "mlfq"} and job["quantum_left"] <= 0:
                    job["quantum_left"] = self._time_slice(job, algorithm, quantum)

                lane = gantt[core]
                if lane and lane[-1]["pid"] == pid and lane[-1]["end"] == elapsed:
                    lane[-1]["end"] = elapsed + 1
                else:
                    lane.append(
                        {
                            "pid": pid,
                            "name": job["name"],
                            "start": elapsed,
                            "end": elapsed + 1,
                        }
                    )

            ready_pids: list[int] = []
            selected_pids = {pid for pid in assignments if pid is not None}
            for job in self._rank(candidates, algorithm, aging_interval, elapsed):
                if job["pid"] not in selected_pids:
                    ready_pids.append(job["pid"])
                    job["state"] = "READY"
                    job["waiting_time"] += 1
                    if job["ready_since"] is None:
                        job["ready_since"] = elapsed

            timeline.append(
                {
                    "time": elapsed,
                    "cores": [
                        {
                            "core": core,
                            "pid": assignments[core],
                            "name": by_pid[assignments[core]]["name"] if assignments[core] else None,
                            "quantum_left": by_pid[assignments[core]]["quantum_left"] if assignments[core] else 0,
                        }
                        for core in range(cores)
                    ],
                    "ready_queue": ready_pids,
                }
            )
            busy_units += len(selected_pids)

            for core, job in enumerate(selected):
                if job is None:
                    continue
                job["remaining_time"] -= 1
                if algorithm in {"rr", "mlfq"}:
                    job["quantum_left"] -= 1
                if job["remaining_time"] == 0:
                    job["finish_time"] = elapsed + 1
                    job["turnaround_time"] = job["finish_time"] - job["arrival_time"]
                    job["state"] = "TERMINATED"
                    current[core] = None
                elif algorithm in {"rr", "mlfq"} and job["quantum_left"] == 0:
                    if algorithm == "mlfq":
                        job["level"] = min(job["level"] + 1, 4)
                    job["ready_since"] = elapsed + 1
                    job["ready_order"] = sequence
                    job["state"] = "READY"
                    sequence += 1
                    current[core] = None

            elapsed += 1

        scheduled = [
            {
                key: job[key]
                for key in (
                    "pid", "name", "arrival_time", "burst_time", "priority",
                    "remaining_time", "state", "start_time", "finish_time",
                    "waiting_time", "turnaround_time", "response_time",
                )
            }
            for job in sorted(jobs, key=lambda item: item["pid"])
        ]
        completed = len(scheduled)
        metrics = {
            "average_waiting_time": round(sum(job["waiting_time"] for job in jobs) / completed, 2),
            "average_turnaround_time": round(sum(job["turnaround_time"] for job in jobs) / completed, 2),
            "average_response_time": round(sum(job["response_time"] for job in jobs) / completed, 2),
            "cpu_utilization": round((busy_units / (elapsed * cores)) * 100, 2) if elapsed else 0,
            "throughput": round(completed / elapsed, 3) if elapsed else 0,
            "context_switches": context_switches,
            "elapsed_time": elapsed,
            "completed_processes": completed,
            "core_count": cores,
        }
        return {
            "algorithm": algorithm,
            "quantum": quantum,
            "cores": cores,
            "processes": scheduled,
            "gantt": gantt,
            "timeline": timeline,
            "metrics": metrics,
        }

    @staticmethod
    def _time_slice(job: dict[str, Any], algorithm: str, quantum: int) -> int:
        return quantum * (2 ** job["level"]) if algorithm == "mlfq" else quantum

    def _select(
        self,
        candidates: list[dict[str, Any]],
        current: list[int | None],
        algorithm: str,
        aging_interval: int,
        cores: int,
        now: int,
    ) -> list[dict[str, Any] | None]:
        pinned_algorithms = {"fcfs", "sjf", "priority-nonpreemptive"}
        chosen: list[dict[str, Any]] = []
        if algorithm in pinned_algorithms:
            for pid in current:
                job = next((candidate for candidate in candidates if candidate["pid"] == pid), None)
                if job is not None and job not in chosen:
                    chosen.append(job)
        for job in self._rank(candidates, algorithm, aging_interval, now):
            if job not in chosen and len(chosen) < cores:
                chosen.append(job)
        chosen_ids = {job["pid"] for job in chosen}
        result: list[dict[str, Any] | None] = [None] * cores
        for core, pid in enumerate(current):
            if pid in chosen_ids:
                job = next(candidate for candidate in chosen if candidate["pid"] == pid)
                result[core] = job
                chosen_ids.remove(pid)
        next_jobs = iter(job for job in chosen if job["pid"] in chosen_ids)
        for core in range(cores):
            if result[core] is None:
                result[core] = next(next_jobs, None)
        return result

    @staticmethod
    def _rank(
        candidates: list[dict[str, Any]],
        algorithm: str,
        aging_interval: int,
        now: int,
    ) -> list[dict[str, Any]]:
        if algorithm == "sjf":
            key = lambda job: (job["burst_time"], job["arrival_time"], job["pid"])
        elif algorithm == "srtf":
            key = lambda job: (job["remaining_time"], job["arrival_time"], job["pid"])
        elif algorithm.startswith("priority"):
            key = lambda job: (
                job["priority"] - (
                    max(0, now - job["ready_since"]) // aging_interval
                    if job["ready_since"] is not None
                    else 0
                ),
                job["ready_order"] if job["ready_order"] is not None else -1,
                job["pid"],
            )
        elif algorithm == "mlfq":
            key = lambda job: (
                job["level"],
                job["ready_order"] if job["ready_order"] is not None else -1,
                job["arrival_time"],
                job["pid"],
            )
        elif algorithm == "rr":
            key = lambda job: (
                job["ready_order"] if job["ready_order"] is not None else -1,
                job["arrival_time"],
                job["pid"],
            )
        else:
            key = lambda job: (
                job["arrival_time"],
                job["ready_order"] if job["ready_order"] is not None else -1,
                job["pid"],
            )
        return sorted(candidates, key=key)
