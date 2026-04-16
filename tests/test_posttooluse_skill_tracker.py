from __future__ import annotations

import json
import unittest

try:
    from tests.helpers import (
        make_symlinked_skill,
        make_temp_runtime,
        read_session_state,
        run_python_script,
        write_skill,
    )
except ModuleNotFoundError:  # pragma: no cover - unittest discovery fallback
    from helpers import (  # type: ignore
        make_symlinked_skill,
        make_temp_runtime,
        read_session_state,
        run_python_script,
        write_skill,
    )


class SkillTrackerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = make_temp_runtime()

    def tearDown(self) -> None:
        self.runtime.cleanup()

    def test_tracker_detects_local_codex_skill_usage(self) -> None:
        skill_path = write_skill(self.runtime.codex_skills_dir, "local-skill")
        session_id = "tracker-local-skill"
        payload = json.dumps({"tool_name": "Read", "input": {"path": str(skill_path)}}, ensure_ascii=False)

        result = run_python_script(
            self.runtime.tracker_path,
            [],
            runtime=self.runtime,
            session_id=session_id,
            input_text=payload,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Detected skill use", result.stdout)

        state = read_session_state(self.runtime, session_id)
        self.assertEqual(len(state["skills_used"]), 1)
        self.assertEqual(state["skills_used"][0]["skill_name"], "local-skill")
        self.assertEqual(state["retrospective"]["status"], "pending")

    def test_tracker_detects_external_agents_skill_usage(self) -> None:
        skill_path = write_skill(self.runtime.agents_skills_dir, "external-skill")
        session_id = "tracker-external-skill"
        payload = json.dumps({"tool_name": "Read", "input": {"path": str(skill_path)}}, ensure_ascii=False)

        result = run_python_script(
            self.runtime.tracker_path,
            [],
            runtime=self.runtime,
            session_id=session_id,
            input_text=payload,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Detected skill use", result.stdout)

        state = read_session_state(self.runtime, session_id)
        self.assertEqual(len(state["skills_used"]), 1)
        self.assertEqual(state["skills_used"][0]["skill_name"], "external-skill")
        self.assertEqual(state["retrospective"]["status"], "pending")

    def test_tracker_detects_symlinked_skill_usage_and_normalizes_it(self) -> None:
        symlink_path, real_path = make_symlinked_skill(self.runtime, "symlinked-skill")
        session_id = "tracker-symlinked-skill"
        payload = json.dumps({"tool_name": "Read", "input": {"path": str(symlink_path)}}, ensure_ascii=False)

        result = run_python_script(
            self.runtime.tracker_path,
            [],
            runtime=self.runtime,
            session_id=session_id,
            input_text=payload,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Detected skill use", result.stdout)

        state = read_session_state(self.runtime, session_id)
        self.assertEqual(len(state["skills_used"]), 1)
        self.assertEqual(state["skills_used"][0]["skill_name"], "symlinked-skill")
        self.assertEqual(state["skills_used"][0]["skill_path"], str(real_path.resolve()))
        self.assertEqual(state["retrospective"]["status"], "pending")

    def test_tracker_ignores_non_skill_paths(self) -> None:
        non_skill_path = self.runtime.home_dir / "README.md"
        non_skill_path.write_text("# not a skill\n", encoding="utf-8")
        session_id = "tracker-non-skill"
        payload = json.dumps({"tool_name": "Read", "input": {"path": str(non_skill_path)}}, ensure_ascii=False)

        result = run_python_script(
            self.runtime.tracker_path,
            [],
            runtime=self.runtime,
            session_id=session_id,
            input_text=payload,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertNotIn("Detected skill use", result.stdout)
        session_path = self.runtime.codex_home / "skill-evolution-state" / "sessions" / f"{session_id}.json"
        self.assertFalse(session_path.exists())


if __name__ == "__main__":
    unittest.main()
