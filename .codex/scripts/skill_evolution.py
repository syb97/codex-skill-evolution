#!/usr/bin/env python3
"""Review-queue workflow for safe skill evolution in Codex."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


HOME_DIR = Path(os.environ.get("HOME", str(Path.home()))).expanduser()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", str(Path(__file__).resolve().parents[1]))).expanduser()
SKILLS_DIR = CODEX_HOME / "skills"
USER_SKILLS_DIR = Path(os.environ.get("AGENTS_SKILLS_DIR", str(HOME_DIR / ".agents" / "skills"))).expanduser()
LEARNINGS_DIR = CODEX_HOME / "skill-learnings"
PROPOSALS_DIR = CODEX_HOME / "skill-proposals"
BACKUPS_DIR = CODEX_HOME / "skill-backups"
STATE_DIR = CODEX_HOME / "skill-evolution-state"
SESSIONS_DIR = STATE_DIR / "sessions"
CHANGE_LOG_PATH = CODEX_HOME / "skill-change-log.jsonl"
AGENTS_PATH = CODEX_HOME / "AGENTS.md"
DEFAULT_SESSION_ENV = "CODEX_THREAD_ID"
DEFAULT_REMINDER_COOLDOWN_SECONDS = 180
ALLOWED_STATUSES = {"proposed", "approved", "rejected", "applied"}
ALLOWED_KINDS = {
    "project-convention",
    "workflow-improvement",
    "new-capability",
    "recurring-failure",
}
RETROSPECTIVE_OUTCOMES = {"no_reusable_learning", "proposal_created"}
MARKER_PREFIX = "skill-evolution-proposal"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def ensure_dirs() -> None:
    for path in (LEARNINGS_DIR, PROPOSALS_DIR, BACKUPS_DIR, SESSIONS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "proposal"


def sanitize_session_id(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    return sanitized or "default-session"


def resolve_session_id(raw_session_id: str | None) -> str:
    return sanitize_session_id(raw_session_id or os.environ.get(DEFAULT_SESSION_ENV, "default-session"))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def infer_skill_path(skill_name: str) -> Path | None:
    for root in get_readable_skill_roots():
        candidate = root / skill_name / "SKILL.md"
        if candidate.exists():
            return normalize_skill_path(candidate)
    return None


def infer_skill_name(skill_path: Path) -> str:
    return skill_path.parent.name


def is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def normalize_skill_path(path: Path) -> Path:
    return path.expanduser().resolve()


def get_readable_skill_roots() -> list[Path]:
    roots = [
        SKILLS_DIR,
        SKILLS_DIR / ".system",
        USER_SKILLS_DIR,
    ]
    return [root for root in roots if root.exists()]


def get_writable_skill_roots() -> list[Path]:
    roots = [
        SKILLS_DIR,
        USER_SKILLS_DIR,
    ]
    return [root for root in roots if root.exists()]


def is_system_skill_path(path: Path) -> bool:
    return is_within(normalize_skill_path(path), SKILLS_DIR / ".system")


def is_allowed_skill_path(path: Path, *, writable: bool) -> bool:
    roots = get_writable_skill_roots() if writable else get_readable_skill_roots()
    normalized = normalize_skill_path(path)
    return any(is_within(normalized, root) for root in roots)


def validate_destination(target_type: str, destination_path: Path) -> None:
    resolved = normalize_skill_path(destination_path)
    if target_type == "agents_md":
        if resolved != AGENTS_PATH.resolve():
            raise ValueError(f"AGENTS.md proposals must target {AGENTS_PATH}")
        return

    if target_type == "skill_md":
        if not is_allowed_skill_path(resolved, writable=True):
            raise ValueError("Skill proposals must target a path under a writable skills root")
        if not str(resolved).endswith("/SKILL.md"):
            raise ValueError("Skill proposals must target a SKILL.md file")
        if is_system_skill_path(resolved):
            raise ValueError("System skills are read-only for auto-apply; route to AGENTS.md or a new custom skill")
        return

    if target_type == "new_skill":
        if not is_allowed_skill_path(resolved, writable=True):
            raise ValueError("New skills must be created under a writable skills root")
        if not str(resolved).endswith("/SKILL.md"):
            raise ValueError("New skill destination must be a SKILL.md path")
        if is_system_skill_path(resolved):
            raise ValueError("New skills cannot be created inside .system")
        return

    if target_type == "test_checklist_script":
        allowed_roots = [
            CODEX_HOME / "scripts",
            CODEX_HOME / "checklists",
            CODEX_HOME / "tests",
            SKILLS_DIR,
        ]
        if not any(is_within(resolved, root) for root in allowed_roots):
            joined = ", ".join(str(root) for root in allowed_roots)
            raise ValueError(f"Hardening artifacts must live under one of: {joined}")
        if is_within(resolved, SKILLS_DIR / ".system"):
            raise ValueError("Hardening artifacts cannot be written inside .system")
        return

    raise ValueError(f"Unknown target type: {target_type}")


def classify_destination(
    *,
    problem_kind: str,
    skill_name: str,
    skill_path: str | None,
    destination_path: str | None,
) -> tuple[str, Path, str, str]:
    inferred_path = normalize_skill_path(Path(skill_path)) if skill_path else infer_skill_path(skill_name)
    system_skill = bool(inferred_path and is_system_skill_path(inferred_path))

    if problem_kind == "project-convention":
        return (
            "agents_md",
            AGENTS_PATH,
            "append",
            "Project-level conventions should be routed to AGENTS.md.",
        )

    if problem_kind == "workflow-improvement":
        if system_skill:
            return (
                "agents_md",
                AGENTS_PATH,
                "append",
                "The learning came from a system skill, so the safe default is to update AGENTS.md instead of patching .system.",
            )
        if inferred_path is None:
            return (
                "agents_md",
                AGENTS_PATH,
                "append",
                "The source skill path could not be resolved, so the safe fallback is AGENTS.md.",
            )
        return (
            "skill_md",
            inferred_path,
            "append",
            "Workflow improvements for a custom skill should update that skill's SKILL.md.",
        )

    if problem_kind == "new-capability":
        if not destination_path:
            raise ValueError("new-capability proposals require --destination-path for the new skill")
        return (
            "new_skill",
            Path(destination_path).expanduser(),
            "create",
            "Independent reusable workflows should be split into a new skill.",
        )

    if problem_kind == "recurring-failure":
        if not destination_path:
            raise ValueError("recurring-failure proposals require --destination-path for the hardening artifact")
        return (
            "test_checklist_script",
            Path(destination_path).expanduser(),
            "create",
            "Repeatable mistakes should be hardened with a test, checklist, or script rather than text-only rules.",
        )

    raise ValueError(f"Unsupported problem kind: {problem_kind}")


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{sanitize_session_id(session_id)}.json"


def build_session_state(session_id: str, cwd: str | None) -> dict[str, Any]:
    now = utc_now()
    return {
        "session_id": session_id,
        "cwd": cwd,
        "created_at": now,
        "updated_at": now,
        "skills_used": [],
        "retrospective": {
            "status": "not_started",
            "completed_at": None,
            "outcome": None,
            "proposal_id": None,
            "note": None,
        },
        "reminder": {
            "last_emitted_at": None,
        },
    }


def load_session_state(session_id: str, cwd: str | None = None) -> tuple[Path, dict[str, Any]]:
    ensure_dirs()
    path = session_path(session_id)
    if path.exists():
        state = read_json(path)
        if cwd and not state.get("cwd"):
            state["cwd"] = cwd
        return path, state
    return path, build_session_state(session_id, cwd)


def save_session_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    write_json(path, state)


def find_skill_usage_entry(state: dict[str, Any], skill_path: str) -> dict[str, Any] | None:
    for item in state.get("skills_used", []):
        if item.get("skill_path") == skill_path:
            return item
    return None


def add_skill_usage(
    *,
    session_id: str,
    cwd: str,
    skill_name: str,
    skill_path: Path,
    source: str,
    tool_name: str | None = None,
) -> tuple[dict[str, Any], bool, bool]:
    path, state = load_session_state(session_id, cwd)
    skill_path_str = str(skill_path.resolve())
    now = utc_now()
    entry = find_skill_usage_entry(state, skill_path_str)
    new_skill = entry is None

    if entry is None:
        state["skills_used"].append(
            {
                "skill_name": skill_name,
                "skill_path": skill_path_str,
                "first_detected_at": now,
                "last_detected_at": now,
                "source": source,
                "last_tool_name": tool_name,
            }
        )
    else:
        entry["last_detected_at"] = now
        entry["source"] = source
        entry["last_tool_name"] = tool_name

    retrospective = state["retrospective"]
    if retrospective["status"] in {"not_started", "completed"} and new_skill:
        retrospective["status"] = "pending"
        retrospective["completed_at"] = None
        retrospective["outcome"] = None
        retrospective["proposal_id"] = None
        retrospective["note"] = None

    save_session_state(path, state)
    return state, True, new_skill


def mark_retrospective(
    *,
    session_id: str,
    cwd: str | None,
    outcome: str,
    proposal_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if outcome not in RETROSPECTIVE_OUTCOMES:
        joined = ", ".join(sorted(RETROSPECTIVE_OUTCOMES))
        raise ValueError(f"Retrospective outcome must be one of: {joined}")

    path, state = load_session_state(session_id, cwd)
    state["retrospective"] = {
        "status": "completed",
        "completed_at": utc_now(),
        "outcome": outcome,
        "proposal_id": proposal_id,
        "note": note,
    }
    save_session_state(path, state)
    return state


def session_status_payload(
    session_id: str,
    *,
    cwd: str | None,
    cooldown_seconds: int,
) -> dict[str, Any]:
    _, state = load_session_state(session_id, cwd)
    last_emitted_at = parse_utc(state["reminder"].get("last_emitted_at"))
    pending = bool(state.get("skills_used")) and state["retrospective"]["status"] == "pending"
    should_emit_reminder = pending
    if pending and last_emitted_at is not None:
        should_emit_reminder = datetime.now(timezone.utc) - last_emitted_at >= timedelta(seconds=cooldown_seconds)

    return {
        "session_id": session_id,
        "cwd": state.get("cwd"),
        "skills_used": state.get("skills_used", []),
        "retrospective": state.get("retrospective", {}),
        "pending": pending,
        "should_emit_reminder": should_emit_reminder,
        "reminder": state.get("reminder", {}),
    }


def touch_reminder(session_id: str, cwd: str | None) -> dict[str, Any]:
    path, state = load_session_state(session_id, cwd)
    state["reminder"]["last_emitted_at"] = utc_now()
    save_session_state(path, state)
    return state


def build_record_payload(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    if args.problem_kind not in ALLOWED_KINDS:
        raise ValueError(f"--problem-kind must be one of: {', '.join(sorted(ALLOWED_KINDS))}")

    target_type, destination_path, change_mode, classification_reason = classify_destination(
        problem_kind=args.problem_kind,
        skill_name=args.skill_name,
        skill_path=args.skill_path,
        destination_path=args.destination_path,
    )
    validate_destination(target_type, destination_path)

    proposal_id = args.proposal_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{slugify(args.skill_name)}"
    learning_id = proposal_id
    created_at = utc_now()
    session_id = resolve_session_id(args.session_id)
    effective_skill_path = str(Path(args.skill_path).expanduser()) if args.skill_path else None
    if effective_skill_path is None:
        inferred = infer_skill_path(args.skill_name)
        effective_skill_path = str(inferred) if inferred else None

    learning = {
        "learning_id": learning_id,
        "created_at": created_at,
        "session_id": session_id,
        "cwd": args.cwd,
        "skill_name": args.skill_name,
        "skill_path": effective_skill_path,
        "trigger_scenario": args.trigger_scenario,
        "problem": args.problem,
        "problem_kind": args.problem_kind,
        "reusable_rationale": args.reusable_rationale,
        "suggested_target_type": target_type,
        "suggested_destination_path": str(destination_path),
        "classification_reason": classification_reason,
        "notes": args.notes,
        "source": "task-retrospective",
    }

    proposal = {
        "proposal_id": proposal_id,
        "status": "proposed",
        "created_at": created_at,
        "updated_at": created_at,
        "learning_id": learning_id,
        "skill_name": args.skill_name,
        "skill_path": effective_skill_path,
        "trigger_scenario": args.trigger_scenario,
        "problem": args.problem,
        "problem_kind": args.problem_kind,
        "reusable_rationale": args.reusable_rationale,
        "recommended_target_type": target_type,
        "recommended_destination_path": str(destination_path),
        "classification_reason": classification_reason,
        "change_mode": change_mode,
        "proposed_text": args.proposed_text,
        "risk": args.risk,
        "notes": args.notes,
        "approval": {
            "reviewed_at": None,
            "review_note": None,
        },
        "apply": {
            "applied_at": None,
            "backup_path": None,
            "destination_existed": None,
            "last_change": None,
        },
    }
    return learning, proposal


def cmd_record(args: argparse.Namespace) -> int:
    ensure_dirs()
    learning, proposal = build_record_payload(args)
    if args.dry_run:
        print(json.dumps({"learning": learning, "proposal": proposal}, indent=2, ensure_ascii=True))
        return 0

    learning_path = LEARNINGS_DIR / f"{learning['learning_id']}.json"
    proposal_path = PROPOSALS_DIR / f"{proposal['proposal_id']}.json"
    write_json(learning_path, learning)
    write_json(proposal_path, proposal)
    if learning["skill_path"]:
        add_skill_usage(
            session_id=learning["session_id"],
            cwd=learning["cwd"],
            skill_name=learning["skill_name"],
            skill_path=Path(learning["skill_path"]),
            source="record-command",
            tool_name=None,
        )
    mark_retrospective(
        session_id=learning["session_id"],
        cwd=learning["cwd"],
        outcome="proposal_created",
        proposal_id=proposal["proposal_id"],
        note="Proposal created from task retrospective.",
    )
    print(f"Recorded learning: {learning_path}")
    print(f"Generated proposal: {proposal_path}")
    return 0


def iter_proposals() -> list[tuple[Path, dict[str, Any]]]:
    ensure_dirs()
    items: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(PROPOSALS_DIR.glob("*.json")):
        payload = read_json(path)
        items.append((path, payload))
    items.sort(key=lambda pair: pair[1].get("created_at", ""), reverse=True)
    return items


def render_proposal_summary(path: Path, proposal: dict[str, Any], full: bool = False) -> str:
    lines = [
        f"{proposal['proposal_id']} [{proposal['status']}]",
        f"  file: {path}",
        f"  skill: {proposal['skill_name']}",
        f"  target: {proposal['recommended_target_type']}",
        f"  destination: {proposal['recommended_destination_path']}",
        f"  scenario: {proposal['trigger_scenario']}",
        f"  problem: {proposal['problem']}",
    ]
    if full:
        lines.extend(
            [
                f"  reusable_rationale: {proposal['reusable_rationale']}",
                f"  risk: {proposal['risk']}",
                "  proposed_text:",
                indent_block(proposal["proposed_text"], prefix="    "),
            ]
        )
    return "\n".join(lines)


def indent_block(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def cmd_review(args: argparse.Namespace) -> int:
    items = iter_proposals()
    if args.proposal_id:
        path = PROPOSALS_DIR / f"{args.proposal_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Proposal not found: {args.proposal_id}")
        proposal = read_json(path)
        if args.json:
            print(json.dumps(proposal, indent=2, ensure_ascii=True))
        else:
            print(render_proposal_summary(path, proposal, full=True))
        return 0

    desired_status = args.status
    filtered = [(path, payload) for path, payload in items if desired_status == "all" or payload.get("status") == desired_status]
    if not filtered:
        print("No matching proposals.")
        return 0

    for index, (path, proposal) in enumerate(filtered, start=1):
        if args.json:
            print(json.dumps(proposal, indent=2, ensure_ascii=True))
        else:
            print(render_proposal_summary(path, proposal, full=args.verbose))
        if index != len(filtered):
            print()
    return 0


def load_proposal(proposal_id: str) -> tuple[Path, dict[str, Any]]:
    path = PROPOSALS_DIR / f"{proposal_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Proposal not found: {proposal_id}")
    return path, read_json(path)


def save_proposal(path: Path, proposal: dict[str, Any]) -> None:
    proposal["updated_at"] = utc_now()
    write_json(path, proposal)


def update_status(path: Path, proposal: dict[str, Any], *, status: str, note: str | None, action: str) -> None:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported status: {status}")
    proposal["status"] = status
    proposal["approval"]["reviewed_at"] = utc_now()
    proposal["approval"]["review_note"] = note
    save_proposal(path, proposal)
    append_jsonl(
        CHANGE_LOG_PATH,
        {
            "timestamp": utc_now(),
            "proposal_id": proposal["proposal_id"],
            "action": action,
            "status": status,
            "note": note,
        },
    )


def cmd_approve(args: argparse.Namespace) -> int:
    path, proposal = load_proposal(args.proposal_id)
    if proposal["status"] == "applied":
        raise ValueError("Applied proposals cannot be re-approved without rollback")
    update_status(path, proposal, status="approved", note=args.note, action="approve")
    print(f"Approved proposal: {args.proposal_id}")
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    path, proposal = load_proposal(args.proposal_id)
    if proposal["status"] == "applied":
        raise ValueError("Applied proposals cannot be rejected without rollback")
    update_status(path, proposal, status="rejected", note=args.note, action="reject")
    print(f"Rejected proposal: {args.proposal_id}")
    return 0


def backup_destination(proposal_id: str, destination: Path) -> tuple[Path | None, bool]:
    backup_dir = BACKUPS_DIR / proposal_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    existed = destination.exists()
    if not existed:
        return None, False
    backup_path = backup_dir / destination.name
    shutil.copy2(destination, backup_path)
    return backup_path, True


def proposal_marker_start(proposal_id: str) -> str:
    return f"<!-- {MARKER_PREFIX}: {proposal_id} -->"


def proposal_marker_end(proposal_id: str) -> str:
    return f"<!-- /{MARKER_PREFIX}: {proposal_id} -->"


def append_markdown_block(destination: Path, proposal: dict[str, Any]) -> None:
    current = destination.read_text(encoding="utf-8") if destination.exists() else ""
    marker = proposal_marker_start(proposal["proposal_id"])
    if marker in current:
        raise ValueError(f"Proposal {proposal['proposal_id']} is already present in {destination}")

    block = (
        f"\n\n{marker}\n"
        f"{proposal['proposed_text'].rstrip()}\n"
        f"{proposal_marker_end(proposal['proposal_id'])}\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(current.rstrip() + block if current else proposal["proposed_text"].rstrip() + "\n", encoding="utf-8")


def remove_markdown_block(destination: Path, proposal_id: str) -> bool:
    if not destination.exists():
        return False

    current = destination.read_text(encoding="utf-8")
    marker_start = proposal_marker_start(proposal_id)
    marker_end = proposal_marker_end(proposal_id)
    start_index = current.find(marker_start)
    if start_index == -1:
        return False

    end_index = current.find(marker_end, start_index)
    if end_index == -1:
        return False

    end_index += len(marker_end)
    before = current[:start_index].rstrip("\n")
    after = current[end_index:].lstrip("\n")

    if before and after:
        updated = before + "\n" + after
    elif before:
        updated = before + "\n"
    else:
        updated = after

    destination.write_text(updated, encoding="utf-8")
    return True


def create_new_file(destination: Path, proposal: dict[str, Any], force: bool) -> None:
    if destination.exists() and not force:
        raise ValueError(f"Destination already exists: {destination}. Re-run with --force to overwrite.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(proposal["proposed_text"].rstrip() + "\n", encoding="utf-8")


def cmd_apply(args: argparse.Namespace) -> int:
    path, proposal = load_proposal(args.proposal_id)
    if proposal["status"] != "approved":
        raise ValueError("Only approved proposals can be applied")

    target_type = proposal["recommended_target_type"]
    destination = Path(proposal["recommended_destination_path"]).expanduser()
    validate_destination(target_type, destination)

    backup_path, destination_existed = backup_destination(proposal["proposal_id"], destination)

    if target_type in {"agents_md", "skill_md"}:
        append_markdown_block(destination, proposal)
    elif target_type in {"new_skill", "test_checklist_script"}:
        create_new_file(destination, proposal, force=args.force)
    else:
        raise ValueError(f"Unsupported target type for apply: {target_type}")

    proposal["status"] = "applied"
    proposal["apply"]["applied_at"] = utc_now()
    proposal["apply"]["backup_path"] = str(backup_path) if backup_path else None
    proposal["apply"]["destination_existed"] = destination_existed
    proposal["apply"]["last_change"] = "applied"
    proposal["apply"]["target_type"] = target_type
    proposal["apply"]["destination_real_path"] = str(destination.resolve())
    proposal["apply"]["marker_start"] = proposal_marker_start(proposal["proposal_id"]) if target_type in {"agents_md", "skill_md"} else None
    proposal["apply"]["marker_end"] = proposal_marker_end(proposal["proposal_id"]) if target_type in {"agents_md", "skill_md"} else None
    save_proposal(path, proposal)
    append_jsonl(
        CHANGE_LOG_PATH,
        {
            "timestamp": utc_now(),
            "proposal_id": proposal["proposal_id"],
            "action": "apply",
            "status": "applied",
            "destination_path": str(destination),
            "backup_path": str(backup_path) if backup_path else None,
        },
    )
    print(f"Applied proposal {args.proposal_id} to {destination}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    path, proposal = load_proposal(args.proposal_id)
    if proposal["status"] != "applied":
        raise ValueError("Only applied proposals can be rolled back")

    destination = Path(proposal["recommended_destination_path"]).expanduser()
    backup_path = proposal["apply"].get("backup_path")
    destination_existed = bool(proposal["apply"].get("destination_existed"))
    target_type = proposal["apply"].get("target_type") or proposal["recommended_target_type"]

    if target_type in {"agents_md", "skill_md"}:
        removed = remove_markdown_block(destination, proposal["proposal_id"])
        if not removed and destination_existed:
            if not backup_path:
                raise ValueError("Missing backup path for rollback")
            shutil.copy2(Path(backup_path), destination)
        elif not removed:
            raise ValueError(f"Could not remove proposal block from {destination}")
    else:
        if destination_existed:
            if not backup_path:
                raise ValueError("Missing backup path for rollback")
            shutil.copy2(Path(backup_path), destination)
        elif destination.exists():
            destination.unlink()

    proposal["status"] = "approved"
    proposal["apply"]["last_change"] = "rolled_back"
    proposal["apply"]["rolled_back_at"] = utc_now()
    save_proposal(path, proposal)
    append_jsonl(
        CHANGE_LOG_PATH,
        {
            "timestamp": utc_now(),
            "proposal_id": proposal["proposal_id"],
            "action": "rollback",
            "status": proposal["status"],
            "destination_path": str(destination),
            "backup_path": backup_path,
        },
    )
    print(f"Rolled back proposal {args.proposal_id}")
    return 0


def cmd_mark_used(args: argparse.Namespace) -> int:
    ensure_dirs()
    session_id = resolve_session_id(args.session_id)
    skill_path = Path(args.skill_path).expanduser().resolve()
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill path not found: {skill_path}")
    state, _, new_skill = add_skill_usage(
        session_id=session_id,
        cwd=args.cwd,
        skill_name=args.skill_name or infer_skill_name(skill_path),
        skill_path=skill_path,
        source=args.source,
        tool_name=args.tool_name,
    )
    payload = {
        "session_id": session_id,
        "new_skill": new_skill,
        "skill_count": len(state["skills_used"]),
        "retrospective_status": state["retrospective"]["status"],
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(f"Marked skill usage for session {session_id}: {skill_path}")
    return 0


def cmd_mark_retrospective(args: argparse.Namespace) -> int:
    ensure_dirs()
    session_id = resolve_session_id(args.session_id)
    state = mark_retrospective(
        session_id=session_id,
        cwd=args.cwd,
        outcome=args.outcome,
        proposal_id=args.proposal_id,
        note=args.note,
    )
    payload = {
        "session_id": session_id,
        "retrospective": state["retrospective"],
        "skills_used": len(state["skills_used"]),
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(f"Marked retrospective for session {session_id}: {state['retrospective']['outcome']}")
    return 0


def render_session_status(payload: dict[str, Any]) -> str:
    lines = [
        f"session: {payload['session_id']}",
        f"cwd: {payload.get('cwd')}",
        f"skills_used: {len(payload.get('skills_used', []))}",
        f"retrospective_status: {payload['retrospective'].get('status')}",
        f"retrospective_outcome: {payload['retrospective'].get('outcome')}",
        f"pending: {payload['pending']}",
        f"should_emit_reminder: {payload['should_emit_reminder']}",
    ]
    for item in payload.get("skills_used", []):
        lines.append(f"  - {item['skill_name']} -> {item['skill_path']}")
    return "\n".join(lines)


def cmd_session_status(args: argparse.Namespace) -> int:
    ensure_dirs()
    session_id = resolve_session_id(args.session_id)
    payload = session_status_payload(
        session_id,
        cwd=args.cwd,
        cooldown_seconds=args.cooldown_seconds,
    )
    if args.mark_reminded and payload["should_emit_reminder"]:
        touch_reminder(session_id, args.cwd)
        payload = session_status_payload(
            session_id,
            cwd=args.cwd,
            cooldown_seconds=args.cooldown_seconds,
        )
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=True))
    else:
        print(render_session_status(payload))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe review-queue workflow for Codex skill evolution")
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="Record a raw learning and generate a proposal")
    record.add_argument("--skill-name", required=True)
    record.add_argument("--skill-path")
    record.add_argument("--session-id")
    record.add_argument("--cwd", default=os.getcwd())
    record.add_argument("--trigger-scenario", required=True)
    record.add_argument("--problem", required=True)
    record.add_argument("--problem-kind", required=True, choices=sorted(ALLOWED_KINDS))
    record.add_argument("--reusable-rationale", required=True)
    record.add_argument("--destination-path")
    record.add_argument("--proposed-text", required=True)
    record.add_argument("--risk", required=True)
    record.add_argument("--notes")
    record.add_argument("--proposal-id")
    record.add_argument("--dry-run", action="store_true")
    record.set_defaults(func=cmd_record)

    review = subparsers.add_parser("review", help="List or inspect proposals")
    review.add_argument("--status", default="proposed", choices=["all", *sorted(ALLOWED_STATUSES)])
    review.add_argument("--proposal-id")
    review.add_argument("--verbose", action="store_true")
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)

    approve = subparsers.add_parser("approve", help="Mark a proposal as approved")
    approve.add_argument("--proposal-id", required=True)
    approve.add_argument("--note")
    approve.set_defaults(func=cmd_approve)

    reject = subparsers.add_parser("reject", help="Mark a proposal as rejected")
    reject.add_argument("--proposal-id", required=True)
    reject.add_argument("--note")
    reject.set_defaults(func=cmd_reject)

    apply_cmd = subparsers.add_parser("apply", help="Apply an approved proposal")
    apply_cmd.add_argument("--proposal-id", required=True)
    apply_cmd.add_argument("--force", action="store_true", help="Allow overwrite for create-mode targets")
    apply_cmd.set_defaults(func=cmd_apply)

    rollback = subparsers.add_parser("rollback", help="Restore the pre-apply backup for an applied proposal")
    rollback.add_argument("--proposal-id", required=True)
    rollback.set_defaults(func=cmd_rollback)

    mark_used = subparsers.add_parser("mark-used", help="Mark that a skill was used in the current session")
    mark_used.add_argument("--skill-path", required=True)
    mark_used.add_argument("--skill-name")
    mark_used.add_argument("--session-id")
    mark_used.add_argument("--cwd", default=os.getcwd())
    mark_used.add_argument("--source", default="manual")
    mark_used.add_argument("--tool-name")
    mark_used.add_argument("--json", action="store_true")
    mark_used.set_defaults(func=cmd_mark_used)

    retrospective = subparsers.add_parser("mark-retrospective", help="Mark the session retrospective as completed")
    retrospective.add_argument("--session-id")
    retrospective.add_argument("--cwd", default=os.getcwd())
    retrospective.add_argument("--outcome", required=True, choices=sorted(RETROSPECTIVE_OUTCOMES))
    retrospective.add_argument("--proposal-id")
    retrospective.add_argument("--note")
    retrospective.add_argument("--json", action="store_true")
    retrospective.set_defaults(func=cmd_mark_retrospective)

    session_status = subparsers.add_parser("session-status", help="Inspect session-level skill evolution state")
    session_status.add_argument("--session-id")
    session_status.add_argument("--cwd", default=os.getcwd())
    session_status.add_argument("--cooldown-seconds", type=int, default=DEFAULT_REMINDER_COOLDOWN_SECONDS)
    session_status.add_argument("--mark-reminded", action="store_true")
    session_status.add_argument("--json", action="store_true")
    session_status.set_defaults(func=cmd_session_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - CLI surface
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
