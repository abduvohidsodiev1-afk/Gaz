import re
import unittest
from unittest.mock import Mock, patch
import group_wait
import propanbot
import script_style
import station_directory


class ScriptStyleTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)

    def message(self, mid, text, stamp=1000):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'from': {'id': 10}, 'message_id': mid, 'date': stamp, 'text': text}

    def test_latin_question_gets_latin_card_after_thirty_seconds(self):
        api = Mock()
        station_directory.observe(self.db, self.message(1, 'Майорский 8200', 900))
        with patch('group_wait.time.time', return_value=1000):
            propanbot.handle_message(api, self.db, self.message(2, 'mayorskida narx qanaqa'))
        group_wait.tick(api, self.db, now=1029)
        api.call.assert_not_called()
        group_wait.tick(api, self.db, now=1030)
        payload = api.call.call_args.args[1]
        self.assertIn('Mayorskiy', payload['text'])
        self.assertIn('8 200', payload['text'])
        self.assertNotRegex(payload['text'], r'[А-Яа-яЎўҚқҒғҲҳ]')
        self.assertEqual(payload['reply_markup']['inline_keyboard'][0][0]['text'], '💰 Narx manbasi')

    def test_cyrillic_question_gets_cyrillic_card(self):
        api = Mock()
        with patch('group_wait.time.time', return_value=1000):
            propanbot.handle_message(api, self.db, self.message(2, 'Майорский нарх қанақа'))
        group_wait.tick(api, self.db, now=1030)
        payload = api.call.call_args.args[1]
        self.assertIn('Майорский', payload['text'])
        self.assertEqual(payload['reply_markup']['inline_keyboard'][0][0]['text'], '💰 Нарх манбаси')

    def test_urls_ids_and_phone_numbers_are_preserved(self):
        original = {'text': 'Нарх 8200. https://t.me/propan_uzbekistan_2026/42 +998901234567',
                    'reply_markup': {'inline_keyboard': [[{'text': 'Мўлжал', 'url': 'https://clck.ru/3PdhfF'}, {'text': 'Нарх', 'callback_data': 'st:14'}]]}}
        rendered = script_style.render(original, 'lat')
        self.assertIn('Narx 8200', rendered['text'])
        self.assertIn('https://t.me/propan_uzbekistan_2026/42', rendered['text'])
        self.assertIn('+998901234567', rendered['text'])
        self.assertEqual(rendered['reply_markup']['inline_keyboard'][0][0]['url'], original['reply_markup']['inline_keyboard'][0][0]['url'])
        self.assertEqual(rendered['reply_markup']['inline_keyboard'][0][1]['callback_data'], 'st:14')

    def test_inline_refresh_retains_original_card_script(self):
        api = Mock()
        station_directory.callback(api, self.db, {'id': 'cb', 'data': 'st:14', 'message': {'chat': {'id': -1, 'username': 'propan_uzbekistan_2026'}, 'message_id': 7, 'text': 'Mayorskiy narx'}})
        self.assertEqual(api.call.call_args.args[0], 'editMessageText')
        self.assertIn('Mayorskiy', api.call.call_args.args[1]['text'])
        self.assertNotRegex(api.call.call_args.args[1]['text'], r'[А-Яа-яЎўҚқҒғҲҳ]')

    def test_existing_sixty_second_deadline_is_shortened_once(self):
        self.db.execute("UPDATE wait_config SET value=60 WHERE key='seconds'")
        self.db.execute('INSERT INTO pending_questions VALUES (?, ?, ?, ?, ?)', (-1, 99, 1060, 'waiting', '{}'))
        self.db.commit()
        group_wait.initialize(self.db)
        self.assertEqual(self.db.execute('SELECT due FROM pending_questions WHERE message_id=99').fetchone()[0], 1030)
        group_wait.initialize(self.db)
        self.assertEqual(self.db.execute('SELECT due FROM pending_questions WHERE message_id=99').fetchone()[0], 1030)
