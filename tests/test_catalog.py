import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import catalog
import propanbot


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'catalog.json'
        # Synthetic test fixtures; these are not public listings.
        self.data = {'stations': [
            {'id': 's1', 'name': 'Test A', 'region': 'Тошкент', 'address': 'Test street', 'price': 6000, 'updated': '2026-01-01', 'latitude': 41.3, 'longitude': 69.2},
            {'id': 's2', 'name': 'Test B', 'region': 'Бухоро', 'address': 'Test street', 'latitude': 39.7, 'longitude': 64.4}],
            'masters': [{'id': 'm1', 'name': 'Test master', 'region': 'Тошкент', 'address': 'Test workshop', 'specialty': 'Test service', 'phone': '+998900000000'}]}
        self.load()

    def load(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')
        catalog.import_catalog(self.db, self.path)

    def test_search_latin_and_cyrillic(self):
        results = catalog.directory(self.db, 'stations', 'Toshkent')
        self.assertEqual(len(results), 1)
        self.assertIn('Test A', results[0])
        self.assertIn('6 000', results[0])
        self.assertIn('2026-01-01', results[0])
        self.assertIn('google.com/maps', results[0])
        self.assertNotIn('Test B', results[0])

    def test_nearest_and_no_location_persistence(self):
        before = self.db.total_changes
        results = catalog.responses(self.db, {'location': {'latitude': 39.7, 'longitude': 64.4}})
        self.assertIn('Test B', results[0])
        self.assertIn('0.0 км', results[0])
        self.assertEqual(self.db.total_changes, before)

    def test_master_button_and_command(self):
        for text in [catalog.MASTERS, '/masters@gazpropan_uz_bot Toshkent']:
            result = catalog.responses(self.db, {'text': text})
            self.assertEqual(len(result), 1)
            self.assertIn('+998900000000', result[0])
            self.assertIn('Test service', result[0])

    def test_invalid_import_keeps_previous_data(self):
        self.data['stations'][0]['price'] = -10
        with self.assertRaises(ValueError):
            self.load()
        self.assertIn('6 000', catalog.directory(self.db, 'prices', 'Тошкент')[0])

    def test_no_data_and_missing_price_are_explicit(self):
        self.assertIn('нарх киритилмаган', catalog.directory(self.db, 'prices', 'Бухоро')[0])
        self.assertIn('топилмади', catalog.directory(self.db, 'masters', 'Хоразм')[0])
        with self.db:
            self.db.execute('DELETE FROM catalog')
        self.assertIn('қўшилмаган', catalog.responses(self.db, {'text': catalog.STATIONS})[0])

    def test_private_message_routing(self):
        api = Mock()
        propanbot.handle_message(api, self.db, {'chat': {'type': 'group', 'id': 1}, 'text': '/masters'})
        api.call.assert_not_called()
        propanbot.handle_message(api, self.db, {'chat': {'type': 'private', 'id': 1}, 'text': '/masters'})
        self.assertEqual(api.call.call_args.args[0], 'sendMessage')
        payload = api.call.call_args.args[1]
        self.assertIn('+998900000000', payload['text'])
        self.assertIn('keyboard', payload['reply_markup'])

    def test_all_regions_available(self):
        self.assertEqual(len(catalog.REGIONS), 14)
        self.assertIn('Қорақалпоғистон', catalog.responses(self.db, {'text': '/regions'})[0])


if __name__ == '__main__':
    unittest.main()
