import unittest
from unittest.mock import Mock
import conversation
import propanbot
import group_answers


class LandmarkTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)

    def msg(self, mid, text):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'from': {'id': 1}, 'message_id': mid, 'date': 1793100000 + mid, 'text': text}

    def test_all_bridge_spellings_keep_before_and_after_distinct(self):
        for bridge in ['сассу мост', 'сассиқ мост', 'сассу кўприк', 'сассиқ кўприк']:
            self.assertEqual(conversation.canonical_place(bridge + 'га етмасдан'), '8 zapravka')
            self.assertEqual(conversation.canonical_place(bridge + 'дан кейин'), '9 zapravka')
            self.assertEqual(conversation.landmark_place(bridge), '8 zapravka' if bridge == 'сассу кўприк' else '9 zapravka')

    def test_coffee_red_and_opposite_are_one_station(self):
        for text in ['кофе заправка', 'қизил заправка', 'сассу мостадан кейин 9 заправкани тўғрисидаги заправка']:
            self.assertEqual(conversation.canonical_place(text), 'kofe zapravka')

    def test_prices_update_by_alias_without_mixing_three_stations(self):
        messages = ['8 заправка 8000дан', '9 заправка 9000дан', 'кофе заправка 8500дан', 'қизил заправка 8600дан']
        for mid, text in enumerate(messages, 1):
            conversation.observe(self.db, self.msg(mid, text))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM area_prices').fetchone()[0], 3)
        self.assertIn('8,600', conversation.listings(self.db, 'кофе заправка')[0])
        self.assertIn('8,000', conversation.listings(self.db, 'сассиқ мостга етмасдан')[0])
        self.assertIn('9,000', conversation.listings(self.db, 'сассу кўприкдан кейин')[0])

    def test_ambiguous_bridge_is_not_used_as_station(self):
        self.assertIsNone(conversation.proposal('сассик купру 8000дан'))
        answer = group_answers.answer(self.db, self.msg(1, 'Сассик купруда пропан қанча?'))
        self.assertIn('8-заправками', answer)
        self.assertIn('9-заправками', answer)
        self.assertIn('Қизил', answer)

    def test_group_queries_return_landmark_and_correct_price(self):
        conversation.observe(self.db, self.msg(1, 'қизил заправка 8600дан'))
        api = Mock()
        propanbot.handle_message(api, self.db, self.msg(2, 'Кофе заправкада пропан қанча?'))
        self.assertIn('8,600', api.call.call_args.args[1]['text'])
        self.assertIn('рўпарасида', api.call.call_args.args[1]['text'])
        answer = group_answers.answer(self.db, self.msg(3, 'Сассу мостдан кейин заправка қаерда?'))
        self.assertIn('9-заправка', answer)
