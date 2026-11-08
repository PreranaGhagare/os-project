"""Scheduler algorithms, metrics, and process lifecycle tests."""

from __future__ import annotations

import unittest
import asyncio
import tempfile
from pathlib import Path

from kernel.boot import Kernel
from kernel.process import ProcessManager
from kernel.scheduler import Scheduler


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = Scheduler()
        self.workload = [
            {"pid": 11, "name": "long", "arrival_time": 0, "burst_time": 5, "priority": 5},
            {"pid": 12, "name": "short", "arrival_time": 1, "burst_time": 2, "priority": 1},
            {"pid": 13, "name": "medium", "arrival_time": 2, "burst_time": 3, "priority": 4},
        ]

    def test_fcfs_metrics_and_completion(self) -> None:
        result = self.scheduler.run(self.workload, algorithm="fcfs")
        processes = {process["pid"]: process for process in result["processes"]}

        self.assertEqual([segment["pid"] for segment in result["gantt"][0]], [11, 12, 13])
        self.assertEqual(processes[11]["start_time"], 0)
        self.assertEqual(processes[11]["finish_time"], 5)
        self.assertEqual(processes[12]["waiting_time"], 4)
        self.assertEqual(processes[13]["turnaround_time"], 8)
        self.assertEqual(result["metrics"]["elapsed_time"], 10)
        self.assertEqual(result["metrics"]["completed_processes"], 3)

    def test_srtf_preempts_for_shorter_job(self) -> None:
        result = self.scheduler.run(self.workload, algorithm="srtf")
        segments = result["gantt"][0]

        self.assertEqual([segment["pid"] for segment in segments[:3]], [11, 12, 13])
        self.assertEqual(segments[0]["end"], 1)
        self.assertEqual(segments[1]["end"], 3)

    def test_round_robin_rotates_after_quantum(self) -> None:
        workload = [
            {"pid": 1, "name": "a", "arrival_time": 0, "burst_time": 4},
            {"pid": 2, "name": "b", "arrival_time": 0, "burst_time": 3},
        ]
        result = self.scheduler.run(workload, algorithm="rr", quantum=2)

        self.assertEqual(
            [(segment["pid"], segment["start"], segment["end"]) for segment in result["gantt"][0]],
            [(1, 0, 2), (2, 2, 4), (1, 4, 6), (2, 6, 7)],
        )

    def test_priority_modes_and_mlfq_finish_all_processes(self) -> None:
        for algorithm in ("priority-preemptive", "priority-nonpreemptive", "mlfq"):
            result = self.scheduler.run(self.workload, algorithm=algorithm, quantum=1)
            self.assertTrue(all(process["state"] == "TERMINATED" for process in result["processes"]))

    def test_priority_aging_eventually_runs_a_low_priority_process(self) -> None:
        workload = [
            {"pid": 1, "name": "high-priority", "arrival_time": 0, "burst_time": 30, "priority": 0},
            {"pid": 2, "name": "aging-guest", "arrival_time": 0, "burst_time": 1, "priority": 10},
        ]
        result = self.scheduler.run(workload, algorithm="priority-preemptive", aging_interval=1)
        guest = next(process for process in result["processes"] if process["pid"] == 2)

        self.assertGreater(guest["start_time"], 0)
        self.assertLess(guest["start_time"], 30)

    def test_multi_core_metrics_and_gantt_lanes(self) -> None:
        result = self.scheduler.run(self.workload, algorithm="fcfs", cores=2)

        self.assertEqual(len(result["gantt"]), 2)
        self.assertLess(result["metrics"]["elapsed_time"], 10)
        self.assertEqual(result["metrics"]["core_count"], 2)
        self.assertGreater(result["metrics"]["cpu_utilization"], 50)

    def test_invalid_inputs_are_explicit(self) -> None:
        with self.assertRaises(ValueError):
            self.scheduler.run(self.workload, algorithm="unknown")
        with self.assertRaises(ValueError):
            self.scheduler.run(self.workload, cores=5)
        with self.assertRaises(ValueError):
            self.scheduler.run([{"name": "zero", "burst_time": 0}])


class ProcessManagerTests(unittest.TestCase):
    def test_fork_nice_kill_and_wait_lifecycle(self) -> None:
        manager = ProcessManager()
        child = manager.fork(2, "worker")
        self.assertEqual(child.state, "READY")
        manager.nice(child.pid, 1)
        self.assertEqual(manager.get(child.pid).priority, 1)
        manager.kill(child.pid)
        self.assertEqual(manager.wait(2, child.pid).state, "TERMINATED")

    def test_init_cannot_be_terminated(self) -> None:
        with self.assertRaises(ValueError):
            ProcessManager().kill(1)

    def test_kernel_schedule_creates_and_updates_real_pcbs(self) -> None:
        kernel = Kernel()
        result = kernel.schedule_workload(
            [
                {"name": "alpha", "arrival_time": 0, "burst_time": 2, "priority": 2},
                {"name": "beta", "arrival_time": 1, "burst_time": 1, "priority": 1},
            ],
            algorithm="srtf",
            cores=2,
        )
        self.assertTrue(all(process["pid"] >= 4 for process in result["processes"]))
        self.assertTrue(
            all(kernel.processes.get(process["pid"]).state == "TERMINATED" for process in result["processes"])
        )
        self.assertEqual(kernel.events.snapshot()[-1]["type"], "scheduler_result")

    def test_terminal_sched_command_uses_kernel_scheduler(self) -> None:
        from shell.commands import execute

        kernel = Kernel()
        result = execute(
            "sched rr 2",
            kernel.processes.list_processes(),
            [],
            scheduler=kernel.run_scheduler_command,
            process_manager=kernel.processes,
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(any("Algorithm: rr" in line for line in result["output"]))

    def test_process_actions_publish_updated_table(self) -> None:
        kernel = Kernel()
        child = kernel.processes.fork(2, "table-worker")
        result = kernel.manage_process({"operation": "nice", "pid": child.pid, "priority": 1})
        self.assertTrue(result["ok"])
        self.assertEqual(result["processes"][-1]["priority"], 1)

        rejected = kernel.manage_process({"operation": "kill", "pid": 1})
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["processes"][0]["state"], "RUNNING")

    def test_kernel_process_action_validation_and_error_reporting(self) -> None:
        kernel = Kernel()
        requests = (
            ({"operation": "kill", "pid": True}, "PID must be an integer"),
            ({"operation": "kill", "pid": "2"}, "PID must be an integer"),
            ({"operation": "kill", "pid": 999}, "no such process"),
            ({"operation": "nice", "pid": 2, "priority": True}, "priority must be an integer"),
            ({"operation": "nice", "pid": 2, "priority": "1"}, "priority must be an integer"),
            ({"operation": "nice", "pid": 2, "priority": 11}, "priority must be between"),
            ({"operation": "unknown", "pid": 2}, "unsupported process operation"),
        )
        for request, expected_error in requests:
            with self.subTest(request=request):
                result = kernel.manage_process(request)
                self.assertFalse(result["ok"])
                self.assertIn(expected_error, result["error"])
                self.assertEqual(result["type"], "process_result")

        self.assertEqual(kernel.events.snapshot()[-1]["type"], "process_result")
        self.assertTrue(any(
            event["type"] == "request_trace"
            and event["request_type"] == "process_action"
            and not event["ok"]
            for event in kernel.events.snapshot()
        ))

    def test_process_kill_releases_synchronization_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())
            child = kernel.processes.fork(2, "managed-worker")
            kernel.memory.allocate(child.pid, 2)
            kernel.memory.simulate(child.pid, [0, 1])

            result = kernel.manage_process({
                "request_id": "kill-managed-worker",
                "operation": "kill",
                "pid": child.pid,
            })

            self.assertTrue(result["ok"], result["error"])
            self.assertEqual(result["result"], {"pid": child.pid, "state": "TERMINATED"})
            self.assertEqual(kernel.memory.snapshot()["memory"]["used_frames"], 0)
            event_types = [event["type"] for event in kernel.events.snapshot()]
            self.assertIn("sync_state", event_types)
            self.assertIn("resource_state", event_types)


if __name__ == "__main__":
    unittest.main()
