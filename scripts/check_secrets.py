#!/usr/bin/env python3
"""Deteta credenciais de formato conhecido sem revelar o valor encontrado."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PATTERNS = {
    "Anthropic API key": re.compile(rb"sk-ant-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})"),
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_-]{30,}"),
    "Slack token": re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        content = path.read_bytes()
    except OSError:
        return []
    if b"\0" in content:
        return []

    findings: list[tuple[int, str]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append((line_number, label))
    return findings


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = [
        (path.relative_to(root), line_number, label)
        for path in tracked_files(root)
        for line_number, label in scan_file(path)
    ]
    if not findings:
        print("Nenhum segredo de formato conhecido encontrado nos ficheiros versionados.")
        return 0

    print("Possíveis segredos encontrados (os valores foram ocultados):", file=sys.stderr)
    for path, line_number, label in findings:
        print(f"- {path}:{line_number}: {label}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
