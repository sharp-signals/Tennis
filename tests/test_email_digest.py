import unittest
from unittest.mock import patch

from src import email_digest


class EmailDigestTests(unittest.TestCase):
    @staticmethod
    def _reports():
        high_payload = {
            "player_a": "A <One>", "player_b": "B", "tournament": "Open & Co",
            "market_odds_decimal": {"A <One>": 2.1, "B": 1.8},
            "divergencia": {"classificacao": {"nivel": 3}},
        }
        candidate_payload = {
            "player_a": "C", "player_b": "D", "tournament": "Masters",
            "market_odds_decimal": {"C": 2.4, "D": 1.6},
            "divergencia": {"classificacao": {"nivel": 1}},
            "pricing": {
                "available": True, "candidate_side": "a",
                "players": {"a": {"fair_odd": 2.05, "market_odd": 2.4,
                                   "expected_edge_pct": 17.1}},
            },
        }
        return [
            (high_payload, {"summary_line": "Alta <atenção>"}, "https://example.test/a"),
            (candidate_payload, {"summary_line": "Experimental"}, "https://example.test/c"),
        ]

    def test_manifest_and_html_include_all_links_and_experimental_pricing(self):
        manifest = email_digest.build_digest_manifest(
            self._reports(), "2026-08-26", "https://example.test/index",
        )
        rendered = email_digest.build_digest_html(manifest)
        self.assertEqual(len(manifest["games"]), 2)
        self.assertEqual(manifest["counts"]["high"], 1)
        self.assertEqual(manifest["counts"]["candidate"], 1)
        self.assertIn("https://example.test/index", rendered)
        self.assertIn("https://example.test/a", rendered)
        self.assertIn("Fair odd 2.05", rendered)
        self.assertIn("expected edge 17.1%", rendered)
        self.assertIn("A &lt;One&gt;", rendered)
        self.assertNotIn("Alta <atenção>", rendered)

    @patch("src.email_digest.smtplib.SMTP_SSL")
    def test_one_message_is_sent_to_all_recipients(self, smtp_cls):
        manifest = email_digest.build_digest_manifest(
            self._reports(), "2026-08-26", "https://example.test/index",
        )
        env = {
            "REPORT_EMAIL_SMTP_USERNAME": "bot@example.test",
            "REPORT_EMAIL_SMTP_PASSWORD": "secret",
            "REPORT_EMAIL_TO": "first@example.test, second@example.test",
        }
        sent = email_digest.send_digest(manifest, environ=env)
        smtp = smtp_cls.return_value.__enter__.return_value
        self.assertEqual(sent, 2)
        smtp.login.assert_called_once_with("bot@example.test", "secret")
        smtp.send_message.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "first@example.test, second@example.test")
        self.assertTrue(message.is_multipart())


if __name__ == "__main__":
    unittest.main()
