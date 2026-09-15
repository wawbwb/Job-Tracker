import os
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit

from src.database import Database
from src.ui.main_window import MainWindow


class UrlUiTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.app = QApplication.instance() or QApplication([])

	def setUp(self):
		self.database = Database(":memory:")
		self.url = "https://seer-group.jobs.feishu.cn/apply/record?lang=zh-CN#applications"
		self.job_id = self.database.save_job({
			"company": "测试公司", "position": "软件工程师", "location": "上海", "url": self.url,
		})
		with patch("src.ui.main_window.BrowserManager", autospec=True):
			self.window = MainWindow(self.database)
		self.window.show()
		self.window.activateWindow()
		self.app.processEvents()
		self.addCleanup(self.close_window)

	def close_window(self):
		self.window._cancel_url_open()
		self.window.close()
		self.window.deleteLater()
		self.app.processEvents()

	def assert_url_preserved(self, expected=None):
		expected = self.url if expected is None else expected
		self.assertEqual(self.database.get_job(self.job_id)["url"], expected)
		item = self.window.table.item(0, 3)
		self.assertEqual(item.data(Qt.ItemDataRole.UserRole + 1), expected)
		self.assertEqual(item.toolTip(), expected)
		self.assertEqual(item.text(), MainWindow._short_url(expected))

	def begin_keyboard_edit(self):
		self.window.table.setCurrentCell(0, 3)
		self.window.table.setFocus()
		QTest.keyClick(self.window.table, Qt.Key.Key_F2)
		self.app.processEvents()
		editor = self.app.focusWidget()
		self.assertIsInstance(editor, QLineEdit)
		self.assertEqual(editor.text(), self.url)
		return editor

	def test_editing_other_fields_preserves_full_url(self):
		self.window.table.item(0, 0).setText("测试公司新名称")
		self.assert_url_preserved()
		self.window.table.item(0, 1).setText("后端工程师")
		self.assert_url_preserved()
		location = self.window.table.cellWidget(0, 2)
		location.setText("杭州")
		location.editingFinished.emit()
		self.assert_url_preserved()
		self.assertEqual(self.database.get_job(self.job_id)["location"], "杭州")

	def test_cancel_keyboard_edit_preserves_url_and_abbreviated_display(self):
		editor = self.begin_keyboard_edit()
		editor.setText("https://example.com/unsaved")
		QTest.keyClick(editor, Qt.Key.Key_Escape)
		self.app.processEvents()
		self.assert_url_preserved()
		self.window.table.item(0, 1).setText("新岗位")
		self.assert_url_preserved()

	def test_confirm_keyboard_edit_saves_new_full_url(self):
		editor = self.begin_keyboard_edit()
		new_url = "https://seer-group.jobs.feishu.cn/apply/another?lang=en#record"
		editor.setText(new_url)
		QTest.keyClick(editor, Qt.Key.Key_Return)
		self.app.processEvents()
		self.assert_url_preserved(new_url)
		self.window.table.item(0, 0).setText("另一个名称")
		self.assert_url_preserved(new_url)

	def test_double_click_edits_full_url_and_cancels_open(self):
		item = self.window.table.item(0, 3)
		point = self.window.table.visualItemRect(item).center()
		QTest.mouseClick(self.window.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
		QTest.mouseDClick(self.window.table.viewport(), Qt.MouseButton.LeftButton, pos=point)
		self.app.processEvents()
		editor = self.app.focusWidget()
		self.assertIsInstance(editor, QLineEdit)
		self.assertEqual(editor.text(), self.url)
		self.assertFalse(self.window.url_open_timer.isActive())
		self.assertIsNone(self.window.pending_url_job_id)
		QTest.keyClick(editor, Qt.Key.Key_Escape)
		self.assert_url_preserved()

	def test_keyboard_edit_cancels_pending_single_click(self):
		self.window.open_url_from_cell(0, 3)
		self.assertTrue(self.window.url_open_timer.isActive())
		editor = self.begin_keyboard_edit()
		self.assertFalse(self.window.url_open_timer.isActive())
		QTest.keyClick(editor, Qt.Key.Key_Escape)

	def test_display_population_does_not_write_to_database(self):
		with patch.object(self.database, "save_job", wraps=self.database.save_job) as save:
			self.window._reload_jobs()
			save.assert_not_called()
		self.assert_url_preserved()

	def test_multiple_links_on_same_domain_remain_distinct(self):
		other_id = self.database.save_job({
			"company": "测试公司", "url": "https://seer-group.jobs.feishu.cn/apply/other",
		})
		self.window._reload_jobs()
		self.window.table.item(0, 1).setText("新岗位一")
		self.window.table.item(1, 1).setText("新岗位二")
		self.assert_url_preserved()
		self.assertEqual(len(self.database.list_jobs()), 2)
		self.assertEqual(self.database.get_job(other_id)["url"], "https://seer-group.jobs.feishu.cn/apply/other")

	def test_links_without_scheme_can_be_opened_and_skip_markers_are_ignored(self):
		self.window.table.item(0, 3).setText("seer-group.jobs.feishu.cn/apply/record")
		self.window.open_url_from_cell(0, 3)
		self.assertEqual(self.window.pending_url_job_id, self.job_id)
		self.window._cancel_url_open()
		self.window.table.item(0, 3).setText("无需查询")
		self.window.open_url_from_cell(0, 3)
		self.assertFalse(self.window.url_open_timer.isActive())


if __name__ == "__main__":
	unittest.main()
