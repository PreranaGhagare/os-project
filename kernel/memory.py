"""Demand-paged memory simulation and page-replacement algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kernel.process import Process, ProcessManager


PAGE_REPLACEMENT_ALGORITHMS = {"fifo", "lru", "optimal"}


@dataclass
class Frame:
    pid: int
    page: int
    loaded_at: int
    last_used: int


class MemoryManager:
    """Track per-process virtual pages and a shared set of physical frames."""

    def __init__(
        self,
        processes: ProcessManager,
        *,
        frame_count: int = 8,
        page_size: int = 256,
    ) -> None:
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or not 1 <= frame_count <= 256:
            raise ValueError("frame count must be between 1 and 256")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
            raise ValueError("page size must be a positive integer")
        self.processes = processes
        self.frame_count = frame_count
        self.page_size = page_size
        self._frames: list[Frame | None] = [None] * frame_count
        self._address_spaces: dict[int, int] = {}
        self._clock = 0
        self._last_run: dict[str, Any] | None = None

    def allocate(self, pid: int, pages: int) -> dict[str, Any]:
        process = self._active_process(pid)
        if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= 64:
            raise ValueError("virtual page count must be between 1 and 64")
        if pid in self._address_spaces:
            raise ValueError(f"PID {pid} already has a {self._address_spaces[pid]}-page address space")
        self._address_spaces[pid] = pages
        process.memory_pages = []
        return self.snapshot()

    def release(self, pid: int) -> dict[str, Any]:
        process = self.processes.get(pid)
        self._address_spaces.pop(pid, None)
        for index, frame in enumerate(self._frames):
            if frame is not None and frame.pid == pid:
                self._frames[index] = None
        process.memory_pages = []
        return self.snapshot()

    def terminate_process(self, pid: int) -> None:
        """Release a terminated process's address space and resident pages."""
        self.release(pid)

    def simulate(
        self,
        pid: int,
        references: list[int],
        *,
        algorithm: str = "fifo",
    ) -> dict[str, Any]:
        self._active_process(pid)
        if not isinstance(algorithm, str):
            raise ValueError("page-replacement algorithm must be text")
        normalized_algorithm = algorithm.strip().lower()
        if normalized_algorithm not in PAGE_REPLACEMENT_ALGORITHMS:
            raise ValueError(f"unknown page-replacement algorithm: {normalized_algorithm}")
        if not isinstance(references, list) or not references or len(references) > 200:
            raise ValueError("page reference string must contain between 1 and 200 page numbers")
        page_count = self._address_spaces.get(pid)
        if page_count is None:
            raise ValueError(f"PID {pid} does not have an allocated address space")
        if any(
            isinstance(page, bool) or not isinstance(page, int) or not 0 <= page < page_count
            for page in references
        ):
            raise ValueError(f"page references must be integers from 0 to {page_count - 1}")

        self._clear_resident_pages(pid)
        page_faults = 0
        evictions: list[dict[str, int]] = []
        trace: list[dict[str, Any]] = []

        for position, page in enumerate(references):
            self._clock += 1
            frame_index = self._find_frame(pid, page)
            hit = frame_index is not None
            evicted: dict[str, int | str] | None = None
            if not hit:
                page_faults += 1
                frame_index = self._find_free_frame()
                if frame_index is None:
                    frame_index = self._select_victim(pid, normalized_algorithm, references[position + 1 :])
                    old_frame = self._frames[frame_index]
                    if old_frame is None:
                        raise RuntimeError("page replacement selected an empty frame")
                    evicted = {
                        "pid": old_frame.pid,
                        "process": self.processes.get(old_frame.pid).name,
                        "page": old_frame.page,
                        "frame": frame_index,
                    }
                    evictions.append(evicted)
                self._frames[frame_index] = Frame(pid, page, self._clock, self._clock)
            else:
                frame = self._frames[frame_index]
                if frame is None:
                    raise RuntimeError("page lookup resolved to an empty frame")
                frame.last_used = self._clock
            self._sync_all_process_frames()
            trace.append(
                {
                    "step": position + 1,
                    "page": page,
                    "frame": frame_index,
                    "hit": hit,
                    "evicted": evicted,
                    "resident_pages": [
                        {"frame": index, "page": frame.page}
                        for index, frame in enumerate(self._frames)
                        if frame is not None and frame.pid == pid
                    ],
                }
            )

        self._last_run = {
            "pid": pid,
            "algorithm": normalized_algorithm,
            "references": list(references),
            "page_faults": page_faults,
            "hits": len(references) - page_faults,
            "fault_rate": round(page_faults / len(references) * 100, 2),
            "evictions": evictions,
            "trace": trace,
        }
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        frames = [
            {
                "frame": index,
                "pid": None if frame is None else frame.pid,
                "process": None if frame is None else self.processes.get(frame.pid).name,
                "page": None if frame is None else frame.page,
                "loaded_at": None if frame is None else frame.loaded_at,
                "last_used": None if frame is None else frame.last_used,
            }
            for index, frame in enumerate(self._frames)
        ]
        page_tables = [
            {
                "pid": pid,
                "process": self.processes.get(pid).name,
                "virtual_pages": pages,
                "resident_pages": [
                    {"page": frame.page, "frame": index}
                    for index, frame in enumerate(self._frames)
                    if frame is not None and frame.pid == pid
                ],
            }
            for pid, pages in sorted(self._address_spaces.items())
            if self.processes.get(pid).state != "TERMINATED"
        ]
        return {
            "memory": {
                "frame_count": self.frame_count,
                "page_size": self.page_size,
                "used_frames": sum(frame is not None for frame in self._frames),
                "free_frames": sum(frame is None for frame in self._frames),
                "frames": frames,
                "page_tables": page_tables,
                "last_run": self._last_run,
            }
        }

    def _active_process(self, pid: int) -> Process:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise ValueError("PID must be an integer")
        process = self.processes.get(pid)
        if process.state == "TERMINATED":
            raise ValueError(f"PID {pid} is already terminated")
        return process

    def _find_frame(self, pid: int, page: int) -> int | None:
        return next(
            (
                index
                for index, frame in enumerate(self._frames)
                if frame is not None and frame.pid == pid and frame.page == page
            ),
            None,
        )

    def _find_free_frame(self) -> int | None:
        return next((index for index, frame in enumerate(self._frames) if frame is None), None)

    def _select_victim(self, pid: int, algorithm: str, future: list[int]) -> int:
        candidates = [(index, frame) for index, frame in enumerate(self._frames) if frame is not None]
        if not candidates:
            raise ValueError("no physical frames available for this process")
        if algorithm == "fifo":
            return min(candidates, key=lambda item: (item[1].loaded_at, item[0]))[0]
        if algorithm == "lru":
            return min(candidates, key=lambda item: (item[1].last_used, item[0]))[0]

        def next_use(candidate: tuple[int, Frame]) -> tuple[int, int]:
            index, frame = candidate
            if frame.pid != pid:
                return len(future) + 1, index
            try:
                distance = future.index(frame.page)
            except ValueError:
                distance = len(future) + 1
            return distance, index

        return max(candidates, key=next_use)[0]

    def _clear_resident_pages(self, pid: int) -> None:
        for index, frame in enumerate(self._frames):
            if frame is not None and frame.pid == pid:
                self._frames[index] = None
        self._sync_process_frames(pid)

    def _sync_process_frames(self, pid: int) -> None:
        process = self.processes.get(pid)
        process.memory_pages = [
            index for index, frame in enumerate(self._frames)
            if frame is not None and frame.pid == pid
        ]

    def _sync_all_process_frames(self) -> None:
        for process in self.processes.list_processes():
            self._sync_process_frames(process.pid)
