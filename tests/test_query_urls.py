import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.browser.manager import BrowserManager
from src.urls import normalize_query_url


class QueryUrlTests(unittest.TestCase):
	def test_complete_links_keep_their_path_query_and_fragment(self):
		for url in (
			"https://seer-group.jobs.feishu.cn/apply/record?lang=zh-CN#applications",
			"http://localhost:8123/applications",
			"https://example.com/a%20b?redirect=https%3A%2F%2Fexample.com#record",
			"http://[::1]:8123/applications",
		):
			with self.subTest(url=url):
				self.assertEqual(normalize_query_url(f"  {url}  "), url)

	def test_missing_scheme_defaults_to_https(self):
		url = "seer-group.jobs.feishu.cn/apply/record?lang=zh-CN#applications"
		self.assertEqual(normalize_query_url(url), f"https://{url}")
		self.assertEqual(normalize_query_url(f"//{url}"), f"https://{url}")
		redirect_url = "example.com/login?redirect=https://example.com/apply#record"
		self.assertEqual(normalize_query_url(redirect_url), f"https://{redirect_url}")

	def test_abbreviations_explain_how_to_repair_the_link(self):
		for url in (
			"seer-group.jobs.feishu.cn/...",
			"https://seer-group.jobs.feishu.cn/...",
			"https://example.com/…",
			"https://example.com/%2E%2E%2E?lang=zh-CN",
		):
			with self.subTest(url=url):
				with self.assertRaisesRegex(ValueError, "缩略地址.*完整链接"):
					normalize_query_url(url)

	def test_invalid_links_are_rejected(self):
		for url in (
			"", "   ", "not-a-url", "https://", "https:///apply/record",
			"https://bad host.com", "https://example.com/a\nb", "https://[bad-ip]/",
			"https://example.com:invalid/", "https://example.com:65536/",
			"https://example.com\\apply", "javascript:alert(1)",
			"file:///C:/data/jobs.db", "ftp://example.com/apply",
		):
			with self.subTest(url=url):
				with self.assertRaises(ValueError):
					normalize_query_url(url)


class BrowserQueryUrlTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory(prefix="job_tracker_urls_")
		self.addCleanup(self.temp.cleanup)
		self.manager = BrowserManager(Path(self.temp.name) / "profiles")
		self.company = "测试公司"
		self.url = "seer-group.jobs.feishu.cn/apply/record?lang=zh-CN#applications"
		self.playwright = MagicMock()
		self.sync = patch("playwright.sync_api.sync_playwright")
		self.sync_mock = self.sync.start()
		self.addCleanup(self.sync.stop)
		self.sync_mock.return_value.__enter__.return_value = self.playwright

	def test_invalid_links_fail_before_starting_playwright_or_creating_profile(self):
		for method in (self.manager.fetch_status, self.manager.open_for_view):
			for url in ("seer-group.jobs.feishu.cn/...", "https:///", ""):
				with self.subTest(method=method.__name__, url=url):
					with self.assertRaises(ValueError):
						method(url, self.company)
		self.sync_mock.assert_not_called()
		self.assertFalse(self.manager.profile_for(self.company).parent.exists())

	def test_fetch_uses_the_complete_normalized_link_in_each_session_path(self):
		for mode in ("manual", "saved", "legacy"):
			with self.subTest(mode=mode):
				company = f"{self.company}_{mode}"
				state_path = self.manager.profile_for(company)
				if mode != "manual":
					state_path.parent.mkdir(parents=True)
					if mode == "saved":
						state_path.write_text("{}", encoding="utf-8")
					else:
						(state_path.parent / "legacy-marker").touch()
				context = MagicMock()
				page = context.new_page.return_value
				context.pages = [page]
				self.playwright.chromium.launch.return_value.new_context.return_value = context
				self.playwright.chromium.launch_persistent_context.return_value = context
				with (
					patch.object(self.manager, "_read_status", return_value="面试中"),
					patch.object(self.manager, "_read_authenticated_status", return_value="面试中"),
				):
					self.assertEqual(self.manager.fetch_status(self.url, company), "面试中")
				page.goto.assert_called_once_with(
					f"https://{self.url}", wait_until="domcontentloaded", timeout=60_000
				)

	def test_view_uses_the_complete_normalized_link(self):
		context = self.playwright.chromium.launch.return_value.new_context.return_value
		page = context.new_page.return_value
		page.is_closed.return_value = True
		self.manager.open_for_view(self.url, self.company)
		page.goto.assert_called_once_with(
			f"https://{self.url}", wait_until="domcontentloaded", timeout=60_000
		)


if __name__ == "__main__":
	unittest.main()
