"""Stage 2 file-system, allocation, seed-data, and persistence checks."""

from __future__ import annotations

import asyncio
import copy
import tempfile
import unittest
from pathlib import Path

from kernel.boot import Kernel
from kernel.disk import DiskImage, DiskImageError
from kernel.filesystem import FileSystem, FileSystemError
from kernel.journal import JournalError
from kernel.seed_data import seed_filesystem


class FileSystemTests(unittest.TestCase):
    def test_constructor_and_allocation_method_validation(self) -> None:
        for options in (
            {"block_count": 15},
            {"block_size": 31},
            {"allocation_method": "random"},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                FileSystem(**options)

        filesystem = FileSystem()
        self.assertEqual(filesystem.set_allocation_method("linked"), "linked")
        self.assertEqual(filesystem.allocation_method, "linked")
        with self.assertRaises(FileSystemError) as error:
            filesystem.set_allocation_method("random")
        self.assertEqual(error.exception.code, "EINVAL")

    def test_path_metadata_and_creation_errors(self) -> None:
        filesystem = FileSystem()
        file_inode = filesystem.create_file("/home/guest/note.txt", "hello")
        self.assertEqual(filesystem.stat(file_inode["path"])["content"], "hello")
        self.assertNotIn("content", filesystem.stat("/home/guest"))
        self.assertEqual(
            [entry["name"] for entry in filesystem.list_directory("/home")],
            ["guest"],
        )

        cases = (
            (lambda: filesystem.list_directory("/missing"), "ENOENT"),
            (lambda: filesystem.list_directory(file_inode["path"]), "ENOTDIR"),
            (lambda: filesystem.stat("/missing"), "ENOENT"),
            (lambda: filesystem.read_file("/missing"), "ENOENT"),
            (lambda: filesystem.read_file("/home/guest"), "EISDIR"),
            (lambda: filesystem.create_file(file_inode["path"], "duplicate"), "EEXIST"),
            (lambda: filesystem.create_file("/missing/file", "data"), "ENOENT"),
            (lambda: filesystem.create_file(f"{file_inode['path']}/child", "data"), "ENOTDIR"),
            (lambda: filesystem.create_file("/home/guest/binary", b"not text"), "EINVAL"),
            (lambda: filesystem.create_file("/home/guest/bad", "data", allocation="random"), "EINVAL"),
        )
        for operation, expected_code in cases:
            with self.subTest(expected_code=expected_code), self.assertRaises(FileSystemError) as error:
                operation()
            self.assertEqual(error.exception.code, expected_code)

        for invalid_path in ("", "bad\\path", "bad\x00path"):
            with self.subTest(invalid_path=invalid_path), self.assertRaises(FileSystemError) as error:
                filesystem.stat(invalid_path)
            self.assertEqual(error.exception.code, "EINVAL")

    def test_write_and_directory_lifecycle_permissions(self) -> None:
        filesystem = FileSystem()
        file_inode = filesystem.create_file("/home/guest/note.txt", "original", owner="guest")
        filesystem.write_file(file_inode["path"], "replaced", owner="root")
        self.assertEqual(filesystem.read_file(file_inode["path"]), "replaced")

        with self.assertRaises(FileSystemError) as error:
            filesystem.write_file(file_inode["path"], "denied", owner="other")
        self.assertEqual(error.exception.code, "EACCES")

        filesystem.make_directory("/home/guest/empty")
        with self.assertRaises(FileSystemError) as error:
            filesystem.make_directory("/")
        self.assertEqual(error.exception.code, "EEXIST")
        with self.assertRaises(FileSystemError) as error:
            filesystem.make_directory("/home/guest/empty")
        self.assertEqual(error.exception.code, "EEXIST")
        with self.assertRaises(FileSystemError) as error:
            filesystem.make_directory("/missing/child")
        self.assertEqual(error.exception.code, "ENOENT")

        for operation, expected_code in (
            (lambda: filesystem.write_file("/missing", "data"), "ENOENT"),
            (lambda: filesystem.write_file("/home/guest/empty", "data"), "EISDIR"),
            (lambda: filesystem.delete("/missing"), "ENOENT"),
            (lambda: filesystem.delete("/"), "EPERM"),
            (lambda: filesystem.delete("/home/guest"), "ENOTEMPTY"),
            (lambda: filesystem.delete(file_inode["path"], owner="other"), "EACCES"),
        ):
            with self.subTest(expected_code=expected_code), self.assertRaises(FileSystemError) as error:
                operation()
            self.assertEqual(error.exception.code, expected_code)

        filesystem.delete("/home/guest/empty")
        filesystem.delete(file_inode["path"], owner="admin")
        self.assertEqual(filesystem.disk_usage()["used_blocks"], 0)

    def test_empty_files_and_invalid_block_text(self) -> None:
        for method in ("contiguous", "linked", "indexed"):
            with self.subTest(method=method):
                filesystem = FileSystem(allocation_method=method)
                inode = filesystem.create_file("/home/guest/empty.txt", "")
                self.assertEqual(inode["blocks"], [])
                self.assertIsNone(inode["index_block"])
                self.assertEqual(filesystem.read_file(inode["path"]), "")
                filesystem.write_file(inode["path"], "content")
                filesystem.write_file(inode["path"], "")
                self.assertEqual(filesystem.disk_usage()["used_blocks"], 0)

        filesystem = FileSystem()
        inode = filesystem.create_file("/home/guest/invalid.txt", "valid")
        filesystem.block_data[inode["blocks"][0]] = b"\xff"
        with self.assertRaises(FileSystemError) as error:
            filesystem.read_file(inode["path"])
        self.assertEqual(error.exception.code, "EIO")

    def test_disk_image_rejects_invalid_structure_and_allocations(self) -> None:
        filesystem = FileSystem()
        filesystem.create_file("/first.txt", "first")
        filesystem.create_file("/second.txt", "second")
        valid_image = filesystem.to_image()

        invalid_images = []
        bad_format = copy.deepcopy(valid_image)
        bad_format["format"] = "other"
        invalid_images.append(bad_format)

        bad_bitmap = copy.deepcopy(valid_image)
        bad_bitmap["free_block_bitmap"].pop()
        invalid_images.append(bad_bitmap)

        bad_base64 = copy.deepcopy(valid_image)
        bad_base64["blocks"][str(filesystem.inodes["/first.txt"]["blocks"][0])] = "!"
        invalid_images.append(bad_base64)

        overlapping = copy.deepcopy(valid_image)
        duplicate_allocation = copy.deepcopy(overlapping["inode_table"][-1])
        duplicate_allocation["path"] = "/overlap.txt"
        overlapping["inode_table"].append(duplicate_allocation)
        invalid_images.append(overlapping)

        missing_block = copy.deepcopy(valid_image)
        block = filesystem.inodes["/first.txt"]["blocks"][0]
        del missing_block["blocks"][str(block)]
        invalid_images.append(missing_block)

        for image in invalid_images:
            with self.subTest(image=image), self.assertRaises(FileSystemError) as error:
                FileSystem.from_image(image)
            self.assertEqual(error.exception.code, "EIO")

    def test_seed_records_are_files(self) -> None:
        filesystem = FileSystem()
        seed_filesystem(filesystem)

        self.assertEqual(len(filesystem.list_directory("/books")), 60)
        self.assertEqual(len(filesystem.list_directory("/members")), 25)
        self.assertEqual(len(filesystem.list_directory("/issued")), 20)
        self.assertEqual(len(filesystem.list_directory("/fines")), 8)

    def test_file_round_trip_and_delete_releases_blocks(self) -> None:
        filesystem = FileSystem()
        record = filesystem.create_file("/home/guest/hello.txt", "Hello, LibraOS 🌙")

        self.assertEqual(filesystem.read_file(record["path"]), "Hello, LibraOS 🌙")
        used_before_delete = filesystem.disk_usage()["used_blocks"]
        filesystem.delete(record["path"])
        self.assertEqual(filesystem.disk_usage()["used_blocks"], used_before_delete - 2)

    def test_contiguous_allocation_reports_fragmentation(self) -> None:
        filesystem = FileSystem(block_count=16, block_size=32, allocation_method="contiguous")
        for name in "abcdefgh":
            filesystem.create_file(f"/{name}", "x" * 64)
        for name in "bdfh":
            filesystem.delete(f"/{name}")

        self.assertEqual(filesystem.disk_usage()["free_blocks"], 8)
        with self.assertRaises(FileSystemError) as error:
            filesystem.create_file("/large", "x" * 96)
        self.assertEqual(error.exception.code, "ENOSPC")

    def test_failed_write_preserves_previous_data(self) -> None:
        filesystem = FileSystem(block_count=16, block_size=32, allocation_method="contiguous")
        for name in "abcdefgh":
            filesystem.create_file(f"/{name}", "x" * 64)
        for name in "dfh":
            filesystem.delete(f"/{name}")
        with self.assertRaises(FileSystemError):
            filesystem.write_file("/a", "y" * 96)
        self.assertEqual(filesystem.read_file("/a"), "x" * 64)

    def test_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(FileSystemError) as error:
            FileSystem().list_directory("/books/../etc")
        self.assertEqual(error.exception.code, "EPERM")

    def test_disk_image_round_trip(self) -> None:
        filesystem = FileSystem()
        filesystem.create_file("/home/guest/note.txt", "persist me")
        image = filesystem.to_image()
        restored = FileSystem.from_image(image)

        self.assertEqual(restored.read_file("/home/guest/note.txt"), "persist me")
        self.assertEqual(restored.disk_usage(), filesystem.disk_usage())

    def test_allocation_methods_store_and_retrieve_file_data(self) -> None:
        for method in ("contiguous", "linked", "indexed"):
            with self.subTest(method=method):
                filesystem = FileSystem(allocation_method=method)
                inode = filesystem.create_file("/home/guest/data.bin", "block data " * 70)
                self.assertEqual(inode["allocation"], method)
                self.assertEqual(filesystem.read_file(inode["path"]), "block data " * 70)
                self.assertEqual(inode["index_block"] is not None, method == "indexed")


class KernelPersistenceTests(unittest.TestCase):
    def test_filesystem_request_dispatch_covers_supported_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())

            listing = kernel.execute_filesystem_request({"operation": "list", "path": "/etc"})
            self.assertTrue(listing["ok"])
            self.assertEqual(listing["result"]["entries"][0]["name"], "libraos.json")

            reading = kernel.execute_filesystem_request({
                "operation": "read",
                "path": "/books/B001.json",
            })
            self.assertTrue(reading["ok"])
            self.assertIn('"id": "B001"', reading["result"]["content"])

            stat = kernel.execute_filesystem_request({
                "operation": "stat",
                "path": "/books/B001.json",
            })
            self.assertTrue(stat["ok"])
            self.assertEqual(stat["result"]["type"], "file")

            made_directory = kernel.execute_filesystem_request({
                "operation": "mkdir",
                "path": "/home/guest/request-test",
                "request_id": "mkdir-request",
            })
            self.assertTrue(made_directory["ok"])
            self.assertEqual(made_directory["request_id"], "mkdir-request")

            created = kernel.execute_filesystem_request({
                "operation": "create",
                "path": "/home/guest/request-test/note.txt",
                "content": "first version",
                "allocation": "linked",
                "request_id": "create-request",
            })
            self.assertTrue(created["ok"])
            self.assertEqual(created["result"]["allocation"], "linked")

            written = kernel.execute_filesystem_request({
                "operation": "write",
                "path": "/home/guest/request-test/note.txt",
                "content": "updated",
                "allocation": "contiguous",
            })
            self.assertTrue(written["ok"])
            self.assertEqual(
                kernel.filesystem.read_file("/home/guest/request-test/note.txt"),
                "updated",
            )

            allocation = kernel.execute_filesystem_request({
                "operation": "set_allocation",
                "path": "/",
                "allocation": "indexed",
            })
            self.assertTrue(allocation["ok"])
            self.assertEqual(allocation["result"]["allocation_method"], "indexed")

            usage = kernel.execute_filesystem_request({"operation": "usage"})
            self.assertTrue(usage["ok"])
            self.assertGreater(usage["result"]["used_blocks"], 0)

            deleted = kernel.execute_filesystem_request({
                "operation": "delete",
                "path": "/home/guest/request-test/note.txt",
            })
            self.assertTrue(deleted["ok"])
            self.assertTrue(deleted["result"]["deleted"])

            self.assertTrue(any(
                event["type"] == "request_trace"
                and event["request_id"] == "create-request"
                and event["ok"]
                for event in kernel.events.snapshot()
            ))

    def test_filesystem_request_rejects_malformed_and_unsupported_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            with self.assertRaises(RuntimeError):
                kernel.execute_filesystem_request({"operation": "usage"})
            asyncio.run(kernel.boot())

            invalid_requests = (
                ({"operation": 1}, "EINVAL"),
                ({"operation": "usage", "path": 1}, "EINVAL"),
                ({"operation": "create", "path": "/home/guest/bad", "content": 1}, "EINVAL"),
                (
                    {
                        "operation": "create",
                        "path": "/home/guest/bad",
                        "content": "text",
                        "allocation": 1,
                    },
                    "EINVAL",
                ),
                ({"operation": "write", "path": "/home/guest/note.txt", "content": None}, "EINVAL"),
                ({"operation": "write", "path": "/home/guest/note.txt", "content": "x", "allocation": 1}, "EINVAL"),
                ({"operation": "set_allocation", "allocation": 1}, "EINVAL"),
                ({"operation": "unknown"}, "ENOSYS"),
                ({"operation": "mkdir", "path": "/books/new"}, "EACCES"),
            )
            for request, expected_code in invalid_requests:
                with self.subTest(request=request):
                    response = kernel.execute_filesystem_request(request)
                    self.assertFalse(response["ok"])
                    self.assertEqual(response["error_code"], expected_code)
                    self.assertIsNotNone(response["error"])

            kernel.security.login("librarian")
            for request in (
                {"operation": "read", "path": "/books/missing.json"},
                {"operation": "create", "path": "/books/missing/file.json", "content": "x"},
                {"operation": "delete", "path": "/books/missing.json"},
            ):
                response = kernel.execute_filesystem_request(request)
                self.assertFalse(response["ok"])
                self.assertEqual(response["error_code"], "ENOENT")

            self.assertFalse(
                kernel.execute_filesystem_request({
                    "operation": "set_allocation",
                    "allocation": "unknown",
                })["ok"]
            )

    def test_filesystem_request_rolls_back_mutations_when_persistence_fails(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())
            original_usage = kernel.filesystem.disk_usage()

            with patch.object(
                kernel.disk_image,
                "save",
                side_effect=DiskImageError("disk unavailable"),
            ):
                response = kernel.execute_filesystem_request({
                    "operation": "create",
                    "path": "/home/guest/not-durable.txt",
                    "content": "should roll back",
                })

            self.assertFalse(response["ok"])
            self.assertEqual(response["error_code"], "EIO")
            self.assertEqual(kernel.filesystem.disk_usage(), original_usage)
            self.assertEqual(kernel.journal.snapshot()[-1]["kind"], "abort")

            with patch.object(
                kernel.journal,
                "begin",
                side_effect=JournalError("journal unavailable"),
            ):
                failed_journal = kernel.execute_filesystem_request({
                    "operation": "mkdir",
                    "path": "/home/guest/not-journaled",
                })
            self.assertFalse(failed_journal["ok"])
            self.assertEqual(failed_journal["error_code"], "EIO")
            self.assertNotIn("/home/guest/not-journaled", kernel.filesystem.inodes)

    def test_filesystem_requests_cannot_impersonate_file_owners(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())
            result = kernel.execute_filesystem_request(
                {
                    "operation": "write",
                    "path": "/books/B001.json",
                    "content": "unauthorized edit",
                    "owner": "librarian",
                }
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["error_code"], "EACCES")

    def test_shutdown_saves_and_next_boot_restores(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "disk.img.json"
            kernel = Kernel(disk_path=image_path)
            asyncio.run(kernel.boot())
            created = kernel.execute_filesystem_request(
                {
                    "operation": "create",
                    "path": "/home/guest/persisted.txt",
                    "content": "survives shutdown",
                    "owner": "guest",
                }
            )
            self.assertTrue(created["ok"])
            asyncio.run(kernel.power("shutdown"))

            restored_kernel = Kernel(disk_path=image_path)
            asyncio.run(restored_kernel.boot())
            self.assertEqual(
                restored_kernel.filesystem.read_file("/home/guest/persisted.txt"),
                "survives shutdown",
            )
            self.assertIsInstance(DiskImage(image_path).load(), dict)

    def test_security_roles_enforce_library_and_home_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())

            kernel.security.login("guest")
            blocked = kernel.execute_filesystem_request(
                {
                    "operation": "create",
                    "path": "/books/B999.json",
                    "content": "tampering",
                }
            )
            self.assertFalse(blocked["ok"])
            self.assertEqual(blocked["error_code"], "EACCES")

            kernel.security.login("librarian")
            allowed = kernel.execute_filesystem_request(
                {
                    "operation": "create",
                    "path": "/books/LIBRARIAN_NOTE.json",
                    "content": "allowed",
                }
            )
            self.assertTrue(allowed["ok"])
            self.assertEqual(kernel.filesystem.read_file("/books/LIBRARIAN_NOTE.json"), "allowed")

    def test_syscall_requests_enforce_security_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())

            kernel.security.login("guest")
            denied = kernel.execute_syscall(
                "write",
                path="/books/B999.json",
                user="guest",
                content="forbidden",
            )
            self.assertFalse(denied["ok"])
            self.assertIn("not allowed", denied["error"])

            kernel.security.login("librarian")
            allowed = kernel.execute_syscall(
                "read",
                path="/books/B001.json",
                user="guest",
            )
            self.assertTrue(allowed["ok"])
            self.assertEqual(allowed["result"]["path"], "/books/B001.json")
            self.assertEqual(allowed["user"], "librarian")
            self.assertEqual(kernel.syscall_tracer.snapshot()[-1]["user"], "librarian")

    def test_syscall_dispatch_supports_filesystem_and_fallback_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())

            listing = kernel.execute_syscall("list", path="/etc")
            self.assertTrue(listing["ok"])
            self.assertEqual(listing["result"]["entries"][0]["name"], "libraos.json")

            stat = kernel.execute_syscall("stat", path="/books/B001.json")
            self.assertTrue(stat["ok"])
            self.assertEqual(stat["result"]["type"], "file")

            opened = kernel.execute_syscall("open", path="/books/B001.json", flags="r")
            self.assertEqual(opened["result"]["flags"], "r")

            created = kernel.execute_syscall(
                "create",
                request_id="syscall-create-file",
                path="/home/guest/syscall.txt",
                content="created by syscall",
            )
            self.assertTrue(created["ok"], created.get("error"))
            self.assertEqual(
                kernel.filesystem.read_file("/home/guest/syscall.txt"),
                "created by syscall",
            )
            written = kernel.execute_syscall(
                "write",
                path="/home/guest/syscall.txt",
                content="updated by syscall",
            )
            self.assertTrue(written["ok"], written.get("error"))
            self.assertEqual(
                kernel.filesystem.read_file("/home/guest/syscall.txt"),
                "updated by syscall",
            )

            made = kernel.execute_syscall("mkdir", path="/home/guest/syscall-dir")
            self.assertTrue(made["ok"], made.get("error"))
            deleted = kernel.execute_syscall("delete", path="/home/guest/syscall.txt")
            self.assertTrue(deleted["ok"], deleted.get("error"))

            unsupported = kernel.execute_syscall("clock", path="/clock")
            self.assertTrue(unsupported["ok"])
            self.assertEqual(unsupported["result"], {"path": "/clock"})
            self.assertEqual(kernel.journal.snapshot()[-2]["operation"], "syscall:delete")

    def test_syscall_reports_invalid_names_permissions_and_filesystem_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            unmounted = kernel.execute_syscall("read", path="/books/B001.json")
            self.assertTrue(unmounted["ok"])
            self.assertEqual(unmounted["result"], {"path": "/books/B001.json"})
            asyncio.run(kernel.boot())

            with self.assertRaises(ValueError):
                kernel.execute_syscall("  ")

            denied = kernel.execute_syscall(
                "write",
                path="/books/B001.json",
                content="blocked",
            )
            self.assertFalse(denied["ok"])
            self.assertIn("not allowed", denied["error"])

            missing = kernel.execute_syscall("read", path="/books/no-such-book.json")
            self.assertFalse(missing["ok"])
            self.assertIn("no such file", missing["error"])

            invalid_payloads = (
                {"path": "/home/guest/bad.txt", "content": None},
                {"path": "/home/guest/bad.txt", "content": "text", "allocation": 1},
            )
            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    failed = kernel.execute_syscall("create", **payload)
                    self.assertFalse(failed["ok"])
                    self.assertTrue(failed["error"])

    def test_syscall_mutation_rolls_back_when_disk_save_fails(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            kernel = Kernel(disk_path=Path(directory) / "disk.img.json")
            asyncio.run(kernel.boot())

            with patch.object(
                kernel.disk_image,
                "save",
                side_effect=DiskImageError("disk unavailable"),
            ):
                result = kernel.execute_syscall(
                    "create",
                    request_id="syscall-failed-save",
                    path="/home/guest/not-saved.txt",
                    content="rollback",
                )

            self.assertFalse(result["ok"])
            self.assertIn("disk unavailable", result["error"])
            self.assertNotIn("/home/guest/not-saved.txt", kernel.filesystem.inodes)
            self.assertEqual(kernel.journal.snapshot()[-1]["kind"], "abort")


if __name__ == "__main__":
    unittest.main()
