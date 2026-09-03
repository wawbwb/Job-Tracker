"""Generic status extraction for custom recruitment portals."""

from __future__ import annotations

import re
from typing import Any


class OtherParser:
	def parse(self, page: Any) -> str:
		text = page.locator("body").inner_text()
		label_pattern = r"(?:当前进度|当前状态|申请状态|投递状态|应聘状态|应聘进度|流程状态)\s*[:：]?\s*([^\r\n|]{1,80})"
		match = re.search(label_pattern, text, re.IGNORECASE)
		if match:
			status = re.sub(r"\s+", " ", match.group(1)).strip(" ：:")
			if self._is_specific_status(status):
				return status
		labeled_status = self._extract_labeled_status(text)
		if labeled_status:
			return labeled_status
		progress_status = self._extract_progress_status(text)
		if progress_status:
			return progress_status

		fallback_statuses = []
		for selector in ("[class*='status']", "[class*='Status']", "[class*='stage']", "[class*='Stage']", "[data-status]"):
			try:
				for line in page.locator(selector).all_inner_texts():
					status = re.sub(r"\s+", " ", line).strip(" ：:")
					if self._is_specific_status(status):
						fallback_statuses.append(status)
			except Exception:
				continue
		if fallback_statuses:
			return max(fallback_statuses, key=self._status_score)

		body_statuses = []
		for line in (re.sub(r"\s+", " ", line).strip(" ：:") for line in text.splitlines()):
			if self._is_specific_status(line) and self._has_status_marker(line):
				body_statuses.append(line)
		if body_statuses:
			return max(body_statuses, key=self._status_score)
		return "未找到状态"

	@staticmethod
	def _is_specific_status(text: str) -> bool:
		if not 1 < len(text) <= 80 or OtherParser._is_page_description(text):
			return False
		return text not in {"进行中", "已结束", "已完成", "招聘中", "已关闭", "开放中"}

	@staticmethod
	def _extract_labeled_status(text: str) -> str:
		lines = [re.sub(r"\s+", " ", line).strip(" ：:") for line in text.splitlines()]
		labels = ("当前进度", "当前状态", "申请状态", "投递状态", "应聘状态", "应聘进度", "流程状态")
		for index, line in enumerate(lines):
			if not any(line.startswith(label) for label in labels):
				continue
			value = re.sub(r"^(?:当前进度|当前状态|申请状态|投递状态|应聘状态|应聘进度|流程状态)\s*[:：]?\s*", "", line).strip()
			if not value and index + 1 < len(lines):
				value = lines[index + 1]
			if OtherParser._is_specific_status(value):
				return value
		return ""

	@staticmethod
	def _status_score(text: str) -> int:
		markers = ("网申", "筛选", "面试", "笔试", "录用", "Offer", "offer", "通过", "成功", "终止", "淘汰", "待评估", "待审核", "待评审")
		return sum(marker in text for marker in markers) * 10 - len(text)

	@staticmethod
	def _has_status_marker(text: str) -> bool:
		markers = ("网申", "投递", "筛选", "面试", "笔试", "录用", "Offer", "offer", "通过", "成功", "终止", "淘汰", "待评估", "待审核", "待评审", "流程")
		return any(marker in text for marker in markers)

	@staticmethod
	def _is_page_description(text: str) -> bool:
		return any(phrase in text for phrase in (
			"跟进应聘进度", "查询投递记录", "投递记录", "应聘记录",
			"暂无进行中的岗位申请", "暂无待办", "请选择心仪岗位",
			"岗位投递", "我的申请", "我的投递", "扫描成功", "微信中轻触允许",
		))

	@staticmethod
	def _extract_progress_status(text: str) -> str:
		lines = [line.strip() for line in text.splitlines() if line.strip()]
		stage_markers = ("职位申请", "简历筛选", "考试", "测评", "面试", "Offer", "入职", "网申", "筛选", "简历投递", "岗位投递")
		status_markers = ("进行中", "待评估", "待审核", "待评审", "已完成", "已通过", "未通过", "成功", "失败")
		stage_pattern = "|".join(re.escape(marker) for marker in sorted(stage_markers, key=len, reverse=True))
		status_pattern = "|".join(re.escape(marker) for marker in sorted(status_markers, key=len, reverse=True))
		all_stages = list(re.finditer(stage_pattern, text, re.IGNORECASE))
		all_statuses = list(re.finditer(status_pattern, text, re.IGNORECASE))
		active_statuses = {"进行中", "待评估", "待审核", "待评审"}
		if all_stages and all_statuses:
			for status_index, match in enumerate(all_statuses):
				status = match.group(0)
				if status in active_statuses and status_index < len(all_stages):
					return f"{all_stages[status_index].group(0)}—{status}"

		candidates = []
		stages = []
		statuses = []
		for index, line in enumerate(lines):
			if line in status_markers and index > 0:
				previous = lines[index - 1]
				if any(marker in previous for marker in stage_markers):
					candidates.append((previous, line))
			if len(line) <= 30 and any(marker in line for marker in stage_markers):
				stages.append(line)
			if line in status_markers:
				statuses.append(line)
		if stages and statuses:
			for status_index, status in enumerate(statuses):
				if status in active_statuses and status_index < len(stages):
					return f"{stages[status_index]}—{status}"
		if not candidates:
			return ""
		active = [candidate for candidate in candidates if candidate[1] in active_statuses]
		stage, status = (active or candidates)[-1]
		return f"{stage}—{status}"
