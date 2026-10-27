import json
import unittest
from unittest.mock import Mock
import ingestion
import propanbot


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.text = 'Шохобча: Test station\nҲудуд: Тошкент\nМанзил: Test street\nНарх: 6000 сўм'

    def message(self, text=None, stamp=1800000000, sender=42):
        return {'text': text or self.text, 'date': stamp, 'from': {'id': sender}, 'chat': {'id': sender, 'type': 'private'}}

    def entries(self):
        return [json.loads(r[0]) for r in self.db.execute('SELECT body FROM catalog')]

    def test_any_target_group_participant_can_submit_and_update(self):
        api = Mock()
        first = self.message(sender=123)
        second = self.message(self.text.replace('6000', '6500'), 1800000010, sender=456)
        for message in (first, second):
            message['chat'] = {'id': -123, 'type': 'supergroup', 'username': ingestion.SOURCE_USERNAME}
            propanbot.handle_message(api, self.db, message)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.entries()[0]['price'], 6500)
        api.call.assert_not_called()

    def test_duplicate_is_idempotent(self):
        ingestion.ingest(self.db, self.message())
        result = ingestion.ingest(self.db, self.message())
        self.assertIn('аввал', result)
        self.assertEqual(len(self.entries()), 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM inbox').fetchone()[0], 1)

    def test_old_forward_does_not_replace_new_price(self):
        ingestion.ingest(self.db, self.message())
        old = self.message(self.text.replace('6000', '5000'), 1800001000)
        old['forward_origin'] = {'date': 1700000000}
        self.assertIn('Эски', ingestion.ingest(self.db, old))
        self.assertEqual(self.entries()[0]['price'], 6000)

    def test_ambiguous_and_unrelated_messages(self):
        self.assertIsNone(ingestion.ingest(self.db, self.message('Ассалому алайкум')))
        self.assertIn('Текшириш', ingestion.ingest(self.db, self.message('Пропан 6000 сўм')))
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.db.execute("SELECT status FROM inbox").fetchone()[0], 'review')

    def test_master_import_and_phone_normalization(self):
        msg = self.message('Уста: Test master\nҲудуд: Бухоро\nМанзил: Test workshop\nХизмат: Пропан ускунаси\nТелефон: 90 000 00 00')
        ingestion.ingest(self.db, msg)
        self.assertEqual(self.entries()[0]['phone'], '+998900000000')
        self.assertEqual(self.entries()[0]['specialty'], 'Пропан ускунаси')

    def test_only_target_group_is_ingested_and_never_replied_to(self):
        api = Mock()
        msg = self.message()
        # Private submissions and the previously mentioned group cannot write.
        propanbot.handle_message(api, self.db, msg)
        self.assertEqual(self.entries(), [])
        api.reset_mock()
        for username in ('propangr', 'another_group', ''):
            msg['chat'] = {'id': -123, 'type': 'supergroup', 'username': username}
            propanbot.handle_message(api, self.db, msg)
            self.assertEqual(self.entries(), [])
        msg['chat']['username'] = ingestion.SOURCE_USERNAME
        propanbot.handle_message(api, self.db, msg)
        self.assertEqual(len(self.entries()), 1)
        api.call.assert_not_called()

    def test_multiple_places_not_guessed(self):
        text = self.text + '\nШохобча: Second\nНарх: 7000 сўм'
        self.assertIn('Текшириш', ingestion.ingest(self.db, self.message(text)))
        self.assertEqual(self.entries(), [])

    def test_catalog_reload_does_not_erase_live_updates(self):
        import tempfile
        from pathlib import Path
        import catalog
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.json'
            path.write_text('{"stations": [], "masters": []}')
            catalog.import_catalog(self.db, path)
            ingestion.ingest(self.db, self.message())
            catalog.import_catalog(self.db, path)
            self.assertEqual(len(self.entries()), 1)
