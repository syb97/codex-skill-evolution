#!/usr/bin/env python3
"""Detect skill usage and keep the retrospective workflow from being skipped."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
PLUGIN_ROOT = SCRIPT_PATH.parents[1]
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(SCRIPT_PATH.parents[3]))).expanduser()
ASSET_SCRIPT = CODEX_HOME / "scripts" / "skill_evolution.py"
sys.path.insert(0, str(CODEX_HOME / "scripts"))

import skill_evolution  # noqa: E402


PATH_PATTERN = re.compile(r"(?:~|/|\./|\.\./)[^\s\"'<>]*SKILL\.md")


def iter_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(iter_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(iter_strings(item))
    return strings


def normalize_candidate(raw: str) -> str:
    candidate = raw.strip().strip("\"'`")
    while candidate and candidate[-1] in ",.;:)]}":
        candidate = candidate[:-1]
    return candidate


def resolve_candidate(raw: str) -> Path | None:
    candidate = normalize_candidate(raw)
    if not candidate.endswith("SKILL.md"):
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if not path.exists() or path.name != "SKILL.md":
        return None
    return path


def extract_skill_paths(raw_stdin: str) -> list[tuple[Path, Path]]:
    candidates: dict[str, tuple[Path, Path]] = {}
    string_values = [raw_stdin]
    try:
        parsed = json.loads(raw_stdin)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        string_values.extend(iter_strings(parsed))

    for text in string_values:
        if "SKILL.md" not in text:
            continue
        for match in PATH_PATTERN.findall(text):
            observed = resolve_candidate(match)
            if observed is None:
                continue
            canonical = skill_evolution.normalize_skill_path(observed)
            if not skill_evolution.is_allowed_skill_path(canonical, writable=False):
                continue
            candidates[str(canonical)] = (observed, canonical)
    return sorted(candidates.values(), key=lambda item: str(item[1]))


def format_skill_list(items: list[dict[str, Any]]) -> str:
    names = sorted({item["skill_name"] for item in items})
    return ", ".join(names)


def print_detection_message(skill_names: list[str]) -> None:
    skill_label = ", ".join(sorted(set(skill_names)))
    print(
        "[skill-evolution] "
        f"Detected skill use in this session: {skill_label}. "
        "Before the final answer, run a mandatory retrospective. "
        f"If there is reusable learning, run `python3 {ASSET_SCRIPT} record ...` and wait for approval. "
        f"If there is no reusable learning, run `python3 {ASSET_SCRIPT} mark-retrospective --outcome no_reusable_learning`."
    )


def print_pending_message(status: dict[str, Any]) -> None:
    print(
        "[skill-evolution] "
        f"Pending skill retrospective for: {format_skill_list(status['skills_used'])}. "
        "Do not finish silently. Before the final answer, emit exactly one of: "
        "`Skill retrospective: no reusable learning` or "
        "`Skill retrospective: proposal created <proposal-id>, waiting for approval`."
    )


def main() -> int:
    raw_stdin = sys.stdin.read()
    session_id = skill_evolution.resolve_session_id(os.environ.get(skill_evolution.DEFAULT_SESSION_ENV))
    cwd = os.getcwd()
    tool_name = None
    try:
        payload = json.loads(raw_stdin)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        tool_name = payload.get("tool_name") or payload.get("toolName")

    detected_skill_names: list[str] = []
    for _observed_path, skill_path in extract_skill_paths(raw_stdin):
        _, _, new_skill = skill_evolution.add_skill_usage(
            session_id=session_id,
            cwd=cwd,
            skill_name=skill_evolution.infer_skill_name(skill_path),
            skill_path=skill_path,
            source="hook-detected",
            tool_name=tool_name,
        )
        if new_skill:
            detected_skill_names.append(skill_evolution.infer_skill_name(skill_path))

    status = skill_evolution.session_status_payload(
        session_id,
        cwd=cwd,
        cooldown_seconds=skill_evolution.DEFAULT_REMINDER_COOLDOWN_SECONDS,
    )

    if detected_skill_names:
        skill_evolution.touch_reminder(session_id, cwd)
        print_detection_message(detected_skill_names)
        return 0

    if status["should_emit_reminder"]:
        skill_evolution.touch_reminder(session_id, cwd)
        print_pending_message(status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
