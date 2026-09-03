"""Status extraction for Feishu Jobs candidate pages."""

from __future__ import annotations

import re
from typing import Any


class FeishuParser:
	STATUS_WORDS = (
		"流程终止", "流程结束", "已终止", "已结束", "已淘汰", "已撤回", "已关闭",
		"投递成功", "简历筛选中", "筛选通过", "面试通过", "已发放offer", "已录用", "待入职",
		"已入职", "不合适", "淘汰", "投递简历", "已投递", "待筛选", "筛选中", "简历筛选",
		"待沟通", "面试中", "一面", "二面", "终面", "笔试中", "已通过", "offer", "Offer", "录用",
	)
	SELECTORS = (
		"[class*='status']", "[class*='Status']", "[class*='stage']",
		"[class*='Stage']", "[class*='progress']", "[class*='Progress']",
		"[id*='status']", "[id*='stage']", "[aria-label*='status']",
		"[data-status]", "[data-stage]", "[data-testid*='status']", "[data-testid*='stage']",
	)

	def parse(self, page: Any) -> str:
		try:
			body = page.locator("body").inner_text()
			application_text = self._application_section(body)
			if application_text:
				status = self._find_status(application_text)
				if status:
					return status
		except Exception:
			pass
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
			return self._find_status(page.locator("body").inner_text()) or "未找到状态"
		except Exception:
			return "未找到状态"

	@classmethod
	def _find_status(cls, text: str) -> str:
		compact = re.sub(r"[ \t]+", " ", text).strip()
		pattern = "|".join(re.escape(word) for word in sorted(cls.STATUS_WORDS, key=len, reverse=True))
		matches = list(re.finditer(pattern, compact))
		if matches:
			return matches[-1].group(0)
		match = re.search(r"(?:申请状态|投递状态|当前状态|应聘进度)\s*[:：]?\s*([^\r\n|]{2,30})", compact)
		return match.group(1).strip(" ：:") if match else ""

	@staticmethod
	def _clean_status(text: str) -> str:
		return re.sub(r"\s+", " ", text).strip(" ：:\r\n")

	@staticmethod
	def _looks_like_container(text: str) -> bool:
		return len(text) > 80 or "\n" in text

	@staticmethod
	def _application_section(text: str) -> str:
		match = re.search(r"应聘记录(.*?)(?:修改志愿顺序|常见问题|招聘流程|联系我们|$)", text, re.S)
		return match.group(1) if match else ""