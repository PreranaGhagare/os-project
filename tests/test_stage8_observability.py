"""Stage 8 journal, tracing, scenario, and comparison checks."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.boot import Kernel
from kernel.disk import DiskImage, DiskImageError
from kernel.filesystem import FileSystem, FileSystemError
from kernel.scenarios import SCHEDULER_SCENARIO, run_scenario, compare_schedulers


class Stage8Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.image_path = Path(self.temp_directory.name) / "disk.img.json"
        self.kernel = Kernel(disk_path=self.image_path)
        asyncio.run(self.kernel.boot())

    def test_initial_boot_seeds_disk_and_publishes_ready_state(self) -> None:
        image_path = Path(self.temp_directory.name) / "first-boot.json"
        kernel = Kernel(disk_path=image_path)

        self.assertEqual(kernel.status, "stopped")
        asyncio.run(kernel.boot())

        self.assertEqual(kernel.status, "running")
        self.assertTrue(image_path.is_file())
        self.assertEqual(kernel.filesystem.read_file("/books/B001.json")[:1], "{")
        events = kernel.events.snapshot()
        self.assertEqual(events[-1]["type"], "system")
        self.assertEqual(events[-1]["status"], "running")
        self.assertTrue(any(
            event.get("module") == "filesystem"
            and "Initialized disk image" in event.get("message", "")
            for event in events
        ))

    def test_reboot_saves_filesystem_and_returns_to_running_state(self) -> None:
        self.kernel.filesystem.create_file(
            "/home/guest/reboot-persisted.txt",
            "saved before reboot",
        )

        asyncio.run(self.kernel.power("reboot"))

        self.assertEqual(self.kernel.status, "running")
        self.assertEqual(
            self.kernel.filesystem.read_file("/home/guest/reboot-persisted.txt"),
            "saved before reboot",
        )
        events = self.kernel.events.snapshot()
        reboot_event = next(
            event for event in events
            if event["type"] == "power" and event["action"] == "reboot"
        )
        self.assertEqual(reboot_event["status"], "stopped")
        self.assertEqual(events[-1]["type"], "system")
        self.assertEqual(events[-1]["status"], "running")

    def test_failed_power_save_reports_error_without_changing_status(self) -> None:
        from unittest.mock import patch

        with patch.object(
            self.kernel.disk_image,
            "save",
            side_effect=DiskImageError("disk unavailable"),
        ):
            asyncio.run(self.kernel.power("shutdown"))

        self.assertEqual(self.kernel.status, "running")
        events = self.kernel.events.snapshot()
        self.assertEqual(events[-1]["type"], "power")
        self.assertEqual(events[-1]["action"], "error")
        self.assertEqual(events[-1]["status"], "running")
        self.assertTrue(any(
            event["type"] == "log"
            and event["module"] == "disk"
            and event["severity"] == "error"
            for event in events
        ))

    def test_power_rejects_invalid_action_and_save_before_boot(self) -> None:
        with self.assertRaises(ValueError):
            asyncio.run(self.kernel.power("suspend"))

        unbooted = Kernel(disk_path=Path(self.temp_directory.name) / "unbooted.json")
        with self.assertRaises(RuntimeError):
            unbooted.save_disk_image()

    def test_filesystem_mutations_are_journaled_and_immediately_persisted(self) -> None:
        result = self.kernel.execute_filesystem_request({
            "request_id": "fs-create-1",
            "operation": "create",
            "path": "/home/guest/journaled.txt",
            "content": "durable",
        })

        self.assertTrue(result["ok"])
        self.assertEqual(FileSystem.from_image(DiskImage(self.image_path).load()).read_file(
            "/home/guest/journaled.txt"
        ), "durable")
        journal = self.kernel.journal.snapshot()
        self.assertEqual([entry["kind"] for entry in journal[-2:]], ["begin", "commit"])
        self.assertEqual(journal[-2]["request_id"], "fs-create-1")

    def test_failed_disk_commit_rolls_back_the_in_memory_mutation(self) -> None:
        from unittest.mock import patch

        with patch.object(self.kernel.disk_image, "save", side_effect=DiskImageError("disk unavailable")):
            response = self.kernel.execute_filesystem_request({
                "request_id": "failed-commit",
                "operation": "create",
                "path": "/home/guest/not-committed.txt",
                "content": "should roll back",
            })

        self.assertFalse(response["ok"])
        self.assertEqual(response["error_code"], "EIO")
        with self.assertRaises(FileSystemError):
            self.kernel.filesystem.read_file("/home/guest/not-committed.txt")
        self.assertEqual(self.kernel.journal.snapshot()[-1]["kind"], "abort")

    def test_boot_redoes_a_pending_journal_transaction(self) -> None:
        self.kernel.filesystem.create_file(
            "/home/guest/recovered.txt",
            "redo after restart",
            owner="guest",
        )
        self.kernel.journal.begin(
            "filesystem:create",
            "pending-transaction",
            self.kernel.filesystem.to_image(),
        )

        restored = Kernel(disk_path=self.image_path)
        asyncio.run(restored.boot())

        self.assertEqual(restored.filesystem.read_file("/home/guest/recovered.txt"), "redo after restart")
        recovery_logs = [
            item for item in restored.events.snapshot()
            if item["type"] == "log" and item["module"] == "journal"
        ]
        self.assertTrue(any("Recovered 1 pending" in item["message"] for item in recovery_logs))
        self.assertEqual(restored.journal.snapshot()[-1]["recovered"], True)

    def test_request_trace_correlates_filesystem_request_result(self) -> None:
        response = self.kernel.execute_filesystem_request({
            "request_id": "trace-me",
            "operation": "usage",
        })

        self.assertTrue(response["ok"])
        trace = self.kernel.request_tracer.snapshot()[-1]
        self.assertEqual(trace["request_id"], "trace-me")
        self.assertEqual(trace["request_type"], "filesystem")
        self.assertEqual(trace["operation"], "usage")
        self.assertTrue(trace["ok"])
        self.assertGreaterEqual(trace["duration_ms"], 0)
        self.assertTrue(any(
            item["type"] == "request_trace" and item["request_id"] == "trace-me"
            for item in self.kernel.events.snapshot()
        ))

    def test_scheduler_comparison_is_isolated_and_returns_each_algorithm(self) -> None:
        original_processes = self.kernel.process_snapshot()
        comparison = compare_schedulers(
            self.kernel.scheduler,
            SCHEDULER_SCENARIO,
            algorithms=["fcfs", "srtf", "rr"],
            quantum=2,
            cores=2,
        )

        self.assertEqual(
            [item["algorithm"] for item in comparison["results"]],
            ["fcfs", "srtf", "rr"],
        )
        self.assertEqual(self.kernel.process_snapshot(), original_processes)
        self.assertEqual(
            self.kernel.manage_scenarios({"operation": "compare", "request_id": "compare-1",
                                          "workload": SCHEDULER_SCENARIO,
                                          "algorithms": ["fcfs", "srtf"]})["result"]["comparison"]["kind"],
            "scheduler",
        )

    def test_resource_scenarios_compare_algorithms_without_mutating_kernel(self) -> None:
        disk = run_scenario("disk-queue", self.kernel.filesystem.block_count, self.kernel.scheduler)
        memory = run_scenario("page-pressure", self.kernel.filesystem.block_count, self.kernel.scheduler)

        self.assertEqual(len(disk["comparison"]["results"]), 6)
        self.assertEqual(len(memory["comparison"]["results"]), 3)
        self.assertEqual(
            [item["algorithm"] for item in memory["comparison"]["results"]],
            ["fifo", "lru", "optimal"],
        )
        self.assertEqual(self.kernel.memory.snapshot()["memory"]["used_frames"], 0)

    def test_library_and_terminal_writes_are_journaled(self) -> None:
        self.kernel.security.login("librarian")
        checkout = self.kernel.manage_library({
            "operation": "checkout",
            "request_id": "library-checkout",
            "book_id": "B013",
            "member_id": "M025",
        })
        self.assertTrue(checkout["ok"])

        asyncio.run(self.kernel.execute_command("mkdir /home/guest/notes", "mkdir-1"))
        operations = [entry.get("operation") for entry in self.kernel.journal.snapshot() if entry["kind"] == "begin"]

        self.assertIn("library:checkout", operations)
        self.assertIn("terminal:mkdir", operations)

    def test_syscall_mutations_use_journal_and_trace(self) -> None:
        self.kernel.security.login("librarian")
        result = self.kernel.execute_syscall(
            "create",
            request_id="syscall-create-1",
            path="/books/SYSCALL.json",
            content='{"id":"SYSCALL"}',
            user="librarian",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(self.kernel.filesystem.read_file("/books/SYSCALL.json"), '{"id":"SYSCALL"}')
        self.assertEqual(self.kernel.journal.snapshot()[-2]["operation"], "syscall:create")
        trace = self.kernel.request_tracer.snapshot()[-1]
        self.assertEqual(trace["request_id"], "syscall-create-1")
        self.assertEqual(trace["request_type"], "syscall")


if __name__ == "__main__":
    unittest.main()
