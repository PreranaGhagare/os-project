"""Atomic JSON disk-image persistence for the simulated file system."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DiskImageError(Exception):
    """Disk-image read or write failure surfaced to the simulated kernel."""


class DiskImage:
    """Load and atomically save a single JSON representation of virtual disk."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> dict[str, Any]:
        """Read the image, reporting malformed JSON and operating-system errors."""
        try:
            with self.path.open("r", encoding="utf-8") as image_file:
                image = json.load(image_file)
        except (OSError, json.JSONDecodeError) as error:
            raise DiskImageError(f"could not read disk image {self.path}: {error}") from error
        if not isinstance(image, dict):
            raise DiskImageError(f"disk image {self.path} must contain a JSON object")
        return image

    def save(self, image: dict[str, Any]) -> None:
        """Write a complete image and replace the old file only after success."""
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary_path.open("w", encoding="utf-8", newline="\n") as image_file:
                json.dump(image, image_file, ensure_ascii=False, indent=2)
                image_file.write("\n")
            temporary_path.replace(self.path)
        except (OSError, TypeError, ValueError) as error:
            raise DiskImageError(f"could not save disk image {self.path}: {error}") from error
