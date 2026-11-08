"""Stage 7 catalog and circulation checks."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from kernel.boot import Kernel


class LibraryApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.kernel = Kernel(disk_path=Path(self.temp_directory.name) / "disk.img.json")
        asyncio.run(self.kernel.boot())

    def write_record(self, path: str, record: dict[str, object]) -> None:
        content = json.dumps(record)
        if path in self.kernel.filesystem.inodes:
            self.kernel.filesystem.write_file(path, content, owner="root")
        else:
            self.kernel.filesystem.create_file(path, content, owner="root")

    def test_dashboard_search_filters_and_request_validation(self) -> None:
        dashboard = self.kernel.manage_library({"operation": "dashboard"})
        self.assertTrue(dashboard["ok"])
        self.assertEqual(len(dashboard["result"]["books"]), 60)
        self.assertEqual(len(dashboard["result"]["members"]), 25)
        self.assertTrue(dashboard["result"]["loans"])

        members = self.kernel.manage_library({
            "operation": "members",
            "query": "M025",
        })
        self.assertTrue(members["ok"])
        self.assertEqual([item["id"] for item in members["result"]["members"]], ["M025"])

        self.kernel.filesystem.make_directory("/books/archive", owner="root")
        self.kernel.filesystem.create_file("/books/readme.txt", "skip non-JSON", owner="root")
        self.write_record("/issued/extra.json", {
            "id": "extra",
            "book_id": 7,
            "member_id": "M025",
            "status": "issued",
        })
        self.assertEqual(len(self.kernel.library.search_catalog()), 60)

        for request in (
            {"operation": "catalog", "query": 1},
            {"operation": "members", "query": False},
            {"operation": "unsupported"},
            {},
        ):
            with self.subTest(request=request):
                result = self.kernel.manage_library(request)
                self.assertFalse(result["ok"])
                self.assertIsNotNone(result["error"])

    def test_checkout_validates_account_state_and_record_limits(self) -> None:
        self.kernel.security.login("librarian")
        invalid_ids = (
            (None, "M025"),
            (123, "M025"),
            ("../x", "M025"),
            ("B013", None),
            ("B013", "M0"),
        )
        for book_id, member_id in invalid_ids:
            with self.subTest(book_id=book_id, member_id=member_id):
                result = self.kernel.manage_library({
                    "operation": "checkout",
                    "book_id": book_id,
                    "member_id": member_id,
                })
                self.assertFalse(result["ok"])
                self.assertIn("invalid", result["error"])

        member_path = "/members/M025.json"
        original_member = json.loads(self.kernel.filesystem.read_file(member_path))
        inactive_member = {**original_member, "status": "inactive"}
        self.write_record(member_path, inactive_member)
        inactive = self.kernel.manage_library({
            "operation": "checkout", "book_id": "B013", "member_id": "M025",
        })
        self.assertIn("not active", inactive["error"])

        for loan_limit in (True, 0, "3"):
            self.write_record(member_path, {**original_member, "max_books_allowed": loan_limit})
            result = self.kernel.manage_library({
                "operation": "checkout", "book_id": "B013", "member_id": "M025",
            })
            self.assertIn("invalid loan limit", result["error"])

        self.write_record(member_path, original_member)
        book_path = "/books/B013.json"
        original_book = json.loads(self.kernel.filesystem.read_file(book_path))
        for copy_count in (True, 0, "2"):
            self.write_record(book_path, {**original_book, "total_copies": copy_count})
            result = self.kernel.manage_library({
                "operation": "checkout", "book_id": "B013", "member_id": "M025",
            })
            self.assertIn("invalid copy count", result["error"])

    def test_checkout_issue_ids_ignore_nonmatching_filenames(self) -> None:
        self.kernel.security.login("librarian")
        self.write_record("/issued/notes.json", {
            "id": "notes",
            "status": "returned",
        })
        result = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B013",
            "member_id": "M025",
        })
        self.assertTrue(result["ok"], result["error"])
        self.assertEqual(result["result"]["issue"]["id"], "I021")

    def test_return_validation_no_fine_and_atomic_rollback(self) -> None:
        self.kernel.security.login("librarian")
        for issue_id in ("../I001", 7, None):
            result = self.kernel.manage_library({"operation": "return", "issue_id": issue_id})
            self.assertFalse(result["ok"])
            self.assertIn("invalid issue ID", result["error"])

        missing = self.kernel.manage_library({"operation": "return", "issue_id": "I9999"})
        self.assertFalse(missing["ok"])

        issue_path = "/issued/I020.json"
        issue = json.loads(self.kernel.filesystem.read_file(issue_path))
        self.write_record(issue_path, {**issue, "status": "returned"})
        inactive = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertIn("not active", inactive["error"])

        self.write_record(
            issue_path,
            {**issue, "status": "issued", "due_date": "not-a-date"},
        )
        bad_date = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertIn("invalid due date", bad_date["error"])

        future_issue = {
            **issue,
            "status": "issued",
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
        }
        self.write_record(issue_path, future_issue)
        fine_count = len(self.kernel.filesystem.list_directory("/fines"))
        returned = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertTrue(returned["ok"], returned["error"])
        self.assertEqual(returned["result"]["issue"]["fine"], 0)
        self.assertEqual(len(self.kernel.filesystem.list_directory("/fines")), fine_count)

        overdue_issue = {
            **issue,
            "status": "issued",
            "due_date": (date.today() - timedelta(days=2)).isoformat(),
        }
        self.write_record(issue_path, overdue_issue)
        member_path = "/members/M020.json"
        self.write_record(member_path, {
            **json.loads(self.kernel.filesystem.read_file(member_path)),
            "fines_due": True,
        })
        rollback = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertFalse(rollback["ok"])
        restored_issue = json.loads(self.kernel.filesystem.read_file(issue_path))
        self.assertEqual(restored_issue["status"], "issued")
        self.assertEqual(restored_issue["due_date"], overdue_issue["due_date"])

    def test_malformed_library_records_and_fine_balances_are_reported(self) -> None:
        self.kernel.security.login("librarian")
        self.kernel.filesystem.write_file("/books/B001.json", "{bad json", owner="root")
        bad_json = self.kernel.manage_library({"operation": "catalog"})
        self.assertIn("invalid JSON", bad_json["error"])

        self.kernel.filesystem.write_file("/books/B001.json", "[]", owner="root")
        bad_shape = self.kernel.manage_library({"operation": "catalog"})
        self.assertIn("invalid record", bad_shape["error"])

        self.kernel.filesystem.write_file(
            "/books/B001.json",
            json.dumps({"id": "B001", "total_copies": True}),
            owner="root",
        )
        bad_copy_count = self.kernel.manage_library({"operation": "catalog"})
        self.assertIn("invalid copy count", bad_copy_count["error"])

        issue_path = "/issued/I020.json"
        issue = json.loads(self.kernel.filesystem.read_file(issue_path))
        issue.update(
            status="issued",
            due_date=(date.today() - timedelta(days=1)).isoformat(),
        )
        self.write_record(issue_path, issue)
        self.write_record("/members/M020.json", {
            **json.loads(self.kernel.filesystem.read_file("/members/M020.json")),
            "fines_due": "invalid",
        })
        invalid_balance = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertIn("invalid fine balance", invalid_balance["error"])

        self.write_record("/members/M020.json", {
            **json.loads(self.kernel.filesystem.read_file("/members/M020.json")),
            "fines_due": 0.0,
        })
        self.write_record("/fines/F999.json", {
            "id": "F999",
            "issue_id": "I020",
            "member_id": "M020",
            "amount": True,
            "status": "unpaid",
        })
        invalid_fine = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertIn("invalid amount", invalid_fine["error"])

        self.kernel.filesystem.delete("/fines/F999.json", owner="root")
        self.write_record(issue_path, {
            **issue,
            "status": "issued",
            "due_date": (date.today() - timedelta(days=1)).isoformat(),
            "member_id": "not-a-member",
        })
        invalid_member = self.kernel.manage_library({"operation": "return", "issue_id": "I020"})
        self.assertIn("invalid member ID", invalid_member["error"])

    def test_catalog_search_and_availability_use_active_loans(self) -> None:
        result = self.kernel.manage_library({"operation": "catalog", "query": "Ursula K. Le Guin"})

        self.assertTrue(result["ok"])
        books = result["result"]["books"]
        self.assertTrue(books)
        self.assertTrue(all("Ursula K. Le Guin" in book["author"] for book in books))
        book_one = next(book for book in self.kernel.manage_library(
            {"operation": "catalog", "query": "B001"}
        )["result"]["books"] if book["id"] == "B001")
        self.assertEqual(book_one["available_copies"], 0)

    def test_guest_can_search_but_cannot_check_out(self) -> None:
        catalog = self.kernel.manage_library({"operation": "catalog", "query": "B013"})
        denied = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B013",
            "member_id": "M025",
        })

        self.assertTrue(catalog["ok"])
        self.assertFalse(denied["ok"])
        self.assertIn("not allowed", denied["error"])
        self.assertEqual(len(self.kernel.filesystem.list_directory("/issued")), 20)

    def test_librarian_checkout_checks_limits_and_updates_catalog(self) -> None:
        self.kernel.security.login("librarian")
        unavailable = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B001",
            "member_id": "M025",
        })
        self.assertFalse(unavailable["ok"])
        self.assertIn("no copies", unavailable["error"])

        response = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B013",
            "member_id": "M025",
        })

        self.assertTrue(response["ok"], response["error"])
        issue = response["result"]["issue"]
        self.assertEqual(issue["status"], "issued")
        self.assertEqual(
            date.fromisoformat(issue["due_date"]) - date.fromisoformat(issue["issue_date"]),
            timedelta(days=14),
        )
        book = next(
            item
            for item in self.kernel.manage_library(
                {"operation": "catalog", "query": "B013"}
            )["result"]["books"]
            if item["id"] == "B013"
        )
        self.assertEqual(book["available_copies"], 2)

        self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B014",
            "member_id": "M025",
        })
        self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B015",
            "member_id": "M025",
        })
        over_limit = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B016",
            "member_id": "M025",
        })
        self.assertFalse(over_limit["ok"])
        self.assertIn("loan limit", over_limit["error"])

    def test_return_records_fine_and_does_not_duplicate_existing_fine(self) -> None:
        self.kernel.security.login("librarian")
        seeded_fine_count = len(self.kernel.filesystem.list_directory("/fines"))
        seeded_return = self.kernel.manage_library({"operation": "return", "issue_id": "I001"})

        self.assertTrue(seeded_return["ok"], seeded_return["error"])
        self.assertEqual(seeded_return["result"]["issue"]["status"], "returned")
        self.assertEqual(len(self.kernel.filesystem.list_directory("/fines")), seeded_fine_count)

        checkout = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "B013",
            "member_id": "M025",
        })
        issue = checkout["result"]["issue"]
        issue["due_date"] = (date.today() - timedelta(days=2)).isoformat()
        self.kernel.filesystem.write_file(
            f"/issued/{issue['id']}.json",
            json.dumps(issue),
            owner="librarian",
        )
        returned = self.kernel.manage_library({"operation": "return", "issue_id": issue["id"]})

        self.assertTrue(returned["ok"], returned["error"])
        self.assertEqual(returned["result"]["issue"]["fine"], 1.0)
        self.assertEqual(len(self.kernel.filesystem.list_directory("/fines")), seeded_fine_count + 1)
        member = json.loads(self.kernel.filesystem.read_file("/members/M025.json"))
        self.assertEqual(member["fines_due"], 1.0)

    def test_invalid_identifiers_are_rejected_without_writing(self) -> None:
        self.kernel.security.login("librarian")
        response = self.kernel.manage_library({
            "operation": "checkout",
            "book_id": "../etc/libraos.json",
            "member_id": "M025",
        })

        self.assertFalse(response["ok"])
        self.assertEqual(len(self.kernel.filesystem.list_directory("/issued")), 20)

    def test_requests_publish_correlated_events_and_survive_shutdown(self) -> None:
        self.kernel.security.login("librarian")
        checkout = self.kernel.manage_library({
            "operation": "checkout",
            "request_id": "library-checkout-1",
            "book_id": "B013",
            "member_id": "M025",
        })
        event = self.kernel.events.snapshot()[-1]
        self.assertEqual(event["type"], "library_result")
        self.assertEqual(event["request_id"], "library-checkout-1")

        asyncio.run(self.kernel.power("shutdown"))
        restored = Kernel(disk_path=Path(self.temp_directory.name) / "disk.img.json")
        asyncio.run(restored.boot())

        self.assertTrue(checkout["ok"])
        persisted_issue = json.loads(
            restored.filesystem.read_file(
                f"/issued/{checkout['result']['issue']['id']}.json"
            )
        )
        self.assertEqual(persisted_issue["status"], "issued")


if __name__ == "__main__":
    unittest.main()
