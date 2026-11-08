"""Synchronization primitives, deadlock handling, and race demo tests."""

from __future__ import annotations

import unittest

from kernel.boot import Kernel
from kernel.process import ProcessManager
from kernel.synchronization import SynchronizationManager


class SynchronizationManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.processes = ProcessManager()
        self.sync = SynchronizationManager(self.processes)
        self.first = self.processes.spawn("first-worker", state="READY")
        self.second = self.processes.spawn("second-worker", state="READY")

    def test_mutex_blocks_and_fifo_release_wakes_waiter(self) -> None:
        self.sync.create_resource("queue-lock", "mutex")
        self.assertTrue(self.sync.acquire(self.first.pid, "queue-lock")["acquired"])
        self.assertFalse(self.sync.acquire(self.second.pid, "queue-lock")["acquired"])
        self.assertEqual(self.second.state, "BLOCKED")

        released = self.sync.release(self.first.pid, "queue-lock")

        self.assertEqual(released["awakened_pids"], [self.second.pid])
        self.assertEqual(self.second.state, "READY")
        self.assertEqual(self.second.held_locks, ["queue-lock"])
        self.assertEqual(self.sync.snapshot()["deadlocked_pids"], [])

    def test_semaphore_permits_and_wait_queue(self) -> None:
        self.sync.create_resource("reader-slots", "semaphore", capacity=2)
        third = self.processes.spawn("third-worker", state="READY")

        self.sync.acquire(self.first.pid, "reader-slots")
        self.sync.acquire(self.second.pid, "reader-slots")
        waiting = self.sync.acquire(third.pid, "reader-slots")

        self.assertFalse(waiting["acquired"])
        self.assertEqual(self.sync.snapshot()["resources"][-1]["available"], 0)
        released = self.sync.release(self.first.pid, "reader-slots")
        self.assertEqual(released["awakened_pids"], [third.pid])
        self.assertEqual(third.state, "READY")

    def test_mutex_is_not_reentrant_and_cannot_be_released_by_non_owner(self) -> None:
        self.sync.acquire(self.first.pid, "catalog-lock")

        with self.assertRaisesRegex(ValueError, "not reentrant"):
            self.sync.acquire(self.first.pid, "catalog-lock")
        with self.assertRaisesRegex(ValueError, "does not hold"):
            self.sync.release(self.second.pid, "catalog-lock")

    def test_deadlock_detection_and_recovery_release_victim_resources(self) -> None:
        demo = self.sync.create_deadlock_demo()

        self.assertEqual(self.sync.detect_deadlock(), demo["processes"])
        self.assertEqual(len(self.sync.snapshot()["wait_for"]), 2)

        recovered = self.sync.recover_deadlock()
        victim_pid = max(demo["processes"])
        surviving_pid = min(demo["processes"])

        self.assertEqual(recovered["victim_pid"], victim_pid)
        self.assertEqual(self.processes.get(victim_pid).state, "TERMINATED")
        self.assertEqual(self.processes.get(surviving_pid).state, "READY")
        self.assertEqual(self.sync.detect_deadlock(), [])
        self.assertEqual(recovered["awakened_pids"], [surviving_pid])

    def test_recovery_is_a_no_op_when_there_is_no_deadlock(self) -> None:
        result = self.sync.recover_deadlock()

        self.assertFalse(result["recovered"])
        self.assertIsNone(result["victim_pid"])

    def test_resource_creation_validates_kind_capacity_and_name(self) -> None:
        for name, kind, capacity in (
            ("bad name", "mutex", 1),
            ("bad-kind", "spinlock", 1),
            ("bad-mutex", "mutex", 2),
            ("bad-capacity", "semaphore", 17),
            ("bad-type", [], 1),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.sync.create_resource(name, kind, capacity)

    def test_race_demo_exposes_lost_update_and_mutex_result(self) -> None:
        result = self.sync.run_race_demo()

        self.assertEqual(result["unsafe_counter"], 1)
        self.assertEqual(result["safe_counter"], 2)
        self.assertEqual(result["safe_counter"], result["expected_counter"])
        self.assertEqual(len(result["unsafe_trace"]), 4)


class KernelSynchronizationTests(unittest.TestCase):
    def test_sync_websocket_dispatch_publishes_result_and_snapshot(self) -> None:
        kernel = Kernel()
        created = kernel.manage_synchronization(
            {
                "request_id": "sync-create",
                "operation": "create",
                "name": "test-lock",
                "kind": "mutex",
            }
        )

        self.assertTrue(created["ok"])
        self.assertEqual(created["request_id"], "sync-create")
        self.assertIn("test-lock", [item["name"] for item in created["resources"]])
        self.assertEqual(kernel.events.snapshot()[-1]["type"], "sync_result")

    def test_killing_process_cleans_held_sync_resources(self) -> None:
        kernel = Kernel()
        child = kernel.processes.fork(2, "lock-holder")
        kernel.synchronization.acquire(child.pid, "catalog-lock")

        result = kernel.manage_process({"operation": "kill", "pid": child.pid})

        catalog = next(
            item for item in kernel.synchronization.snapshot()["resources"]
            if item["name"] == "catalog-lock"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(catalog["holders"], [])
        self.assertEqual(child.held_locks, [])
        self.assertEqual(kernel.events.snapshot()[-1]["type"], "process_result")

    def test_terminal_termination_releases_held_resources(self) -> None:
        from shell.commands import execute

        processes = ProcessManager()
        sync = SynchronizationManager(processes)
        child = processes.fork(2, "terminal-lock-holder")
        sync.acquire(child.pid, "catalog-lock")

        result = execute(
            f"kill {child.pid}",
            processes.list_processes(),
            [],
            process_manager=processes,
            sync_manager=sync,
        )

        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["sync_changed"])
        catalog = next(item for item in sync.snapshot()["resources"] if item["name"] == "catalog-lock")
        self.assertEqual(catalog["holders"], [])


if __name__ == "__main__":
    unittest.main()
