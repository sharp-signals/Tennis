import os
import unittest
from unittest.mock import Mock, patch

import requests

from src import telegram_bot, telegraph


class TelegramTests(unittest.TestCase):
    def test_missing_credentials_falls_back_to_log_without_request(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(telegram_bot.requests, "post") as post, \
             patch("builtins.print") as output:
            telegram_bot.send_message("mensagem local")

        post.assert_not_called()
        self.assertTrue(any("mensagem local" in str(call) for call in output.call_args_list))

    def test_success_uses_html_and_disables_link_preview(self):
        response = Mock()
        response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "secret-token", "TELEGRAM_CHAT_ID": "123"},
            clear=True,
        ), patch.object(telegram_bot.requests, "post", return_value=response) as post:
            telegram_bot.send_message("<b>resultado</b>")

        payload = post.call_args.kwargs["data"]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertTrue(payload["disable_web_page_preview"])
        self.assertEqual(post.call_args.kwargs["timeout"], telegram_bot.REQUEST_TIMEOUT)

    def test_http_error_does_not_leak_bot_token(self):
        token = "highly-sensitive-token"
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": "123"},
            clear=True,
        ), patch.object(
            telegram_bot.requests,
            "post",
            side_effect=requests.ConnectionError(f"failed https://api.telegram.org/bot{token}/sendMessage"),
        ):
            with self.assertRaises(RuntimeError) as raised:
                telegram_bot.send_message("teste")

        self.assertNotIn(token, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_logical_api_failure_is_not_treated_as_success(self):
        response = Mock()
        response.json.return_value = {"ok": False, "description": "bad request"}
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "123"},
            clear=True,
        ), patch.object(telegram_bot.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "recusou"):
                telegram_bot.send_message("teste")


class TelegraphTests(unittest.TestCase):
    def setUp(self):
        telegraph._TOKEN_CACHE.clear()

    def tearDown(self):
        telegraph._TOKEN_CACHE.clear()

    def test_markdown_conversion_preserves_structure_and_inline_emphasis(self):
        nodes = telegraph._markdown_to_telegraph_nodes(
            "# Título\n\nParágrafo **forte** em *itálico*.\n\n- Um\n- Dois\n\n---"
        )

        self.assertEqual([node["tag"] for node in nodes], ["h3", "p", "ul", "hr"])
        paragraph = nodes[1]["children"]
        self.assertIn({"tag": "b", "children": ["forte"]}, paragraph)
        self.assertIn({"tag": "i", "children": ["itálico"]}, paragraph)
        self.assertEqual(len(nodes[2]["children"]), 2)

    def test_environment_token_is_cached_without_creating_account(self):
        with patch.dict(os.environ, {"TELEGRAPH_ACCESS_TOKEN": "existing"}, clear=True), \
             patch.object(telegraph.requests, "post") as post:
            first = telegraph._get_or_create_access_token()
            second = telegraph._get_or_create_access_token()

        self.assertEqual((first, second), ("existing", "existing"))
        post.assert_not_called()

    def test_created_account_requires_valid_token(self):
        response = Mock()
        response.json.return_value = {"ok": False, "error": "invalid"}
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(telegraph.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "sem access token"):
                telegraph._get_or_create_access_token()

    def test_publish_truncates_title_and_supplies_content_for_empty_report(self):
        response = Mock()
        response.json.return_value = {"ok": True, "result": {"url": "https://telegra.ph/report"}}
        with patch.object(telegraph, "_get_or_create_access_token", return_value="token"), \
             patch.object(telegraph.requests, "post", return_value=response) as post:
            url = telegraph.publish_report("T" * 300, "")

        self.assertEqual(url, "https://telegra.ph/report")
        request_body = post.call_args.kwargs["json"]
        self.assertEqual(len(request_body["title"]), 256)
        self.assertEqual(request_body["content"], [{"tag": "p", "children": ["T" * 300]}])

    def test_publish_rejects_success_response_without_url(self):
        response = Mock()
        response.json.return_value = {"ok": True, "result": {}}
        with patch.object(telegraph, "_get_or_create_access_token", return_value="token"), \
             patch.object(telegraph.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "sem URL"):
                telegraph.publish_report("Relatório", "conteúdo")

    def test_publish_rejects_non_object_json_response(self):
        response = Mock()
        response.json.return_value = ["unexpected"]
        with patch.object(telegraph, "_get_or_create_access_token", return_value="token"), \
             patch.object(telegraph.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "recusou"):
                telegraph.publish_report("Relatório", "conteúdo")


if __name__ == "__main__":
    unittest.main()
