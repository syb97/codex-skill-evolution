from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

try:
    from tests.helpers import make_temp_source_root
except ModuleNotFoundError:  # pragma: no cover - unittest discovery fallback
    from helpers import make_temp_source_root  # type: ignore


SMOKE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_skill_evolution_smoke.py"


class SkillEvolutionSmokeTests(unittest.TestCase):
    def run_smoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SMOKE_SCRIPT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_smoke_check_reports_ok_for_minimal_runtime(self) -> None:
        result = self.run_smoke("--json")

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["overall_status"], "ok")

    def test_smoke_check_json_output_has_expected_shape(self) -> None:
        result = self.run_smoke("--json")

        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertIn("overall_status", payload)
        self.assertIn("checks", payload)
        self.assertIsInstance(payload["checks"], list)
        self.assertGreater(len(payload["checks"]), 0)
        self.assertTrue(all("name" in item and "status" in item and "evidence" in item for item in payload["checks"]))

    def test_smoke_check_fails_when_tracker_script_missing(self) -> None:
        source_root = make_temp_source_root(include_tracker=False)
        try:
            result = self.run_smoke("--json", "--source-root", str(source_root))
        finally:
            shutil.rmtree(source_root, ignore_errors=True)

        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        payload = json.loads(result.stdout)
        self.assertNotEqual(payload["overall_status"], "ok")
        assets_check = next(item for item in payload["checks"] if item["name"] == "assets")
        self.assertEqual(assets_check["status"], "fail")


if __name__ == "__main__":
    unittest.main()
