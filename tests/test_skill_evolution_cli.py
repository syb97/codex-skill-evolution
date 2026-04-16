from __future__ import annotations

import unittest

try:
    from tests.helpers import (
        make_proposal,
        make_temp_runtime,
        read_json,
        run_python_script,
        write_proposal,
        write_skill,
    )
except ModuleNotFoundError:  # pragma: no cover - unittest discovery fallback
    from helpers import (  # type: ignore
        make_proposal,
        make_temp_runtime,
        read_json,
        run_python_script,
        write_proposal,
        write_skill,
    )


class SkillEvolutionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = make_temp_runtime()

    def tearDown(self) -> None:
        self.runtime.cleanup()

    def test_apply_rejects_unapproved_proposal(self) -> None:
        skill_path = write_skill(self.runtime.codex_skills_dir, "local-skill")
        proposal = make_proposal(
            proposal_id="unapproved-proposal",
            status="proposed",
            target_type="skill_md",
            destination_path=skill_path,
        )
        write_proposal(self.runtime, proposal)

        result = run_python_script(
            self.runtime.skill_evolution_path,
            ["apply", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Only approved proposals can be applied", result.stderr)

    def test_apply_appends_marker_block_to_skill_md(self) -> None:
        skill_path = write_skill(self.runtime.codex_skills_dir, "local-skill")
        proposal = make_proposal(
            proposal_id="append-proposal",
            status="approved",
            target_type="skill_md",
            destination_path=skill_path,
            proposed_text="## Added Section\n- Added by proposal",
        )
        proposal_path = write_proposal(self.runtime, proposal)

        result = run_python_script(
            self.runtime.skill_evolution_path,
            ["apply", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        updated_text = skill_path.read_text(encoding="utf-8")
        self.assertIn("<!-- skill-evolution-proposal: append-proposal -->", updated_text)
        self.assertIn("## Added Section", updated_text)
        self.assertIn("<!-- /skill-evolution-proposal: append-proposal -->", updated_text)

        updated_proposal = read_json(proposal_path)
        self.assertEqual(updated_proposal["status"], "applied")

    def test_marker_aware_rollback_removes_only_the_proposal_block(self) -> None:
        skill_path = write_skill(self.runtime.codex_skills_dir, "local-skill")
        original_text = skill_path.read_text(encoding="utf-8")
        proposal = make_proposal(
            proposal_id="rollback-proposal",
            status="approved",
            target_type="skill_md",
            destination_path=skill_path,
            proposed_text="## Added Section\n- Added by proposal",
        )
        write_proposal(self.runtime, proposal)

        apply_result = run_python_script(
            self.runtime.skill_evolution_path,
            ["apply", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )
        self.assertEqual(apply_result.returncode, 0, msg=apply_result.stderr)

        skill_path.write_text(skill_path.read_text(encoding="utf-8") + "\nUser-added line after apply\n", encoding="utf-8")

        rollback_result = run_python_script(
            self.runtime.skill_evolution_path,
            ["rollback", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )
        self.assertEqual(rollback_result.returncode, 0, msg=rollback_result.stderr)

        final_text = skill_path.read_text(encoding="utf-8")
        self.assertIn("User-added line after apply", final_text)
        self.assertIn("local-skill", final_text)
        self.assertNotIn("Added by proposal", final_text)
        self.assertEqual(final_text.rstrip(), (original_text.rstrip() + "\nUser-added line after apply").rstrip())

    def test_rollback_falls_back_to_backup_restore_when_marker_missing(self) -> None:
        skill_path = write_skill(self.runtime.codex_skills_dir, "local-skill")
        original_text = skill_path.read_text(encoding="utf-8")
        proposal = make_proposal(
            proposal_id="fallback-proposal",
            status="approved",
            target_type="skill_md",
            destination_path=skill_path,
            proposed_text="## Added Section\n- Added by proposal",
        )
        proposal_path = write_proposal(self.runtime, proposal)

        apply_result = run_python_script(
            self.runtime.skill_evolution_path,
            ["apply", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )
        self.assertEqual(apply_result.returncode, 0, msg=apply_result.stderr)

        text_without_markers = skill_path.read_text(encoding="utf-8").replace(
            "<!-- skill-evolution-proposal: fallback-proposal -->\n", ""
        ).replace(
            "<!-- /skill-evolution-proposal: fallback-proposal -->\n", ""
        )
        skill_path.write_text(text_without_markers, encoding="utf-8")

        rollback_result = run_python_script(
            self.runtime.skill_evolution_path,
            ["rollback", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )
        self.assertEqual(rollback_result.returncode, 0, msg=rollback_result.stderr)
        self.assertEqual(skill_path.read_text(encoding="utf-8"), original_text)
        updated_proposal = read_json(proposal_path)
        self.assertEqual(updated_proposal["status"], "approved")

    def test_rollback_for_created_file_still_uses_file_restore_logic(self) -> None:
        destination_path = self.runtime.codex_skills_dir / "created-skill" / "SKILL.md"
        proposal = make_proposal(
            proposal_id="new-skill-proposal",
            status="approved",
            target_type="new_skill",
            destination_path=destination_path,
            skill_name="created-skill",
            proposed_text="---\nname: created-skill\ndescription: created by test\n---\n\n# created-skill\n",
        )
        proposal_path = write_proposal(self.runtime, proposal)

        apply_result = run_python_script(
            self.runtime.skill_evolution_path,
            ["apply", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )
        self.assertEqual(apply_result.returncode, 0, msg=apply_result.stderr)
        self.assertTrue(destination_path.exists())

        rollback_result = run_python_script(
            self.runtime.skill_evolution_path,
            ["rollback", "--proposal-id", proposal["proposal_id"]],
            runtime=self.runtime,
        )
        self.assertEqual(rollback_result.returncode, 0, msg=rollback_result.stderr)
        self.assertFalse(destination_path.exists())
        updated_proposal = read_json(proposal_path)
        self.assertEqual(updated_proposal["status"], "approved")


if __name__ == "__main__":
    unittest.main()
