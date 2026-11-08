"""Block-based simulated file system used by LibraOS."""

from __future__ import annotations

import base64
import json
import math
import posixpath
from datetime import datetime, timezone
from typing import Any


ALLOCATION_METHODS = {"contiguous", "linked", "indexed"}
ROOT_DIRECTORIES = ("/books", "/members", "/issued", "/fines", "/logs", "/etc", "/home")


class FileSystemError(Exception):
    """Expected file-system failure with a syscall-style error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FileSystem:
    """An inode tree backed by simulated disk blocks, not host files."""

    def __init__(
        self,
        *,
        block_count: int = 512,
        block_size: int = 256,
        allocation_method: str = "indexed",
    ) -> None:
        if block_count < 16 or block_size < 32:
            raise ValueError("the simulated disk must have at least 16 blocks of 32 bytes")
        if allocation_method not in ALLOCATION_METHODS:
            raise ValueError(f"unsupported allocation method: {allocation_method}")

        self.block_count = block_count
        self.block_size = block_size
        self.allocation_method = allocation_method
        self.next_inode = 1
        self.inodes: dict[str, dict[str, Any]] = {}
        self.block_data: dict[int, bytes] = {}
        self._create_directory("/", "root")
        for directory in ROOT_DIRECTORIES:
            self._create_directory(directory, "root")
        self._create_directory("/home/guest", "guest")

    @classmethod
    def from_image(cls, image: dict[str, Any]) -> FileSystem:
        """Restore and validate a simulated disk image."""
        try:
            if image.get("format") != "libraos-disk-image" or image.get("version") != 1:
                raise ValueError("unsupported disk image format")
            superblock = image["superblock"]
            fs = cls(
                block_count=superblock["block_count"],
                block_size=superblock["block_size"],
                allocation_method=superblock["allocation_method"],
            )
            table = image["inode_table"]
            bitmap = image["free_block_bitmap"]
            if not isinstance(table, list) or not isinstance(bitmap, list):
                raise ValueError("inode table and free-block bitmap must be arrays")
            if len(bitmap) != fs.block_count or any(not isinstance(bit, bool) for bit in bitmap):
                raise ValueError("free-block bitmap does not match the disk size")

            fs.inodes = {}
            fs.block_data = {}
            used_blocks: set[int] = set()
            for entry in table:
                inode = dict(entry)
                path = fs._normalize_path(inode["path"])
                if path in fs.inodes:
                    raise ValueError(f"duplicate inode path: {path}")
                if inode.get("type") not in {"file", "directory"}:
                    raise ValueError(f"invalid inode type for {path}")
                allocated = list(inode.get("blocks", []))
                index_block = inode.get("index_block")
                all_blocks = allocated + ([] if index_block is None else [index_block])
                if any(not isinstance(block, int) or block < 0 or block >= fs.block_count for block in all_blocks):
                    raise ValueError(f"invalid block reference in {path}")
                if used_blocks.intersection(all_blocks):
                    raise ValueError(f"overlapping block allocation in {path}")
                used_blocks.update(all_blocks)
                inode["path"] = path
                fs.inodes[path] = inode

            if "/" not in fs.inodes or fs.inodes["/"].get("type") != "directory":
                raise ValueError("disk image is missing the root directory")
            for path, inode in fs.inodes.items():
                if path != "/" and posixpath.dirname(path) not in fs.inodes:
                    raise ValueError(f"missing parent directory for {path}")
                if path != "/" and fs.inodes[posixpath.dirname(path)].get("type") != "directory":
                    raise ValueError(f"parent is not a directory for {path}")
                if inode["type"] == "file":
                    data_blocks = inode["blocks"]
                    expected = math.ceil(inode.get("size", 0) / fs.block_size)
                    if len(data_blocks) != expected:
                        raise ValueError(f"file block count does not match its size: {path}")
                    if inode.get("allocation") == "indexed" and data_blocks and inode.get("index_block") is None:
                        raise ValueError(f"indexed file is missing its index block: {path}")
                    if inode.get("allocation") != "indexed" and inode.get("index_block") is not None:
                        raise ValueError(f"unexpected index block for {path}")
                elif inode.get("blocks") or inode.get("index_block") is not None:
                    raise ValueError(f"directory unexpectedly owns data blocks: {path}")

            block_payloads = image.get("blocks")
            if not isinstance(block_payloads, dict):
                raise ValueError("disk image block data must be an object")
            for block_text, payload in block_payloads.items():
                block = int(block_text)
                if block not in used_blocks:
                    raise ValueError(f"orphaned block data: {block}")
                fs.block_data[block] = base64.b64decode(payload, validate=True)
            for block in used_blocks:
                if block not in fs.block_data:
                    raise ValueError(f"missing block data: {block}")
            if any(bitmap[block] for block in used_blocks) or any(
                not bitmap[block] for block in range(fs.block_count) if block not in used_blocks
            ):
                raise ValueError("free-block bitmap does not match inode allocations")

            fs.next_inode = int(superblock["next_inode"])
            if fs.next_inode <= max(inode["inode"] for inode in fs.inodes.values()):
                raise ValueError("next inode number is not greater than existing inode numbers")
            return fs
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise FileSystemError("EIO", f"invalid disk image: {error}") from error

    def to_image(self) -> dict[str, Any]:
        """Serialize the superblock, inodes, bitmap, and block contents."""
        bitmap = [True] * self.block_count
        for block in self.block_data:
            bitmap[block] = False
        return {
            "format": "libraos-disk-image",
            "version": 1,
            "superblock": {
                "block_count": self.block_count,
                "block_size": self.block_size,
                "allocation_method": self.allocation_method,
                "next_inode": self.next_inode,
            },
            "inode_table": [dict(inode) for inode in sorted(self.inodes.values(), key=lambda item: item["inode"])],
            "free_block_bitmap": bitmap,
            "blocks": {
                str(block): base64.b64encode(data).decode("ascii")
                for block, data in sorted(self.block_data.items())
            },
        }

    def set_allocation_method(self, method: str) -> str:
        """Select how newly written files acquire blocks."""
        if method not in ALLOCATION_METHODS:
            raise FileSystemError("EINVAL", f"allocation must be one of: {', '.join(sorted(ALLOCATION_METHODS))}")
        self.allocation_method = method
        return method

    def list_directory(self, path: str = "/") -> list[dict[str, Any]]:
        """List direct children of a simulated directory."""
        normalized = self._normalize_path(path)
        directory = self.inodes.get(normalized)
        if directory is None:
            raise FileSystemError("ENOENT", f"no such path: {normalized}")
        if directory["type"] != "directory":
            raise FileSystemError("ENOTDIR", f"not a directory: {normalized}")
        children = [
            self._public_inode(inode)
            for child_path, inode in self.inodes.items()
            if child_path != normalized and posixpath.dirname(child_path) == normalized
        ]
        return sorted(children, key=lambda item: (item["type"] != "directory", item["name"].casefold()))

    def stat(self, path: str) -> dict[str, Any]:
        """Return inode and block-allocation metadata for a path."""
        normalized = self._normalize_path(path)
        inode = self.inodes.get(normalized)
        if inode is None:
            raise FileSystemError("ENOENT", f"no such path: {normalized}")
        result = self._public_inode(inode)
        if inode["type"] == "file":
            result["content"] = self.read_file(normalized)
        return result

    def read_file(self, path: str) -> str:
        """Read a file from its allocated simulated blocks."""
        normalized = self._normalize_path(path)
        inode = self.inodes.get(normalized)
        if inode is None:
            raise FileSystemError("ENOENT", f"no such file: {normalized}")
        if inode["type"] != "file":
            raise FileSystemError("EISDIR", f"is a directory: {normalized}")
        data = b"".join(self.block_data[block] for block in inode["blocks"])
        try:
            return data[: inode["size"]].decode("utf-8")
        except UnicodeDecodeError as error:
            raise FileSystemError("EIO", f"file contains invalid UTF-8: {normalized}") from error

    def create_file(
        self,
        path: str,
        content: str = "",
        *,
        owner: str = "guest",
        allocation: str | None = None,
    ) -> dict[str, Any]:
        """Create a file and allocate its contents on the simulated disk."""
        normalized = self._normalize_path(path)
        if normalized in self.inodes:
            raise FileSystemError("EEXIST", f"path already exists: {normalized}")
        self._require_parent(normalized)
        data = self._encode_content(content)
        method = allocation or self.allocation_method
        data_blocks, index_block = self._allocate_blocks(data, method)
        inode = self._new_inode(
            normalized,
            "file",
            owner,
            mode="0644",
            size=len(data),
            blocks=data_blocks,
            index_block=index_block,
            allocation=method,
        )
        self.inodes[normalized] = inode
        self._write_block_contents(data, data_blocks, index_block)
        return self._public_inode(inode)

    def write_file(
        self,
        path: str,
        content: str,
        *,
        owner: str = "guest",
        allocation: str | None = None,
    ) -> dict[str, Any]:
        """Replace a file's contents without losing old data on allocation failure."""
        normalized = self._normalize_path(path)
        inode = self.inodes.get(normalized)
        if inode is None:
            raise FileSystemError("ENOENT", f"no such file: {normalized}")
        if inode["type"] != "file":
            raise FileSystemError("EISDIR", f"is a directory: {normalized}")
        if owner not in {inode["owner"], "root", "librarian", "admin"}:
            raise FileSystemError("EACCES", f"write access denied: {normalized}")
        data = self._encode_content(content)
        method = allocation or self.allocation_method
        old_data_blocks = list(inode["blocks"])
        old_index_block = inode["index_block"]
        reusable_blocks = set(old_data_blocks)
        if old_index_block is not None:
            reusable_blocks.add(old_index_block)
        data_blocks, index_block = self._allocate_blocks(data, method, reusable_blocks)
        new_blocks = set(data_blocks)
        if index_block is not None:
            new_blocks.add(index_block)
        old_blocks = reusable_blocks
        for block in old_blocks - new_blocks:
            self.block_data.pop(block, None)
        inode.update(
            size=len(data),
            blocks=data_blocks,
            index_block=index_block,
            allocation=method,
            modified=_now(),
        )
        self._write_block_contents(data, data_blocks, index_block)
        return self._public_inode(inode)

    def make_directory(self, path: str, *, owner: str = "guest") -> dict[str, Any]:
        """Create one directory under an existing directory."""
        normalized = self._normalize_path(path)
        if normalized == "/":
            raise FileSystemError("EEXIST", "root directory already exists")
        if normalized in self.inodes:
            raise FileSystemError("EEXIST", f"path already exists: {normalized}")
        self._require_parent(normalized)
        inode = self._new_inode(normalized, "directory", owner, mode="0755")
        self.inodes[normalized] = inode
        return self._public_inode(inode)

    def delete(self, path: str, *, owner: str = "guest") -> None:
        """Delete a file or an empty directory and release its blocks."""
        normalized = self._normalize_path(path)
        inode = self.inodes.get(normalized)
        if inode is None:
            raise FileSystemError("ENOENT", f"no such path: {normalized}")
        if normalized == "/":
            raise FileSystemError("EPERM", "cannot delete the root directory")
        if inode["type"] == "directory" and any(
            child_path != normalized and posixpath.dirname(child_path) == normalized
            for child_path in self.inodes
        ):
            raise FileSystemError("ENOTEMPTY", f"directory is not empty: {normalized}")
        if owner not in {inode["owner"], "root", "librarian", "admin"}:
            raise FileSystemError("EACCES", f"delete access denied: {normalized}")
        for block in inode["blocks"] + ([] if inode["index_block"] is None else [inode["index_block"]]):
            self.block_data.pop(block, None)
        del self.inodes[normalized]

    def disk_usage(self) -> dict[str, int | str]:
        """Report simulated block capacity and use."""
        used = len(self.block_data)
        return {
            "block_count": self.block_count,
            "block_size": self.block_size,
            "used_blocks": used,
            "free_blocks": self.block_count - used,
            "inode_count": len(self.inodes),
            "allocation_method": self.allocation_method,
        }

    def _create_directory(self, path: str, owner: str) -> None:
        self.inodes[path] = self._new_inode(path, "directory", owner, mode="0755")

    def _new_inode(
        self,
        path: str,
        kind: str,
        owner: str,
        *,
        mode: str,
        size: int = 0,
        blocks: list[int] | None = None,
        index_block: int | None = None,
        allocation: str | None = None,
    ) -> dict[str, Any]:
        inode = {
            "inode": self.next_inode,
            "path": path,
            "type": kind,
            "owner": owner,
            "mode": mode,
            "size": size,
            "blocks": blocks or [],
            "index_block": index_block,
            "allocation": allocation,
            "created": _now(),
            "modified": _now(),
        }
        self.next_inode += 1
        return inode

    def _allocate_blocks(
        self,
        data: bytes,
        method: str,
        reusable: set[int] | None = None,
    ) -> tuple[list[int], int | None]:
        if method not in ALLOCATION_METHODS:
            raise FileSystemError("EINVAL", f"unsupported allocation method: {method}")
        count = math.ceil(len(data) / self.block_size)
        index_count = 1 if method == "indexed" and count else 0
        available = set(range(self.block_count)) - set(self.block_data)
        available.update(reusable or set())
        required = count + index_count
        if len(available) < required:
            raise FileSystemError("ENOSPC", "not enough free disk blocks")

        if method == "contiguous" and count:
            data_blocks = self._find_contiguous_run(available, count)
            if data_blocks is None:
                raise FileSystemError("ENOSPC", "no contiguous run is large enough")
        else:
            data_blocks = sorted(available)[:count]

        reserved = set(data_blocks)
        index_block = None
        if index_count:
            index_block = min(available - reserved)
        return data_blocks, index_block

    @staticmethod
    def _find_contiguous_run(available: set[int], count: int) -> list[int] | None:
        run: list[int] = []
        for block in sorted(available):
            if run and block != run[-1] + 1:
                run.clear()
            run.append(block)
            if len(run) == count:
                return run
        return None

    def _write_block_contents(self, data: bytes, blocks: list[int], index_block: int | None) -> None:
        for index, block in enumerate(blocks):
            start = index * self.block_size
            self.block_data[block] = data[start : start + self.block_size]
        if index_block is not None:
            self.block_data[index_block] = json.dumps(blocks, separators=(",", ":")).encode("ascii")

    @staticmethod
    def _encode_content(content: str) -> bytes:
        if not isinstance(content, str):
            raise FileSystemError("EINVAL", "file content must be text")
        return content.encode("utf-8")

    def _require_parent(self, path: str) -> None:
        parent = posixpath.dirname(path)
        if parent not in self.inodes:
            raise FileSystemError("ENOENT", f"parent directory does not exist: {parent}")
        if self.inodes[parent]["type"] != "directory":
            raise FileSystemError("ENOTDIR", f"parent is not a directory: {parent}")

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
            raise FileSystemError("EINVAL", "path must be a non-empty POSIX path")
        if any(part == ".." for part in path.split("/")):
            raise FileSystemError("EPERM", "parent-directory traversal is not allowed")
        return posixpath.normpath("/" + path.lstrip("/"))

    @staticmethod
    def _public_inode(inode: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": posixpath.basename(inode["path"]) or "/",
            "path": inode["path"],
            "type": inode["type"],
            "inode": inode["inode"],
            "owner": inode["owner"],
            "mode": inode["mode"],
            "size": inode["size"],
            "blocks": list(inode["blocks"]),
            "index_block": inode["index_block"],
            "allocation": inode["allocation"],
            "created": inode["created"],
            "modified": inode["modified"],
        }
