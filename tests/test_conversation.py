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

    def test_opening_report_with_attached_currency(self):
        message = self.msg(20, 'Янги Узбекистан ишга тушди 8300сум')
        conversation.observe(self.db, message)
        row = self.prices()[0]
        self.assertEqual(row['place'], 'yangi uzbekistan')
        self.assertEqual(row['price'], 8300)
        self.assertNotIn('ishga', row['place'])

    def test_currency_and_opening_variants(self):
        for text in ['Yangi Uzbekistan ishga tushdi 8300sum',
                     'Yangi Uzbekistan ochildi 8300 som',
                     'Янги Узбекистан 8300сўм']:
            result = conversation.proposal(text)
            self.assertEqual(result['price'], 8300)
            self.assertEqual(result['place'], 'yangi uzbekistan')
        self.assertIsNone(conversation.proposal('Янги Узбекистан ишга тушмади 8300сум'))

    def test_ibr_and_yangi_uzbekistan_are_separate(self):
        conversation.observe(self.db, self.msg(30, 'Янги Узбекистан ишга тушди 8300сум'))
        conversation.observe(self.db, self.msg(31, 'IBR 8400 dan'))
        self.assertEqual(len(self.prices()), 2)
        self.assertIn('8,400', conversation.listings(self.db, 'ИБР')[0])
        self.assertIn('8,300', conversation.listings(self.db, 'Янги Ўзбекистон')[0])
        self.assertEqual(len(conversation.listings(self.db, 'ИБР')), 1)
        self.assertEqual(len(conversation.listings(self.db, 'Янги Ўзбекистон')), 1)
        # Do not conflate other qualified station names with this exact alias.
        self.assertNotEqual(conversation.canonical_place('Кибрай ИБР'), 'yangi uzbekistan')

    def test_old_ibr_rows_are_kept_separate_on_startup(self):
        for place, price, stamp in [('ibr', 8300, 100), ('yangi uzbekistan', 8400, 200)]:
            row = {'place': place, 'price': price, 'updated': '2026-10-27', 'report_stamp': stamp, 'explicit_date': False}
            self.db.execute('INSERT INTO area_prices VALUES (?, ?)', (place, json.dumps(row)))
        self.db.commit()
        conversation.initialize(self.db)
        self.assertEqual(len(self.prices()), 2)
        self.assertIn('8,300', conversation.listings(self.db, 'ibr')[0])
        self.assertIn('8,400', conversation.listings(self.db, 'yangi uzbekistan')[0])

    def test_wrong_saved_ibr_alias_is_corrected_from_raw_context(self):
        self.db.execute('INSERT INTO station_aliases VALUES (?, ?)', ('ibr', 'yangi uzbekistan'))
        context = {'place': 'yangi uzbekistan', '_raw_place': 'ibr', 'price': 8200, 'question': False, 'stamp': 100}
        row = {'place': 'yangi uzbekistan', 'price': 8200, 'updated': '2026-10-20', 'report_stamp': 100, 'explicit_date': False, '_price_source': {'link': 'https://t.me/propan_uzbekistan_2026/42'}}
        self.db.execute('INSERT INTO price_context VALUES (?, ?, ?)', (-1, 42, json.dumps(context)))
        self.db.execute('INSERT INTO area_prices VALUES (?, ?)', ('yangi uzbekistan', json.dumps(row)))
        self.db.commit()
        conversation.initialize(self.db)
        self.assertEqual(conversation.known_aliases(self.db)['ibr'], 'kibray ibr')
        self.assertEqual(self.prices()[0]['place'], 'kibray ibr')
        self.assertEqual(len(self.prices()), 1)

    def test_no_station_or_coordinates_invented(self):
        conversation.observe(self.db, self.msg(1, 'Choshtepa 8500 dan'))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM catalog').fetchone()[0], 0)
        self.assertIn('манзил кўрсатилмаган', conversation.listings(self.db)[0])


if __name__ == '__main__':
    unittest.main()
