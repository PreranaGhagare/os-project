"""Tests for the allow-listed simulated terminal commands."""

from __future__ import annotations

import asyncio
import unittest
import tempfile
from pathlib import Path
from typing import Any

from kernel.boot import Kernel
from shell.commands import execute


class ShellCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.kernel = Kernel(disk_path=Path(self.temporary_directory.name) / "disk.img.json")
        asyncio.run(self.kernel.boot())

    def run_command(self, command: str, **overrides: Any) -> dict[str, Any]:
        events = overrides.pop("events", self.kernel.events.snapshot())
        managers = {
            "filesystem": self.kernel.filesystem,
            "scheduler": self.kernel.run_scheduler_command,
            "process_manager": self.kernel.processes,
            "sync_manager": self.kernel.synchronization,
            "memory_manager": self.kernel.memory,
        }
        managers.update(overrides)
        return execute(
            command,
            self.kernel.processes.list_processes(),
            events,
            **managers,
        )

    def test_parser_help_and_basic_system_commands(self) -> None:
        malformed = self.run_command("echo 'unfinished")
        self.assertEqual(malformed["exit_code"], 2)
        self.assertTrue(malformed["output"][0].startswith("parse error:"))

        self.assertEqual(self.run_command("   ")["output"], [])
        self.assertIn("help", "\n".join(self.run_command("help")["output"]))
        self.assertTrue(self.run_command("clear")["clear"])

        process_list = self.run_command("ps")["output"]
        self.assertIn("PID  PPID  STATE", process_list[0])
        self.assertTrue(any("libra-shell" in line for line in process_list))
        self.assertIn("Processes: 3", self.run_command("top")["output"])
        self.assertEqual(self.run_command("pwd")["output"], ["/home/guest"])
        self.assertEqual(self.run_command("whoami")["output"], ["guest (demo session)"])
        self.assertIn("simulated-kernel", self.run_command("uname")["output"][0])
        self.assertRegex(self.run_command("date")["output"][0], r"\+\d\d:\d\d$")
        self.assertEqual(self.run_command('echo "hello LibraOS"')["output"], ["hello LibraOS"])
        self.assertEqual(self.run_command("unknown-command")["exit_code"], 127)
        self.assertIn("] [", self.run_command("dmesg")["output"][0])

    def test_virtual_filesystem_commands_and_error_paths(self) -> None:
        root = self.run_command("ls")
        self.assertEqual(root["exit_code"], 0)
        self.assertIn("books/", root["output"])
        self.assertEqual(self.run_command("ls /missing")["exit_code"], 2)
        self.assertIn("usage:", self.run_command("cat")["output"][0])
        self.assertIn("usage:", self.run_command("mkdir")["output"][0])

        record = self.run_command("cat /books/B001.json")
        self.assertEqual(record["exit_code"], 0)
        self.assertTrue(any("The Left Hand of Darkness" in line for line in record["output"]))
        self.assertEqual(self.run_command("cat /books/missing.json")["exit_code"], 2)

        created = self.run_command("mkdir /home/guest/shell-test")
        self.assertEqual(created["exit_code"], 0)
        self.assertEqual(self.run_command("ls /home/guest")["exit_code"], 0)
        self.assertEqual(self.run_command("mkdir /home/guest/shell-test")["exit_code"], 2)
        usage = self.run_command("df")
        self.assertEqual(usage["exit_code"], 0)
        self.assertIn("libra-disk", usage["output"][1])

        self.assertEqual(self.run_command("cat x", filesystem=None)["exit_code"], 2)
        self.assertEqual(self.run_command("mkdir x", filesystem=None)["exit_code"], 2)
        self.assertEqual(self.run_command("df", filesystem=None)["exit_code"], 2)
        self.assertEqual(self.run_command("ls /invalid", filesystem=None)["exit_code"], 2)
        self.assertEqual(self.run_command("ls /etc", filesystem=None)["output"], ["libraos.conf"])

    def test_scheduler_command_validates_and_formats_result(self) -> None:
        self.assertEqual(self.run_command("sched a b c")["exit_code"], 2)
        self.assertEqual(self.run_command("sched", scheduler=None)["exit_code"], 2)
        self.assertEqual(self.run_command("sched rr nope")["exit_code"], 2)
        self.assertEqual(self.run_command("sched invalid")["exit_code"], 2)
        result = self.run_command("sched rr 2")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(any("Algorithm: rr" in line for line in result["output"]))

    def test_process_commands_cover_lifecycle_and_validation(self) -> None:
        self.assertEqual(self.run_command("fork", process_manager=None)["exit_code"], 2)
        self.assertEqual(self.run_command("fork invalid")["exit_code"], 2)
        self.assertEqual(self.run_command("fork 2 shell-child")["exit_code"], 0)
        child = self.kernel.processes.list_processes()[-1]

        self.assertEqual(self.run_command("exec", process_manager=None)["exit_code"], 2)
        self.assertEqual(self.run_command(f"exec {child.pid} new-image")["exit_code"], 0)
        self.assertEqual(self.run_command("exec not-a-pid image")["exit_code"], 2)
        self.assertEqual(self.run_command("exec 999 image")["exit_code"], 2)
        self.assertEqual(self.run_command(f"nice {child.pid} 1")["exit_code"], 0)
        self.assertEqual(self.run_command(f"nice {child.pid} 11")["exit_code"], 2)
        self.assertEqual(self.run_command("nice not-a-pid 1")["exit_code"], 2)
        self.assertEqual(self.run_command(f"exit {child.pid}")["exit_code"], 0)
        self.assertEqual(self.run_command("exit not-a-pid")["exit_code"], 2)
        self.assertEqual(self.run_command("exit 9999")["exit_code"], 2)
        self.assertTrue(self.run_command(f"wait 2 {child.pid}")["output"][0].startswith("PID 2"))
        self.assertEqual(self.run_command("wait 2 3")["exit_code"], 2)
        self.assertEqual(self.run_command("wait not-a-pid 3")["exit_code"], 2)
        for command in ("exec 1 x", "exit 1", "kill 1", "nice 1 1", "wait 1 2"):
            self.assertEqual(
                self.run_command(command, process_manager=None)["exit_code"],
                2,
                command,
            )

        fork_test = self.run_command("fork-test")
        self.assertEqual(fork_test["exit_code"], 0)
        self.assertIn("Created READY processes:", fork_test["output"][0])
        self.assertEqual(self.run_command("fork-test", process_manager=None)["exit_code"], 2)

        kill_target = self.kernel.processes.fork(2, "kill-target")
        killed = self.run_command(f"kill {kill_target.pid}")
        self.assertEqual(killed["exit_code"], 0)
        self.assertTrue(killed["sync_changed"])
        self.assertTrue(killed["memory_changed"])
        self.assertEqual(self.run_command("kill 1")["exit_code"], 2)
        self.assertEqual(self.run_command("kill not-a-pid")["exit_code"], 2)

        optional_cleanup_target = self.kernel.processes.fork(2, "optional-cleanup")
        optional_cleanup = self.run_command(
            f"exit {optional_cleanup_target.pid}",
            sync_manager=None,
            memory_manager=None,
        )
        self.assertFalse(optional_cleanup["sync_changed"])
        self.assertFalse(optional_cleanup["memory_changed"])
        optional_kill_target = self.kernel.processes.fork(2, "optional-kill")
        optional_kill = self.run_command(
            f"kill {optional_kill_target.pid}",
            sync_manager=None,
        )
        self.assertFalse(optional_kill["sync_changed"])
        self.assertTrue(optional_kill["memory_changed"])

    def test_terminal_power_aliases_and_kernel_log_output(self) -> None:
        for command, action in (
            ("shutdown", "shutdown"),
            ("reboot", "reboot"),
            ("restart", "reboot"),
        ):
            with self.subTest(command=command):
                result = self.run_command(command)
                self.assertEqual(result["action"], action)
                self.assertEqual(result["exit_code"], 0)

        self.kernel.events.publish(
            "log",
            module="test",
            severity="warning",
            message="shell test log entry",
        )
        self.assertTrue(any("shell test log entry" in line for line in self.run_command("dmesg")["output"]))
        self.assertEqual(
            self.run_command("dmesg", events=[])["output"],
            ["No kernel messages"],
        )


if __name__ == "__main__":
    unittest.main()
