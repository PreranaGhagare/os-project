"""Write-ahead redo journal for simulated disk-image transactions."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kernel.disk import DiskImage


class JournalError(RuntimeError):
    """Raised when the simulated disk journal cannot be read or written."""


class DiskJournal:
    """Persist transaction intents before committing their disk-image snapshot."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: list[dict[str, Any]] = []
        if self.path.is_file():
            self._records = self._read_records()

    def begin(self, operation: str, request_id: str, image: dict[str, Any]) -> str:
        transaction_id = uuid.uuid4().hex
        self._append({
            "kind": "begin",
            "transaction_id": transaction_id,
            "timestamp": self._now(),
            "operation": operation,
            "request_id": request_id,
            "image": image,
        })
        return transaction_id

    def commit(self, transaction_id: str) -> None:
        self._append({
            "kind": "commit",
            "transaction_id": transaction_id,
            "timestamp": self._now(),
        })
        self._compact()

    def abort(self, transaction_id: str, reason: str) -> None:
        self._append({
            "kind": "abort",
            "transaction_id": transaction_id,
            "timestamp": self._now(),
            "reason": reason,
        })
        self._compact()

    def recover(self, disk_image: DiskImage) -> list[dict[str, Any]]:
        """Redo any transaction with a durable intent but no commit marker."""
        if not self.path.is_file():
            return []
        pending: dict[str, dict[str, Any]] = {}
        for record in self._records:
            transaction_id = record["transaction_id"]
            if record["kind"] == "begin":
                pending[transaction_id] = record
            elif record["kind"] in {"commit", "abort"}:
                pending.pop(transaction_id, None)

        recovered = []
        for transaction_id, record in pending.items():
            image = record.get("image")
            if not isinstance(image, dict):
                raise JournalError(f"journal transaction {transaction_id} has no disk image")
            try:
                from kernel.filesystem import FileSystem, FileSystemError

                FileSystem.from_image(image)
            except (FileSystemError, TypeError, ValueError, RuntimeError) as error:
                raise JournalError(
                    f"journal transaction {transaction_id} contains an invalid disk image: {error}"
                ) from error
            disk_image.save(image)
            self._append({
                "kind": "commit",
                "transaction_id": transaction_id,
                "timestamp": self._now(),
                "recovered": True,
            })
            recovered.append({
                "transaction_id": transaction_id,
                "operation": record.get("operation", "unknown"),
                "request_id": record.get("request_id", ""),
            })
        if recovered:
            self._compact()
        return recovered

    def snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent journal summaries without internal recovery snapshots."""
        visible = []
        for record in self._records:
            if record["kind"] == "begin":
                visible.append({
                    key: value for key, value in record.items()
                    if key != "image"
                })
            elif record["kind"] in {"commit", "abort"}:
                visible.append(dict(record))
        return visible[-limit:]

    def _append(self, record: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as journal_file:
                journal_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                journal_file.flush()
                os.fsync(journal_file.fileno())
        except (OSError, TypeError, ValueError) as error:
            raise JournalError(f"could not write disk journal {self.path}: {error}") from error
        self._records.append(record)

    def _compact(self) -> None:
        compact_records = []
        commits = {
            record["transaction_id"]: record
            for record in self._records
            if record["kind"] in {"commit", "abort"}
        }
        beginnings = [
            record for record in self._records if record["kind"] == "begin"
        ]
        for begin in beginnings:
            compact_records.append({
                key: value for key, value in begin.items()
                if key != "image"
            })
            outcome = commits.get(begin["transaction_id"])
            if outcome is not None:
                compact_records.append(outcome)

        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as journal_file:
                for record in compact_records:
                    journal_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                journal_file.flush()
                os.fsync(journal_file.fileno())
            temporary_path.replace(self.path)
        except (OSError, TypeError, ValueError) as error:
            raise JournalError(f"could not compact disk journal {self.path}: {error}") from error
        self._records = compact_records

    def _read_records(self) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise JournalError(f"could not read disk journal {self.path}: {error}") from error
        records: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                if index == len(lines) - 1:
                    try:
                        self.path.write_text(
                            "".join(
                                json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
                                for item in records
                            ),
                            encoding="utf-8",
                            newline="\n",
                        )
                    except OSError as write_error:
                        raise JournalError(
                            f"could not truncate incomplete journal record: {write_error}"
                        ) from write_error
                    break
                raise JournalError(f"invalid journal record on line {index + 1}") from error
            if (
                not isinstance(record, dict)
                or record.get("kind") not in {"begin", "commit", "abort"}
                or not isinstance(record.get("transaction_id"), str)
            ):
                raise JournalError(f"invalid journal record on line {index + 1}")
            records.append(record)
        return records

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
