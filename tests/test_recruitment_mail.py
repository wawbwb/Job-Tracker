import unittest
from datetime import datetime, timedelta
from email.message import EmailMessage
from unittest.mock import MagicMock

from src.database import Database
from src.mail_repository import MailRepository
from src.recruitment_mail import CHINA, QQMailClient, assessment_kind, extract_times, mail_stage, match_jobs, parse_message, reminder_key


RECEIVED = datetime(2026, 9, 8, 10, 0, tzinfo=CHINA)
PRIVACY_BODY = """禾赛招聘隐私政策\u200b
&#x20; 为了在招聘的过程中更好地保护您的个人信息，请您务必仔细阅读、理解本《招聘隐私政策》。
本政策所称公司指上海禾赛科技有限公司及其各关联公司。
二、公司如何收集和使用您的个人信息
招聘流程中收集或产生的其他信息，如第三方求职网站、猎头服务供应商提供的信息，
面试和笔试记录以及为进行薪酬评估收集的您的历史薪酬信息。
三、关于共享、公开个人信息
为进行必要的招聘管理，公司可能会向供应商提供个人信息。
"""


def raw_mail(body="请在收到邮件后三天内完成测评", subject="仙工智能测评通知", html=False):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "招聘平台 <noreply@example.com>"
    message["Message-ID"] = "<test-recruitment@example.com>"
    message["Date"] = "Mon, 7 Sep 2026 10:00:00 +0800"
    message.set_content(body, subtype="html" if html else "plain", charset="utf-8")
    return message.as_bytes()


class MailParserTests(unittest.TestCase):
    def test_relative_deadline_uses_receipt_not_header_date(self):
        mail = parse_message(raw_mail(), RECEIVED)
        self.assertEqual(mail["deadline"], (RECEIVED + timedelta(days=3)).isoformat())
        self.assertEqual(mail["estimated"], 1)
        self.assertIn("收件时间", mail["evidence"])

    def test_relative_hours_and_no_receipt(self):
        for text in ("请在72小时内完成测评", "请在七十二小时内完成测评"):
            self.assertEqual(extract_times(text, RECEIVED)["deadline"], (RECEIVED + timedelta(hours=72)).isoformat())
        self.assertEqual(parse_message(raw_mail())["deadline"], "")

    def test_absolute_deadline_and_unrelated_date(self):
        value = extract_times("测评截止时间：2026年9月12日 18:00。邮件发送时间：2026年9月8日 10:00。", RECEIVED)
        self.assertEqual(value["deadline"], "2026-09-12T18:00:00+08:00")
        self.assertEqual(value["estimated"], 0)

    def test_exam_window_and_year_rollover(self):
        value = extract_times("笔试时间：2026年9月12日 18:00-20:00", RECEIVED)
        self.assertEqual(value["starts_at"], "2026-09-12T18:00:00+08:00")
        self.assertEqual(value["deadline"], "2026-09-12T20:00:00+08:00")
        value = extract_times("请于1月2日前完成测评", datetime(2026, 12, 30, tzinfo=CHINA))
        self.assertEqual(value["deadline"], "2027-01-02T23:59:00+08:00")
        self.assertTrue(value["estimated"])

    def test_unclear_time_does_not_invent_deadline(self):
        for text in ("三个工作日内完成测评", "点击链接后3天内完成测评", "测评截止2026年2月30日", "测评时间请查看图片", "测评截止2026年9月12日18:00 PST"):
            with self.subTest(text=text):
                self.assertEqual(extract_times(text, RECEIVED)["deadline"], "")

    def test_html_encoding_and_safe_plain_text(self):
        mail = parse_message(raw_mail('<style>hidden</style><p>三天内完成测评</p><a href="https://example.com/test">入口</a><script>danger</script>', html=True), RECEIVED)
        self.assertEqual(mail["subject"], "仙工智能测评通知")
        self.assertIn("https://example.com/test", mail["body"])
        self.assertNotIn("hidden", mail["body"])
        self.assertNotIn("danger", mail["body"])

    def test_non_recruitment_mail_is_not_cached(self):
        self.assertIsNone(parse_message(raw_mail("今天晚上聚餐", "周末计划"), RECEIVED))

    def test_match_third_party_sender_and_ambiguous_jobs(self):
        jobs = [{"id": 1, "company": "仙工智能", "position": "开发"}, {"id": 2, "company": "仙工智能", "position": "测试"}]
        mail = parse_message(raw_mail(), RECEIVED)
        self.assertIsNone(match_jobs(mail, jobs, {})[0])
        mail["body"] += "应聘开发岗位"
        self.assertEqual(match_jobs(mail, jobs, {})[0], 1)
        mail["subject"] = "SEER assessment"
        self.assertEqual(match_jobs(mail, jobs, {"仙工智能": ["SEER"]})[0], 1)

    def test_stage_gate(self):
        for status in ("测评中", "待笔试", "在线测试", "简历筛选通过，笔试中", "测评已完成/笔试中"):
            self.assertTrue(mail_stage(status))
        for status in ("测评已完成", "笔试未通过", "面试中", "已完成测评"):
            self.assertFalse(mail_stage(status))

    def test_hesai_privacy_notice_is_not_a_test_invitation(self):
        for title in ("禾赛招聘隐私政策", "禾赛科技招聘通知", ""):
            with self.subTest(title=title):
                self.assertIsNone(parse_message(raw_mail(PRIVACY_BODY, title), RECEIVED))

    def test_incidental_records_results_and_cancellation_are_not_tasks(self):
        for title, body in (
            ("招聘流程说明", "招聘流程包含简历筛选、笔试和面试。"),
            ("笔试结果通知", "感谢参与，您的笔试已完成。"),
            ("个人信息收集说明", "我们收集笔试记录、测评结果和历史薪酬。"),
            ("笔试通知", "本次笔试已取消，无需参加笔试。"),
        ):
            with self.subTest(title=title):
                self.assertIsNone(assessment_kind(title, body))

    def test_actual_invitation_with_policy_footer_is_retained(self):
        mail = parse_message(raw_mail("请在三天内完成测评。\n\n" + PRIVACY_BODY, "禾赛科技测评邀请"), RECEIVED)
        self.assertEqual(mail["kind"], "测评")
        self.assertTrue(mail["deadline"])
        self.assertNotIn("&#x20;", mail["body"])
        self.assertNotIn("\u200b", mail["body"])

    def test_actual_instructions_do_not_require_a_known_deadline(self):
        for title, body in (
            ("禾赛科技笔试邀请", "请查看附件中的安排。"),
            ("招聘进展", "诚邀您参加本次笔试，具体时间另行通知。"),
            ("招聘进展", "笔试链接：https://example.com/test"),
            ("招聘进展", "测评时间：2026年9月12日 18:00"),
            ("Recruitment update", "You are invited to complete an online test."),
        ):
            with self.subTest(title=title, body=body):
                self.assertIsNotNone(parse_message(raw_mail(body, title), RECEIVED))

    def test_policy_retention_period_is_not_an_exam_deadline(self):
        body = "邀请您参加测评，安排请查看附件。\n招聘隐私政策\n公司将在三天内完成测评记录的删除。"
        mail = parse_message(raw_mail(body, "禾赛科技测评邀请"), RECEIVED)
        self.assertEqual(mail["deadline"], "")


class MailClientTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.factory = MagicMock()
        self.factory.return_value.__enter__.return_value = self.client
        self.client.select.return_value = ("OK", [b"1"])
        self.client.response.return_value = ("UIDVALIDITY", [b"77"])
        self.client.uid.side_effect = self.uid
        self.raw = raw_mail()
        self.service = QQMailClient(self.factory)

    def uid(self, action, *args):
        if action == "search":
            return "OK", [b"1 2"]
        return "OK", [(b'1 (UID 1 INTERNALDATE "08-Sep-2026 10:00:00 +0800" RFC822.SIZE ' + str(len(self.raw)).encode() + b')', self.raw), b")"]

    def test_readonly_peek_and_checkpoint(self):
        result = self.service.sync("test@qq.com", "fake-secret", ["INBOX"], {})
        self.client.select.assert_called_with('"INBOX"', readonly=True)
        self.assertTrue(self.factory.call_args.kwargs["ssl_context"].check_hostname)
        self.assertEqual(result["checkpoints"]["INBOX"], {"validity": "77", "uid": 2})
        self.assertEqual(result["messages"][0]["received"], RECEIVED.isoformat())
        self.assertEqual(result["messages"][0]["deadline"], (RECEIVED + timedelta(days=3)).isoformat())
        for call in self.client.uid.call_args_list:
            if call.args[0] == "fetch":
                self.assertIn("BODY.PEEK", call.args[2])
        self.client.store.assert_not_called()

    def test_incremental_uid_and_epoch_reset(self):
        result = self.service.sync("test@qq.com", "fake", ["INBOX"], {"INBOX": {"validity": "77", "uid": 2}})
        self.assertEqual(result["messages"], [])
        self.client.uid.assert_called_with("search", None, "UID", "3:*")
        self.client.uid.reset_mock()
        result = self.service.sync("test@qq.com", "fake", ["INBOX"], {"INBOX": {"validity": "old", "uid": 100}})
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(self.client.uid.call_args_list[0].args[2], "SINCE")

    def test_login_only_does_not_download_mail(self):
        self.service.sync("test@qq.com", "fake", ["INBOX"], {}, test_only=True)
        self.client.uid.assert_not_called()

    def test_authentication_error_has_actionable_message(self):
        import imaplib
        self.client.login.side_effect = imaplib.IMAP4.error("private server reply")
        with self.assertRaisesRegex(RuntimeError, "邮箱认证失败.*完整授权码") as caught:
            self.service.sync("test@qq.com", "fake", ["INBOX"], {}, test_only=True)
        self.assertNotIn("private server reply", str(caught.exception))

    def test_error_and_cancellation_do_not_return_success(self):
        self.client.uid.return_value = ("NO", [])
        self.client.uid.side_effect = None
        with self.assertRaises(RuntimeError):
            self.service.sync("test@qq.com", "fake", ["INBOX"], {})
        with self.assertRaises(RuntimeError):
            self.service.sync("test@qq.com", "fake", ["INBOX"], {}, cancelled=lambda: True)


class MailRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.addCleanup(self.db.close)
        self.repo = MailRepository(self.db)
        self.job_id = self.db.save_job({"company": "仙工智能", "position": "开发"})
        mail = parse_message(raw_mail(), RECEIVED)
        mail["folder"] = "INBOX"
        self.result = {"messages": [mail], "checkpoints": {"INBOX": {"validity": "77", "uid": 1}}}

    def test_repeated_sync_preserves_manual_corrections_and_completion(self):
        self.assertEqual(self.repo.ingest("test@qq.com", self.result), 1)
        mail = self.repo.list_mail("test@qq.com")[0]
        self.assertEqual(mail["job_id"], self.job_id)
        self.repo.update(mail["id"], state="done", deadline="2026-09-10T10:00:00+08:00", reminder="custom")
        self.assertEqual(self.repo.ingest("test@qq.com", self.result), 0)
        saved = self.repo.list_mail("test@qq.com")[0]
        self.assertEqual(saved["state"], "done")
        self.assertEqual(saved["deadline"], "2026-09-10T10:00:00+08:00")
        self.assertEqual(saved["reminder"], "custom")

    def test_account_isolation_and_job_delete_retains_mail(self):
        self.repo.ingest("test@qq.com", self.result)
        self.assertEqual(self.repo.list_mail("other@qq.com"), [])
        self.db.delete_job(self.job_id)
        self.assertIsNone(self.repo.list_mail("test@qq.com")[0]["job_id"])

    def test_reminder_stages(self):
        self.repo.ingest("test@qq.com", self.result)
        mail = self.repo.list_mail("test@qq.com")[0]
        deadline = datetime.fromisoformat(mail["deadline"])
        self.assertEqual(reminder_key(mail, deadline - timedelta(hours=25)), "")
        self.assertIn("24小时内", reminder_key(mail, deadline - timedelta(hours=20)))
        self.assertIn("3小时内", reminder_key(mail, deadline - timedelta(hours=2)))
        self.assertIn("已到时间", reminder_key(mail, deadline))
        mail["state"] = "done"
        self.assertEqual(reminder_key(mail, deadline), "")

    def test_transaction_failure_does_not_advance_checkpoint(self):
        bad = {"messages": [{**self.result["messages"][0], "subject": None}], "checkpoints": self.result["checkpoints"]}
        # Invalid mail must roll back together with its checkpoint.
        with self.assertRaises(Exception):
            self.repo.ingest("test@qq.com", bad)
        self.assertEqual(self.repo.checkpoints("test@qq.com"), {})

    def test_cached_privacy_notices_are_ignored_without_deleting_or_overriding_edits(self):
        notices = []
        for key in ("auto", "manual", "done"):
            notices.append({**self.result["messages"][0], "message_key": key,
                            "subject": "禾赛招聘隐私政策", "body": PRIVACY_BODY})
        self.repo.ingest("test@qq.com", {"messages": [*notices, self.result["messages"][0]], "checkpoints": {}})
        rows = {m["message_key"]: m for m in self.repo.list_mail("test@qq.com")}
        self.repo.update(rows["manual"]["id"], evidence="用户手动核对")
        self.repo.update(rows["done"]["id"], state="done")
        self.repo.set_setting("assessment_filter_version", 0)
        repo = MailRepository(self.db)
        rows = {m["message_key"]: m for m in repo.list_mail("test@qq.com")}
        self.assertEqual(rows["auto"]["state"], "ignored")
        self.assertIn("自动忽略", rows["auto"]["match_note"])
        self.assertEqual(rows["auto"]["body"], PRIVACY_BODY)
        self.assertEqual(rows["manual"]["state"], "pending")
        self.assertEqual(rows["done"]["state"], "done")
        self.assertEqual(rows[self.result["messages"][0]["message_key"]]["state"], "pending")
        repo.update(rows["auto"]["id"], state="pending")
        MailRepository(self.db)
        self.assertEqual(repo.list_mail("test@qq.com")[0]["state"], "pending")


if __name__ == "__main__":
    unittest.main()
