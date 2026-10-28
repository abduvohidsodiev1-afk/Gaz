import json
from pathlib import Path
import tempfile
import unittest
import history_import
import propanbot


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'result.json'
        self.chat = -1001234567890

    def export(self, messages, group_id=1234567890):
        self.path.write_text(json.dumps({'id': group_id, 'type': 'public_supergroup', 'messages': messages}))

    def msg(self, mid, text, reply=None):
        row = {'type': 'message', 'id': mid, 'date_unixtime': str(1793100000 + mid), 'text': text}
        if reply:
            row['reply_to_message_id'] = reply
        return row

    def test_last_1000_and_latest_price_win_regardless_of_export_order(self):
        messages = [self.msg(i, 'Ассалому алайкум') for i in range(1, 1005)]
        messages[0]['text'] = 'IBR 9000дан'
        messages[500]['text'] = 'IBR 8300дан'
        messages[1003]['text'] = 'Янги Узбекистан ишга тушди 8400сум'
        self.export(list(reversed(messages)))
        result = history_import.import_file(self.db, self.path, self.chat)
        self.assertEqual(result['messages'], 1000)
        self.assertEqual(result['prices'], 1)
        body = json.loads(self.db.execute('SELECT body FROM area_prices').fetchone()[0])
        self.assertEqual(body['price'], 8400)
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_history').fetchone()[0], 1000)

    def test_reply_chain_from_rich_text_export(self):
        self.export([self.msg(1, [{'type': 'bold', 'text': 'Choshtepa'}, ' 8500 danmi?']), self.msg(2, 'Ha shunaqa', 1)])
        history_import.import_file(self.db, self.path, self.chat)
        row = json.loads(self.db.execute('SELECT body FROM area_prices').fetchone()[0])
        self.assertEqual(row['price'], 8500)
        # Import and reanalysis do not send group messages or create reply acknowledgments.
        self.assertEqual(self.db.execute('SELECT count(*) FROM group_answers').fetchone()[0], 0)

    def test_wrong_group_is_rejected_before_writing(self):
        self.export([self.msg(1, 'IBR 8500dan')], group_id=999)
        with self.assertRaises(ValueError):
            history_import.import_file(self.db, self.path, self.chat)
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_history').fetchone()[0], 0)

    def test_repeat_import_and_replay_are_idempotent(self):
        self.export([self.msg(1, 'IBR 8500dan')])
        history_import.import_file(self.db, self.path, self.chat)
        history_import.import_file(self.db, self.path, self.chat)
        history_import.replay(self.db)
        self.assertEqual(self.db.execute('SELECT count(*) FROM area_prices').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM price_context').fetchone()[0], 1)

    def test_own_bot_export_messages_are_excluded(self):
        own = self.msg(2, 'IBR 9500dan')
        own['from_id'] = 'user123'
        self.export([self.msg(1, 'IBR 8500dan'), own])
        result = history_import.import_file(self.db, self.path, self.chat, own_bot_id=123)
        self.assertEqual(result['messages'], 1)

    def test_master_address_and_phone_are_updated(self):
        old = 'Уста: Test master\nҲудуд: Тошкент\nМанзил: Old test address\nХизмат: Пропан\nТелефон: 900000000'
        new = old.replace('Old test address', 'New test address').replace('900000000', '910000000')
        self.export([self.msg(1, old), self.msg(2, new)])
        result = history_import.import_file(self.db, self.path, self.chat)
        self.assertEqual(result['masters'], 1)
        row = json.loads(self.db.execute("SELECT body FROM catalog WHERE kind='masters'").fetchone()[0])
        self.assertEqual(row['address'], 'New test address')
        self.assertEqual(row['phone'], '+998910000000')

    def test_live_history_bounded_and_replay_has_no_outgoing_messages(self):
        from unittest.mock import Mock
        api = Mock()
        for mid in range(1, 1003):
            propanbot.handle_message(api, self.db, {'chat': {'id': self.chat, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'message_id': mid, 'date': 1793100000 + mid, 'text': 'Салом'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_history').fetchone()[0], 1000)
        self.assertEqual(history_import.replay(self.db), 1000)
        api.call.assert_not_called()
