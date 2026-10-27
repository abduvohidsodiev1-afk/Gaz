import contextlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import propanbot as bot


class BotTests(unittest.TestCase):
    def test_offset_survives_reopen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.sqlite3'
            with contextlib.closing(bot.connect_db(path)) as db:
                self.assertEqual(bot.offset(db), 0)
                bot.save_offset(db, 123)
            with contextlib.closing(bot.connect_db(path)) as db:
                self.assertEqual(bot.offset(db), 123)

    def test_token_loaded_from_executable_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {}, clear=True):
            base = Path(folder)
            with self.assertRaises(ValueError):
                bot.load_token(base)
            (base / '.env').write_text('TELEGRAM_BOT_TOKEN=123:example', encoding='utf-8')
            self.assertEqual(bot.load_token(base), '123:example')

    def test_commands(self):
        self.assertIn('Propan', bot.reply_text('/start@gazpropan_uz_bot'))
        self.assertIn('/start', bot.reply_text('/help'))
        self.assertIn('/help', bot.reply_text('salom'))

    def test_network_error_does_not_expose_token(self):
        import urllib.error
        secret = '123:example'
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError(secret)):
            with self.assertRaises(RuntimeError) as caught:
                bot.Telegram(secret).call('getMe', {})
        self.assertNotIn(secret, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
