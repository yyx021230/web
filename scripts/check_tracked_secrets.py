#!/usr/bin/env python3
"""High-confidence secret scan for tracked and unignored source files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 2 * 1024 * 1024
SKIP_SUFFIXES = {
    ".apk", ".gif", ".ico", ".jar", ".jpeg", ".jpg", ".lock", ".pdf", ".png", ".webp",
}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{24,}"),
    "AWS access key": re.compile(r"(?<![A-Z0-9])AKIA[A-Z0-9]{16}(?![A-Z0-9])"),
    "GitHub token": re.compile(r"(?<![A-Za-z0-9_])gh[opsu]_[A-Za-z0-9]{30,}"),
}


def candidate_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    )
    return [ROOT / item.decode() for item in output.split(b"\0") if item]


findings: list[str] = []
for path in candidate_files():
    if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES or path.stat().st_size > MAX_TEXT_BYTES:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append(f"{path.relative_to(ROOT)}:{line}: {label}")

if findings:
    raise SystemExit("Potential secrets found:\n" + "\n".join(findings))

print("Tracked secret scan passed")
