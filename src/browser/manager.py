
"""Lightweight browser sessions and status retrieval."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Callable

from src.database import detect_platform
from src.parser.beisen import BeisenParser
from src.parser.feishu import FeishuParser
from src.parser.moka import MokaParser
from src.parser.other import OtherParser


logger = logging.getLogger(__name__)


class BrowserManager:
	def __init__(self, profiles_dir: str | Path = "data/profiles") -> None:
		self.profiles_dir = Path(profiles_dir)
		self.profiles_dir.mkdir(parents=True, exist_ok=True)

	def fetch_status(self, url: str, company: str, on_message: Callable[[str], None] | None = None) -> str:
		"""Reuse a small storage-state file and show a browser only when needed."""
		from playwright.sync_api import sync_playwright

		state_path = self.profile_for(company)
		state_path.parent.mkdir(parents=True, exist_ok=True)
		platform = detect_platform(url)
		logger.info("浏览器任务: company=%s platform=%s url=%s state=%s", company, platform, url, state_path)
		with sync_playwright() as playwright:
			legacy_files = [item for item in state_path.parent.iterdir() if item.name != "state.json"]
			context_options = {"storage_state": str(state_path)} if state_path.exists() else {}
			if not state_path.exists() and legacy_files:
				logger.info("发现旧版浏览器目录，尝试迁移: %s", state_path.parent)
				legacy_context = playwright.chromium.launch_persistent_context(
					str(state_path.parent), headless=True
				)
				try:
					legacy_page = legacy_context.pages[0] if legacy_context.pages else legacy_context.new_page()
					logger.info("旧版 profile 页面加载: %s", url)
					legacy_page.goto(url, wait_until="domcontentloaded", timeout=60_000)
					status = self._read_status(legacy_page, platform, attempts=1, stop_on_login=True)
					logger.info("旧版 profile 状态: %s", status)
					legacy_context.storage_state(path=str(state_path))
				finally:
					legacy_context.close()
				if status != "未找到状态":
					self._remove_legacy_files(state_path.parent, state_path)
					return status

			if state_path.exists():
				browser = playwright.chromium.launch(headless=True)
				logger.info("启动无头浏览器: company=%s", company)
				context = browser.new_context(**context_options)
				try:
					page = context.new_page()
					logger.info("无头页面加载: %s", url)
					page.goto(url, wait_until="domcontentloaded", timeout=60_000)
					status_attempts = 10 if platform == "飞书" else 3
					status = self._read_status(page, platform, attempts=status_attempts, stop_on_login=True)
					logger.info("无头状态结果: company=%s status=%s", company, status)
					if status != "未找到状态":
						context.storage_state(path=str(state_path))
						return status
				finally:
					context.close()
					browser.close()
			else:
				logger.info("未找到保存的登录状态，跳过无头等待: company=%s", company)

			logger.warning("需要人工登录或页面状态不可读，打开可见浏览器: company=%s", company)
			browser = playwright.chromium.launch(headless=False)
			context = browser.new_context(**context_options)
			try:
				page = context.new_page()
				page.goto(url, wait_until="domcontentloaded", timeout=60_000)
				logger.info("可见页面已加载，等待登录或状态: company=%s", company)
				initial_session = self._session_fingerprint(context)
				if on_message:
					on_message("需要登录，请在浏览器中完成登录")
				status = self._read_authenticated_status(page, context, platform, initial_session, attempts=60)
				logger.info("可见浏览器状态结果: company=%s status=%s", company, status)
				context.storage_state(path=str(state_path))
				self._remove_legacy_files(state_path.parent, state_path)
				return status
			finally:
				context.close()
				browser.close()

	def open_for_view(self, url: str, company: str, on_message: Callable[[str], None] | None = None) -> None:
		"""Open a visible page with the saved session and keep it open for manual viewing."""
		from playwright.sync_api import sync_playwright

		state_path = self.profile_for(company)
		state_path.parent.mkdir(parents=True, exist_ok=True)
		context_options = {"storage_state": str(state_path)} if state_path.exists() else {}
		logger.info("打开网页查看: company=%s url=%s state=%s", company, url, state_path)
		with sync_playwright() as playwright:
			browser = playwright.chromium.launch(headless=False)
			context = browser.new_context(**context_options)
			try:
				page = context.new_page()
				page.goto(url, wait_until="domcontentloaded", timeout=60_000)
				logger.info("网页查看已打开: company=%s", company)
				if on_message:
					on_message("网页已打开，可直接查看或完成登录")
				try:
					while not page.is_closed():
						page.wait_for_timeout(1_000)
					context.storage_state(path=str(state_path))
				except Exception as error:
					if "TargetClosedError" not in type(error).__name__:
						raise
					logger.info("用户已关闭查看窗口: company=%s", company)
			finally:
				try:
					context.close()
				finally:
					browser.close()
		logger.info("网页查看已关闭: company=%s", company)

	def _read_status(self, page: object, platform: str, attempts: int, stop_on_login: bool = False) -> str:
		for attempt in range(1, attempts + 1):
			if stop_on_login and self._looks_like_login_page(page):
				return "未找到状态"
			status = self._parse_platform(page, platform)
			if status != "未找到状态":
				return status
			if attempt in (1, attempts):
				logger.debug("状态未找到: platform=%s attempt=%s/%s", platform, attempt, attempts)
			page.wait_for_timeout(2_000)
		return self._parse_platform(page, platform)

	def _read_authenticated_status(
		self, page: object, context: object, platform: str, initial_session: tuple, attempts: int
	) -> str:
		for attempt in range(1, attempts + 1):
			if (
				(self._session_fingerprint(context) != initial_session or self._has_authenticated_content(page))
				and not self._looks_like_login_page(page)
				and not self._looks_like_login_prompt(page)
			):
				status = self._parse_platform(page, platform)
				if status != "未找到状态":
					return status
			if attempt in (1, attempts):
				logger.debug("等待登录会话: platform=%s attempt=%s/%s", platform, attempt, attempts)
			page.wait_for_timeout(2_000)
		return "未找到状态"

	@staticmethod
	def _session_fingerprint(context: object) -> tuple:
		try:
			cookies = context.cookies()
			keys = (
				"token", "session", "auth", "login", "access", "user", "sid", "jwt", "openid",
			)
			cookie_values = tuple(sorted(
				(cookie.get("name", ""), cookie.get("value", ""))
				for cookie in cookies
				if any(key in cookie.get("name", "").lower() for key in keys)
			))
			storage_values = []
			for origin in context.storage_state().get("origins", []):
				for item in origin.get("localStorage", []):
					name = item.get("name", "")
					if any(key in name.lower() for key in keys):
						storage_values.append((name, item.get("value", "")))
			return cookie_values + tuple(sorted(storage_values))
		except Exception:
			return ()

	@staticmethod
	def _looks_like_login_page(page: object) -> bool:
		try:
			text = page.locator("body").inner_text()
			if BrowserManager._has_authenticated_content(page):
				return False
			return any(phrase in text for phrase in ("请登录", "登录/注册", "登录注册", "立即登录"))
		except Exception:
			return False

	@staticmethod
	def _looks_like_login_prompt(page: object) -> bool:
		try:
			text = page.locator("body").inner_text()
			return any(phrase in text for phrase in ("扫码", "扫描成功", "微信中轻触", "点击允许", "验证码登录"))
		except Exception:
			return False

	@staticmethod
	def _has_authenticated_content(page: object) -> bool:
		try:
			text = page.locator("body").inner_text()
			markers = ("投递记录", "应聘记录", "候选人", "个人资料", "申请成功", "当前进度", "当前状态")
			return any(marker in text for marker in markers)
		except Exception:
			return False

	@staticmethod
	def _parse_platform(page: object, platform: str) -> str:
		if platform == "北森":
			return BeisenParser().parse(page)
		if platform == "Moka":
			return MokaParser().parse(page)
		if platform == "飞书":
			return FeishuParser().parse(page)
		return OtherParser().parse(page)

	def profile_for(self, company: str) -> Path:
		return self.profiles_dir / self._safe_name(company) / "state.json"

	@staticmethod
	def _remove_legacy_files(folder: Path, state_path: Path) -> None:
		for item in folder.iterdir():
			if item == state_path:
				continue
			if item.is_dir():
				shutil.rmtree(item, ignore_errors=True)
			else:
				item.unlink(missing_ok=True)

	@staticmethod
	def _safe_name(company: str) -> str:
		name = "".join(char for char in company if char not in '<>:"/\\|?*').strip()
		return name or "未命名公司"
