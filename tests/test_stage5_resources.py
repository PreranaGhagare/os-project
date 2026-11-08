"""Memory-management, page replacement, and disk-scheduling tests."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.boot import Kernel
from kernel.disk_scheduler import DiskScheduler
from kernel.memory import MemoryManager
from kernel.process import ProcessManager


class MemoryManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.processes = ProcessManager()
        self.memory = MemoryManager(self.processes, frame_count=3, page_size=128)
        self.process = self.processes.spawn("pager-worker", state="READY")
        self.memory.allocate(self.process.pid, 8)

    def test_fifo_lru_and_optimal_page_fault_counts(self) -> None:
        references = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2]
        counts = {}

        for algorithm in ("fifo", "lru", "optimal"):
            result = self.memory.simulate(self.process.pid, references, algorithm=algorithm)
            counts[algorithm] = result["memory"]["last_run"]["page_faults"]

        self.assertEqual(counts, {"fifo": 10, "lru": 9, "optimal": 7})
        self.assertEqual(self.memory.snapshot()["memory"]["used_frames"], 3)

    def test_page_trace_reports_hits_evictions_and_frame_table(self) -> None:
        result = self.memory.simulate(self.process.pid, [0, 1, 0, 2, 3], algorithm="lru")
        run = result["memory"]["last_run"]

        self.assertEqual([step["hit"] for step in run["trace"]], [False, False, True, False, False])
        self.assertEqual(
            run["evictions"],
            [{"pid": self.process.pid, "process": self.process.name, "page": 1, "frame": 1}],
        )
        self.assertEqual(len(result["memory"]["frames"]), 3)
        self.assertEqual(self.process.memory_pages, [0, 1, 2])

    def test_address_space_validation_and_duplicate_allocation(self) -> None:
        with self.assertRaisesRegex(ValueError, "already has"):
            self.memory.allocate(self.process.pid, 2)
        with self.assertRaisesRegex(ValueError, "between 1 and 64"):
            self.memory.allocate(self.processes.get(1).pid, 0)
        with self.assertRaisesRegex(ValueError, "from 0 to 7"):
            self.memory.simulate(self.process.pid, [8])
        with self.assertRaisesRegex(ValueError, "unknown page-replacement"):
            self.memory.simulate(self.process.pid, [0], algorithm="clock")
        with self.assertRaisesRegex(ValueError, "reference string"):
            self.memory.simulate(self.process.pid, [])

    def test_releasing_address_space_frees_resident_frames(self) -> None:
        self.memory.simulate(self.process.pid, [0, 1, 2])

        state = self.memory.release(self.process.pid)

        self.assertEqual(state["memory"]["used_frames"], 0)
        self.assertEqual(state["memory"]["page_tables"], [])
        self.assertEqual(self.process.memory_pages, [])

    def test_page_replacement_uses_shared_frames_and_updates_other_process(self) -> None:
        other = self.processes.spawn("other-worker", state="READY")
        self.memory.allocate(other.pid, 3)
        self.memory.simulate(self.process.pid, [0, 1, 2])

        result = self.memory.simulate(other.pid, [0], algorithm="fifo")

        self.assertEqual(result["memory"]["last_run"]["evictions"][0]["pid"], self.process.pid)
        self.assertEqual(len(self.process.memory_pages), 2)
        self.assertEqual(len(other.memory_pages), 1)

class DiskSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = DiskScheduler()
        self.requests = [98, 183, 37, 122, 14, 124, 65, 67]

    def test_fcfs_and_sstf_service_orders_and_movement(self) -> None:
        fcfs = self.scheduler.run(self.requests, head=53, disk_size=200, algorithm="fcfs")
        sstf = self.scheduler.run(self.requests, head=53, disk_size=200, algorithm="sstf")

        self.assertEqual(fcfs["service_order"], self.requests)
        self.assertEqual(fcfs["total_movement"], 640)
        self.assertEqual(sstf["service_order"], [65, 67, 37, 14, 98, 122, 124, 183])
        self.assertEqual(sstf["total_movement"], 236)
        self.assertEqual(sum(step["movement"] for step in sstf["steps"]), 236)

    def test_scan_variants_and_look_variants_follow_direction(self) -> None:
        scan = self.scheduler.run(self.requests, head=53, disk_size=200, algorithm="scan")
        c_scan = self.scheduler.run(self.requests, head=53, disk_size=200, algorithm="c-scan")
        look = self.scheduler.run(self.requests, head=53, disk_size=200, algorithm="look")
        c_look = self.scheduler.run(self.requests, head=53, disk_size=200, algorithm="c-look")
        left_scan = self.scheduler.run(
            self.requests, head=53, disk_size=200, algorithm="scan", direction="left"
        )

        self.assertEqual(scan["service_order"], [65, 67, 98, 122, 124, 183, 37, 14])
        self.assertEqual(scan["path"], [53, 65, 67, 98, 122, 124, 183, 199, 37, 14])
        self.assertEqual(scan["total_movement"], 331)
        self.assertEqual(c_scan["total_movement"], 382)
        self.assertEqual(c_scan["steps"][6]["kind"], "boundary")
        self.assertEqual(c_scan["steps"][7]["kind"], "wrap")
        self.assertEqual(look["total_movement"], 299)
        self.assertEqual(c_look["total_movement"], 322)
        self.assertEqual(left_scan["service_order"], [37, 14, 65, 67, 98, 122, 124, 183])
        self.assertEqual(left_scan["path"], [53, 37, 14, 0, 65, 67, 98, 122, 124, 183])

    def test_invalid_disk_workloads_are_explicit(self) -> None:
        invalid_workloads = (
            {"requests": [], "head": 0, "disk_size": 100, "algorithm": "fcfs"},
            {"requests": [100], "head": 0, "disk_size": 100, "algorithm": "fcfs"},
            {"requests": [1], "head": 100, "disk_size": 100, "algorithm": "fcfs"},
            {"requests": [True], "head": 1, "disk_size": 100, "algorithm": "fcfs"},
            {"requests": [1], "head": 0, "disk_size": 100, "algorithm": "random"},
            {"requests": [1], "head": 0, "disk_size": 100, "algorithm": "fcfs", "direction": "up"},
        )
        for workload in invalid_workloads:
            with self.subTest(workload=workload), self.assertRaises(ValueError):
                self.scheduler.run(**workload)


class KernelResourceTests(unittest.TestCase):
    def test_resource_requests_update_kernel_memory_and_disk_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())
            self._assert_resource_requests(kernel)

    def _assert_resource_requests(self, kernel: Kernel) -> None:
        process = kernel.processes.fork(2, "resource-worker")
        allocated = kernel.manage_resources(
            {
                "request_id": "memory-allocate",
                "operation": "memory_allocate",
                "pid": process.pid,
                "pages": 5,
            }
        )
        paged = kernel.manage_resources(
            {
                "request_id": "memory-run",
                "operation": "memory_simulate",
                "pid": process.pid,
                "algorithm": "fifo",
                "references": [0, 1, 2, 0, 3],
            }
        )
        disk = kernel.manage_resources(
            {
                "request_id": "disk-run",
                "operation": "disk_schedule",
                "requests": [5, 1, 9],
                "head": 4,
                "algorithm": "sstf",
                "direction": "right",
            }
        )

        self.assertTrue(allocated["ok"])
        self.assertEqual(paged["memory"]["last_run"]["page_faults"], 4)
        self.assertEqual(paged["memory"]["used_frames"], 4)
        self.assertEqual(disk["disk_size"], 512)
        self.assertEqual(disk["result"]["service_order"], [5, 1, 9])
        self.assertEqual(kernel.events.snapshot()[-1]["type"], "resource_result")

    def test_process_termination_releases_its_memory_frames(self) -> None:
        kernel = Kernel()
        child = kernel.processes.fork(2, "memory-worker")
        kernel.memory.allocate(child.pid, 2)
        kernel.memory.simulate(child.pid, [0, 1])

        result = kernel.manage_process({"operation": "kill", "pid": child.pid})

        self.assertTrue(result["ok"])
        self.assertEqual(child.memory_pages, [])
        self.assertEqual(kernel.memory.snapshot()["memory"]["used_frames"], 0)

    def test_deadlock_recovery_also_releases_victim_memory(self) -> None:
        kernel = Kernel()
        demo = kernel.synchronization.create_deadlock_demo()
        victim_pid = max(demo["processes"])
        kernel.memory.allocate(victim_pid, 2)
        kernel.memory.simulate(victim_pid, [0, 1])

        result = kernel.manage_synchronization({"operation": "recover"})

        victim = kernel.processes.get(victim_pid)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["victim_pid"], victim_pid)
        self.assertEqual(victim.memory_pages, [])
        self.assertEqual(kernel.memory.snapshot()["memory"]["used_frames"], 0)


if __name__ == "__main__":
    unittest.main()
