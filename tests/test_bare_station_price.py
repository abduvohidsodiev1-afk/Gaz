import unittest
from unittest.mock import Mock, patch
import group_wait
import history_import
import price_parse
import propanbot
import station_directory


class BareStationPriceTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.api = Mock()

    def message(self, mid, text, stamp):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'from': {'id': 10, 'first_name': 'Reporter'}, 'message_id': mid, 'date': stamp, 'text': text}

    def test_exact_screenshot_price_precedes_question_and_is_found_after_wait(self):
        propanbot.handle_message(self.api, self.db, self.message(1, 'майорский 8200', 1000))
        with patch('group_wait.time.time', return_value=1540):
            propanbot.handle_message(self.api, self.db, self.message(2, 'майорский канча', 1540))
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1599)
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1600)
        payload = self.api.call.call_args.args[1]
        self.assertIn('8 200', payload['text'])
        self.assertIn('Майорский', payload['text'])
        self.assertNotIn('Нарх базада топилмади', payload['text'])
        self.assertIn('Очиқ/ёпиқлиги: хабар берилмаган', payload['text'])
        self.assertIn('/1', str(payload['reply_markup']))

    def test_all_listed_name_fact_variants_work_without_currency(self):
        for mid, text in enumerate(['майорский 8200', 'Майорский: 8 200', 'Майорский - 8300', 'Майорский 8400 очиқ'], 1):
            station_directory.observe(self.db, self.message(mid, text, 1000+mid))
        card = station_directory.detail(self.db, '14')
        self.assertIn('8 400', card['text'])
        self.assertIn('Очиқ / газ бор', card['text'])

    def test_history_reanalysis_recovers_previously_skipped_fact(self):
        history_import.remember(self.db, self.message(1, 'майорский 8200', 1000))
        history_import.replay(self.db)
        self.assertIn('8 200', station_directory.detail(self.db, '14')['text'])

    def test_unrelated_numbers_dates_phone_ranges_and_questions_are_not_prices(self):
        for text in ['Майорский канча', 'Майорский 8200?', 'Майорский 8200ми',
                     'Майорский +998 90 123 45 67', 'Майорский 20.10.2026',
                     'Майорский 8000-8200', 'Майорский ВАЗ2107', 'Майорский 2026 йил',
                     'Майорский 8200 эски нарх']:
            self.assertIsNone(price_parse.amount(text), text)
        self.assertEqual(price_parse.amount('Майорский 8200 +998901234567'), 8200)

    def test_bare_price_does_not_invent_an_unknown_station(self):
        station_directory.observe(self.db, self.message(1, 'Ноаниқ янги ном 8200', 1000))
        self.assertEqual(self.db.execute('SELECT count(*) FROM station_updates').fetchone()[0], 0)
