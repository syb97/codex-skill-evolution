#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
}


@dataclass(frozen=True)
class PatternSpec:
    category: str
    pattern: re.Pattern[str]
    description: str


PATTERNS = [
    PatternSpec("local_path", re.compile(r"/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+"), "Local absolute path"),
    PatternSpec("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "Email address"),
    PatternSpec("private_key", re.compile(r"BEGIN [A-Z ]*PRIVATE KEY"), "Private key material"),
    PatternSpec("ssh_public_key", re.compile(r"ssh-ed25519 AAAA|ssh-rsa AAAA"), "SSH public key"),
    PatternSpec("api_key_like", re.compile(r"\b(?:sk|ghp|github_pat|cpa)_[A-Za-z0-9_\-]{12,}\b"), "API key-like token"),
    PatternSpec("session_secret", re.compile(r"\b(?:authenticity_token|user_session|_gh_sess)\b"), "Session or CSRF token field"),
    PatternSpec(
        "desktop_env",
        re.compile(r"\b(?:XAUTHORITY|DBUS_SESSION_BUS_ADDRESS|DISPLAY=|WAYLAND_DISPLAY)\b"),
        "Local desktop environment variable",
    ),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a repository tree for privacy-sensitive publish artifacts")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="Repository root to scan")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def should_skip(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in DEFAULT_EXCLUDED_DIRS for part in relative.parts)


def iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path, root):
            continue
        files.append(path)
    return sorted(files)


def collect_findings(root: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for spec in PATTERNS:
                match = spec.pattern.search(line)
                if not match:
                    continue
                findings.append(
                    {
                        "category": spec.category,
                        "description": spec.description,
                        "path": str(path.relative_to(root)),
                        "line": line_no,
                        "match": match.group(0),
                    }
                )
    return findings


def render_json(findings: list[dict[str, object]]) -> str:
    payload = {
        "overall_status": "ok" if not findings else "fail",
        "findings": findings,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_text(findings: list[dict[str, object]]) -> str:
    if not findings:
        return "overall: ok\n\n- no privacy findings"
    lines = ["overall: fail", ""]
    for item in findings:
        lines.append(f"- {item['category']}: {item['path']}:{item['line']} -> {item['match']}")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    findings = collect_findings(root)
    output = render_json(findings) if args.json else render_text(findings)
    print(output)
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
