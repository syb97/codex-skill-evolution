from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Iterator
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL_EVOLUTION = PROJECT_ROOT / ".codex" / "scripts" / "skill_evolution.py"
SOURCE_TRACKER = PROJECT_ROOT / ".codex" / "plugins" / "skill-evolution-hooks" / "scripts" / "posttooluse_skill_tracker.py"
SOURCE_HOOKS = PROJECT_ROOT / ".codex" / "plugins" / "skill-evolution-hooks" / "hooks.json"
SOURCE_PLUGIN_MANIFEST = PROJECT_ROOT / ".codex" / "plugins" / "skill-evolution-hooks" / ".codex-plugin" / "plugin.json"


@dataclass
class TempRuntime:
    root_dir: Path
    home_dir: Path
    codex_home: Path
    agents_home: Path
    codex_skills_dir: Path
    system_skills_dir: Path
    agents_skills_dir: Path
    scripts_dir: Path
    skill_evolution_path: Path
    agents_md_path: Path
    plugin_root: Path
    tracker_path: Path
    hooks_path: Path
    plugin_manifest_path: Path

    def cleanup(self) -> None:
        shutil.rmtree(self.root_dir, ignore_errors=True)


def make_temp_runtime() -> TempRuntime:
    root_dir = Path(tempfile.mkdtemp(prefix="skill-evolution-test-"))
    home_dir = root_dir / "home"
    codex_home = home_dir / ".codex"
    agents_home = home_dir / ".agents"
    codex_skills_dir = codex_home / "skills"
    system_skills_dir = codex_skills_dir / ".system"
    agents_skills_dir = agents_home / "skills"
    scripts_dir = codex_home / "scripts"
    plugin_root = codex_home / "plugins" / "skill-evolution-hooks"
    plugin_scripts_dir = plugin_root / "scripts"
    plugin_manifest_dir = plugin_root / ".codex-plugin"

    for path in (
        codex_skills_dir,
        system_skills_dir,
        agents_skills_dir,
        scripts_dir,
        plugin_scripts_dir,
        plugin_manifest_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)

    agents_md_path = codex_home / "AGENTS.md"
    agents_md_path.write_text("# Test AGENTS\n", encoding="utf-8")

    skill_evolution_path = scripts_dir / "skill_evolution.py"
    shutil.copy2(SOURCE_SKILL_EVOLUTION, skill_evolution_path)
    tracker_path = plugin_scripts_dir / "posttooluse_skill_tracker.py"
    hooks_path = plugin_root / "hooks.json"
    plugin_manifest_path = plugin_manifest_dir / "plugin.json"
    shutil.copy2(SOURCE_TRACKER, tracker_path)
    shutil.copy2(SOURCE_HOOKS, hooks_path)
    shutil.copy2(SOURCE_PLUGIN_MANIFEST, plugin_manifest_path)

    return TempRuntime(
        root_dir=root_dir,
        home_dir=home_dir,
        codex_home=codex_home,
        agents_home=agents_home,
        codex_skills_dir=codex_skills_dir,
        system_skills_dir=system_skills_dir,
        agents_skills_dir=agents_skills_dir,
        scripts_dir=scripts_dir,
        skill_evolution_path=skill_evolution_path,
        agents_md_path=agents_md_path,
        plugin_root=plugin_root,
        tracker_path=tracker_path,
        hooks_path=hooks_path,
        plugin_manifest_path=plugin_manifest_path,
    )


@contextmanager
def runtime_env(runtime: TempRuntime) -> Iterator[None]:
    with patch.dict(
        os.environ,
        {
            "HOME": str(runtime.home_dir),
            "CODEX_HOME": str(runtime.codex_home),
        },
        clear=False,
    ):
        yield


def load_skill_evolution_module(runtime: TempRuntime) -> ModuleType:
    module_name = f"skill_evolution_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, runtime.skill_evolution_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load temporary skill_evolution module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    with runtime_env(runtime):
        spec.loader.exec_module(module)
    return module


def runtime_env_vars(runtime: TempRuntime, *, session_id: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(runtime.home_dir)
    env["CODEX_HOME"] = str(runtime.codex_home)
    if session_id is not None:
        env["CODEX_THREAD_ID"] = session_id
    return env


def write_skill(skill_root: Path, name: str) -> Path:
    skill_dir = skill_root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        (
            "---\n"
            f"name: {name}\n"
            "description: test skill\n"
            "---\n\n"
            f"# {name}\n"
        ),
        encoding="utf-8",
    )
    return skill_path


def make_symlinked_skill(runtime: TempRuntime, name: str) -> tuple[Path, Path]:
    real_path = write_skill(runtime.agents_skills_dir, name)
    symlink_dir = runtime.codex_skills_dir / name
    symlink_dir.symlink_to(real_path.parent, target_is_directory=True)
    return symlink_dir / "SKILL.md", real_path


def make_record_args(
    runtime: TempRuntime,
    *,
    skill_name: str,
    skill_path: Path,
    proposal_id: str = "test-proposal",
) -> SimpleNamespace:
    return SimpleNamespace(
        problem_kind="workflow-improvement",
        skill_name=skill_name,
        skill_path=str(skill_path),
        destination_path=None,
        session_id="test-session",
        cwd=str(runtime.home_dir),
        trigger_scenario="test trigger",
        problem="test problem",
        reusable_rationale="test rationale",
        proposed_text="## test proposal",
        risk="test risk",
        notes=None,
        proposal_id=proposal_id,
    )


def run_python_script(
    script_path: Path,
    args: list[str],
    *,
    runtime: TempRuntime,
    session_id: str | None = None,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or runtime.home_dir),
        env=runtime_env_vars(runtime, session_id=session_id),
        check=False,
    )


def read_session_state(runtime: TempRuntime, session_id: str) -> dict:
    session_path = runtime.codex_home / "skill-evolution-state" / "sessions" / f"{session_id}.json"
    return read_json(session_path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def make_proposal(
    *,
    proposal_id: str,
    status: str,
    target_type: str,
    destination_path: Path,
    skill_name: str = "local-skill",
    skill_path: Path | None = None,
    proposed_text: str = "## test proposal",
) -> dict:
    change_mode = "append" if target_type in {"agents_md", "skill_md"} else "create"
    problem_kind = "workflow-improvement" if change_mode == "append" else "new-capability"
    skill_path_value = str((skill_path or destination_path).resolve()) if skill_path or destination_path.exists() else str(destination_path)
    return {
        "proposal_id": proposal_id,
        "status": status,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "learning_id": proposal_id,
        "skill_name": skill_name,
        "skill_path": skill_path_value,
        "trigger_scenario": "test trigger",
        "problem": "test problem",
        "problem_kind": problem_kind,
        "reusable_rationale": "test rationale",
        "recommended_target_type": target_type,
        "recommended_destination_path": str(destination_path),
        "classification_reason": "test classification",
        "change_mode": change_mode,
        "proposed_text": proposed_text,
        "risk": "test risk",
        "notes": None,
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


def write_proposal(runtime: TempRuntime, proposal: dict) -> Path:
    proposal_path = runtime.codex_home / "skill-proposals" / f"{proposal['proposal_id']}.json"
    write_json(proposal_path, proposal)
    return proposal_path


def make_temp_source_root(*, include_tracker: bool = True) -> Path:
    root_dir = Path(tempfile.mkdtemp(prefix="skill-evolution-source-"))
    script_dir = root_dir / ".codex" / "scripts"
    tracker_dir = root_dir / ".codex" / "plugins" / "skill-evolution-hooks" / "scripts"
    plugin_manifest_dir = root_dir / ".codex" / "plugins" / "skill-evolution-hooks" / ".codex-plugin"

    for path in (script_dir, tracker_dir, plugin_manifest_dir):
        path.mkdir(parents=True, exist_ok=True)

    shutil.copy2(SOURCE_SKILL_EVOLUTION, script_dir / "skill_evolution.py")
    shutil.copy2(SOURCE_HOOKS, tracker_dir.parent / "hooks.json")
    shutil.copy2(SOURCE_PLUGIN_MANIFEST, plugin_manifest_dir / "plugin.json")
    if include_tracker:
        shutil.copy2(SOURCE_TRACKER, tracker_dir / "posttooluse_skill_tracker.py")

    return root_dir
