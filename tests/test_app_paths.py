import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app_paths import configure_browser_bundle, data_directory


class AppPathsTests(unittest.TestCase):
    def test_source_data_does_not_depend_on_launch_directory(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "frozen", False, create=True):
            self.assertEqual(data_directory(), Path(__file__).resolve().parent.parent / "data")

    def test_frozen_data_is_outside_exe_extraction_directory(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/Test/AppData/Local"}, clear=True), patch.object(sys, "frozen", True, create=True):
            self.assertEqual(data_directory(), Path("C:/Users/Test/AppData/Local/JobTracker"))

    def test_frozen_browser_uses_bundled_binaries(self):
        with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "old-cache"}), patch.object(sys, "frozen", True, create=True), patch.object(sys, "_MEIPASS", "C:/Temp/bundle", create=True):
            configure_browser_bundle()
            self.assertEqual(Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]), Path("C:/Temp/bundle/browsers"))


if __name__ == "__main__":
    unittest.main()
