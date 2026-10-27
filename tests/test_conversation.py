import json
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone
import propanbot
import conversation


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.stamp = int(datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp())

    def msg(self, mid, text, parent=None, username='propan_uzbekistan_2026'):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': username}, 'message_id': mid, 'date': self.stamp + mid, 'text': text, 'reply_to_message': parent}

    def prices(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM area_prices')]

    def test_question_confirmation_then_actual_date(self):
        question = self.msg(1, 'Choshtepa 8500 danmi?')
        confirmation = self.msg(2, 'Ха шунака', question)
        when = self.msg(3, 'Qachon quydiz?', confirmation)
        date = self.msg(4, '20.10.26 год', when)
        conversation.observe(self.db, question)
        self.assertEqual(self.prices(), [])
        conversation.observe(self.db, confirmation)
        self.assertEqual(self.prices()[0]['price'], 8500)
        self.assertFalse(self.prices()[0]['explicit_date'])
        conversation.observe(self.db, when)
        conversation.observe(self.db, date)
        self.assertEqual(self.prices()[0]['updated'], '2026-10-20')
        self.assertTrue(self.prices()[0]['explicit_date'])
        self.assertIn('Choshtepa', conversation.listings(self.db)[0])
        self.assertIn('Қуйилган сана', conversation.listings(self.db)[0])

    def test_reply_parent_can_be_read_without_prior_poll(self):
        question = self.msg(1, 'Choshtepa 8500 danmi?')
        conversation.observe(self.db, self.msg(2, 'Ha shunaqa', question))
        self.assertEqual(self.prices()[0]['price'], 8500)

    def test_unrelated_and_negative_replies_do_not_confirm(self):
        question = self.msg(1, 'Choshtepa 8500 danmi?')
        for i, reply in enumerate(['Yoq', 'Ha endi bilmadim', 'Qachon?', '8500 emas'], 2):
            conversation.observe(self.db, self.msg(i, reply, question))
        self.assertEqual(self.prices(), [])

    def test_bare_yes_and_other_groups_do_not_write(self):
        api = Mock()
        question = self.msg(1, 'Choshtepa 8500 danmi?')
        propanbot.handle_message(api, self.db, self.msg(2, 'Ha shunaqa'))
        propanbot.handle_message(api, self.db, self.msg(3, 'Ha shunaqa', question, 'other_group'))
        self.assertEqual(self.prices(), [])
        api.call.assert_not_called()

    def test_direct_price_and_duplicate(self):
        message = self.msg(1, 'Choshtepa 8500 dan')
        conversation.observe(self.db, message)
        conversation.observe(self.db, message)
        self.assertEqual(len(self.prices()), 1)
        self.assertEqual(len(conversation.listings(self.db, 'Чоштепа')), 1)

    def test_caption_price_question_and_numeric_answer(self):
        photo = self.msg(10, '')
        photo['caption'] = 'Кибрай ИБР очеред кам'
        del photo['text']
        question = self.msg(11, 'Нечи пул пропан ака?', photo)
        answer = self.msg(12, '8200', question)
        for message in (photo, question):
            conversation.observe(self.db, message)
            self.assertEqual(self.prices(), [])
        conversation.observe(self.db, answer)
        self.assertEqual(self.prices()[0]['price'], 8200)
        self.assertIn('ibr', self.prices()[0]['place'])

    def test_bare_number_without_price_question_is_ignored(self):
        photo = self.msg(10, 'Кибрай ИБР очеред кам')
        conversation.observe(self.db, photo)
        conversation.observe(self.db, self.msg(11, '8200', photo))
        self.assertEqual(self.prices(), [])

    def test_no_station_or_coordinates_invented(self):
        conversation.observe(self.db, self.msg(1, 'Choshtepa 8500 dan'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog').fetchone()[0], 0)
        self.assertIn('манзил кўрсатилмаган', conversation.listings(self.db)[0])


if __name__ == '__main__':
    unittest.main()
