import unittest
from unittest.mock import Mock, patch
import group_wait
import conversation
import price_parse
import propanbot
import question_intent
import station_directory


class QuestionIntentTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)

    def message(self, mid, text, stamp=1000):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'from': {'id': 10}, 'message_id': mid, 'date': stamp, 'text': text}

    def test_latin_cyrillic_and_common_requests_without_question_mark(self):
        for text in ['mayorskida narx qanaqa', 'майорскийда нарх қанақа', 'Майорский нарх кандай',
                     'Mayorskiy narx kanday', 'майорский нарх айтворила', 'Mayorskida narx aytvorilar',
                     'Майорский нархи қандей', 'Майорский нархини айтиб юборинг',
                     'Майорский нархини айтиб беринг', 'mayorskiy narx qande',
                     'Майорский нарх қанақакан']:
            self.assertTrue(question_intent.is_question(text), text)
            self.assertTrue(station_directory.reply(self.db, self.message(1, text)), text)
            self.assertIsNone(price_parse.amount(text), text)

    def test_exact_screenshot_waits_and_returns_existing_price(self):
        api = Mock()
        propanbot.handle_message(api, self.db, self.message(1, 'Майорский 8200', 900))
        with patch('group_wait.time.time', return_value=1000):
            propanbot.handle_message(api, self.db, self.message(2, 'mayorskida narx qanaqa'))
        api.call.assert_not_called()
        self.assertEqual(self.db.execute("SELECT count(*) FROM pending_questions WHERE state='waiting'").fetchone()[0], 1)
        group_wait.tick(api, self.db, now=1029)
        api.call.assert_not_called()
        group_wait.tick(api, self.db, now=1030)
        self.assertIn('8 200', api.call.call_args.args[1]['text'])
        labels = [b['text'] for row in api.call.call_args.args[1]['reply_markup']['inline_keyboard'] for b in row]
        self.assertEqual(labels, ['💰 Manba', '🚦 Manba', '📍 Xarita'])

    def test_qnaqa_screenshot_with_one_missing_letter_is_answered(self):
        api = Mock()
        propanbot.handle_message(api, self.db, self.message(1, 'Майорский 8200', 900))
        with patch('group_wait.time.time', return_value=1000):
            propanbot.handle_message(api, self.db, self.message(2, 'mayorskida narx qnaqa'))
        api.call.assert_not_called()
        group_wait.tick(api, self.db, now=1029)
        api.call.assert_not_called()
        group_wait.tick(api, self.db, now=1030)
        payload = api.call.call_args.args[1]
        self.assertIn('8 200', payload['text'])
        self.assertIn('Mayorskiy', payload['text'])
        self.assertNotRegex(payload['text'], r'[А-Яа-яЎўҚқҒғҲҳ]')

    def test_common_missing_letters_and_transpositions_in_question_words(self):
        for word in ['qnaqa', 'қнақа', 'qnacha', 'qacha', 'qnday', 'aytvorla']:
            self.assertTrue(question_intent.is_question('mayorskiy narx ' + word), word)
            self.assertIsNone(price_parse.amount('mayorskiy 8200 ' + word), word)
        for word in ['narx', 'narxi', 'som', 'sum', 'dan', 'ishlayapti', 'ochiq', 'yopiq']:
            self.assertFalse(question_intent.is_question('mayorskiy 8200 ' + word), word)

    def test_question_with_a_number_is_not_learned_as_a_price(self):
        message = self.message(1, 'Майорский 8200 нарх қанақа')
        station_directory.observe(self.db, message)
        self.assertEqual(self.db.execute('SELECT count(*) FROM station_updates').fetchone()[0], 0)
        self.assertIsNone(group_wait.parse_answer(message))
        conversation.observe(self.db, self.message(2, 'Майорский қанақа 8200сум'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM area_prices').fetchone()[0], 0)

    def test_price_facts_stay_facts_in_both_scripts(self):
        for text in ['майорский 8200', 'Mayorskiy narx 8200', 'Майорский нархи 8200', '8200']:
            self.assertFalse(question_intent.is_question(text), text)
            self.assertEqual(price_parse.amount(text), 8200)
