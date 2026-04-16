from __future__ import annotations

import unittest
from pathlib import Path

try:
    from tests.helpers import (
        load_skill_evolution_module,
        make_record_args,
        make_symlinked_skill,
        make_temp_runtime,
        runtime_env,
        write_skill,
    )
except ModuleNotFoundError:  # pragma: no cover - unittest discovery fallback
    from helpers import (  # type: ignore
        load_skill_evolution_module,
        make_record_args,
        make_symlinked_skill,
        make_temp_runtime,
        runtime_env,
        write_skill,
    )


class SkillEvolutionPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = make_temp_runtime()
        self.module = load_skill_evolution_module(self.runtime)

    def tearDown(self) -> None:
        self.runtime.cleanup()

    def test_infer_skill_path_finds_local_codex_skill(self) -> None:
        local_skill = write_skill(self.runtime.codex_skills_dir, "local-skill")

        with runtime_env(self.runtime):
            inferred = self.module.infer_skill_path("local-skill")

        self.assertIsNotNone(inferred)
        self.assertEqual(Path(inferred).resolve(), local_skill.resolve())

    def test_infer_skill_path_finds_external_agents_skill(self) -> None:
        external_skill = write_skill(self.runtime.agents_skills_dir, "external-skill")

        with runtime_env(self.runtime):
            inferred = self.module.infer_skill_path("external-skill")

        self.assertIsNotNone(inferred)
        self.assertEqual(Path(inferred).resolve(), external_skill.resolve())

    def test_validate_destination_allows_external_skill_md(self) -> None:
        external_skill = write_skill(self.runtime.agents_skills_dir, "external-skill")

        with runtime_env(self.runtime):
            try:
                self.module.validate_destination("skill_md", external_skill)
            except Exception as exc:  # pragma: no cover - failure surface for TDD
                self.fail(f"validate_destination rejected external skill path: {exc}")

    def test_build_record_payload_allows_external_skill_workflow_improvement(self) -> None:
        external_skill = write_skill(self.runtime.agents_skills_dir, "external-skill")
        args = make_record_args(
            self.runtime,
            skill_name="external-skill",
            skill_path=external_skill,
            proposal_id="external-skill-test",
        )

        with runtime_env(self.runtime):
            try:
                learning, proposal = self.module.build_record_payload(args)
            except Exception as exc:  # pragma: no cover - failure surface for TDD
                self.fail(f"build_record_payload rejected external skill path: {exc}")

        self.assertEqual(learning["skill_name"], "external-skill")
        self.assertEqual(proposal["recommended_target_type"], "skill_md")
        self.assertEqual(
            Path(proposal["recommended_destination_path"]).resolve(),
            external_skill.resolve(),
        )

    def test_classify_workflow_improvement_routes_system_skill_to_agents_md(self) -> None:
        system_skill = write_skill(self.runtime.system_skills_dir, "system-skill")

        with runtime_env(self.runtime):
            target_type, destination_path, change_mode, _ = self.module.classify_destination(
                problem_kind="workflow-improvement",
                skill_name="system-skill",
                skill_path=str(system_skill),
                destination_path=None,
            )

        self.assertEqual(target_type, "agents_md")
        self.assertEqual(Path(destination_path).resolve(), self.runtime.agents_md_path.resolve())
        self.assertEqual(change_mode, "append")

    def test_validate_destination_accepts_symlinked_skill_md(self) -> None:
        symlink_path, real_path = make_symlinked_skill(self.runtime, "symlinked-skill")

        with runtime_env(self.runtime):
            try:
                self.module.validate_destination("skill_md", symlink_path)
            except Exception as exc:  # pragma: no cover - failure surface for TDD
                self.fail(f"validate_destination rejected symlinked skill path: {exc}")

        self.assertEqual(symlink_path.resolve(), real_path.resolve())


if __name__ == "__main__":
    unittest.main()
