"""Release configuration checks for persistent storage paths."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kernel.boot import Kernel


class ReleaseConfigurationTests(unittest.TestCase):
    def test_data_directory_environment_configures_image_and_journal_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LIBRAOS_DATA_DIR": directory}):
                kernel = Kernel()

            expected_image = Path(directory) / "disk.img.json"
            self.assertEqual(kernel.disk_image.path, expected_image)
            self.assertEqual(
                kernel.journal.path,
                Path(directory) / "disk.img.json.journal.jsonl",
            )
            asyncio.run(kernel.boot())
            self.assertTrue(expected_image.is_file())

    def test_explicit_disk_path_takes_precedence_over_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            explicit_image = Path(directory) / "explicit.img.json"
            with patch.dict(os.environ, {"LIBRAOS_DATA_DIR": str(Path(directory) / "data")}):
                kernel = Kernel(disk_path=explicit_image)

            self.assertEqual(kernel.disk_image.path, explicit_image)
