from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_publish_privacy.py"


class PublishPrivacyTests(unittest.TestCase):
    def make_repo(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="publish-privacy-test-"))
        (root / "README.md").write_text("# test\n", encoding="utf-8")
        return root

    def run_check(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT_PATH), "--root", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_clean_repository_passes(self) -> None:
        root = self.make_repo()
        try:
            result = self.run_check(root, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["overall_status"], "ok")
            self.assertEqual(payload["findings"], [])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_detects_local_paths_and_secret_like_content(self) -> None:
        root = self.make_repo()
        try:
            (root / "notes.txt").write_text(
                "\n".join(
                    [
                        "copied from /home/shenyb/private-project",
                        "email 67506876+syb97@users.noreply.github.com",
                        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBjiItiqQ1c9Hk8+TdBBtEwtePybQ3gzn5n34pmcZyNy publish-key",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.run_check(root, "--json")
            self.assertNotEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["overall_status"], "fail")
            categories = {item["category"] for item in payload["findings"]}
            self.assertIn("local_path", categories)
            self.assertIn("email", categories)
            self.assertIn("ssh_public_key", categories)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_ignores_git_metadata_by_default(self) -> None:
        root = self.make_repo()
        try:
            git_dir = root / ".git"
            git_dir.mkdir(parents=True, exist_ok=True)
            (git_dir / "config").write_text(
                "[user]\n"
                "email = 67506876+syb97@users.noreply.github.com\n"
                "[remote \"origin\"]\n"
                "url = git@github.com:syb97/codex-skill-evolution.git\n",
                encoding="utf-8",
            )

            result = self.run_check(root, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["overall_status"], "ok")
            self.assertEqual(payload["findings"], [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
