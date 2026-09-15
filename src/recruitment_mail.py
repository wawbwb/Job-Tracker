"""Local recruitment mail parsing and read-only QQ IMAP synchronization."""
from __future__ import annotations

import hashlib
import imaplib
import re
import ssl
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from html import unescape

CHINA = timezone(timedelta(hours=8))
SERVICE = "job_tracker.qq_mail"
KINDS = ("测评", "笔试", "在线测试", "在线考试", "assessment", "online test")
POLICY_TITLE = r"(?:招聘隐私政策|隐私政策|隐私声明|个人信息保护政策|个人信息处理告知书|privacy policy|privacy notice)"


def mail_stage(status: str) -> bool:
    for match in re.finditer("|".join(re.escape(word) for word in KINDS), status, re.I):
        following = re.split(r"[，,；;/\n]|测评|笔试|面试|在线测试", status[match.end():], maxsplit=1)[0]
        preceding = re.split(r"[，,；;/\n]", status[:match.start()])[-1].strip()
        if any(word in following for word in ("完成", "通过", "结束", "淘汰", "取消", "终止")):
            continue
        if preceding in ("已完成", "已通过", "已结束", "已取消", "已终止"):
            continue
        return True
    return False


def credential_store():
    # Explicitly select native backends; never fall back to plaintext keyrings.
    import sys
    try:
        if sys.platform == "win32":
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        if sys.platform == "darwin":
            from keyring.backends.macOS import Keyring
            return Keyring()
        from keyring.backends.SecretService import Keyring
        return Keyring()
    except ImportError as error:
        raise RuntimeError("缺少系统凭据库依赖，请运行 pip install -r requirements.txt") from error


def validate_account(account: str) -> str:
    account = account.strip().lower()
    if not re.fullmatch(r"[a-z0-9_.+-]+@(qq|foxmail)\.com", account):
        raise ValueError("请输入完整的 QQ 邮箱或 foxmail.com 邮箱地址")
    return account


def validate_authorization_code(code: str) -> str:
    code = re.sub(r"\s+", "", code)
    if code and not re.fullmatch(r"[A-Za-z]{16}", code):
        raise ValueError("请粘贴生成时显示的完整 16 位字母授权码；列表中的“授权码_xxxx”是名称，不能用作授权码")
    return code


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in ("br", "p", "div", "tr", "li"):
            self.parts.append("\n")
        if tag == "a" and not self.hidden:
            for name, value in attrs:
                if name == "href" and value and value.startswith(("https://", "http://")):
                    self.parts.append(f" {value} ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def chinese_number(value):
    if value.isdigit():
        return int(value)
    digits = {c: n for n, c in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if "十" in value:
        tens, units = value.split("十", 1)
        return digits.get(tens, 1) * 10 + digits.get(units, 0)
    return digits.get(value, 0)


def clean_mail_text(text: str) -> str:
    # Some providers double-encode entities even in their text/plain alternative.
    for _ in range(2):
        text = unescape(text)
    text = re.sub(r"[\u200b-\u200d\ufeff]", "", text).replace("\xa0", " ")
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text).strip()


def task_content(body: str) -> str:
    body = clean_mail_text(body)
    heading = re.search(r"(?im)^[^\n]{0,30}" + POLICY_TITLE + r"[ \t#。]*$", body)
    return body[:heading.start()] if heading else body


def informational_notice(subject: str, body: str) -> bool:
    """Only automatically retire cached entries that clearly describe non-task mail."""
    heading = clean_mail_text(body).split("\n", 1)[0]
    return re.search(POLICY_TITLE + r"|招聘流程|个人信息收集说明|(?:笔试|测评)(?:记录|成绩|结果|取消)", subject + "\n" + heading, re.I) is not None


def assessment_kind(subject: str, body: str) -> str | None:
    """Require an invitation, action request or exam arrangement, not an incidental mention."""
    subject, body = clean_mail_text(subject), clean_mail_text(body)
    exam = r"(?:笔试|测评|在线测试|在线考试|\bassessment\b|\bonline test\b)"
    # Ignore the policy/footer section, while retaining a real invitation above it.
    body = task_content(body)
    body = re.sub(r"https?://\S+", "[链接]", body)
    title_action = re.search(exam + r"[\s:：·-]*(?:邀请|通知|安排|提醒|须知)", subject, re.I)
    reverse_title = re.search(r"(?:邀请|邀您|邀你)[^。！？\n]{0,24}" + exam, subject, re.I)
    if re.search(POLICY_TITLE, subject, re.I) and not (title_action or reverse_title):
        return None
    positive = []
    cancelled = re.search(exam + r"[^。！？\n]{0,12}已取消|(?:无需|不需要)[^。！？\n]{0,15}(?:参加|完成)[^。！？\n]{0,12}" + exam, body, re.I)
    if (title_action or reverse_title) and not cancelled:
        positive.append((title_action or reverse_title).group())
    action_patterns = (
        r"(?:请|诚邀|邀请|邀您|邀你|务必|需要|尚未|尽快)[^。！？\n]{0,60}(?:参加|完成|进行|进入|作答|开始)[^。！？\n]{0,24}" + exam,
        exam + r"[^。！？\n]{0,30}(?:请|务必|尚未|需要)[^。！？\n]{0,40}(?:参加|完成|作答)",
        r"(?:\d+|[一二三四五六七八九十两]+)\s*(?:小时|天|日)内[^。！？\n]{0,20}完成[^。！？\n]{0,12}" + exam,
        exam + r"(?:截止|开始)?(?:时间|链接|入口|地址|口令|账号)[ \t]*[:：][ \t]*\S",
        r"(?:invited|invitation|please|complete|take)[^.!?\n]{0,60}(?:assessment|online test)\b",
        r"\b(?:assessment|online test)\s+(?:invitation|deadline|link|scheduled)\b",
    )
    for pattern in action_patterns:
        for match in re.finditer(pattern, body, re.I):
            # Do not turn cancellation/completion confirmations into new tasks.
            before = re.split(r"[。！？\n]", body[:match.start()])[-1][-25:]
            after = re.split(r"[。！？\n]", body[match.end():])[0][:30]
            if re.search(r"无需|不需要|已取消|已经完成|您已完成|你已完成", before + match.group() + after):
                continue
            positive.append(match.group())
    if not positive:
        return None
    evidence = "\n".join(positive)
    return "笔试" if "笔试" in evidence else "测评" if "测评" in evidence else "在线测试"


def extract_times(text: str, received: datetime | None) -> dict:
    result = {"deadline": "", "starts_at": "", "estimated": 0, "evidence": "未识别到明确时间，请查看原邮件"}
    # Overseas timezones and business-day arithmetic need manual confirmation.
    if re.search(r"工作日|美东|美西|太平洋时间|\b(?:PST|PDT|EST|EDT|GMT|UTC)\b", text, re.I):
        result["evidence"] = "涉及工作日或境外时区，请手动核对时间"
        return result
    date_pattern = re.compile(
        r"(?:(?P<year>20\d{2})[年/\-])?(?P<month>\d{1,2})[月/\-](?P<day>\d{1,2})日?"
        r"(?:\s*(?:[（(][^）)\n]{1,8}[）)])?\s*(?P<hour>\d{1,2})[:：](?P<minute>\d{2}))?"
    )
    for match in date_pattern.finditer(text):
        before = re.split(r"[，,。\n；;！？!?]", text[max(0, match.start() - 40):match.start()])[-1]
        after = re.split(r"[，,。\n；;！？!?]", text[match.end():match.end() + 40])[0]
        context = before + match.group() + after
        if not re.search(r"截止|最晚|完成|有效|结束|笔试时间|测评时间|考试时间|开始|开考", context):
            continue
        if not match["year"] and received is None:
            continue
        year = int(match["year"] or received.year)
        try:
            value = datetime(year, int(match["month"]), int(match["day"]),
                             int(match["hour"] or 23), int(match["minute"] or 59), tzinfo=CHINA)
            if not match["year"] and received.month == 12 and value.month == 1:
                value = value.replace(year=year + 1)
        except ValueError:
            continue
        estimated = not match["year"] or not match["hour"]
        end_time = re.match(r"\s*(?:至|到|[-—~～])\s*(\d{1,2})[:：](\d{2})(?!\d)", after)
        if end_time and match["hour"]:
            try:
                end = value.replace(hour=int(end_time[1]), minute=int(end_time[2]))
            except ValueError:
                continue
            if end < value:
                result["evidence"] = "考试时间跨日或存在歧义，请手动核对"
                continue
            result.update(starts_at=value.isoformat(), deadline=end.isoformat())
        elif result["starts_at"] and re.search(r"(?:至|到|[-—~～])\s*$", before):
            result["deadline"] = value.isoformat()
        elif re.search(r"开始|开考|笔试时间|考试时间", before) and not re.search(r"截止|最晚|完成|结束", before):
            if match["hour"]:
                result["starts_at"] = value.isoformat()
        else:
            result["deadline"] = value.isoformat()
        result["estimated"] = int(bool(result["estimated"] or estimated))
        result["evidence"] = context.strip() + ("（年份或日末时间由程序推定，请核对）" if estimated else "")
    if result["deadline"] and result["starts_at"] and result["deadline"] < result["starts_at"]:
        result.update(deadline="", starts_at="", evidence="开始和截止时间存在歧义，请手动核对")
        return result
    if result["deadline"] or result["starts_at"]:
        return result
    relative = re.search(r"([一二三四五六七八九十两\d]+)\s*(小时|天|日)\s*(?:之)?内", text)
    if relative:
        result["evidence"] = text[max(0, relative.start() - 35):relative.end() + 40].strip()
        if received and not re.search(r"点击|开始答题|进入考试|打开链接", result["evidence"]):
            count = chinese_number(relative[1])
            if 0 < count <= 365:
                delta = timedelta(hours=count) if relative[2] == "小时" else timedelta(days=count)
                result.update(deadline=(received + delta).isoformat(), estimated=1)
                result["evidence"] += "（根据邮箱收件时间推算，请核对）"
    return result


def parse_message(raw: bytes, received: datetime | None = None) -> dict | None:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(message.get("Subject", ""))
    sender = str(message.get("From", ""))
    part = message.get_body(preferencelist=("plain", "html"))
    body = ""
    if part:
        payload = part.get_payload(decode=True) or b""
        try:
            body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except LookupError:
            body = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/html":
            parser = PlainHTML()
            parser.feed(body)
            body = "".join(parser.parts)
    subject, body = clean_mail_text(subject), clean_mail_text(body)
    kind = assessment_kind(subject, body)
    if kind is None:
        return None
    text = subject + "\n" + task_content(body)
    # Date is not necessarily receipt time; do not silently use it for relative deadlines.
    sent = str(message.get("Date", ""))
    return {
        "message_key": hashlib.sha256((str(message.get("Message-ID", "")) or "").encode() + b"\0" + raw).hexdigest(),
        "subject": subject, "sender": sender, "body": body[:200000], "kind": kind,
        "received": received.isoformat() if received else "", "sent": sent,
        **extract_times(text, received),
    }


def match_jobs(mail: dict, jobs: list[dict], aliases: dict) -> tuple[int | None, str]:
    text = (mail["subject"] + "\n" + mail["sender"] + "\n" + mail["body"]).casefold()
    matches = []
    for job in jobs:
        company = job["company"].strip()
        short = re.sub(r"(?:股份)?有限公司$|有限责任公司$", "", company)
        names = [company, short, *aliases.get(company, [])]
        def contains(name):
            name = name.strip().casefold()
            if len(name) < 2:
                return False
            if name.isascii():
                return re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", text) is not None
            return name in text
        if any(contains(name) for name in names):
            matches.append(job)
    if len(matches) > 1:
        positions = [job for job in matches if job["position"] and job["position"].casefold() in text]
        if len(positions) == 1:
            matches = positions
    if len(matches) == 1:
        return matches[0]["id"], "根据公司名称/别名和岗位匹配，请核对邮件"
    return None, "待核对公司：" + ("、".join(dict.fromkeys(j["company"] for j in matches)) or "未找到明确公司名称")


def mailbox_name(name: str) -> str:
    def encode(match):
        import base64
        return "&" + base64.b64encode(match[0].encode("utf-16be")).decode().rstrip("=").replace("/", ",") + "-"
    encoded = re.sub(r"[^\x20-\x7e]+", encode, name.replace("&", "&-"))
    return '"' + encoded.replace("\\", "\\\\").replace('"', '\\"') + '"'


class QQMailClient:
    def __init__(self, factory=imaplib.IMAP4_SSL):
        self.factory = factory

    def sync(self, account, secret, folders, checkpoints, days=30, cancelled=lambda: False, test_only=False):
        account = validate_account(account)
        messages, updates, warnings = [], {}, []
        if not secret:
            raise ValueError("未保存邮箱授权码，请先绑定邮箱")
        with self.factory("imap.qq.com", 993, ssl_context=ssl.create_default_context(), timeout=20) as client:
            try:
                client.login(account, secret)
            except imaplib.IMAP4.error as error:
                raise RuntimeError("邮箱认证失败：请确认该邮箱已开启 IMAP，并使用新生成的完整授权码（不是授权码名称或 QQ 密码）") from error
            for folder in folders:
                if cancelled():
                    raise RuntimeError("邮箱同步已取消")
                typ, _ = client.select(mailbox_name(folder), readonly=True)
                if typ != "OK":
                    raise RuntimeError(f"无法读取文件夹：{folder}，请检查文件夹名称")
                if test_only:
                    continue
                validity_data = client.response("UIDVALIDITY")[1]
                if not validity_data or not validity_data[0]:
                    raise RuntimeError("邮箱未返回 UIDVALIDITY，无法安全保存同步位置")
                validity = validity_data[0].decode()
                checkpoint = checkpoints.get(folder, {})
                last = int(checkpoint.get("uid", 0)) if checkpoint.get("validity") == validity else 0
                if last:
                    typ, data = client.uid("search", None, "UID", f"{last + 1}:*")
                else:
                    since = datetime.now(CHINA) - timedelta(days=days)
                    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
                    typ, data = client.uid("search", None, "SINCE", f"{since.day:02d}-{months[since.month - 1]}-{since.year}")
                if typ != "OK":
                    raise RuntimeError("邮箱搜索失败，请稍后重试")
                uids = sorted(int(uid) for uid in (data[0] or b"").split() if int(uid) > last)
                if len(uids) > 200:
                    warnings.append(f"{folder} 还有 {len(uids) - 200} 封待同步，请再次点击查邮件")
                for uid in uids[:200]:
                    if cancelled():
                        raise RuntimeError("邮箱同步已取消")
                    typ, parts = client.uid("fetch", str(uid), "(INTERNALDATE RFC822.SIZE BODY.PEEK[]<0.2097152>)")
                    if typ != "OK":
                        raise RuntimeError("邮件读取失败，本次同步位置未推进，请重试")
                    literals = [p for p in parts if isinstance(p, tuple)]
                    if not literals:
                        raise RuntimeError("邮件已移动或读取结果为空，请重新同步")
                    header, raw = literals[0]
                    date_match = re.search(rb'INTERNALDATE "([^"]+)"', header)
                    received = None
                    if date_match:
                        try:
                            received = parsedate_to_datetime(date_match[1].decode().replace("-", " ", 2)).astimezone(CHINA)
                        except (ValueError, TypeError, OverflowError):
                            pass
                    parsed = parse_message(raw, received)
                    size = re.search(rb"RFC822.SIZE (\d+)", header)
                    if size and int(size[1]) > len(raw):
                        warnings.append(f"{folder} 有大邮件仅读取前 2MB，请到 QQ 邮箱查看附件及原文")
                    if parsed:
                        parsed["folder"] = folder
                        messages.append(parsed)
                    last = uid
                updates[folder] = {"validity": validity, "uid": last}
        return {"messages": messages, "checkpoints": updates, "warnings": warnings}


def reminder_key(mail: dict, now: datetime | None = None) -> str:
    if mail["state"] != "pending":
        return ""
    now = now or datetime.now(CHINA)
    levels = []
    for field in ("starts_at", "deadline"):
        if not mail[field]:
            continue
        hours = (datetime.fromisoformat(mail[field]) - now).total_seconds() / 3600
        level = "已到时间" if hours <= 0 else "3小时内" if hours <= 3 else "24小时内" if hours <= 24 else ""
        if level:
            levels.append(field + ":" + mail[field] + ":" + level)
    return "|".join(levels) or ("待核对" if not mail["deadline"] and not mail["starts_at"] else "")
