"""Disk-head scheduling simulations over the virtual disk block range."""

from __future__ import annotations

from typing import Any


DISK_ALGORITHMS = {"fcfs", "sstf", "scan", "c-scan", "look", "c-look"}


class DiskScheduler:
    """Run deterministic request-ordering algorithms and count head movement."""

    def run(
        self,
        requests: list[int],
        *,
        head: int,
        disk_size: int,
        algorithm: str = "fcfs",
        direction: str = "right",
    ) -> dict[str, Any]:
        normalized_algorithm = self._normalize_algorithm(algorithm)
        if isinstance(disk_size, bool) or not isinstance(disk_size, int) or not 2 <= disk_size <= 10000:
            raise ValueError("disk size must be between 2 and 10000 tracks")
        if isinstance(head, bool) or not isinstance(head, int) or not 0 <= head < disk_size:
            raise ValueError(f"head position must be between 0 and {disk_size - 1}")
        if not isinstance(direction, str) or direction.lower() not in {"left", "right"}:
            raise ValueError("direction must be left or right")
        direction = direction.lower()
        if not isinstance(requests, list) or len(requests) > 100:
            raise ValueError("request queue must contain between 1 and 100 track numbers")
        if not requests:
            raise ValueError("request queue must not be empty")
        if any(
            isinstance(track, bool) or not isinstance(track, int) or not 0 <= track < disk_size
            for track in requests
        ):
            raise ValueError(f"each track request must be an integer from 0 to {disk_size - 1}")

        order, travel = self._schedule(requests, head, disk_size, normalized_algorithm, direction)
        position = head
        steps = []
        total_movement = 0
        for destination, kind in travel:
            movement = abs(destination - position)
            steps.append(
                {
                    "from": position,
                    "to": destination,
                    "movement": movement,
                    "kind": kind,
                }
            )
            total_movement += movement
            position = destination

        return {
            "algorithm": normalized_algorithm,
            "head": head,
            "disk_size": disk_size,
            "direction": direction,
            "requests": list(requests),
            "service_order": order,
            "path": [head, *(destination for destination, _ in travel)],
            "steps": steps,
            "total_movement": total_movement,
            "average_movement": round(total_movement / len(requests), 2),
            "request_count": len(requests),
        }

    @staticmethod
    def _normalize_algorithm(algorithm: str) -> str:
        if not isinstance(algorithm, str):
            raise ValueError("disk-scheduling algorithm must be text")
        normalized = algorithm.strip().lower().replace("_", "-")
        if normalized not in DISK_ALGORITHMS:
            raise ValueError(f"unknown disk-scheduling algorithm: {normalized}")
        return normalized

    @staticmethod
    def _schedule(
        requests: list[int],
        head: int,
        disk_size: int,
        algorithm: str,
        direction: str,
    ) -> tuple[list[int], list[tuple[int, str]]]:
        remaining = list(requests)
        order: list[int] = []
        travel: list[tuple[int, str]] = []

        if algorithm == "fcfs":
            order = remaining
        elif algorithm == "sstf":
            position = head
            while remaining:
                target = min(remaining, key=lambda track: (abs(track - position), track))
                order.append(target)
                remaining.remove(target)
                position = target
        else:
            lower_ascending = sorted(track for track in remaining if track < head)
            upper_ascending = sorted(track for track in remaining if track >= head)
            if direction == "right":
                near = upper_ascending
                scan_far = list(reversed(lower_ascending))
                circular_far = lower_ascending
            else:
                near = list(reversed(lower_ascending))
                scan_far = upper_ascending
                circular_far = list(reversed(upper_ascending))

            def serve(tracks: list[int]) -> None:
                for track in tracks:
                    order.append(track)
                    travel.append((track, "request"))

            if algorithm in {"scan", "c-scan"}:
                serve(near)
                far = scan_far if algorithm == "scan" else circular_far
                if far:
                    boundary = disk_size - 1 if direction == "right" else 0
                    current = travel[-1][0] if travel else head
                    if current != boundary:
                        travel.append((boundary, "boundary"))
                    if algorithm == "scan":
                        serve(far)
                    else:
                        wrap = 0 if direction == "right" else disk_size - 1
                        travel.append((wrap, "wrap"))
                        serve(far)
            elif algorithm == "look":
                serve(near)
                far = scan_far
                serve(far)
            else:
                serve(near)
                far = circular_far
                if far:
                    travel.append((far[0], "wrap"))
                    serve(far)

        if algorithm in {"fcfs", "sstf"}:
            travel.extend((track, "request") for track in order)
        return order, travel
