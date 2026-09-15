"""Check the release archive for required runtimes and accidental private files."""
import hashlib
import json
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader


def main():
    exe = Path(__file__).resolve().parent.parent / "dist" / "JobTracker.exe"
    archive = CArchiveReader(str(exe))
    entries = [name.replace("\\", "/") for name in archive.toc]
    forbidden = [name for name in entries if name.rsplit("/", 1)[-1] in
                 ("jobs.db", "state.json", ".env", "mail_credentials.json", "qq_mail_credentials.json")]
    if forbidden:
        raise RuntimeError(f"Private files found: {forbidden}")
    for prefix in ("browsers/chromium-", "browsers/chromium_headless_shell-", "PyQt6/"):
        if not any(name.startswith(prefix) for name in entries):
            raise RuntimeError(f"Missing runtime: {prefix}")
    digest = hashlib.sha256()
    with exe.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    report = {"file": exe.name, "bytes": exe.stat().st_size,
              "sha256": digest.hexdigest(), "archive_entries": len(entries), "private_files": forbidden}
    (exe.parent / "release-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
