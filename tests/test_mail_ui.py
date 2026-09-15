import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.database import Database
from src.recruitment_mail import CHINA
from src.ui.main_window import MainWindow
from src.ui.mail_panel import MailWorker, parse_manual_time


def sample_mail():
    return {
        "message_key": "fixture-mail", "folder": "INBOX", "subject": "仙工智能笔试通知",
        "sender": "招聘平台 <recruitment@example.com>", "body": "请及时完成笔试。",
        "kind": "笔试", "received": datetime.now(CHINA).isoformat(), "sent": "",
        "deadline": (datetime.now(CHINA) + timedelta(hours=2)).isoformat(), "starts_at": "",
        "estimated": 0, "evidence": "测试通知截止时间",
    }


class MailUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = Database(":memory:")
        self.job_id = self.db.save_job({"company": "仙工智能", "position": "开发", "status": "测评中"})
        with patch("src.ui.main_window.BrowserManager"), patch("src.ui.mail_panel.QSystemTrayIcon.isSystemTrayAvailable", return_value=False):
            self.window = MainWindow(self.db)
        self.panel = self.window.mail_panel
        self.panel.startup_timer.stop()
        self.config = {"account": "test@qq.com", "folders": ["INBOX"], "days": 30}
        self.panel.repo.set_setting("config", self.config)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.panel.worker:
            self.panel.worker.requestInterruption()
            self.panel.worker.wait(2000)
            self.app.processEvents()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_single_refresh_triggers_even_if_status_unchanged(self):
        with patch.object(self.panel, "sync") as sync:
            self.window.refresh_finished(self.job_id, "测评中")
            self.window.refresh_finished(self.job_id, "测评中")
            self.assertEqual(sync.call_count, 2)

    def test_batch_refresh_syncs_once_at_end(self):
        self.window.batch_active = True
        self.window.batch_total = 2
        with patch.object(self.panel, "sync") as sync:
            self.window.refresh_finished(self.job_id, "测评中")
            self.window.refresh_finished(self.job_id, "笔试中")
            sync.assert_not_called()
            self.window._start_next_batch_job()
            sync.assert_called_once()

    def test_completion_stages_do_not_trigger_sync(self):
        with patch.object(self.panel, "sync") as sync:
            self.window.refresh_finished(self.job_id, "笔试已完成")
            sync.assert_not_called()

    def test_reminder_is_deduplicated_and_completed_items_stop_reminding(self):
        self.panel.repo.ingest("test@qq.com", {"messages": [sample_mail()], "checkpoints": {}})
        with patch("src.ui.mail_panel.QMessageBox") as box:
            self.panel.check_due()
            self.panel.check_due()
            self.assertEqual(box.call_count, 1)
            mail = self.panel.repo.list_mail("test@qq.com")[0]
            self.panel.repo.update(mail["id"], state="done", reminder="")
            self.panel.check_due()
            self.assertEqual(box.call_count, 1)

    def test_tasks_can_complete_ignore_and_restore(self):
        self.panel.repo.ingest("test@qq.com", {"messages": [sample_mail()], "checkpoints": {}})
        self.panel.show_tasks()
        dialog = self.panel.tasks_page
        self.assertEqual(len(dialog.rows), 1)
        self.assertIn("仙工智能", dialog.details.toPlainText())
        dialog.set_state("done")
        self.assertEqual(len(dialog.rows), 0)
        dialog.show_closed.setChecked(True)
        self.assertEqual(len(dialog.rows), 1)
        dialog.set_state("pending")
        self.assertEqual(self.panel.repo.list_mail("test@qq.com")[0]["state"], "pending")
        dialog.set_state("ignored")
        self.assertEqual(self.panel.repo.list_mail("test@qq.com")[0]["state"], "ignored")

    def test_binding_saves_config_but_no_secret_in_database(self):
        self.panel.show_settings()
        result = {"config": {**self.config, "aliases": {"仙工智能": ["SEER"]}}, "binding": True,
                  "messages": [], "checkpoints": {}, "warnings": []}
        self.panel.settings_page.secret.setText("fake-secret")
        self.panel.completed(result)
        self.assertEqual(self.panel.settings_page.secret.text(), "")
        self.assertEqual(self.panel.repo.setting("aliases"), {"仙工智能": ["SEER"]})
        dump = "\n".join(self.db.connection.iterdump())
        self.assertNotIn("fake-secret", dump)
        self.panel.pending_sync = False

    def test_settings_validate_and_disconnect_deletes_credential(self):
        self.panel.show_settings()
        dialog = self.panel.settings_page
        dialog.account.setText("invalid@example.com")
        with patch.object(self.panel, "start_worker") as start:
            dialog.save()
            start.assert_not_called()
        vault = MagicMock()
        vault.get_password.return_value = "fake-secret"
        with patch("src.ui.mail_panel.credential_store", return_value=vault):
            dialog.disconnect()
        vault.delete_password.assert_called_once_with("job_tracker.qq_mail", "test@qq.com")
        self.assertEqual(self.panel.repo.setting("config"), {})

    def test_real_worker_thread_delivers_results_on_gui_thread(self):
        result = {"messages": [sample_mail()], "checkpoints": {"INBOX": {"uid": 1, "validity": "77"}}, "warnings": []}
        with patch("src.ui.mail_panel.credential_store") as vault, patch("src.ui.mail_panel.QQMailClient") as client, patch("src.ui.mail_panel.QMessageBox"):
            vault.return_value.get_password.return_value = "fake-secret"
            client.return_value.sync.return_value = result
            self.panel.sync()
            for _ in range(100):
                QTest.qWait(10)
                if not self.panel.is_busy():
                    break
            self.assertFalse(self.panel.is_busy())
            self.assertEqual(len(self.panel.repo.list_mail("test@qq.com")), 1)
            self.assertIn("同步完成", self.panel.status.text())

    def test_failed_binding_does_not_store_secret(self):
        worker = MailWorker(self.config, {}, secret="fake-secret", binding=True)
        errors = []
        worker.failed.connect(errors.append)
        with patch("src.ui.mail_panel.credential_store") as vault, patch("src.ui.mail_panel.QQMailClient") as client:
            client.return_value.sync.side_effect = OSError("connection failed")
            worker.run()
            vault.return_value.set_password.assert_not_called()
        self.assertTrue(errors)
        self.assertNotIn("fake-secret", errors[0])
        self.assertEqual(worker.secret, "")

    def test_manual_time_input(self):
        self.assertEqual(parse_manual_time("2026-09-12 18:00"), "2026-09-12T18:00:00+08:00")
        self.assertEqual(parse_manual_time(""), "")
        with self.assertRaises(ValueError):
            parse_manual_time("2026-02-30 18:00")

    def test_authorization_label_is_rejected_before_connecting(self):
        self.panel.show_settings()
        dialog = self.panel.settings_page
        for value in ("abcd", "授权码_abcd", "1234567890123456"):
            dialog.secret.setText(value)
            with patch.object(self.panel, "start_worker") as start:
                dialog.save()
                start.assert_not_called()
            self.assertIn("完整 16 位", dialog.info.text())
        dialog.secret.setText("abcd efgh ijkl mnop")
        with patch.object(self.panel, "start_worker", return_value=True) as start:
            dialog.save()
            self.assertEqual(start.call_args.kwargs["secret"], "abcdefghijklmnop")

    def test_mail_pages_switch_inside_main_window_and_preserve_jobs(self):
        self.window.show()
        original_table = self.window.table
        self.panel.show_tasks()
        self.assertIs(self.window.page_stack.currentWidget(), self.panel.tasks_page)
        self.assertFalse(self.panel.tasks_page.isWindow())
        self.assertIs(self.panel.tasks_page.window(), self.window)
        self.panel.show_settings()
        self.assertIs(self.window.page_stack.currentWidget(), self.panel.settings_page)
        self.assertFalse(self.panel.settings_page.isWindow())
        self.panel.settings_page.secret.setText("abcdefghijklmnop")
        self.panel.settings_page.show_secret.setChecked(True)
        self.panel.show_jobs()
        self.assertIs(self.window.page_stack.currentWidget(), original_table)
        self.assertEqual(self.panel.settings_page.secret.text(), "")
        self.assertFalse(self.panel.settings_page.show_secret.isChecked())
        self.assertEqual(self.window.table.item(0, 0).text(), "仙工智能")
        self.panel.show_tasks()
        self.panel.show_settings()
        self.assertEqual(self.window.page_stack.count(), 3)

    def test_inline_correction_survives_refresh_and_saves_without_dialog(self):
        self.panel.repo.ingest("test@qq.com", {"messages": [sample_mail()], "checkpoints": {}})
        self.panel.show_tasks()
        page = self.panel.tasks_page
        page.correct()
        page.correct_deadline.setText("2026-10-01 18:00")
        page.reload()
        self.assertEqual(page.correct_deadline.text(), "2026-10-01 18:00")
        self.assertIs(page.detail_stack.currentWidget(), page.correction)
        self.assertFalse(page.correction.isWindow())
        page.save_correction()
        self.assertIs(page.detail_stack.currentWidget(), page.details)
        self.assertEqual(self.panel.repo.list_mail("test@qq.com")[0]["deadline"], "2026-10-01T18:00:00+08:00")

    def test_task_search_and_empty_selection(self):
        self.panel.repo.ingest("test@qq.com", {"messages": [sample_mail()], "checkpoints": {}})
        self.panel.show_tasks()
        page = self.panel.tasks_page
        page.search.setText("不存在的通知")
        self.assertEqual(page.rows, [])
        self.assertTrue(all(not button.isEnabled() for button in page.action_buttons))
        page.search.clear()
        self.assertEqual(len(page.rows), 1)
        self.assertTrue(all(button.isEnabled() for button in page.action_buttons))


if __name__ == "__main__":
    unittest.main()
