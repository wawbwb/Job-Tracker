
"""Status extraction for Beisen delivery-record pages."""

from __future__ import annotations

import re
from typing import Any


class BeisenParser:
	STATUS_SELECTORS = (
		"text=当前进度",
		"text=投递进度",
		"[class*='progress']",
		"[class*='status']",
	)

	def parse(self, page: Any) -> str:
		for selector in self.STATUS_SELECTORS:
			try:
				locator = page.locator(selector).first
				if locator.count() and locator.is_visible():
					text = locator.inner_text().strip()
					status = self._status_from_text(text)
					if status:
						return status
			except Exception:
				continue
		try:
			return self._status_from_text(page.locator("body").inner_text()) or "未找到状态"
		except Exception:
			return "未找到状态"

	@staticmethod
	def _status_from_text(text: str) -> str:
		compact = re.sub(r"[ \t]+", " ", text).strip()
		match = re.search(r"(?:当前进度|投递进度)\s*[:：]?\s*([^\r\n]{2,80})", compact)
		if match:
			return match.group(1).strip(" ：:")
		return ""
