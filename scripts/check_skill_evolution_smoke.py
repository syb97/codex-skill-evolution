#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    status: str
    evidence: list[str]
    stdout: str = ""
    stderr: str = ""


@dataclass
class TempRuntime:
    root_dir: Path
    home_dir: Path
    codex_home: Path
    skill_evolution_path: Path
    tracker_path: Path
    skill_path: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.root_dir, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke check for the skill evolution workflow")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--timeout", type=int, default=30, help="Per-command timeout in seconds")
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1], help="Project root containing the source assets")
    parser.add_argument("--keep-temp", action="store_true", help="Keep the temporary runtime directory for debugging")
    return parser


def source_paths(source_root: Path) -> dict[str, Path]:
    root = source_root.resolve()
    return {
        "root": root,
        "workflow_script": root / ".codex" / "scripts" / "skill_evolution.py",
        "tracker_script": root / ".codex" / "plugins" / "skill-evolution-hooks" / "scripts" / "posttooluse_skill_tracker.py",
        "hooks_json": root / ".codex" / "plugins" / "skill-evolution-hooks" / "hooks.json",
        "plugin_json": root / ".codex" / "plugins" / "skill-evolution-hooks" / ".codex-plugin" / "plugin.json",
    }


def check_assets(paths: dict[str, Path]) -> CheckResult:
    required = [
        ("workflow script", paths["workflow_script"]),
        ("tracker script", paths["tracker_script"]),
        ("hooks file", paths["hooks_json"]),
        ("plugin manifest", paths["plugin_json"]),
    ]
    missing = [f"missing {label}: {path}" for label, path in required if not path.exists()]
    if missing:
        return CheckResult("assets", "fail", missing)
    return CheckResult(
        "assets",
        "ok",
        [f"found {label}: {path}" for label, path in required],
    )


def make_temp_runtime(paths: dict[str, Path]) -> TempRuntime:
    root_dir = Path(tempfile.mkdtemp(prefix="skill-evolution-smoke-"))
    home_dir = root_dir / "home"
    codex_home = home_dir / ".codex"
    skill_dir = codex_home / "skills" / "smoke-skill"
    scripts_dir = codex_home / "scripts"
    tracker_dir = codex_home / "plugins" / "skill-evolution-hooks" / "scripts"
    plugin_manifest_dir = codex_home / "plugins" / "skill-evolution-hooks" / ".codex-plugin"

    for path in (skill_dir, scripts_dir, tracker_dir, plugin_manifest_dir):
        path.mkdir(parents=True, exist_ok=True)

    shutil.copy2(paths["workflow_script"], scripts_dir / "skill_evolution.py")
    shutil.copy2(paths["tracker_script"], tracker_dir / "posttooluse_skill_tracker.py")
    shutil.copy2(paths["hooks_json"], tracker_dir.parent / "hooks.json")
    shutil.copy2(paths["plugin_json"], plugin_manifest_dir / "plugin.json")
    (codex_home / "AGENTS.md").write_text("# Smoke AGENTS\n", encoding="utf-8")

    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\nname: smoke-skill\ndescription: smoke skill\n---\n\n# smoke-skill\n",
        encoding="utf-8",
    )

    return TempRuntime(
        root_dir=root_dir,
        home_dir=home_dir,
        codex_home=codex_home,
        skill_evolution_path=scripts_dir / "skill_evolution.py",
        tracker_path=tracker_dir / "posttooluse_skill_tracker.py",
        skill_path=skill_path,
    )


def run_command(
    script_path: Path,
    args: list[str],
    *,
    runtime: TempRuntime,
    timeout: int,
    session_id: str | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(runtime.home_dir)
    env["CODEX_HOME"] = str(runtime.codex_home)
    if session_id:
        env["CODEX_THREAD_ID"] = session_id
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        check=False,
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_tracker_detection(runtime: TempRuntime, timeout: int) -> CheckResult:
    payload = json.dumps({"tool_name": "Read", "input": {"path": str(runtime.skill_path)}}, ensure_ascii=False)
    result = run_command(
        runtime.tracker_path,
        [],
        runtime=runtime,
        timeout=timeout,
        session_id="smoke-detect",
        input_text=payload,
    )
    session_path = runtime.codex_home / "skill-evolution-state" / "sessions" / "smoke-detect.json"
    evidence: list[str] = []
    if result.stdout.strip():
        evidence.append(result.stdout.strip().splitlines()[-1])
    if not session_path.exists():
        evidence.append(f"missing session state: {session_path}")
        return CheckResult("tracker-detection", "fail", evidence, result.stdout, result.stderr)

    state = read_json(session_path)
    evidence.append(f"skills_used={len(state.get('skills_used', []))}")
    evidence.append(f"retrospective={state.get('retrospective', {}).get('status')}")
    if (
        result.returncode == 0
        and "Detected skill use" in result.stdout
        and len(state.get("skills_used", [])) == 1
        and state.get("retrospective", {}).get("status") == "pending"
    ):
        return CheckResult("tracker-detection", "ok", evidence, result.stdout, result.stderr)
    return CheckResult("tracker-detection", "fail", evidence, result.stdout, result.stderr)


def run_record_check(runtime: TempRuntime, timeout: int) -> CheckResult:
    proposal_id = "smoke-proposal"
    result = run_command(
        runtime.skill_evolution_path,
        [
            "record",
            "--session-id",
            "smoke-record",
            "--proposal-id",
            proposal_id,
            "--skill-name",
            "smoke-skill",
            "--skill-path",
            str(runtime.skill_path),
            "--trigger-scenario",
            "public smoke check",
            "--problem",
            "Smoke check verifies proposal generation",
            "--problem-kind",
            "workflow-improvement",
            "--reusable-rationale",
            "If this fails, the review queue is broken",
            "--proposed-text",
            "## Smoke Proposal\n- Temporary proposal for smoke testing.",
            "--risk",
            "Low risk temporary smoke test proposal",
        ],
        runtime=runtime,
        timeout=timeout,
    )
    proposal_path = runtime.codex_home / "skill-proposals" / f"{proposal_id}.json"
    evidence = [f"proposal_path={proposal_path}"]
    if not proposal_path.exists():
        evidence.append("proposal file missing")
        return CheckResult("proposal-record", "fail", evidence, result.stdout, result.stderr)
    proposal = read_json(proposal_path)
    evidence.append(f"proposal_status={proposal.get('status')}")
    if result.returncode == 0 and proposal.get("status") == "proposed":
        return CheckResult("proposal-record", "ok", evidence, result.stdout, result.stderr)
    return CheckResult("proposal-record", "fail", evidence, result.stdout, result.stderr)


def run_approval_gate_check(runtime: TempRuntime, timeout: int) -> CheckResult:
    result = run_command(
        runtime.skill_evolution_path,
        ["apply", "--proposal-id", "smoke-proposal"],
        runtime=runtime,
        timeout=timeout,
    )
    evidence = []
    if result.stderr.strip():
        evidence.append(result.stderr.strip().splitlines()[-1])
    if result.returncode != 0 and "Only approved proposals can be applied" in result.stderr:
        return CheckResult("approval-gate", "ok", evidence, result.stdout, result.stderr)
    evidence.append(f"unexpected returncode={result.returncode}")
    return CheckResult("approval-gate", "fail", evidence, result.stdout, result.stderr)


def overall_status(results: list[CheckResult]) -> str:
    return "ok" if all(result.status == "ok" for result in results) else "fail"


def render_json(results: list[CheckResult]) -> str:
    payload = {
        "overall_status": overall_status(results),
        "checks": [
            {
                "name": result.name,
                "status": result.status,
                "evidence": result.evidence,
                "stdout_tail": result.stdout[-500:],
                "stderr_tail": result.stderr[-500:],
            }
            for result in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_text(results: list[CheckResult]) -> str:
    lines = [f"overall: {overall_status(results)}", ""]
    for result in results:
        lines.append(f"- {result.name}: {result.status}")
    return "\n".join(lines)


def main() -> int:
    args = build_parser().parse_args()
    paths = source_paths(args.source_root)
    results = [check_assets(paths)]
    runtime: TempRuntime | None = None
    try:
        if results[0].status == "ok":
            runtime = make_temp_runtime(paths)
            results.append(run_tracker_detection(runtime, args.timeout))
            results.append(run_record_check(runtime, args.timeout))
            results.append(run_approval_gate_check(runtime, args.timeout))
    finally:
        if runtime and not args.keep_temp:
            runtime.cleanup()

    output = render_json(results) if args.json else render_text(results)
    print(output)
    return 0 if overall_status(results) == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
