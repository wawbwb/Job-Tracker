"""Mail persistence; all methods are called on the GUI/database thread."""
import json

from src.recruitment_mail import assessment_kind, informational_notice, match_jobs


class MailRepository:
    def __init__(self, database):
        self.db = database
        self.conn = database.connection
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS mail_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recruitment_mail (
                id INTEGER PRIMARY KEY, account TEXT NOT NULL, message_key TEXT NOT NULL,
                folder TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL,
                kind TEXT NOT NULL, received TEXT NOT NULL, sent TEXT NOT NULL,
                deadline TEXT NOT NULL, starts_at TEXT NOT NULL, estimated INTEGER NOT NULL,
                evidence TEXT NOT NULL, job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
                match_note TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                reminder TEXT NOT NULL DEFAULT '', UNIQUE(account, message_key)
            );
        """)
        self.conn.commit()
        self.review_cached_mail()

    def review_cached_mail(self):
        """Reclassify old automatic pending entries once, without deleting mail or user edits."""
        if self.setting("assessment_filter_version", 0) >= 1:
            return
        with self.conn:
            rows = self.conn.execute("""SELECT id, subject, body FROM recruitment_mail
                WHERE state='pending' AND evidence <> '用户手动核对' AND match_note <> '用户手动关联'""").fetchall()
            for row in rows:
                if informational_notice(row["subject"], row["body"]) and assessment_kind(row["subject"], row["body"]) is None:
                    self.conn.execute("""UPDATE recruitment_mail SET state='ignored', reminder='',
                        match_note='自动忽略：未发现实际测评或笔试任务，可能是隐私政策、流程说明或记录通知'
                        WHERE id=?""", (row["id"],))
            self.conn.execute("INSERT INTO mail_settings VALUES ('assessment_filter_version', '1') ON CONFLICT(key) DO UPDATE SET value='1'")

    def setting(self, key, default=None):
        row = self.conn.execute("SELECT value FROM mail_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        self.conn.execute("INSERT INTO mail_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))
        self.conn.commit()

    def checkpoints(self, account):
        return self.setting("checkpoints:" + account, {})

    def ingest(self, account, result):
        jobs = self.db.list_jobs()
        aliases = self.setting("aliases", {})
        added = 0
        with self.conn:
            for mail in result["messages"]:
                job_id, note = match_jobs(mail, jobs, aliases)
                values = {**mail, "account": account, "job_id": job_id, "match_note": note}
                cursor = self.conn.execute("""INSERT INTO recruitment_mail
                    (account,message_key,folder,subject,sender,body,kind,received,sent,deadline,starts_at,estimated,evidence,job_id,match_note)
                    VALUES (:account,:message_key,:folder,:subject,:sender,:body,:kind,:received,:sent,:deadline,:starts_at,:estimated,:evidence,:job_id,:match_note)
                    ON CONFLICT(account,message_key) DO NOTHING""", values)
                added += cursor.rowcount
            checkpoint = {**self.checkpoints(account), **result["checkpoints"]}
            self.conn.execute("INSERT INTO mail_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("checkpoints:" + account, json.dumps(checkpoint)))
        self.rematch(account)
        return added

    def rematch(self, account):
        jobs = self.db.list_jobs()
        aliases = self.setting("aliases", {})
        with self.conn:
            for mail in self.list_mail(account):
                if mail["job_id"] is None and mail["state"] == "pending" and mail["match_note"] != "用户手动关联":
                    job_id, note = match_jobs(mail, jobs, aliases)
                    self.conn.execute("UPDATE recruitment_mail SET job_id=?,match_note=? WHERE id=?", (job_id, note, mail["id"]))

    def list_mail(self, account):
        return [dict(row) for row in self.conn.execute("""SELECT m.*, j.company, j.position FROM recruitment_mail m
            LEFT JOIN jobs j ON j.id=m.job_id WHERE m.account=?
            ORDER BY CASE WHEN state='pending' THEN 0 ELSE 1 END,
            CASE WHEN deadline='' THEN 1 ELSE 0 END, deadline, received DESC""", (account,))]

    def update(self, mail_id, **values):
        allowed = {"state", "deadline", "starts_at", "estimated", "evidence", "job_id", "match_note", "reminder"}
        if not values or not set(values) <= allowed:
            raise ValueError("无效的邮件更新字段")
        self.conn.execute("UPDATE recruitment_mail SET " + ",".join(key + "=?" for key in values) + " WHERE id=?", (*values.values(), mail_id))
        self.conn.commit()
