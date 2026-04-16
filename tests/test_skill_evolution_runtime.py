from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from tests.helpers import SOURCE_SKILL_EVOLUTION, SOURCE_TRACKER, make_temp_runtime, run_python_script, write_skill
except ModuleNotFoundError:  # pragma: no cover - unittest discovery fallback
    from helpers import SOURCE_SKILL_EVOLUTION, SOURCE_TRACKER, make_temp_runtime, run_python_script, write_skill  # type: ignore


class SkillEvolutionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = make_temp_runtime()

    def tearDown(self) -> None:
        self.runtime.cleanup()

    def test_record_respects_codex_home_override_when_script_lives_outside_runtime_tree(self) -> None:
        outside_root = Path(tempfile.mkdtemp(prefix="skill-evo-portable-"))
        try:
            script_dir = outside_root / "tool" / "scripts"
            script_dir.mkdir(parents=True, exist_ok=True)
            script_path = script_dir / "skill_evolution.py"
            shutil.copy2(SOURCE_SKILL_EVOLUTION, script_path)

            skill_path = write_skill(self.runtime.codex_skills_dir, "portable-skill")
            result = run_python_script(
                script_path,
                [
                    "record",
                    "--session-id",
                    "portable-test",
                    "--proposal-id",
                    "portable-proposal",
                    "--skill-name",
                    "portable-skill",
                    "--skill-path",
                    str(skill_path),
                    "--trigger-scenario",
                    "portable smoke",
                    "--problem",
                    "portable code home override",
                    "--problem-kind",
                    "workflow-improvement",
                    "--reusable-rationale",
                    "portable runtime should not depend on script location",
                    "--proposed-text",
                    "## portable test",
                    "--risk",
                    "test risk",
                ],
                runtime=self.runtime,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((self.runtime.codex_home / "skill-proposals" / "portable-proposal.json").exists())
            self.assertFalse((outside_root / "tool" / "skill-proposals" / "portable-proposal.json").exists())
        finally:
            shutil.rmtree(outside_root, ignore_errors=True)

    def test_tracker_respects_codex_home_override_when_script_lives_outside_runtime_tree(self) -> None:
        outside_root = Path(tempfile.mkdtemp(prefix="skill-tracker-portable-"))
        try:
            tracker_dir = outside_root / "tool" / "plugins" / "skill-evolution-hooks" / "scripts"
            tracker_dir.mkdir(parents=True, exist_ok=True)
            tracker_path = tracker_dir / "posttooluse_skill_tracker.py"
            shutil.copy2(SOURCE_TRACKER, tracker_path)

            skill_path = write_skill(self.runtime.codex_skills_dir, "portable-skill")
            payload = json.dumps({"tool_name": "Read", "input": {"path": str(skill_path)}}, ensure_ascii=False)
            result = run_python_script(
                tracker_path,
                [],
                runtime=self.runtime,
                session_id="portable-tracker",
                input_text=payload,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Detected skill use", result.stdout)
            session_path = self.runtime.codex_home / "skill-evolution-state" / "sessions" / "portable-tracker.json"
            self.assertTrue(session_path.exists())
        finally:
            shutil.rmtree(outside_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
