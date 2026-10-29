"""Live plumbing and source/30-second contracts. Mock model outputs, not AI quality."""
import contextlib
import io
import json
import threading
import unittest
from unittest.mock import Mock, patch
import local_ai
import propanbot
import station_directory
import group_wait


class LocalAITests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.api = Mock()

    def msg(self, mid, text, reply=None, author=10):
        m = {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'},
             'message_id': mid, 'date': 1000+mid, 'from': {'id': author, 'username': 'asker'}, 'text': text}
        if reply: m['reply_to_message'] = reply
        return m

    def helper(self):
        # No worker/network. Feed completed inference separately from receipt.
        with patch('local_ai.threading.Thread'):
            ai = local_ai.LocalAI()
        self.addCleanup(ai.close)
        return ai

    def finish(self, ai, kind='price_question'):
        message = ai.jobs.get_nowait()
        ai.results.put((message, kind))
        ai.drain(self.api, self.db)

    def test_screenshot_question_and_bridge_identity_both_scripts(self):
        for name in ['sassu kopri', 'сассу кўприк', 'сассиқ мост', 'сассик купру']:
            self.assertEqual(station_directory.find(name), ['bridge8'])
            self.assertEqual(station_directory.find(name + 'дан кейин'), ['bridge9'])
        self.assertEqual(station_directory.find('8 заправка ёки 9 заправка'), ['bridge8', 'bridge9'])
        with patch('group_wait.time.time', return_value=1000):
            propanbot.handle_message(self.api, self.db, self.msg(1, 'сассу кўприк 8200'))
            propanbot.handle_message(self.api, self.db, self.msg(2, 'sassu kopri narxi nec pul'))
        group_wait.tick(self.api, self.db, now=1029)
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1030)
        payload = self.api.call.call_args.args[1]
        self.assertIn('8 200', payload['text'])
        self.assertIn('8-zapravka', payload['text'])
        self.assertEqual(len(payload['reply_markup']['inline_keyboard'][0]), 3)

    def test_new_question_uses_original_deadline_and_no_ai_price(self):
        ai = self.helper()
        station_directory.observe(self.db, self.msg(0, 'Майорский 8300'))
        with patch('local_ai.time.time', return_value=1000):
            propanbot.handle_message(self.api, self.db, self.msg(1, 'mayorskida litriga tolovni eslatvor'), ai)
        group_wait.tick(self.api, self.db, now=1030)
        self.api.call.assert_not_called()  # Reserved, not yet approved by AI.
        with patch('local_ai.time.time', return_value=1007):
            self.finish(ai)
        self.assertEqual(self.db.execute('SELECT due FROM pending_questions').fetchone()[0], 1030)
        group_wait.tick(self.api, self.db, now=1029)
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1030)
        payload = self.api.call.call_args.args[1]
        self.assertIn('8 300', payload['text'])
        self.assertEqual(payload['reply_parameters']['message_id'], 1)
        group_wait.tick(self.api, self.db, now=1060)
        self.assertEqual(self.api.call.call_count, 1)

    def test_human_reply_during_inference_wins(self):
        ai = self.helper()
        q = self.msg(1, 'mayorskida litriga tolovni eslatvor')
        with patch('local_ai.time.time', return_value=1000):
            propanbot.handle_message(self.api, self.db, q, ai)
        propanbot.handle_message(self.api, self.db, self.msg(2, '8200', reply=q, author=20), ai)
        with patch('local_ai.time.time', return_value=1008): self.finish(ai)
        group_wait.tick(self.api, self.db, now=1040)
        self.api.call.assert_not_called()
        self.assertIn('8 200', station_directory.detail(self.db, '14')['text'])
        self.assertIn('/2', str(station_directory.detail(self.db, '14')['reply_markup']))

    def test_two_inflight_questions_mention_number_not_guessed(self):
        ai = self.helper()
        with patch('local_ai.time.time', return_value=1000):
            propanbot.handle_message(self.api, self.db, self.msg(1, 'mayorskida litriga tolovni eslatvor'), ai)
            propanbot.handle_message(self.api, self.db, self.msg(2, 'ibr litriga tolovni eslatvor'), ai)
        propanbot.handle_message(self.api, self.db, self.msg(3, '@asker 8200', author=20), ai)
        self.assertEqual(self.db.execute('SELECT count(*) FROM station_updates').fetchone()[0], 0)

    def test_other_stale_and_malformed_results_never_send_or_write(self):
        for intent, now in [('other', 1001), ('price_question', 1035)]:
            ai = self.helper()
            with patch('local_ai.time.time', return_value=1000):
                propanbot.handle_message(self.api, self.db, self.msg(1, 'mayorskida litriga tolovni eslatvor'), ai)
            with patch('local_ai.time.time', return_value=now): self.finish(ai, intent)
            group_wait.tick(self.api, self.db, now=1100)
            self.api.call.assert_not_called()
            self.assertEqual(self.db.execute('SELECT count(*) FROM pending_questions').fetchone()[0], 0)
        for content in ['{}', '{"intent":"price_question","price":8200}', '{"intent":"price_report"}', 'not json']:
            with patch('local_ai.request', return_value={'message': {'content': content}}):
                with self.assertRaises((ValueError, KeyError)):
                    local_ai.classify('mayorskiy')
        self.assertEqual(self.db.execute('SELECT count(*) FROM station_updates').fetchone()[0], 0)

    def test_only_unrecognized_known_station_messages_go_to_ai(self):
        ai = self.helper()
        for text in ['mayorskiy 8200', 'mayorskiy ochiq', 'mayorskiy qancha', 'salom', '/status', '@asker 8200']:
            self.assertFalse(ai.submit(self.msg(1, text), self.db), text)
        for chat in [{'type': 'private', 'id': 1}, {'type': 'supergroup', 'id': -2, 'username': 'propangr'}]:
            m = self.msg(1, 'mayorskiy litriga tolovni eslatvor');m['chat'] = chat
            self.assertFalse(ai.submit(m, self.db))
        with patch('local_ai.time.time', return_value=1000):
            for i in range(8): self.assertTrue(ai.submit(self.msg(i+1, 'mayorskiy litriga tolovni eslatvor'), self.db))
            self.assertFalse(ai.submit(self.msg(9, 'mayorskiy litriga tolovni eslatvor'), self.db))

    def test_model_prompt_contains_text_only_and_fixed_local_endpoint(self):
        with patch('local_ai.request', return_value={'message': {'content': '{"intent":"price_question"}'}}) as req:
            self.assertEqual(local_ai.classify('майорский эслатвор'), 'price_question')
            args = req.call_args.args
            self.assertEqual(args[0], '/api/chat')
            self.assertEqual(args[1]['messages'][1], {'role': 'user', 'content': 'майорский эслатвор'})
            self.assertNotIn('token', json.dumps(args))
        self.assertEqual(local_ai.URL, 'http://127.0.0.1:11434')

    def test_background_worker_handles_real_flow_and_recovers_from_error(self):
        ready = threading.Event()
        def classify(text):
            ready.set()
            return 'price_question'
        with patch('local_ai.request', return_value={'models': [{'name': local_ai.MODEL}]}), patch('local_ai.classify', side_effect=classify):
            ai = local_ai.LocalAI()
            try:
                ai.submit(self.msg(1, 'mayorskiy litriga tolovni eslatvor'), self.db)
                self.assertTrue(ready.wait(2))
                result = ai.results.get(timeout=2)
                self.assertEqual(result[1], 'price_question')
                self.assertEqual(ai.completed, 1)
            finally:
                ai.close();ai.worker.join(2)
        with patch('local_ai.request', side_effect=OSError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(local_ai.check(), 1)
