"""Offline checks runnable from the distributed EXE, using disposable data only."""
import json
import os
import tempfile
import traceback
from pathlib import Path


def run(report_path: str) -> int:
    report = {"ok": False, "checks": []}
    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PyQt6.QtWidgets import QApplication
        from playwright.sync_api import sync_playwright
        from src.database import Database
        from src.recruitment_mail import credential_store, assessment_kind
        from src.ui.main_window import MainWindow

        with tempfile.TemporaryDirectory(prefix="jobtracker_package_test_") as folder:
            os.environ["JOB_TRACKER_DATA_DIR"] = folder
            app = QApplication([])
            window = MainWindow(Database(Path(folder) / "jobs.db"))
            window.mail_panel.stop()
            assert window.table.rowCount() == 0
            window.mail_panel.show_tasks()
            window.mail_panel.show_settings()
            window.mail_panel.show_jobs()
            assert window.page_stack.count() == 3
            report["checks"].append("Qt pages and empty isolated database")
            assert type(credential_store()).__name__ == "WinVaultKeyring"
            report["checks"].append("Windows credential backend imports (no credentials read)")
            assert assessment_kind("测评邀请", "请在三天内完成测评") == "测评"
            report["checks"].append("Mail classification")
            with sync_playwright() as pw:
                for headless, args, label in (
                    (True, [], "Chromium headless shell"),
                    (False, ["--headless=new"], "Full Chromium binary in headless mode"),
                ):
                    browser = pw.chromium.launch(headless=headless, args=args)
                    page = browser.new_page()
                    page.set_content("<title>JobTracker smoke</title><p>offline</p>")
                    assert page.title() == "JobTracker smoke"
                    browser.close()
                    report["checks"].append(label)
            window.close()
            window.deleteLater()
            app.processEvents()
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
