"""Validate query links before starting a browser."""

import re
from urllib.parse import unquote, urlsplit


def normalize_query_url(url: str) -> str:
	"""Accept web links with an optional scheme, but never display abbreviations."""
	url = url.strip()
	if not url:
		raise ValueError("查询 URL 为空，请填写完整网页地址")
	if any(char.isspace() or ord(char) < 32 for char in url) or "\\" in url:
		raise ValueError("查询 URL 无效，请填写完整的 http:// 或 https:// 网页地址")
	if url.startswith("//"):
		url = f"https:{url}"
	elif not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", url):
		url = f"https://{url}"
	try:
		parsed = urlsplit(url)
		hostname = parsed.hostname or ""
		port = parsed.port
	except ValueError as error:
		raise ValueError("查询 URL 格式无效，请检查域名和端口") from error
	if any(part in ("...", "…") for part in unquote(parsed.path).split("/")):
		raise ValueError("查询 URL 是缩略地址，缺少完整路径；请双击查询 URL，重新粘贴浏览器地址栏中的完整链接")
	if (
		parsed.scheme not in ("http", "https")
		or not hostname
		or not ("." in hostname or ":" in hostname or hostname == "localhost")
		or any(char in hostname for char in "%<>\"'")
		or parsed.username is not None
		or parsed.password is not None
		or port == 0
	):
		raise ValueError("查询 URL 无效，请填写完整的 http:// 或 https:// 网页地址")
	return url
