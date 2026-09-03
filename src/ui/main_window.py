
from __future__ import annotations

import logging
import random
from pathlib import Path
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
	QCompleter, QHBoxLayout, QLabel, QLineEdit, QPushButton,
	QHeaderView, QMenu, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.browser.manager import BrowserManager
from src.database import Database, now_text


COLUMNS = ["公司名称", "岗位", "工作地点", "查询URL", "平台", "状态", "更新时间", "操作"]
EDITABLE_COLUMNS = {0: "company", 1: "position", 2: "location", 3: "url"}
SKIP_QUERY_MARKERS = ("无法查询", "跳过查询", "无需查询")
TERMINAL_STATUS_MARKERS = ("流程终止", "已终止", "流程结束", "已结束", "已完成", "已淘汰", "淘汰", "已撤回", "已关闭", "未通过", "不合适", "感谢", "谢谢")
logger = logging.getLogger(__name__)


def should_skip_query(url: str) -> bool:
	return any(marker in url.strip() for marker in SKIP_QUERY_MARKERS)


def should_skip_job(job: dict) -> bool:
	return should_skip_query(job.get("url", "")) or should_skip_query(job.get("status", ""))


def should_skip_batch_job(job: dict) -> bool:
	if should_skip_job(job):
		return True
	status = job.get("status", "").strip()
	return any(marker in status for marker in TERMINAL_STATUS_MARKERS)


class RefreshWorker(QObject):
	finished = pyqtSignal(int, str)
	failed = pyqtSignal(int, str)
	message = pyqtSignal(str)

	def __init__(self, job: dict, manager: BrowserManager) -> None:
		super().__init__()
		self.job = job
		self.manager = manager

	@pyqtSlot()
	def run(self) -> None:
		logger.info("开始刷新: job_id=%s company=%s url=%s", self.job["id"], self.job["company"], self.job["url"])
		if not self.job["company"]:
			logger.warning("刷新跳过: job_id=%s 公司名称为空", self.job["id"])
			self.failed.emit(self.job["id"], "公司名称为空")
			return
		if not self.job["url"]:
			logger.warning("刷新跳过: job_id=%s 查询URL为空", self.job["id"])
			self.failed.emit(self.job["id"], "查询URL为空")
			return
		try:
			status = self.manager.fetch_status(self.job["url"], self.job["company"], self.message.emit)
			logger.info("刷新完成: job_id=%s status=%s", self.job["id"], status)
			self.finished.emit(self.job["id"], status)
		except Exception as error:
			logger.exception("刷新异常: job_id=%s company=%s", self.job["id"], self.job["company"])
			self.failed.emit(self.job["id"], str(error))


class ViewBrowserWorker(QObject):
	finished = pyqtSignal(int)
	failed = pyqtSignal(int, str)
	message = pyqtSignal(str)

	def __init__(self, job: dict, manager: BrowserManager) -> None:
		super().__init__()
		self.job = job
		self.manager = manager

	@pyqtSlot()
	def run(self) -> None:
		try:
			self.manager.open_for_view(self.job["url"], self.job["company"], self.message.emit)
			self.finished.emit(self.job["id"])
		except Exception as error:
			logger.exception("打开网页失败: job_id=%s company=%s", self.job["id"], self.job["company"])
			self.failed.emit(self.job["id"], str(error))


class MainWindow(QWidget):
	def __init__(self, database: Database | None = None) -> None:
		super().__init__()
		self.database = database or Database(Path("data/jobs.db"))
		self.manager = BrowserManager(Path("data/profiles"))
		self.threads: list[QThread] = []
		self.workers: list[RefreshWorker] = []
		self.batch_total = 0
		self.batch_done = 0
		self.batch_queue: list[dict] = []
		self.batch_active = False
		self.loading = False
		self.url_double_clicked = False
		self.color_maps = {"location": {}, "platform": {}, "status": {}}
		self.color_palettes = {
			"location": [("#e7f3ff", "#28628f"), ("#e9f7ef", "#28734a"), ("#fff3df", "#94651e"), ("#f2eaff", "#6945a0"), ("#ffe9ef", "#9b4d67"), ("#e4f4f4", "#286b73"), ("#fff0e8", "#9a5639"), ("#edf3ff", "#42639a"), ("#f4edff", "#7451a3"), ("#eff8e5", "#4c762c"), ("#fff4e9", "#9b6631"), ("#e8f0f4", "#4b6575")],
			"platform": [("#e6f4f1", "#28766e"), ("#eaf0ff", "#3d5f9e"), ("#fff0e5", "#9a5b31"), ("#f1ebff", "#694e9b"), ("#edf2f7", "#536579"), ("#e4f4f4", "#286b73"), ("#fff3df", "#96611e"), ("#edf3ff", "#42639a")],
			"status": [("#e8f5ed", "#287348"), ("#e7f1ff", "#2b6098"), ("#fff2df", "#96611e"), ("#f2eaff", "#6945a0"), ("#ffe9ee", "#a04c65"), ("#e8f4f5", "#286b73"), ("#eff8e5", "#4c762c"), ("#fff0e8", "#9a5639"), ("#edf3ff", "#42639a"), ("#f4edff", "#7451a3"), ("#e8f0f4", "#4b6575"), ("#fff4e9", "#9b6631")],
		}
		self.setWindowTitle("求职进度追踪")
		self.resize(1180, 650)
		self.setMinimumSize(760, 420)
		self._build_ui()
		self._load_jobs()

	def _build_ui(self) -> None:
		self.setStyleSheet("""
			QWidget {
				font-family: "Microsoft YaHei UI";
				font-size: 14px;
				color: #243247;
				background: #f4f7fb;
			}
			QLabel { background: transparent; }
			QTableWidget {
				background: #ffffff;
				alternate-background-color: #f8fafc;
				border: 1px solid #e3eaf3;
				border-radius: 10px;
				gridline-color: #edf1f6;
				selection-background-color: #e6f2f4;
				selection-color: #173b45;
				outline: none;
			}
			QHeaderView::section {
				background: #f7f9fc;
				color: #718096;
				font-size: 12px;
				font-weight: 600;
				padding: 10px 8px;
				border: 0;
				border-bottom: 1px solid #e3eaf3;
			}
			QTableWidget::item { padding: 6px; border: 0; }
			QPushButton {
				min-height: 32px;
				padding: 0 15px;
				border: 1px solid #c9dce1;
				border-radius: 8px;
				background: #eaf5f6;
				color: #23616b;
				font-weight: 600;
			}
			QPushButton:hover { background: #d9eef0; border-color: #a8cbd0; }
			QPushButton:pressed { background: #c9e5e8; }
			QPushButton:disabled { background: #edf1f5; color: #a0aab8; border-color: #e1e6ec; }
			QPushButton#primaryButton { background: #4f9da6; border-color: #4f9da6; color: #ffffff; }
			QPushButton#primaryButton:hover { background: #438c95; border-color: #438c95; }
			QPushButton#primaryButton:pressed { background: #397b83; border-color: #397b83; }
			QPushButton#secondaryButton { background: #ffffff; border-color: #d7e1ea; color: #526579; }
			QPushButton#secondaryButton:hover { background: #f7fafc; border-color: #b9cbd9; }
			QLineEdit {
				padding: 7px 8px;
				border: 1px solid transparent;
				border-radius: 6px;
				background: transparent;
				selection-background-color: #cdebed;
			}
			QLineEdit:hover { background: #f1f7f8; border-color: #d8e8eb; }
			QLineEdit:focus { background: #ffffff; border-color: #8fc4ca; }
			QCompleter QAbstractItemView {
				background: #ffffff;
				border: 1px solid #dce6ee;
				selection-background-color: #e6f2f4;
				selection-color: #23616b;
			}
			QScrollBar:vertical {
				width: 9px;
				margin: 3px 2px 3px 0;
				background: transparent;
			}
			QScrollBar::handle:vertical {
				min-height: 42px;
				border-radius: 4px;
				background: #cbd7e3;
			}
			QScrollBar::handle:vertical:hover { background: #aebfce; }
			QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
			QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
				background: transparent;
				height: 0;
			}
			QScrollBar:horizontal {
				height: 9px;
				margin: 0 3px 2px 3px;
				background: transparent;
			}
			QScrollBar::handle:horizontal {
				min-width: 42px;
				border-radius: 4px;
				background: #cbd7e3;
			}
			QScrollBar::handle:horizontal:hover { background: #aebfce; }
			QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
			QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
				background: transparent;
				width: 0;
			}
		""")
		layout = QVBoxLayout(self)
		layout.setContentsMargins(24, 20, 24, 24)
		layout.setSpacing(16)
		toolbar = QHBoxLayout()
		toolbar.setSpacing(10)
		title = QLabel("求职进度")
		title.setStyleSheet("font-size: 22px; font-weight: 700; color: #1f3448;")
		toolbar.addWidget(title)
		toolbar.addStretch()
		self.progress = QLabel("就绪")
		self.progress.setStyleSheet("color: #718096; padding: 0 8px;")
		toolbar.addWidget(self.progress)
		self.count_label = QLabel("共 0 条记录")
		self.count_label.setStyleSheet("color: #718096; padding: 0 8px;")
		toolbar.addWidget(self.count_label)
		add_button = QPushButton("＋ 添加记录")
		add_button.setObjectName("secondaryButton")
		add_button.clicked.connect(self.add_row)
		toolbar.addWidget(add_button)
		self.update_all_button = QPushButton("↻ 更新全部")
		self.update_all_button.setObjectName("primaryButton")
		self.update_all_button.clicked.connect(self.update_all)
		toolbar.addWidget(self.update_all_button)
		layout.addLayout(toolbar)

		self.table = QTableWidget(0, len(COLUMNS))
		self.table.setHorizontalHeaderLabels(COLUMNS)
		self.table.setAlternatingRowColors(True)
		self.table.setSortingEnabled(False)
		self.table.cellChanged.connect(self.save_cell)
		self.table.cellClicked.connect(self.open_url_from_cell)
		self.table.cellDoubleClicked.connect(self.edit_url_cell)
		self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
		self.table.customContextMenuRequested.connect(self.show_context_menu)
		header = self.table.horizontalHeader()
		header.setStretchLastSection(False)
		header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
		header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
		header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
		header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
		header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
		header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
		header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
		header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
		self.table.setColumnWidth(0, 130)
		self.table.setColumnWidth(2, 112)
		self.table.setColumnWidth(3, 220)
		self.table.setColumnWidth(4, 76)
		self.table.setColumnWidth(7, 82)
		self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
		self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
		self.table.verticalHeader().setVisible(False)
		self.table.setShowGrid(False)
		layout.addWidget(self.table)
		self._update_count()

	def _load_jobs(self) -> None:
		for job in self.database.list_jobs():
			self._append_job(job)
		self._update_count()

	def _update_count(self) -> None:
		count = sum(1 for job in self.database.list_jobs() if job["company"].strip())
		self.count_label.setText(f"共 {count} 条记录")

	def _reload_jobs(self) -> None:
		self.loading = True
		try:
			self.table.blockSignals(True)
			self.table.setRowCount(0)
			for job in self.database.list_jobs():
				self._append_job(job)
			self._update_count()
		finally:
			self.table.blockSignals(False)
			self.loading = False

	def _append_job(self, job: dict) -> int:
		row = self.table.rowCount()
		self.table.insertRow(row)
		self.table.setRowHeight(row, 42)
		for column, key in EDITABLE_COLUMNS.items():
			if column == 2:
				continue
			item = QTableWidgetItem(job.get(key, ""))
			item.setData(Qt.ItemDataRole.UserRole, job["id"])
			if column == 3:
				full_url = job.get(key, "")
				item.setText(self._short_url(full_url))
				item.setData(Qt.ItemDataRole.UserRole + 1, full_url)
				item.setForeground(QBrush(QColor("#3576a8")))
				item.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.Normal, True))
				item.setToolTip(full_url)
			self.table.setItem(row, column, item)
		for column, value in ((6, job.get("updated_at", "")),):
			item = QTableWidgetItem(value)
			item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
			self.table.setItem(row, column, item)
		self._install_pill(row, 4, job.get("platform", "其他"), "platform")
		self._install_status_editor(row, job.get("status", "未查询"))
		button = QPushButton("刷新")
		button.clicked.connect(lambda _checked=False, job_id=job["id"]: self.refresh_job(job_id))
		self.table.setCellWidget(row, 7, button)
		self._install_location_editor(row, job.get("location", ""))
		self._update_count()
		return row

	def _color_for(self, category: str, value: str) -> tuple[str, str]:
		value = value.strip() or "未填写"
		mapping = self.color_maps[category]
		if value not in mapping:
			used = set(mapping.values())
			available = [color for color in self.color_palettes[category] if color not in used]
			mapping[value] = random.choice(available or self.color_palettes[category])
		return mapping[value]

	@staticmethod
	def _short_url(url: str) -> str:
		parsed = urlparse(url)
		if not parsed.netloc:
			return url
		return f"{parsed.netloc}/..."

	def _install_pill(self, row: int, column: int, value: str, category: str) -> QLabel:
		background, foreground = self._color_for(category, value)
		label = QLabel(value)
		label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		label.setStyleSheet(
			f"padding: 5px 7px; border-radius: 8px; background: {background}; color: {foreground}; font-weight: 600;"
		)
		self.table.setCellWidget(row, column, label)
		return label

	def _install_status_editor(self, row: int, status: str) -> QLineEdit:
		background, foreground = self._color_for("status", status)
		editor = QLineEdit(status)
		editor.setFrame(False)
		editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
		editor.setStyleSheet(
		f"QLineEdit {{ padding: 5px 10px; border: 1px solid transparent; border-radius: 8px; background: {background}; color: {foreground}; font-weight: 600; }}"
		f"QLineEdit:focus {{ border: 1px solid {foreground}; background: #ffffff; }}"
		)
		editor.editingFinished.connect(lambda: self.save_status(row, editor))
		self.table.setCellWidget(row, 5, editor)
		return editor

	def _install_location_editor(self, row: int, location: str) -> None:
		background, foreground = self._color_for("location", location)
		editor = QLineEdit(location)
		editor.setFrame(False)
		editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
		editor.setStyleSheet(
		f"QLineEdit {{ padding: 5px 10px; border: 1px solid transparent; border-radius: 8px; background: {background}; color: {foreground}; font-weight: 600; }}"
		f"QLineEdit:focus {{ border: 1px solid {foreground}; background: #ffffff; }}"
		)
		completer = QCompleter(self.database.locations(), editor)
		completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
		editor.setCompleter(completer)
		editor.editingFinished.connect(lambda: self.save_location(row, editor))
		self.table.setCellWidget(row, 2, editor)

	def add_row(self) -> None:
		job_id = self.database.save_job({})
		self._append_job(self.database.get_job(job_id) or {"id": job_id})
		self.table.scrollToBottom()
		self.table.editItem(self.table.item(self.table.rowCount() - 1, 0))

	def show_context_menu(self, position) -> None:
		row = self.table.rowAt(position.y())
		if row < 0 or not self.table.item(row, 0):
			return
		menu = QMenu(self)
		delete_action = menu.addAction("删除记录")
		if menu.exec(self.table.viewport().mapToGlobal(position)) == delete_action:
			job_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
			company = self.table.item(row, 0).text()
			answer = QMessageBox.question(self, "确认删除", f"确定删除“{company or '未命名记录'}”吗？")
			if answer == QMessageBox.StandardButton.Yes:
				self.database.delete_job(job_id)
				self._reload_jobs()

	def _show_status_change(self, job_id: int, old_status: str, new_status: str) -> None:
		if old_status == new_status:
			return
		self.progress.setText(f"状态发生变化：{old_status} → {new_status}")
		self.progress.setStyleSheet("color: #c53030; font-weight: 700; padding: 0 8px;")
		row = self.row_for_job(job_id)
		if row >= 0:
			status_editor = self.table.cellWidget(row, 5)
			if isinstance(status_editor, QLineEdit):
				status_editor.setStyleSheet(
					"QLineEdit { padding: 5px 10px; border-radius: 8px; background: #ffe5e8; color: #a33b50; font-weight: 700; }"
				)

	def row_for_job(self, job_id: int) -> int:
		for row in range(self.table.rowCount()):
			item = self.table.item(row, 0)
			if item and item.data(Qt.ItemDataRole.UserRole) == job_id:
				return row
		return -1

	def save_cell(self, row: int, column: int) -> None:
		if self.loading:
			return
		company_item = self.table.item(row, 0)
		if company_item is None:
			return
		job_id = company_item.data(Qt.ItemDataRole.UserRole)
		if job_id is None:
			return
		if column not in EDITABLE_COLUMNS:
			return
		platform_label = self.table.cellWidget(row, 4)
		if platform_label is None:
			return
		values = {}
		for col, key in EDITABLE_COLUMNS.items():
			if col == 2:
				editor = self.table.cellWidget(row, 2)
				values[key] = editor.text() if isinstance(editor, QLineEdit) else ""
			else:
				item = self.table.item(row, col)
				values[key] = item.text() if item else ""
		values["id"] = job_id
		saved_id = self.database.save_job(values)
		if saved_id != job_id:
			logger.warning("检测到重复记录，已合并: old_job_id=%s kept_job_id=%s", job_id, saved_id)
			self._reload_jobs()
			return
		job = self.database.get_job(job_id)
		if job:
			self._install_pill(row, 4, job["platform"], "platform")
			if column == 3:
				url_item = self.table.item(row, 3)
				if url_item:
					full_url = job["url"]
					self.table.blockSignals(True)
					try:
						url_item.setData(Qt.ItemDataRole.UserRole + 1, full_url)
						url_item.setText(self._short_url(full_url))
						url_item.setToolTip(full_url)
					finally:
						self.table.blockSignals(False)
			self._update_count()

	def save_status(self, row: int, editor: QLineEdit) -> None:
		item = self.table.item(row, 0)
		if not item or self.loading:
			return
		job_id = item.data(Qt.ItemDataRole.UserRole)
		status = editor.text().strip() or "未查询"
		self.database.update_status(job_id, status)
		self._set_status_style(editor, status)
		updated_item = self.table.item(row, 6)
		job = self.database.get_job(job_id)
		if updated_item and job:
			updated_item.setText(job["updated_at"])

	def save_location(self, row: int, editor: QLineEdit) -> None:
		item = self.table.item(row, 0)
		if not item:
			return
		self.database.save_job({"id": item.data(Qt.ItemDataRole.UserRole), "location": editor.text()})
		self._set_pill_style(editor, "location", editor.text())

	def open_url_from_cell(self, row: int, column: int) -> None:
		if column != 3 or self.batch_active:
			return
		url_item = self.table.item(row, column)
		company_item = self.table.item(row, 0)
		if not url_item or not company_item:
			return
		url = url_item.data(Qt.ItemDataRole.UserRole + 1) or url_item.text()
		if not str(url).strip().lower().startswith(("http://", "https://")):
			return
		QTimer.singleShot(250, lambda: self._open_url_if_single(row, url))

	def _open_url_if_single(self, row: int, url: str) -> None:
		if self.url_double_clicked:
			self.url_double_clicked = False
			return
		company_item = self.table.item(row, 0)
		if not company_item:
			return
		job_id = company_item.data(Qt.ItemDataRole.UserRole)
		job = self.database.get_job(job_id)
		if not job:
			return
		logger.info("收到打开网页请求: job_id=%s company=%s", job_id, job["company"])
		thread = QThread(self)
		worker = ViewBrowserWorker(job, self.manager)
		worker.moveToThread(thread)
		thread.started.connect(worker.run)
		worker.message.connect(self.progress.setText)
		worker.failed.connect(lambda _job_id, reason: self.progress.setText(f"打开网页失败：{reason}"))
		worker.finished.connect(thread.quit)
		worker.failed.connect(thread.quit)
		thread.finished.connect(worker.deleteLater)
		thread.finished.connect(thread.deleteLater)
		thread.finished.connect(lambda: self._forget_worker(thread, worker))
		self.threads.append(thread)
		self.workers.append(worker)
		thread.start()

	def edit_url_cell(self, row: int, column: int) -> None:
		if column != 3:
			return
		self.url_double_clicked = True
		item = self.table.item(row, column)
		if not item:
			return
		full_url = item.data(Qt.ItemDataRole.UserRole + 1) or item.text()
		self.table.blockSignals(True)
		item.setText(str(full_url))
		self.table.blockSignals(False)
		self.table.editItem(item)

	def _set_pill_style(self, widget: QLineEdit, category: str, value: str) -> None:
		background, foreground = self._color_for(category, value)
		widget.setStyleSheet(
			f"QLineEdit {{ padding: 5px 10px; border: 1px solid transparent; border-radius: 8px; background: {background}; color: {foreground}; font-weight: 600; }}"
			f"QLineEdit:focus {{ border: 1px solid {foreground}; background: #ffffff; }}"
		)

	def _set_status_style(self, editor: QLineEdit, status: str) -> None:
		self._set_pill_style(editor, "status", status)

	def refresh_job(self, job_id: int) -> None:
		logger.info("收到单条刷新请求: job_id=%s", job_id)
		if self.batch_active:
			logger.warning("批量刷新进行中，忽略单条刷新: job_id=%s", job_id)
			self.progress.setText("批量更新进行中，请等待当前任务完成")
			return
		job = self.database.get_job(job_id)
		if job:
			logger.info("读取任务: job_id=%s company=%s platform=%s", job_id, job["company"], job["platform"])
			if should_skip_job(job):
				logger.info("刷新跳过: job_id=%s 查询栏标记为无需查询", job_id)
				self.progress.setText("已跳过：该记录标记为无需查询")
				return
			self.batch_total = 0
			self.batch_done = 0
			self._start_refresh(job)
		else:
			logger.error("刷新失败: 找不到任务 job_id=%s", job_id)

	def _start_refresh(self, job: dict) -> None:
		profile = str(self.manager.profile_for(job["company"]))
		self.database.save_job({"id": job["id"], "profile": profile})
		thread = QThread(self)
		worker = RefreshWorker(job, self.manager)
		worker.moveToThread(thread)
		thread.started.connect(worker.run)
		worker.finished.connect(self.refresh_finished)
		worker.failed.connect(self.refresh_failed)
		worker.message.connect(self.progress.setText)
		worker.finished.connect(thread.quit)
		worker.failed.connect(thread.quit)
		thread.finished.connect(worker.deleteLater)
		thread.finished.connect(thread.deleteLater)
		thread.finished.connect(lambda: self._thread_finished(thread, worker))
		self.threads.append(thread)
		self.workers.append(worker)
		thread.start()

	def _forget_worker(self, thread: QThread, worker: RefreshWorker) -> None:
		if thread in self.threads:
			self.threads.remove(thread)
		if worker in self.workers:
			self.workers.remove(worker)

	def _thread_finished(self, thread: QThread, worker: RefreshWorker) -> None:
		self._forget_worker(thread, worker)
		if self.batch_active:
			self._start_next_batch_job()

	def refresh_finished(self, job_id: int, status: str) -> None:
		self.batch_done += 1
		old_job = self.database.get_job(job_id)
		old_status = old_job["status"] if old_job else "未查询"
		self.database.update_status(job_id, status, now_text())
		row = self.row_for_job(job_id)
		if row >= 0:
			self.table.blockSignals(True)
			try:
				status_editor = self.table.cellWidget(row, 5)
				if isinstance(status_editor, QLineEdit):
					status_editor.setText(status)
					self._set_status_style(status_editor, status)
				self.table.item(row, 6).setText(now_text())
			finally:
				self.table.blockSignals(False)
		if self.batch_total:
			self.progress.setText(f"正在更新 {self.batch_done}/{self.batch_total}：{status}")
			if self.batch_done >= self.batch_total:
				self.progress.setText(f"更新完成 {self.batch_done}/{self.batch_total}")
		else:
			self.progress.setText(f"已更新：{status}")
		self._show_status_change(job_id, old_status, status)

	def refresh_failed(self, job_id: int, reason: str) -> None:
		self.batch_done += 1
		self.progress.setText(f"更新失败（{job_id}）：{reason} ({self.batch_done}/{self.batch_total})")

	def update_all(self) -> None:
		if self.batch_active:
			logger.warning("批量刷新已在进行中，忽略重复点击")
			return
		all_jobs = self.database.list_jobs()
		jobs = [job for job in all_jobs if job["url"] and not should_skip_batch_job(job)]
		skipped_count = len(all_jobs) - len(jobs)
		logger.info("收到批量刷新请求: total=%s", len(jobs))
		logger.info("批量刷新跳过: count=%s（已标记或已是终态）", skipped_count)
		self.batch_queue = jobs
		self.batch_active = bool(jobs)
		self.batch_total = len(jobs)
		self.batch_done = 0
		self.progress.setText(f"正在更新 0/{self.batch_total}")
		if self.batch_active:
			self._start_next_batch_job()
		else:
			self.progress.setText("没有需要更新的记录")

	def _start_next_batch_job(self) -> None:
		if not self.batch_queue:
			self.batch_active = False
			self.progress.setText(f"更新完成 {self.batch_done}/{self.batch_total}")
			logger.info("批量刷新完成: total=%s", self.batch_total)
			return
		job = self.batch_queue.pop(0)
		logger.info("批量刷新进度: %s/%s company=%s", self.batch_done + 1, self.batch_total, job["company"])
		self._start_refresh(job)

	def closeEvent(self, event) -> None:
		self.database.close()
		event.accept()
