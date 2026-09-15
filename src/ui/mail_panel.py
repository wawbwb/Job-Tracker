"""QQ mailbox settings, background synchronization and local recruitment reminders."""
from datetime import datetime

from PyQt6.QtCore import QSignalBlocker, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle, QSystemTrayIcon,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.mail_repository import MailRepository
from src.recruitment_mail import CHINA, SERVICE, QQMailClient, credential_store, mail_stage, reminder_key, validate_account, validate_authorization_code


class MailWorker(QThread):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, config, checkpoints, parent=None, secret="", binding=False):
        super().__init__(parent)
        self.config = dict(config)
        self.checkpoints = checkpoints
        self.secret = secret
        self.binding = binding

    def run(self):
        stage = "credentials"
        try:
            vault = credential_store()
            secret = self.secret or vault.get_password(SERVICE, self.config["account"])
            if not secret:
                raise ValueError("未保存授权码，请在邮箱设置中重新绑定")
            stage = "connection"
            result = QQMailClient().sync(
                self.config["account"], secret, self.config["folders"], self.checkpoints,
                days=self.config["days"], cancelled=self.isInterruptionRequested, test_only=self.binding,
            )
            if self.isInterruptionRequested():
                return
            if self.binding:
                stage = "save"
                vault.set_password(SERVICE, self.config["account"], secret)
            self.succeeded.emit({**result, "config": self.config, "binding": self.binding})
        except (ValueError, RuntimeError) as error:
            self.failed.emit(str(error))
        except Exception:
            # IMAP/server errors can include account data; never log credentials or raw replies.
            messages = {
                "credentials": "无法读取系统凭据库，请检查 Windows 凭据管理器或重新安装 keyring 依赖",
                "connection": "邮箱网络连接或协议通信失败，请检查网络、代理及 imap.qq.com:993 是否可访问",
                "save": "邮箱连接成功，但授权码未能保存到系统凭据库，请检查系统凭据管理器后重试",
            }
            self.failed.emit(messages[stage])
        finally:
            self.secret = ""


MAIL_PAGE_STYLE = """
    QFrame[mailCard="true"] { background: #ffffff; border: 1px solid #e1e8ef; border-radius: 12px; }
    QLabel { background: transparent; border: none; }
    QLabel[role="heading"] { color: #243d50; font-size: 17px; font-weight: 700; }
    QLabel[role="muted"] { color: #7a8b9d; font-size: 12px; }
    QLabel[role="metric"] { color: #23616b; font-size: 25px; font-weight: 700; }
    QLabel[role="note"] { background: #f0f7f8; color: #507680; border-radius: 8px; padding: 10px 12px; font-size: 12px; }
    QLineEdit, QSpinBox, QComboBox { background: #f9fbfd; border: 1px solid #dce5ed; border-radius: 7px;
        padding: 8px 10px; color: #304b60; min-height: 22px; }
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus { background: #ffffff; border-color: #79b6bf; }
    QPlainTextEdit { background: #f9fbfd; border: 1px solid #dce5ed; border-radius: 8px; padding: 10px; color: #405970; }
    QPlainTextEdit#mailBody { background: #ffffff; border: none; padding: 0; font-size: 13px; }
    QCheckBox { background: transparent; color: #687d8f; font-size: 12px; spacing: 7px; }
    QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #b7cad5; border-radius: 4px; background: white; }
    QCheckBox::indicator:checked { background: #4f9da6; border-color: #4f9da6; }
    QPushButton#mailPrimary { background: #4f9da6; border-color: #4f9da6; color: white; }
    QPushButton#mailPrimary:hover { background: #438c95; }
    QPushButton#mailDanger { background: white; color: #ad6671; border-color: #ecd8dc; }
    QPushButton:disabled { background: #edf1f5; color: #9aa9b7; border-color: #e1e6ec; }
    QScrollArea { background: transparent; border: none; }
    QSplitter::handle { background: transparent; width: 16px; height: 12px; }
    QTableWidget { border: 1px solid #e1e8ef; border-radius: 12px; background: white; alternate-background-color: #fafcfd; }
    QTableWidget::item { padding: 8px; border-bottom: 1px solid #f0f4f7; }
    QTableWidget::item:selected { background: #eaf5f6; color: #23616b; }
"""


def caption(text, role="muted"):
    label = QLabel(text)
    label.setProperty("role", role)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def card():
    frame = QFrame()
    frame.setProperty("mailCard", True)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


class MailSettingsPage(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setStyleSheet(MAIL_PAGE_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        body.setSpacing(16)
        body.addWidget(caption("绑定 QQ 邮箱，自动整理测评和笔试通知。"))
        columns = QHBoxLayout()
        columns.setSpacing(16)
        account_card, account_layout = card()
        account_card.setMinimumWidth(310)
        title_row = QHBoxLayout()
        title_row.addWidget(caption("QQ 邮箱", "heading"))
        title_row.addStretch()
        self.connection_badge = caption("未绑定")
        self.connection_badge.setStyleSheet("background: #edf5f6; color: #42808a; border-radius: 10px; padding: 4px 12px;")
        title_row.addWidget(self.connection_badge)
        account_layout.addLayout(title_row)
        account_layout.addWidget(caption("用于接收测评、笔试和在线测试通知。"))
        config = panel.repo.setting("config", {})
        self.connection_badge.setText("已绑定" if config.get("account") else "未绑定")
        self.account = QLineEdit(config.get("account", ""))
        self.account.setPlaceholderText("你的邮箱地址，例如 name@qq.com")
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("生成时显示的完整 16 位字母授权码")
        account_layout.addWidget(caption("邮箱地址", "field"))
        account_layout.addWidget(self.account)
        account_layout.addWidget(caption("邮箱授权码", "field"))
        account_layout.addWidget(self.secret)
        self.show_secret = QCheckBox("显示授权码")
        self.show_secret.toggled.connect(lambda checked: self.secret.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        account_layout.addWidget(self.show_secret)
        account_layout.addWidget(caption("已绑定时可留空，继续使用保存的授权码。", "muted"))
        self.info = caption("授权码安全保存在系统凭据库中。", "note")
        account_layout.addWidget(self.info)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("测试连接并保存")
        self.save_button.setObjectName("mailPrimary")
        self.save_button.clicked.connect(self.save)
        self.disconnect_button = QPushButton("解除绑定")
        self.disconnect_button.setObjectName("mailDanger")
        self.disconnect_button.clicked.connect(self.disconnect)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.disconnect_button)
        account_layout.addLayout(buttons)
        account_layout.addStretch()
        preferences_card, preferences = card()
        preferences_card.setMinimumWidth(280)
        preferences.addWidget(caption("同步与匹配", "heading"))
        preferences.addWidget(caption("按你的投递习惯，调整查信范围。"))
        self.folders = QLineEdit(",".join(config.get("folders", ["INBOX"])))
        self.folders.setToolTip("默认收件箱。归档或垃圾邮件需填写对应 IMAP 文件夹名称，用英文逗号分隔。")
        self.days = QSpinBox()
        self.days.setRange(1, 365)
        self.days.setValue(config.get("days", 30))
        self.days.setSuffix(" 天")
        self.aliases = QPlainTextEdit()
        self.aliases.setPlaceholderText("公司名称=简称1,简称2\n例如：仙工智能=SEER,仙工")
        self.aliases.setPlainText("\n".join(k + "=" + ",".join(v) for k, v in panel.repo.setting("aliases", {}).items()))
        self.aliases.setFixedHeight(92)
        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.addRow("同步文件夹", self.folders)
        form.addRow("首次回溯", self.days)
        preferences.addLayout(form)
        preferences.addWidget(caption("INBOX 为收件箱；多个文件夹用英文逗号分隔。"))
        preferences.addWidget(caption("公司别名 · 可选", "field"))
        preferences.addWidget(self.aliases)
        preferences.addWidget(caption("每行一家公司，帮助匹配简称与第三方招聘平台邮件。"))
        preferences.addStretch()
        columns.addWidget(account_card, 1)
        columns.addWidget(preferences_card, 1)
        body.addLayout(columns)
        help_card, help_layout = card()
        help_layout.addWidget(caption("如何获取授权码", "heading"))
        help_layout.addWidget(caption("01  登录 QQ 邮箱网页版，进入账户设置，开启 IMAP/SMTP。\n02  点击生成授权码，完成验证，复制显示的完整 16 位字母。\n03  粘贴到左侧输入框，点击测试连接并保存。", "field"))
        help_layout.addWidget(caption("管理列表里的“授权码_xxxx”是名称，不是授权码。查信不会改变邮件的已读状态。"))
        body.addWidget(help_card)
        body.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def hideEvent(self, event):
        self.secret.clear()
        self.show_secret.setChecked(False)
        super().hideEvent(event)

    def save(self):
        try:
            account = validate_account(self.account.text())
            secret = validate_authorization_code(self.secret.text())
            folders = list(dict.fromkeys(x.strip() for x in self.folders.text().split(",") if x.strip()))
            if not folders or any("\n" in f or "\r" in f for f in folders):
                raise ValueError("请填写有效的同步文件夹名称，例如 INBOX")
            aliases = {}
            for line in self.aliases.toPlainText().splitlines():
                if not line.strip():
                    continue
                company, sep, names = line.partition("=")
                if not sep or not company.strip():
                    raise ValueError("公司别名格式应为：公司名称=简称1,简称2")
                aliases[company.strip()] = [x.strip() for x in names.replace("，", ",").split(",") if x.strip()]
            config = {"account": account, "folders": folders, "days": self.days.value(), "aliases": aliases}
            if self.panel.start_worker(config, secret=secret, binding=True):
                self.save_button.setEnabled(False)
                self.disconnect_button.setEnabled(False)
                self.info.setText("正在测试连接，请稍候……")
        except ValueError as error:
            self.info.setText(str(error))

    def disconnect(self):
        if self.panel.is_busy():
            self.info.setText("请等待当前邮箱任务完成")
            return
        account = self.panel.repo.setting("config", {}).get("account")
        try:
            if account:
                vault = credential_store()
                if vault.get_password(SERVICE, account):
                    vault.delete_password(SERVICE, account)
        except Exception:
            self.info.setText("无法删除系统凭据，请检查系统凭据库后重试")
            return
        self.panel.repo.set_setting("config", {})
        self.panel.status.setText("已解除邮箱绑定")
        self.panel.update_summary()
        self.info.setText("已解除绑定并删除授权码；已有本地待办保留，重新绑定同一邮箱可查看。")
        self.secret.clear()


class MailTasksPage(QWidget):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.setStyleSheet(MAIL_PAGE_STYLE)
        self.rows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metrics = []
        for title, color in (("待完成", "#23616b"), ("24 小时内截止", "#bd832c"), ("已逾期", "#b75e6b"), ("待核对", "#7186a0")):
            frame, metric_layout = card()
            metric_layout.setContentsMargins(16, 10, 16, 10)
            metric_layout.setSpacing(0)
            metric_layout.addWidget(caption(title))
            number = caption("0", "metric")
            number.setStyleSheet(f"color: {color};")
            metric_layout.addWidget(number)
            metrics.addWidget(frame)
            self.metrics.append(number)
        layout.addLayout(metrics)
        filter_bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索公司、岗位或通知主题")
        self.search.textChanged.connect(self.reload)
        filter_bar.addWidget(self.search, 1)
        self.show_closed = QCheckBox("包含已完成 / 已忽略")
        self.show_closed.toggled.connect(self.reload)
        filter_bar.addWidget(self.show_closed)
        layout.addLayout(filter_bar)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["公司 / 岗位", "招聘通知", "截止时间", "状态"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.setMinimumWidth(310)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(90)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(2, 155)
        self.table.setColumnWidth(3, 76)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.splitter.addWidget(self.table)
        detail_card, detail_layout = card()
        detail_card.setMinimumWidth(290)
        self.detail_title = caption("选择一封招聘通知", "heading")
        self.detail_title.setMaximumHeight(64)
        self.detail_meta = caption("在左侧查看待办，在这里阅读邮件与处理。")
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_meta)
        self.detail_stack = QStackedWidget()
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setObjectName("mailBody")
        self.detail_stack.addWidget(self.details)
        self.correction = QWidget()
        self._build_correction()
        self.detail_stack.addWidget(self.correction)
        detail_layout.addWidget(self.detail_stack, 1)
        buttons = QGridLayout()
        self.action_buttons = []
        for label, callback in (
            ("标记已完成", lambda: self.set_state("done")),
            ("忽略", lambda: self.set_state("ignored")),
            ("恢复待办", lambda: self.set_state("pending")),
            ("核对信息", self.correct),
        ):
            button = QPushButton(label)
            if not self.action_buttons:
                button.setObjectName("mailPrimary")
            button.clicked.connect(callback)
            index = len(self.action_buttons)
            buttons.addWidget(button, index // 2, index % 2)
            self.action_buttons.append(button)
        detail_layout.addLayout(buttons)
        self.splitter.addWidget(detail_card)
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([660, 360])
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        layout.addWidget(caption("时间均为北京时间。“预计”时间请核对原文；已读邮件不代表任务已完成。"))
        self.reload()

    def selected(self):
        row = self.table.currentRow()
        return self.rows[row] if 0 <= row < len(self.rows) else None

    def reload(self):
        if hasattr(self, "detail_stack") and self.detail_stack.currentWidget() is self.correction:
            # Background refresh must not erase an in-progress correction.
            return
        selected = self.selected()["id"] if hasattr(self, "rows") and self.selected() else None
        account = self.panel.repo.setting("config", {}).get("account", "")
        all_mail = self.panel.repo.list_mail(account)
        pending = [mail for mail in all_mail if mail["state"] == "pending"]
        now = datetime.now(CHINA)
        hours = [(datetime.fromisoformat(mail["deadline"]) - now).total_seconds() / 3600 for mail in pending if mail["deadline"]]
        totals = [len(pending), sum(0 < h <= 24 for h in hours), sum(h <= 0 for h in hours),
                  sum(not m["job_id"] or not m["deadline"] or m["estimated"] for m in pending)]
        for label, total in zip(self.metrics, totals):
            label.setText(str(total))
        query = self.search.text().strip().casefold()
        self.rows = [m for m in all_mail if (self.show_closed.isChecked() or m["state"] == "pending") and
                     query in " ".join(str(m.get(key) or "") for key in ("company", "position", "subject", "sender")).casefold()]
        blocker = QSignalBlocker(self.table)
        self.table.setRowCount(0)
        for row, mail in enumerate(self.rows):
            self.table.insertRow(row)
            self.table.setRowHeight(row, 64)
            deadline = datetime.fromisoformat(mail["deadline"]) if mail["deadline"] else None
            left = "待核对"
            if deadline:
                hours = (deadline - now).total_seconds() / 3600
                left = "已逾期" if hours <= 0 else f"剩余 {int(hours // 24)} 天 {int(hours % 24)} 小时" if hours >= 24 else f"剩余 {int(hours)} 小时 {int(hours * 60) % 60} 分"
            company = f"{mail['company']}\n{mail['position'] or '未指定岗位'}" if mail["company"] else "待核对公司\n请选择对应投递"
            values = [company, mail["subject"].replace("\n", " ") + "\n" + mail["kind"],
                      ("预计 " if mail["estimated"] else "") + (deadline.strftime("%m-%d %H:%M") if deadline else "时间待核对") + "\n" + left,
                      {"pending": "待完成", "done": "已完成", "ignored": "已忽略"}[mail["state"]]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(format_time(mail["deadline"]) + "\n" + mail["evidence"] if col == 2 else value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                if col == 2 and mail["state"] == "pending" and deadline and hours <= 24:
                    item.setForeground(QColor("#b75e6b" if hours <= 0 else "#af7929"))
                if col == 3:
                    item.setForeground(QColor({"pending": "#36848c", "done": "#4b8b68", "ignored": "#92a1b0"}[mail["state"]]))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, col, item)
        del blocker
        if self.rows:
            row = next((i for i, m in enumerate(self.rows) if m["id"] == selected), 0)
            self.table.selectRow(row)
        else:
            self.detail_title.setText("没有匹配的通知" if query else "待办清单很清爽")
            self.detail_meta.setText("试试其他关键词。" if query else "新的招聘通知会在同步后出现在这里。")
            self.details.setPlainText("点击上方“查邮件”，或刷新测评 / 笔试阶段的投递记录。\n\n完成的通知会收起，你可以勾选“包含已完成 / 已忽略”再次查看。")
        self.show_details()

    def show_details(self):
        mail = self.selected()
        self.detail_stack.setCurrentWidget(self.details)
        for button in self.action_buttons:
            button.setEnabled(bool(mail))
        if mail:
            self.detail_title.setText(mail["subject"])
            self.detail_title.setToolTip(mail["subject"])
            self.detail_meta.setText(f"{mail['company'] or '待核对公司'} · {mail['kind']}\n{format_time(mail['received'])} 收到")
            self.details.setPlainText(
                f"截止：{format_time(mail['deadline']) or '待核对'}\n开始：{format_time(mail['starts_at']) or '未注明'}\n\n"
                f"{mail['body']}\n\n发件人：{mail['sender']}\n公司：{mail['company'] or '待核对'}\n\n"
                f"时间依据\n{mail['evidence']}\n\n匹配说明\n{mail['match_note']}"
            )

    def set_state(self, state):
        mail = self.selected()
        if mail:
            self.panel.repo.update(mail["id"], state=state, reminder="")
            self.reload()
            self.panel.update_summary()

    def _build_correction(self):
        layout = QVBoxLayout(self.correction)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 4, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.correct_job = QComboBox()
        self.correct_deadline = QLineEdit()
        self.correct_start = QLineEdit()
        self.correct_deadline.setPlaceholderText("YYYY-MM-DD HH:MM")
        self.correct_start.setPlaceholderText("YYYY-MM-DD HH:MM")
        form.addRow("关联投递", self.correct_job)
        form.addRow("截止时间", self.correct_deadline)
        form.addRow("开始时间", self.correct_start)
        self.correct_info = caption("北京时间；留空表示未知。")
        form.addRow(self.correct_info)
        buttons = QHBoxLayout()
        save = QPushButton("保存核对")
        save.setObjectName("mailPrimary")
        save.clicked.connect(self.save_correction)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.show_details)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        form.addRow(buttons)
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def correct(self):
        mail = self.selected()
        if not mail:
            return
        self.correct_job.clear()
        self.correct_job.addItem("暂不关联公司", None)
        for job in self.panel.database.list_jobs():
            self.correct_job.addItem(f"{job['company']} / {job['position']}", job["id"])
        self.correct_job.setCurrentIndex(max(0, self.correct_job.findData(mail["job_id"])))
        self.correct_deadline.setText(format_time(mail["deadline"]))
        self.correct_start.setText(format_time(mail["starts_at"]))
        self.correct_info.setText("北京时间；留空表示未知。")
        self.detail_stack.setCurrentWidget(self.correction)
        for button in self.action_buttons:
            button.setEnabled(False)

    def save_correction(self):
        mail = self.selected()
        if not mail:
            return
        try:
            end = parse_manual_time(self.correct_deadline.text())
            start = parse_manual_time(self.correct_start.text())
            if start and end and start > end:
                raise ValueError("开始时间不能晚于截止时间")
            self.panel.repo.update(mail["id"], job_id=self.correct_job.currentData(), deadline=end, starts_at=start,
                                   estimated=0, evidence="用户手动核对", match_note="用户手动关联", reminder="")
            self.detail_stack.setCurrentWidget(self.details)
            self.reload()
            self.panel.update_summary()
        except ValueError as error:
            self.correct_info.setText(str(error))


def format_time(value):
    return datetime.fromisoformat(value).astimezone(CHINA).strftime("%Y-%m-%d %H:%M") if value else ""


def parse_manual_time(value):
    if not value.strip():
        return ""
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=CHINA).isoformat()
    except ValueError as error:
        raise ValueError("时间格式应为 YYYY-MM-DD HH:MM，例如 2026-09-12 18:00") from error


class MailPanel(QWidget):
    page_changed = pyqtSignal(str)

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self.repo = MailRepository(database)
        self.worker = None
        self.settings_page = None
        self.tasks_page = None
        self.pending_sync = False
        self.page_stack = None
        self.jobs_page = None
        self.current_page = "jobs"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.navigation = QButtonGroup(self)
        self.nav_buttons = {}
        for key, title, callback in (("jobs", "投递记录", self.show_jobs), ("tasks", "招聘待办", self.show_tasks), ("settings", "邮箱设置", self.show_settings)):
            button = QPushButton(title)
            button.setMinimumWidth(144 if key == "tasks" else 104)
            button.setCheckable(True)
            button.setChecked(key == "jobs")
            button.setStyleSheet("QPushButton { background: transparent; border: none; color: #8292a3; padding: 0 18px; min-height: 36px; border-radius: 8px; } QPushButton:hover { background: #edf3f7; color: #49677c; } QPushButton:checked { background: #e4f1f3; color: #277581; font-weight: 700; }")
            self.navigation.addButton(button)
            self.nav_buttons[key] = button
            button.clicked.connect(callback)
            bar.addWidget(button)
        bar.addStretch()
        self.status = QLabel("邮箱已绑定，可点击查邮件" if self.repo.setting("config", {}).get("account") else "尚未绑定邮箱")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #8494a4; font-size: 12px; padding: 0 8px;")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bar.addWidget(self.status, 1)
        self.sync_button = QPushButton("查邮件")
        self.sync_button.setObjectName("secondaryButton")
        self.sync_button.clicked.connect(self.sync)
        bar.addWidget(self.sync_button)
        layout.addLayout(bar)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #63828e; font-size: 12px; padding: 0 4px;")
        layout.addWidget(self.summary)
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation), self)
            self.tray.setToolTip("招聘待办提醒（程序运行期间）")
            self.tray.messageClicked.connect(self.show_tasks)
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_due)
        self.timer.start(60_000)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.sync_if_active)
        self.poll_timer.start(15 * 60_000)
        self.startup_timer = QTimer(self)
        self.startup_timer.setSingleShot(True)
        self.startup_timer.timeout.connect(self.startup)
        self.startup_timer.start(1000)
        self.update_summary()

    def startup(self):
        self.check_due()
        self.sync_if_active()

    def is_busy(self):
        return self.worker is not None

    def attach_pages(self, stack, jobs_page):
        self.page_stack = stack
        self.jobs_page = jobs_page

    def activate_page(self, key, page):
        self.page_stack.setCurrentWidget(page)
        self.current_page = key
        self.nav_buttons[key].setChecked(True)
        self.update_summary()
        self.page_changed.emit(key)

    def show_jobs(self):
        self.activate_page("jobs", self.jobs_page)

    def show_settings(self):
        if self.settings_page is None:
            self.settings_page = MailSettingsPage(self)
            self.page_stack.addWidget(self.settings_page)
        self.activate_page("settings", self.settings_page)

    def show_tasks(self):
        if self.tasks_page is None:
            self.tasks_page = MailTasksPage(self)
            self.page_stack.addWidget(self.tasks_page)
        self.tasks_page.reload()
        self.activate_page("tasks", self.tasks_page)

    def sync_if_active(self):
        if any(mail_stage(job["status"]) for job in self.database.list_jobs()):
            self.sync()

    def sync(self):
        config = self.repo.setting("config", {})
        if not config.get("account"):
            self.status.setText("请先在“邮箱设置”中绑定 QQ 邮箱")
            return
        if self.is_busy():
            self.pending_sync = True
            return
        self.start_worker(config)

    def start_worker(self, config, secret="", binding=False):
        if self.is_busy():
            self.status.setText("邮箱任务正在进行，请稍候")
            return False
        self.worker = MailWorker(config, self.repo.checkpoints(config["account"]), self, secret, binding)
        self.worker.succeeded.connect(self.completed)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()
        self.status.setText("正在测试邮箱连接……" if binding else "正在同步招聘邮件……")
        return True

    def completed(self, result):
        config = result["config"]
        if result["binding"]:
            previous = self.repo.setting("config", {})
            aliases = config.pop("aliases", {})
            self.repo.set_setting("aliases", aliases)
            self.repo.set_setting("config", config)
            if previous.get("days") != config["days"]:
                self.repo.set_setting("checkpoints:" + config["account"], {})
            self.repo.rematch(config["account"])
            self.status.setText("邮箱连接成功，已保存绑定")
            if self.settings_page:
                self.settings_page.secret.clear()
                self.settings_page.info.setText("连接成功，授权码已存入系统凭据库。")
            self.pending_sync = True
        else:
            added = self.repo.ingest(config["account"], result)
            self.status.setText(f"同步完成，新增 {added} 条招聘通知。" + "；".join(dict.fromkeys(result["warnings"])))
            self.check_due()
        self.update_summary()
        if self.tasks_page:
            self.tasks_page.reload()

    def failed(self, reason):
        self.status.setText(reason)
        self.pending_sync = False
        if self.settings_page:
            self.settings_page.info.setText(reason)

    def worker_finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        if self.settings_page:
            self.settings_page.save_button.setEnabled(True)
            self.settings_page.disconnect_button.setEnabled(True)
        if self.pending_sync:
            self.pending_sync = False
            self.sync()

    def update_summary(self):
        account = self.repo.setting("config", {}).get("account", "")
        if self.settings_page:
            self.settings_page.connection_badge.setText("已绑定" if account else "未绑定")
        self.summary.hide()
        if not account:
            self.nav_buttons["tasks"].setText("招聘待办")
            return
        rows = [mail for mail in self.repo.list_mail(account) if mail["state"] == "pending"]
        urgent = sum(bool(reminder_key(mail)) for mail in rows)
        self.nav_buttons["tasks"].setText(f"招聘待办 · {len(rows)}" if rows else "招聘待办")
        self.summary.setText(f"招聘邮件中有 {len(rows)} 项待完成，{urgent} 项临近截止、已到期或时间待核对。")
        self.summary.setVisible(bool(rows) and self.current_page == "jobs")

    def check_due(self):
        account = self.repo.setting("config", {}).get("account", "")
        notices = []
        for mail in self.repo.list_mail(account):
            key = reminder_key(mail)
            if key and key != mail["reminder"]:
                prefix = "预计" if mail["estimated"] else ""
                notices.append(f"{mail['company'] or '待核对公司'}：{mail['subject']}\n"
                               f"{prefix}开始：{format_time(mail['starts_at']) or '未注明'}\n"
                               f"{prefix}截止：{format_time(mail['deadline']) or '待核对'}")
                self.repo.update(mail["id"], reminder=key)
        self.update_summary()
        if self.tasks_page and self.tasks_page.isVisible():
            self.tasks_page.reload()
        if notices:
            text = "\n\n".join(notices[:5])
            if len(notices) > 5:
                text += f"\n另有 {len(notices) - 5} 项，请打开招聘待办查看。"
            if self.tray and self.tray.supportsMessages():
                self.tray.showMessage("招聘任务提醒", text, QSystemTrayIcon.MessageIcon.Warning, 12000)
            else:
                box = QMessageBox(QMessageBox.Icon.Warning, "招聘任务提醒", text, parent=self)
                box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                box.setModal(False)
                box.show()

    def stop(self):
        self.pending_sync = False
        self.timer.stop()
        self.poll_timer.stop()
        self.startup_timer.stop()
        if self.worker:
            self.worker.requestInterruption()
        if self.tray:
            self.tray.hide()
