from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.publish_generated_changes import publish
from scripts.recover_generated_outputs import create_recovery, restore
from scripts.stage_generated_outputs import stage


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def init_repo(root: Path) -> None:
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "data").mkdir()
    (root / "data/run_metrics_log.json").write_text("[]\n", encoding="utf-8")
    git(root, "add", "data/run_metrics_log.json")
    git(root, "commit", "-m", "base")


class GeneratedOutputPersistenceTests(unittest.TestCase):
    def test_optional_absent_path_does_not_break_explicit_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            (root / "data/run_metrics_log.json").write_text('[{"ok":true}]\n', encoding="utf-8")
            self.assertEqual(stage(root=root, profile="bot"), ["data/run_metrics_log.json"])
            self.assertIn("data/run_metrics_log.json", git(root, "diff", "--cached", "--name-only"))

    def test_untracked_bytes_round_trip_without_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, artifact, fresh = base / "repo", base / "artifact", base / "fresh"
            root.mkdir(); fresh.mkdir()
            init_repo(root)
            observation = root / "data/market_ledger/observations/2026-10-01.jsonl"
            observation.parent.mkdir(parents=True)
            value = b'{"observation_id":"one"}\n'
            observation.write_bytes(value)
            document = create_recovery(
                root=root, target=artifact, profile="bot", reason="TEST", remote_ref="HEAD",
            )
            self.assertEqual(document["files"][0]["sha256"], __import__("hashlib").sha256(value).hexdigest())
            restore(artifact=artifact, root=fresh)
            restore(artifact=artifact, root=fresh)
            self.assertEqual((fresh / observation.relative_to(root)).read_bytes(), value)

    def test_validation_is_repeated_after_rebase(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bare, root, recovery = base / "remote.git", base / "repo", base / "recovery"
            subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
            root.mkdir(); init_repo(root)
            git(root, "remote", "add", "origin", str(bare))
            git(root, "push", "-u", "origin", "main")
            (root / "data/run_metrics_log.json").write_text('[{"run":1}]\n', encoding="utf-8")
            git(root, "add", "data/run_metrics_log.json"); git(root, "commit", "-m", "generated")
            counter = base / "counter"
            validator = base / "validator.py"
            validator.write_text(
                "import pathlib,sys\np=pathlib.Path(sys.argv[1]); n=int(p.read_text() or 0) if p.exists() else 0; p.write_text(str(n+1)); raise SystemExit(0 if n==0 else 1)\n",
                encoding="utf-8",
            )
            with self.assertRaises(subprocess.CalledProcessError):
                publish(
                    root=root, profile="bot", title="test", recovery_dir=recovery,
                    validation_command=[sys.executable, str(validator), str(counter)], retries=1,
                )
            self.assertEqual(counter.read_text(), "2")
            manifest = json.loads((recovery / "recovery-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["reason_code"], "FORWARD_ONLY_VALIDATION_FAILED_AFTER_REBASE")


if __name__ == "__main__":
    unittest.main()
