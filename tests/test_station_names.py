import unittest
import conversation
import propanbot
import station_names
import group_answers


class StationNameTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)

    def msg(self, mid, text):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'message_id': mid, 'date': 1793100000 + mid, 'text': text}

    def test_q_k_o_u_and_station_word_typo(self):
        for text in ['кизил запрка', 'қизил заправка', 'кизил запрафка']:
            self.assertEqual(conversation.canonical_place(text), 'kofe zapravka')
        for text in ['Майорский', 'маёрский', 'майорски', 'майорскй']:
            self.assertEqual(conversation.canonical_place(text), 'mayorskiy')

    def test_numbers_never_fuzzy_merge(self):
        self.assertEqual(station_names.resolve('8 запрка', {'9 заправка': 'nine'}), ('', []))
        self.assertEqual(conversation.canonical_place('9 запрка сассиқ мост'), '9 zapravka')
        self.assertEqual(conversation.canonical_place('8 запрка сассу куприк'), '8 zapravka')

    def test_latest_owner_mapping_for_bare_bridge_names(self):
        for name in ['сассиқ мост', 'сассу мост', 'сассиқ куприк', 'сассу куприк', 'сассик купру', 'sassu kopri']:
            self.assertEqual(conversation.canonical_place(name), '8 zapravka')
            self.assertEqual(conversation.canonical_place(name + 'дан кейин'), '9 zapravka')

    def test_two_similar_names_are_not_guessed(self):
        self.assertEqual(station_names.resolve('Chushtepa', {'Choshtepa': 'one', 'Chushtepa': 'two'}), ('', ['one', 'two']))
        self.assertEqual(station_names.resolve('IB', {'IBR': 'ibr'}), ('', []))

    def test_dynamic_history_names_and_two_typos(self):
        conversation.observe(self.db, self.msg(1, 'Choshtepa 8300dan'))
        conversation.observe(self.db, self.msg(2, 'Choshteppa 8400dan'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM area_prices').fetchone()[0], 1)
        self.assertIn('8,400', conversation.listings(self.db, 'Choshtepa')[0])
        self.assertEqual(self.db.execute("SELECT canonical FROM station_aliases WHERE alias='choshteppa'").fetchone()[0], 'choshtepa')
        answer = group_answers.answer(self.db, self.msg(3, 'Чоштеппада пропан қанча?'))
        self.assertIn('8,400', answer)

    def test_twenty_plus_known_names_supported_without_invented_station_records(self):
        aliases = {'test station ' + str(i): 'station-' + str(i) for i in range(25)}
        for i in range(25):
            self.assertEqual(station_names.resolve('test statoin ' + str(i), aliases)[0], 'station-' + str(i))
        response = group_answers.answer(self.db, self.msg(1, '/names'))
        self.assertIn('mayorskiy', response)
        self.assertEqual(self.db.execute('SELECT count(*) FROM area_prices').fetchone()[0], 0)
