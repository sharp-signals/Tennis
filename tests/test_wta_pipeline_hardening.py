from __future__ import annotations

import ast
import inspect
import os
import textwrap
import unittest
from unittest.mock import patch

from src import main


class WtaPipelineHardeningTests(unittest.TestCase):

    def test_env_flag_defaults_to_false(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                main._env_flag("WTA_PIPELINE_OBSERVABILITY")
            )

    def test_env_flag_accepts_explicit_truthy_values(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                with patch.dict(
                    os.environ,
                    {"WTA_PIPELINE_OBSERVABILITY": value},
                    clear=True,
                ):
                    self.assertTrue(
                        main._env_flag(
                            "WTA_PIPELINE_OBSERVABILITY"
                        )
                    )

    def test_payload_builder_preserves_player_ids(self):
        source = textwrap.dedent(
            inspect.getsource(main._build_match_payload)
        )
        tree = ast.parse(source)

        dictionary_keys = {
            key.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Dict)
            for key in node.keys
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
        }

        self.assertIn("player_a_id", dictionary_keys)
        self.assertIn("player_b_id", dictionary_keys)


if __name__ == "__main__":
    unittest.main()
