import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
SPEC = importlib.util.spec_from_file_location("check_secrets", MODULE_PATH)
check_secrets = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(check_secrets)


class SecretScanTests(unittest.TestCase):
    def test_detects_secret_without_returning_its_value(self):
        secret = "sk-ant-" + "a" * 24
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.txt"
            path.write_text(f"ANTHROPIC_API_KEY={secret}\n", encoding="utf-8")
            findings = check_secrets.scan_file(path)

        self.assertEqual(findings, [(1, "Anthropic API key")])
        self.assertNotIn(secret, repr(findings))

    def test_ignores_binary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.bin"
            path.write_bytes(b"\x00sk-ant-" + b"a" * 24)
            findings = check_secrets.scan_file(path)

        self.assertEqual(findings, [])
