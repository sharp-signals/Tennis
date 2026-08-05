from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

from src.telegram_bot import send_message


class TelegramBotTests(unittest.TestCase):

    @patch.dict(os.environ, {}, clear=True)
    @patch("src.telegram_bot.requests.post")
    def test_returns_false_without_credentials(self, mock_post):
        result = send_message("Mensagem de teste")

        self.assertFalse(result)
        mock_post.assert_not_called()

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token-teste",
            "TELEGRAM_CHAT_ID": "12345",
        },
        clear=True,
    )
    @patch("src.telegram_bot.requests.post")
    def test_returns_true_after_successful_request(self, mock_post):
        response = Mock()
        mock_post.return_value = response

        result = send_message("Mensagem de teste")

        self.assertTrue(result)
        mock_post.assert_called_once()
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
