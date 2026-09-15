"""Keep writable user data outside the temporary one-file application bundle."""
import os
import sys
from pathlib import Path


def data_directory() -> Path:
    override = os.environ.get("JOB_TRACKER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return local / "JobTracker"
    return Path(__file__).resolve().parent.parent / "data"


def configure_browser_bundle() -> None:
    if getattr(sys, "frozen", False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path(sys._MEIPASS) / "browsers")
