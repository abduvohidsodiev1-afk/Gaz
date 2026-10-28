import unittest
from unittest.mock import Mock
import json
import propanbot
import conversation


class GroupAnswerTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.api = Mock()
        conversation.observe(self.db, self.msg(1, 'Choshtepa 8500 dan'))

    def msg(self, mid, text, username='propan_uzbekistan_2026'):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': username},
                'from': {'id': 22}, 'message_id': mid, 'date': 1793100000 + mid, 'text': text}

    def test_natural_question_reply_is_sent_in_same_group(self):
        message = self.msg(2, 'Чоштепада пропан қанча?')
        message['message_thread_id'] = 99
        propanbot.handle_message(self.api, self.db, message)
        method, payload = self.api.call.call_args.args
        self.assertEqual(method, 'sendMessage')
        self.assertEqual(payload['chat_id'], -1)
        self.assertEqual(payload['reply_parameters']['message_id'], 2)
        self.assertEqual(payload['message_thread_id'], 99)
        self.assertIn('8 500', payload['text'])
        self.assertIn('inline_keyboard', payload['reply_markup'])
        self.assertNotIn('keyboard', payload['reply_markup'])

    def test_price_question_reply_uses_parent_location(self):
        photo = self.msg(3, '')
        photo['caption'] = 'Кибрай ИБР очеред кам'
        del photo['text']
        propanbot.handle_message(self.api, self.db, photo)
        question = self.msg(4, 'Нечи пул пропан ака?')
        question['reply_to_message'] = photo
        propanbot.handle_message(self.api, self.db, question)
        self.assertIn('топилмади', self.api.call.call_args.args[1]['text'])

    def test_question_not_answered_twice(self):
        message = self.msg(2, '/prices Choshtepa')
        propanbot.handle_message(self.api, self.db, message)
        propanbot.handle_message(self.api, self.db, message)
        self.assertEqual(self.api.call.call_count, 1)

    def test_unrelated_and_other_group_and_bot_messages_ignored(self):
        for message in [self.msg(2, 'Ассалому алайкум'), self.msg(3, '/prices Choshtepa', 'other_group')]:
            propanbot.handle_message(self.api, self.db, message)
        bot = self.msg(4, '/prices Choshtepa')
        bot['from']['is_bot'] = True
        propanbot.handle_message(self.api, self.db, bot)
        self.api.call.assert_not_called()

    def test_no_address_invented_from_price_report(self):
        propanbot.handle_message(self.api, self.db, self.msg(5, 'Чоштепада шохобча қаерда?'))
        self.assertIn('Чоштепа', self.api.call.call_args.args[1]['text'])
        self.assertIn('https://clck.ru/3Pdgm3', str(self.api.call.call_args.args[1]['reply_markup']))

    def test_master_phone_is_returned_in_group(self):
        item = {'id': 'test', 'name': 'Test workshop', 'region': 'Toshkent', 'address': 'Test address', 'phone': 'TEST-PHONE', 'specialty': 'Test service'}
        with self.db:
            self.db.execute('INSERT INTO catalog VALUES (?, ?, ?)', ('masters', 'test', json.dumps(item)))
        propanbot.handle_message(self.api, self.db, self.msg(6, 'Тошкентда уста телефони борми?'))
        self.assertIn('TEST-PHONE', self.api.call.call_args.args[1]['text'])

    def test_missing_location_asks_in_same_chat(self):
        propanbot.handle_message(self.api, self.db, self.msg(7, 'Пропан қанча?'))
        self.assertIn('Қайси шаҳар', self.api.call.call_args.args[1]['text'])

    def test_opening_price_is_answered_back_in_group(self):
        propanbot.handle_message(self.api, self.db, self.msg(20, 'Янги Узбекистан ишга тушди 8300сум'))
        self.api.call.assert_not_called()
        propanbot.handle_message(self.api, self.db, self.msg(21, 'Янги Узбекистанда пропан қанча?'))
        self.assertIn('8 300', self.api.call.call_args.args[1]['text'])

    def test_ibr_question_does_not_borrow_yangi_price(self):
        propanbot.handle_message(self.api, self.db, self.msg(30, 'Янги Узбекистан ишга тушди 8300сум'))
        for mid, text in [(31, 'ИБРда пропан қанча?'), (32, '/prices IBR')]:
            propanbot.handle_message(self.api, self.db, self.msg(mid, text))
            payload = self.api.call.call_args.args[1]
            self.assertIn('Қибрай IBR', payload['text'])
            self.assertNotIn('8 300', payload['text'])
            self.assertIn('нарх ҳали тасдиқланмаган', payload['text'])

    def test_command_for_another_bot_is_ignored(self):
        propanbot.handle_message(self.api, self.db, self.msg(8, '/prices@other_bot Choshtepa'))
        self.api.call.assert_not_called()
