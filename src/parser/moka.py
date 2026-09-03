"""Status extraction for Moka candidate portals."""

from __future__ import annotations

import re
from typing import Any


class MokaParser:
	STATUS_WORDS = (
		"申请成功", "申请失败", "申请已提交", "已投递", "投递成功", "简历筛选中", "简历筛选", "筛选中", "筛选通过", "初筛", "简历评估", "待评估", "待沟通",
		"面试中", "面试通过", "笔试中", "待面试", "offer", "Offer", "已发放offer",
		"已录用", "录用", "待入职", "已入职", "流程中", "进行中", "流程结束", "不合适", "已淘汰",
		"淘汰", "已撤回", "已关闭",
	)
	SELECTORS = (
		"[class*='status']", "[class*='Status']", "[class*='stage']",
		"[class*='Stage']", "[class*='progress']", "[class*='Progress']",
		"[id*='status']", "[id*='stage']", "[aria-label*='status']",
		"[data-status]", "[data-stage]", "[data-testid*='status']", "[data-testid*='stage']",
	)

	def parse(self, page: Any) -> str:
		for selector in self.SELECTORS:
			try:
				locator = page.locator(selector)
				for index in range(locator.count()):
					element = locator.nth(index)
					for attribute in ("data-status", "data-stage", "aria-label"):
						status = self._clean_status(element.get_attribute(attribute) or "")
						if status and status.lower() not in {"status", "stage", "progress"}:
							return status
				for text in locator.all_inner_texts():
					status = self._clean_status(text)
					if status and not self._looks_like_container(text):
						return status
			except Exception:
				continue
		try:
			body = page.locator("body").inner_text()
			return self._find_status(body) or "未找到状态"
		except Exception:
			return "未找到状态"

	@staticmethod
	def _clean_status(text: str) -> str:
		return re.sub(r"\s+", " ", text).strip(" ：:\r\n")

	@staticmethod
	def _looks_like_container(text: str) -> bool:
		return len(text) > 80 or "\n" in text

	@classmethod
	def _find_status(cls, text: str) -> str:
		compact = re.sub(r"[ \t]+", " ", text).strip()
		match = re.search(r"(?:当前进度|当前状态|申请状态|投递状态|应聘进度)\s*[:：]?\s*([^\r\n|]{1,40})", compact)
		if match:
			return match.group(1).strip(" ：:")
		for word in cls.STATUS_WORDS:
			if word in compact:
				return word
		match = re.search(r"(?:申请状态|投递状态|当前状态|应聘进度)\s*[:：]?\s*([^\r\n|]{2,30})", compact)
		return match.group(1).strip(" ：:") if match else ""