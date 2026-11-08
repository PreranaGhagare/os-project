"""HTTP and WebSocket integration tests for the LibraOS server."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from kernel.boot import Kernel
from server.main import create_app


class ServerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        kernel = Kernel(disk_path=Path(self.temporary_directory.name) / "disk.img.json")
        self.app = create_app(kernel)

    def test_http_routes_serve_desktop_health_and_static_files(self) -> None:
        with TestClient(self.app) as client:
            page = client.get("/")
            health = client.get("/health")
            script = client.get("/ui/js/app.js")

        self.assertEqual(page.status_code, 200)
        self.assertIn("LibraOS", page.text)
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"status": "running", "name": "LibraOS"})
        self.assertEqual(script.status_code, 200)
        self.assertIn("connect()", script.text)

    def test_websocket_snapshot_security_and_invalid_command(self) -> None:
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws") as websocket:
                snapshot = websocket.receive_json()
                self.assertEqual(snapshot["type"], "snapshot")
                self.assertEqual(snapshot["status"], "running")

                websocket.send_json({
                    "type": "security",
                    "operation": "login",
                    "username": "librarian",
                    "request_id": "api-login-1",
                })
                login = self._receive_event(websocket, "security_result")
                self.assertEqual(login["request_id"], "api-login-1")
                self.assertTrue(login["ok"])
                self.assertEqual(login["current_user"], "librarian")

                websocket.send_json({
                    "type": "filesystem",
                    "operation": "list",
                    "path": "/books",
                    "request_id": "api-list-1",
                })
                listing = self._receive_event(websocket, "filesystem_result")
                self.assertEqual(listing["request_id"], "api-list-1")
                self.assertTrue(listing["ok"])
                self.assertIn("B001.json", [entry["name"] for entry in listing["result"]["entries"]])

                websocket.send_json({"type": "unsupported"})
                websocket.send_json({
                    "type": "command",
                    "command": 42,
                    "request_id": "api-invalid-command",
                })
                invalid_command = self._receive_event(websocket, "terminal")
                self.assertEqual(invalid_command["request_id"], "api-invalid-command")
                self.assertEqual(invalid_command["output"], ["invalid command request"])
                self.assertEqual(invalid_command["exit_code"], 2)

    def test_websocket_dispatches_observability_scenario_resource_and_sync(self) -> None:
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws") as websocket:
                websocket.receive_json()
                requests = (
                    (
                        {"type": "observability", "operation": "snapshot", "request_id": "observe-1"},
                        "observability_result",
                    ),
                    (
                        {"type": "scenario", "operation": "list", "request_id": "scenario-1"},
                        "scenario_result",
                    ),
                    (
                        {"type": "resource", "operation": "state", "request_id": "resource-1"},
                        "resource_result",
                    ),
                    (
                        {"type": "sync", "operation": "state", "request_id": "sync-1"},
                        "sync_result",
                    ),
                )
                for request, event_type in requests:
                    with self.subTest(event_type=event_type):
                        websocket.send_json(request)
                        event = self._receive_event(websocket, event_type)
                        self.assertEqual(event["request_id"], request["request_id"])
                        self.assertTrue(event["ok"])

    def test_websocket_dispatches_processes_schedule_library_and_syscall(self) -> None:
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws") as websocket:
                websocket.receive_json()

                websocket.send_json({"type": "processes", "request_id": "processes-1"})
                processes = self._receive_event(websocket, "process_snapshot")
                self.assertEqual(processes["request_id"], "processes-1")
                self.assertTrue(processes["processes"])

                websocket.send_json({
                    "type": "schedule",
                    "request_id": "schedule-invalid",
                    "workload": [],
                })
                schedule_error = self._receive_event(websocket, "scheduler_error")
                self.assertEqual(schedule_error["request_id"], "schedule-invalid")
                self.assertIn("non-empty list", schedule_error["message"])

                websocket.send_json({
                    "type": "library",
                    "operation": "catalog",
                    "query": "B001",
                    "request_id": "library-1",
                })
                library = self._receive_event(websocket, "library_result")
                self.assertEqual(library["request_id"], "library-1")
                self.assertTrue(library["ok"])

                websocket.send_json({
                    "type": "syscall",
                    "syscall": "list",
                    "path": "/books",
                    "request_id": "syscall-1",
                })
                syscall = self._receive_event(websocket, "syscall_result")
                self.assertEqual(syscall["request_id"], "syscall-1")
                self.assertTrue(syscall["ok"])

                websocket.send_json({
                    "type": "process_action",
                    "operation": "nice",
                    "pid": 2,
                    "priority": 4,
                    "request_id": "nice-1",
                })
                process_action = self._receive_event(websocket, "process_result")
                self.assertEqual(process_action["request_id"], "nice-1")
                self.assertTrue(process_action["ok"])

    def test_websocket_executes_commands_valid_schedules_and_rejects_power_action(self) -> None:
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws") as websocket:
                websocket.receive_json()

                websocket.send_json({
                    "type": "command",
                    "command": "whoami",
                    "request_id": "command-whoami",
                })
                command = self._receive_event(websocket, "terminal")
                self.assertEqual(command["request_id"], "command-whoami")
                self.assertEqual(command["exit_code"], 0)
                self.assertTrue(any("guest" in line for line in command["output"]))

                websocket.send_json({
                    "type": "schedule",
                    "request_id": "schedule-valid",
                    "workload": [{"name": "integration-job", "burst_time": 2}],
                    "algorithm": "fcfs",
                })
                schedule = self._receive_event(websocket, "scheduler_result")
                self.assertEqual(schedule["request_id"], "schedule-valid")
                self.assertEqual(schedule["algorithm"], "fcfs")
                self.assertEqual(len(schedule["processes"]), 1)

                websocket.send_json({"type": "power", "action": "hibernate"})
                power_log = self._receive_event(websocket, "log")
                while power_log.get("module") != "power":
                    power_log = self._receive_event(websocket, "log")
                self.assertEqual(power_log["severity"], "error")
                self.assertIn("Rejected unsupported power action", power_log["message"])

    @staticmethod
    def _receive_event(websocket: Any, event_type: str) -> dict[str, Any]:
        while True:
            event = websocket.receive_json()
            if event.get("type") == event_type:
                return event
