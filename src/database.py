
"""SQLite persistence for the job tracker."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PLATFORMS = {"zhiye.com": "北森", "jobs.feishu.cn": "飞书", "mokahr.com": "Moka"}


def now_text() -> str:
	return datetime.now().strftime("%Y-%m-%d %H:%M")


def detect_platform(url: str) -> str:
	hostname = urlparse(url if "://" in url else f"https://{url}").hostname or ""
	hostname = hostname.lower().removeprefix("www.")
	for domain, platform in PLATFORMS.items():
		if hostname == domain or hostname.endswith(f".{domain}"):
			return platform
	return "其他"


class Database:
	def __init__(self, path: str | Path = "data/jobs.db") -> None:
		self.path = Path(path)
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.connection = sqlite3.connect(self.path)
		self.connection.row_factory = sqlite3.Row
		self.connection.execute("PRAGMA foreign_keys = ON")
		self.initialize()

	def initialize(self) -> None:
		self.connection.executescript(
			"""
			CREATE TABLE IF NOT EXISTS jobs (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				company TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '',
				location TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
				platform TEXT NOT NULL DEFAULT '其他', status TEXT NOT NULL DEFAULT '未查询',
				updated_at TEXT NOT NULL DEFAULT '', profile TEXT NOT NULL DEFAULT ''
			);
			CREATE UNIQUE INDEX IF NOT EXISTS jobs_company_url ON jobs(company, url)
				WHERE company <> '' AND url <> '';
			CREATE TABLE IF NOT EXISTS status_history (
				id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
				status TEXT NOT NULL, changed_at TEXT NOT NULL,
				FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
			);
			CREATE TABLE IF NOT EXISTS locations (name TEXT PRIMARY KEY);
			"""
		)
		self.connection.commit()

	def list_jobs(self) -> list[dict[str, Any]]:
		return [dict(row) for row in self.connection.execute("SELECT * FROM jobs ORDER BY id")]

	def get_job(self, job_id: int) -> dict[str, Any] | None:
		row = self.connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
		return dict(row) if row else None

	def save_job(self, values: dict[str, Any]) -> int:
		job_id = values.get("id")
		if job_id:
			existing = self.get_job(int(job_id))
			if existing:
				merged = {**existing, **values}
				values = merged
		fields = {
			"company": str(values.get("company", "")).strip(),
			"position": str(values.get("position", "")).strip(),
			"location": str(values.get("location", "")).strip(),
			"url": str(values.get("url", "")).strip(),
			"platform": detect_platform(str(values.get("url", "")).strip()),
			"status": str(values.get("status", "未查询")),
			"updated_at": str(values.get("updated_at", "")),
			"profile": str(values.get("profile", "")),
		}
		if job_id:
			job_id = int(job_id)
			conflict = self.connection.execute(
				"SELECT id FROM jobs WHERE company = ? AND url = ? AND id <> ? AND company <> '' AND url <> ''",
				(fields["company"], fields["url"], job_id),
			).fetchone()
			if conflict:
				job_id = int(conflict["id"])
				self.connection.execute("UPDATE jobs SET company=:company, position=:position, location=:location, url=:url, platform=:platform, status=:status, updated_at=:updated_at, profile=:profile WHERE id=:id", {**fields, "id": job_id})
				self.connection.execute("DELETE FROM jobs WHERE id = ?", (int(values["id"]),))
				if fields["location"]:
					self.connection.execute("INSERT OR IGNORE INTO locations(name) VALUES (?)", (fields["location"],))
				self.connection.commit()
				return job_id
			self.connection.execute("""UPDATE jobs SET company=:company, position=:position,
				location=:location, url=:url, platform=:platform, status=:status,
				updated_at=:updated_at, profile=:profile WHERE id=:id""", {**fields, "id": job_id})
		else:
			existing = self.connection.execute(
				"SELECT id FROM jobs WHERE company = ? AND url = ? AND company <> '' AND url <> ''",
				(fields["company"], fields["url"]),
			).fetchone()
			if existing:
				job_id = int(existing["id"])
				self.connection.execute("UPDATE jobs SET company=:company, position=:position, location=:location, url=:url, platform=:platform, status=:status, updated_at=:updated_at, profile=:profile WHERE id=:id", {**fields, "id": job_id})
			else:
				cursor = self.connection.execute("""INSERT INTO jobs
					(company, position, location, url, platform, status, updated_at, profile)
					VALUES (:company, :position, :location, :url, :platform, :status, :updated_at, :profile)""", fields)
				job_id = int(cursor.lastrowid)
		if fields["location"]:
			self.connection.execute("INSERT OR IGNORE INTO locations(name) VALUES (?)", (fields["location"],))
		self.connection.commit()
		return int(job_id)

	def update_status(self, job_id: int, status: str, updated_at: str | None = None) -> None:
		changed_at = updated_at or now_text()
		old = self.get_job(job_id)
		self.connection.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status, changed_at, job_id))
		if old and old["status"] != status:
			self.connection.execute("INSERT INTO status_history(job_id, status, changed_at) VALUES (?, ?, ?)", (job_id, status, changed_at))
		self.connection.commit()

	def delete_job(self, job_id: int) -> None:
		self.connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
		self.connection.commit()

	def locations(self) -> list[str]:
		return [row[0] for row in self.connection.execute("SELECT name FROM locations ORDER BY name")]

	def close(self) -> None:
		self.connection.close()
