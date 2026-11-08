"""Security boundary regression tests for the demo identity and path rules."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.boot import Kernel
from kernel.security import (
    SecurityError,
    SecurityManager,
    SyscallError,
    SyscallTracer,
    UserAccount,
)


class SecurityHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.security = SecurityManager()

    def test_demo_login_cannot_change_existing_roles_or_admin_identity(self) -> None:
        for username, role in (("guest", "admin"), ("librarian", "guest"), ("root", None)):
            with self.subTest(username=username, role=role):
                with self.assertRaises(SecurityError):
                    self.security.login(username, role=role)
        self.assertEqual(self.security.current_user, "guest")
        self.assertEqual(self.security.whoami()["role"], "guest")

    def test_new_demo_accounts_are_guest_only_and_home_is_fixed(self) -> None:
        with self.assertRaises(SecurityError):
            self.security.login("new-user", role="librarian")
        with self.assertRaises(SecurityError):
            self.security.login("new-user", home="/books")

        account = self.security.login("new-user")

        self.assertEqual(account["role"], "guest")
        self.assertEqual(account["home"], "/home/new-user")

    def test_username_validation_rejects_path_and_control_characters(self) -> None:
        for username in ("../root", "admin/child", "guest\x00"):
            with self.subTest(username=username):
                with self.assertRaises(ValueError):
                    self.security.login(username)

    def test_home_and_librarian_authorization_respects_path_boundaries(self) -> None:
        self.assertFalse(self.security.authorize("write", path="/home/guest-other/file"))
        self.assertFalse(self.security.authorize("write", path="/home/guest/../books/file"))
        self.assertFalse(self.security.authorize("write", path="/home/guest\\file"))

        self.security.login("librarian")
        self.assertTrue(self.security.authorize("write", path="/books/notes.json"))
        self.assertFalse(self.security.authorize("write", path="/books-archive/notes.json"))
        self.assertFalse(self.security.authorize("read", path="/etc/config.json"))
        self.assertFalse(self.security.authorize("write", path="/logs/audit.log"))

    def test_security_api_reports_role_escalation_as_a_denial(self) -> None:
        kernel = Kernel()

        result = kernel.manage_security({
            "operation": "login",
            "username": "guest",
            "role": "admin",
        })

        self.assertFalse(result["ok"])
        self.assertEqual(result["current_user"], "guest")

    def test_syscall_cannot_impersonate_a_privileged_user(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())

            result = kernel.execute_syscall(
                "write",
                path="/books/B001.json",
                content="forbidden",
                user="root",
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["user"], "guest")
        self.assertEqual(kernel.syscall_tracer.snapshot()[-1]["user"], "guest")

    def test_account_serialization_and_custom_user_initialization(self) -> None:
        account = UserAccount("reader", "guest", "/home/reader", active=False)
        self.assertEqual(
            account.as_dict(),
            {
                "username": "reader",
                "role": "guest",
                "home": "/home/reader",
                "active": False,
            },
        )

        security = SecurityManager(
            current_user="CUSTOM",
            users=[
                {"username": "inactive", "role": "guest", "active": False},
                {"user": "student", "role": "student"},
                {"username": "", "role": "admin"},
            ],
        )
        self.assertEqual(security.current_user, "custom")
        self.assertEqual(security.whoami()["home"], "/home/custom")
        users = security.list_users()
        self.assertEqual([user["username"] for user in users], [
            "custom", "guest", "inactive", "librarian", "root", "student",
        ])
        self.assertEqual(security.snapshot()["current_user"], "custom")
        with self.assertRaises(SecurityError):
            security.login("inactive")
        security.current_user = "removed-user"
        with self.assertRaises(SecurityError):
            security.whoami()

    def test_login_normalizes_existing_user_and_validates_new_user_options(self) -> None:
        security = SecurityManager()
        account = security.login("  LIBRARIAN  ", role=" LIBRARIAN ", home="/home/librarian")
        self.assertEqual(account["username"], "librarian")

        for username, role, home in (
            ("new-reader", 1, None),
            ("new-reader", "admin", None),
            ("new-reader", "guest", "/home/other"),
            ("guest", 1, None),
            ("guest", "guest", 1),
        ):
            with self.subTest(username=username, role=role, home=home), self.assertRaises(SecurityError):
                security.login(username, role=role, home=home)

        with self.assertRaises(ValueError):
            security.login(None)

    def test_authorization_policy_covers_roles_actions_and_invalid_inputs(self) -> None:
        security = SecurityManager()
        self.assertTrue(security.authorize("read"))
        self.assertFalse(security.authorize(None))
        self.assertFalse(security.authorize("read", user="../guest"))
        self.assertFalse(security.authorize("write", owner=object()))
        self.assertFalse(security.authorize("write", path="/home/guest/\x00file"))
        self.assertFalse(security.authorize("write", path=""))
        self.assertTrue(security.authorize("read", path="/home//guest/notes"))
        self.assertFalse(security.authorize("write", path="/home/guest-public/notes"))
        self.assertFalse(security.authorize("read", user="missing-account"))
        self.assertFalse(security.authorize("chown", path="/home/guest/private"))

        security = SecurityManager(
            current_user="student",
            users=[{"username": "student", "role": "student"}],
        )
        self.assertTrue(security.authorize("stat", path="/books/B001.json"))
        self.assertFalse(security.authorize("write", path="/books/B001.json"))
        self.assertFalse(security.authorize("search", path="/etc/passwd"))
        self.assertTrue(security.authorize("search", user="librarian"))

        security.login("librarian")
        self.assertTrue(security.authorize("chmod", path="/books/note.json"))
        self.assertFalse(security.authorize("chown", path="/books/note.json"))
        self.assertTrue(security.authorize("read", path="/home/librarian/private.txt"))
        self.assertTrue(
            security.authorize("write", path="/home/librarian/private.txt", owner="another-user")
        )
        self.assertFalse(
            security.authorize("chown", path="/home/librarian/private.txt", owner="librarian")
        )
        self.assertFalse(security.authorize("write", path="/logs/system.log"))

        security = SecurityManager(current_user="root")
        self.assertTrue(security.authorize("anything", path="/invalid\\path"))
        self.assertTrue(security.authorize("anything", owner=object()))

    def test_require_raises_permission_error_with_access_code(self) -> None:
        security = SecurityManager()
        self.assertTrue(security.require("read", path="/books/B001.json"))
        with self.assertRaises(SecurityError) as error:
            security.require("write", path="/books/B001.json")
        self.assertEqual(error.exception.code, "EACCES")
        self.assertIn("guest", str(error.exception))

    def test_syscall_tracer_validates_names_and_can_be_cleared(self) -> None:
        tracer = SyscallTracer()
        result = tracer.trace("  read  ", path="/books/B001.json", user="  ")
        self.assertEqual(result["syscall"], "read")
        self.assertEqual(result["user"], "guest")
        self.assertEqual(tracer.snapshot()[0]["payload"]["path"], "/books/B001.json")

        for syscall in ("", "  ", None):
            with self.subTest(syscall=syscall), self.assertRaises(SyscallError):
                tracer.trace(syscall)

        tracer.clear()
        self.assertEqual(tracer.snapshot(), [])
