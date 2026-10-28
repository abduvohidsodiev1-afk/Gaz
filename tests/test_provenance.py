import json
from pathlib import Path
import tempfile
import unittest
import conversation
import history_import
import provenance
import propanbot


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)

    def message(self, mid, text, user='Reporter', parent=None):
        return {'chat': {'id': -1001234567890, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'from': {'first_name': user, 'username': 'public_user'}, 'message_id': mid, 'date': 1793100000 + mid, 'text': text, 'reply_to_message': parent}

    def test_confirmation_author_not_questioner_and_date_does_not_replace_author(self):
        question = self.message(1, 'Choshtepa 8500 danmi?', 'Questioner')
        confirmed = self.message(2, 'Ha shunaqa', 'Reporter', question)
        when = self.message(3, 'Qachon quydiz?', 'Other user', confirmed)
        date = self.message(4, '20.10.26 год', 'Date author', when)
        for message in (question, confirmed, when, date):
            conversation.observe(self.db, message)
        listing = conversation.listings(self.db)[0]
        self.assertIn('Хабар муаллифи: Reporter', listing)
        self.assertIn('https://t.me/propan_uzbekistan_2026/2', listing)
        self.assertIn('https://t.me/public_user', listing)
        self.assertNotIn('Хабар муаллифи: Questioner', listing)
        self.assertNotIn('Date author', listing)

    def test_export_keeps_author_and_message_link(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'result.json'
            path.write_text(json.dumps({'id': 1234567890, 'type': 'public_supergroup', 'messages': [{'id': 99, 'type': 'message', 'from': 'Export Reporter', 'date_unixtime': '1793100000', 'text': 'Yangi Uzbekistan 8300dan'}]}))
            history_import.import_file(self.db, path, -1001234567890)
        listing = conversation.listings(self.db)[0]
        self.assertIn('Export Reporter', listing)
        self.assertIn('https://t.me/propan_uzbekistan_2026/99', listing)
        self.assertNotIn('Муаллифга ёзиш:', listing)  # Export has no public username.

    def test_hidden_forward_author_is_not_misattributed(self):
        message = self.message(5, 'IBR 8300dan', 'Forwarder')
        message['forward_origin'] = {'type': 'hidden_user', 'sender_user_name': 'Original author', 'date': 1793000000}
        source = provenance.capture(message)
        self.assertEqual(source['name'], 'Original author')
        self.assertNotIn('username', source)
