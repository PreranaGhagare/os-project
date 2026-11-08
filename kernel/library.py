"""Catalog and circulation operations over the simulated file system."""

from __future__ import annotations

import copy
import json
import re
from datetime import date, timedelta
from typing import Any

from kernel.filesystem import FileSystem, FileSystemError
from kernel.security import SecurityManager


_BOOK_ID = re.compile(r"B\d{3}\Z")
_MEMBER_ID = re.compile(r"M\d{3}\Z")
_ISSUE_ID = re.compile(r"I\d{3,}\Z")


class LibraryManager:
    """Read and update library records stored as simulated files."""

    def __init__(self, filesystem: FileSystem, security: SecurityManager) -> None:
        self.filesystem = filesystem
        self.security = security

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        operation = request.get("operation")
        if operation == "dashboard":
            return {
                "books": self.search_catalog(),
                "members": self.list_members(),
                "loans": self.active_loans(),
            }
        if operation == "catalog":
            query = request.get("query", "")
            if not isinstance(query, str):
                raise ValueError("catalog query must be text")
            return {"books": self.search_catalog(query)}
        if operation == "members":
            query = request.get("query", "")
            if not isinstance(query, str):
                raise ValueError("member query must be text")
            return {"members": self.list_members(query)}
        if operation == "checkout":
            return self.checkout(request.get("book_id"), request.get("member_id"))
        if operation == "return":
            return self.return_book(request.get("issue_id"))
        raise ValueError(f"unsupported library operation: {operation}")

    def search_catalog(self, query: str = "") -> list[dict[str, Any]]:
        self.security.require("read", path="/books")
        normalized_query = query.strip().casefold()
        active_by_book: dict[str, int] = {}
        for issue in self._records("/issued"):
            if issue.get("status") in {"issued", "overdue"}:
                book_id = issue.get("book_id")
                if isinstance(book_id, str):
                    active_by_book[book_id] = active_by_book.get(book_id, 0) + 1

        books = []
        for book in self._records("/books"):
            searchable = " ".join(
                str(book.get(field, ""))
                for field in ("id", "title", "author", "category", "isbn")
            ).casefold()
            if normalized_query and normalized_query not in searchable:
                continue
            total_copies = book.get("total_copies", 0)
            if isinstance(total_copies, bool) or not isinstance(total_copies, int):
                raise ValueError(f"invalid copy count for book {book.get('id', 'unknown')}")
            books.append({
                **book,
                "available_copies": max(0, total_copies - active_by_book.get(str(book.get("id")), 0)),
            })
        return books

    def list_members(self, query: str = "") -> list[dict[str, Any]]:
        self.security.require("read", path="/members")
        normalized_query = query.strip().casefold()
        return [
            member
            for member in self._records("/members")
            if not normalized_query
            or normalized_query in " ".join(
                str(member.get(field, ""))
                for field in ("id", "name", "role", "email")
            ).casefold()
        ]

    def active_loans(self) -> list[dict[str, Any]]:
        self.security.require("read", path="/issued")
        return [
            issue
            for issue in self._records("/issued")
            if issue.get("status") in {"issued", "overdue"}
        ]

    def checkout(self, book_id: Any, member_id: Any) -> dict[str, Any]:
        self.security.require("write", path="/issued")
        book_id = self._validated_id(book_id, _BOOK_ID, "book")
        member_id = self._validated_id(member_id, _MEMBER_ID, "member")
        book = self._read_record("/books", book_id)
        member = self._read_record("/members", member_id)

        if member.get("status") != "active":
            raise ValueError(f"member {member_id} is not active")
        active_loans = self.active_loans()
        member_loans = sum(issue.get("member_id") == member_id for issue in active_loans)
        limit = member.get("max_books_allowed", 3)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError(f"invalid loan limit for member {member_id}")
        if member_loans >= limit:
            raise ValueError(f"member {member_id} has reached the loan limit")

        total_copies = book.get("total_copies")
        if isinstance(total_copies, bool) or not isinstance(total_copies, int) or total_copies < 1:
            raise ValueError(f"invalid copy count for book {book_id}")
        copies_out = sum(issue.get("book_id") == book_id for issue in active_loans)
        if copies_out >= total_copies:
            raise ValueError(f"no copies of {book_id} are available")

        issue_id = self._next_record_id("/issued", "I")
        today = date.today()
        issue = {
            "id": issue_id,
            "book_id": book_id,
            "member_id": member_id,
            "issue_date": today.isoformat(),
            "due_date": (today + timedelta(days=14)).isoformat(),
            "return_date": None,
            "fine": 0.0,
            "status": "issued",
        }
        self.filesystem.create_file(
            f"/issued/{issue_id}.json",
            self._encode(issue),
            owner="librarian",
        )
        return {"issue": issue}

    def return_book(self, issue_id: Any) -> dict[str, Any]:
        self.security.require("write", path="/issued")
        issue_id = self._validated_id(issue_id, _ISSUE_ID, "issue")
        issue_path = f"/issued/{issue_id}.json"
        issue = self._decode(issue_path)
        if issue.get("status") not in {"issued", "overdue"}:
            raise ValueError(f"issue {issue_id} is not active")

        today = date.today()
        try:
            due_date = date.fromisoformat(issue["due_date"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"issue {issue_id} has an invalid due date") from error
        existing_fine = next(
            (
                fine_record
                for fine_record in self._records("/fines")
                if fine_record.get("issue_id") == issue_id and fine_record.get("status") == "unpaid"
            ),
            None,
        )
        if existing_fine is not None:
            fine = existing_fine.get("amount", 0.0)
            if isinstance(fine, bool) or not isinstance(fine, (int, float)):
                raise ValueError(f"fine for issue {issue_id} has an invalid amount")
        else:
            fine = round(max(0, (today - due_date).days) * 0.5, 2)
        updated_issue = {
            **issue,
            "return_date": today.isoformat(),
            "fine": fine,
            "status": "returned",
        }
        backup = copy.deepcopy(self.filesystem.__dict__)
        try:
            self.filesystem.write_file(issue_path, self._encode(updated_issue), owner="librarian")
            if fine and existing_fine is None:
                self._create_fine(updated_issue, fine)
        except (FileSystemError, ValueError):
            self.filesystem.__dict__.clear()
            self.filesystem.__dict__.update(backup)
            raise
        return {"issue": updated_issue}

    def _create_fine(self, issue: dict[str, Any], amount: float) -> None:
        member_id = issue.get("member_id")
        if not isinstance(member_id, str) or not _MEMBER_ID.fullmatch(member_id):
            raise ValueError(f"issue {issue.get('id')} has an invalid member ID")
        member_path = f"/members/{member_id}.json"
        member = self._decode(member_path)
        fines_due = member.get("fines_due", 0.0)
        if isinstance(fines_due, bool) or not isinstance(fines_due, (int, float)):
            raise ValueError(f"member {member_id} has an invalid fine balance")
        fine_id = self._next_record_id("/fines", "F")
        fine = {
            "id": fine_id,
            "issue_id": issue["id"],
            "member_id": member_id,
            "amount": amount,
            "status": "unpaid",
        }
        self.filesystem.create_file(
            f"/fines/{fine_id}.json",
            self._encode(fine),
            owner="librarian",
        )
        member["fines_due"] = round(fines_due + amount, 2)
        self.filesystem.write_file(member_path, self._encode(member), owner="librarian")

    def _records(self, directory: str) -> list[dict[str, Any]]:
        self.security.require("read", path=directory)
        records = []
        for inode in self.filesystem.list_directory(directory):
            if inode["type"] != "file" or not inode["name"].endswith(".json"):
                continue
            records.append(self._decode(inode["path"]))
        return records

    def _read_record(self, directory: str, record_id: str) -> dict[str, Any]:
        return self._decode(f"{directory}/{record_id}.json")

    def _decode(self, path: str) -> dict[str, Any]:
        try:
            record = json.loads(self.filesystem.read_file(path))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON in {path}") from error
        if not isinstance(record, dict):
            raise ValueError(f"invalid record in {path}")
        return record

    def _next_record_id(self, directory: str, prefix: str) -> str:
        numbers = []
        for inode in self.filesystem.list_directory(directory):
            match = re.fullmatch(rf"{re.escape(prefix)}(\d+)\.json", inode["name"])
            if match:
                numbers.append(int(match.group(1)))
        return f"{prefix}{max(numbers, default=0) + 1:03}"

    @staticmethod
    def _validated_id(value: Any, pattern: re.Pattern[str], label: str) -> str:
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise ValueError(f"invalid {label} ID")
        return value

    @staticmethod
    def _encode(record: dict[str, Any]) -> str:
        return json.dumps(record, ensure_ascii=False, indent=2) + "\n"
