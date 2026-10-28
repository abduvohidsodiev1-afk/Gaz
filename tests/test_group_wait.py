import unittest
from unittest.mock import Mock, patch
import group_wait
import station_directory
import propanbot


class GroupWaitTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.api = Mock()
        self.clock = patch('group_wait.time.time', return_value=1000)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)

    def message(self, mid, text, stamp=1000, reply=None, author=10, username='asker_one'):
        result = {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'message_id': mid, 'date': stamp, 'text': text, 'from': {'id': author, 'username': username, 'first_name': 'Person'}}
        if reply:
            result['reply_to_message'] = reply
        return result

    def ask(self, mid=1, text='Чоштепада пропан қанча?'):
        message = self.message(mid, text)
        propanbot.handle_message(self.api, self.db, message)
        return message

    def test_waits_thirty_seconds_then_replies_once_in_group(self):
        self.ask()
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1029)
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1030)
        self.assertEqual(self.api.call.call_count, 1)
        self.assertEqual(self.api.call.call_args.args[1]['reply_parameters']['message_id'], 1)
        group_wait.tick(self.api, self.db, now=1100)
        self.assertEqual(self.api.call.call_count, 1)

    def test_bare_numeric_reply_updates_price_and_suppresses_bot(self):
        question = self.ask()
        propanbot.handle_message(self.api, self.db, self.message(2, '8200', 1020, reply=question, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])
        self.assertIn('/2', str(station_directory.detail(self.db, '11/1')['reply_markup']))

    def test_tagged_asker_with_number_and_no_reply(self):
        self.ask()
        propanbot.handle_message(self.api, self.db, self.message(2, '@asker_one 8 200', 1020, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])

    def test_text_mention_by_user_id(self):
        self.ask()
        answer = self.message(2, 'Person 8200', 1020, author=20)
        answer['entities'] = [{'type': 'text_mention', 'offset': 0, 'length': 6, 'user': {'id': 10}}]
        propanbot.handle_message(self.api, self.db, answer)
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()

    def test_same_price_also_cancels_fallback(self):
        station_directory.observe(self.db, self.message(9, 'Чоштепа 8200сум', 900))
        question = self.ask()
        propanbot.handle_message(self.api, self.db, self.message(2, '8200', 1020, reply=question, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()

    def test_tag_is_ambiguous_between_two_stations_no_price_is_guessed(self):
        self.ask()
        self.ask(2, 'Майорский пропан қанча?')
        propanbot.handle_message(self.api, self.db, self.message(3, '@asker_one 8200', 1020, author=20))
        self.assertEqual(self.db.execute('SELECT count(*) FROM station_updates').fetchone()[0], 0)
        group_wait.tick(self.api, self.db, now=1031)
        self.assertEqual(self.api.call.call_count, 2)

    def test_explicit_reply_disambiguates_two_questions(self):
        question = self.ask()
        self.ask(2, 'Майорский пропан қанча?')
        propanbot.handle_message(self.api, self.db, self.message(3, '8200', 1020, reply=question, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.assertEqual(self.api.call.call_count, 1)
        self.assertEqual(self.api.call.call_args.args[1]['reply_parameters']['message_id'], 2)
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])
        self.assertNotIn('8 200', station_directory.detail(self.db, '14')['text'])

    def test_unrelated_number_and_non_answer_do_not_cancel(self):
        question = self.ask()
        propanbot.handle_message(self.api, self.db, self.message(2, '8200', 1020, author=20))
        propanbot.handle_message(self.api, self.db, self.message(3, 'Билмайман', 1021, reply=question, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.assertEqual(self.api.call.call_count, 1)

    def test_named_fact_counts_as_human_answer(self):
        self.ask()
        propanbot.handle_message(self.api, self.db, self.message(2, 'Чоштепа 8200сум', 1020, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])

    def test_persistent_pending_question_survives_reinitialization(self):
        self.ask()
        group_wait.initialize(self.db)
        self.assertEqual(group_wait.poll_timeout(self.db, now=1025), 5)
        group_wait.tick(self.api, self.db, now=1030)
        self.assertEqual(self.api.call.call_count, 1)

    def test_historical_questions_never_schedule_group_posts(self):
        question = self.message(1, 'Чоштепада пропан қанча?')
        answer = self.message(2, '8200', 1020, reply=question, author=20)
        group_wait.learn_history(self.db, question)
        group_wait.learn_history(self.db, answer)
        group_wait.tick(self.api, self.db, now=5000)
        self.api.call.assert_not_called()
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])

    def test_kancha_without_question_mark_waits_then_answers(self):
        for mid, text in [(1, '8 заправкада нарх канча'), (2, 'Чоштепада пропан қанча'), (3, 'Майорскийда пропан kancha')]:
            self.ask(mid, text)
        self.api.call.assert_not_called()
        self.assertEqual(self.db.execute("SELECT count(*) FROM pending_questions WHERE state='waiting'").fetchone()[0], 3)
        group_wait.tick(self.api, self.db, now=1030)
        self.assertEqual(self.api.call.call_count, 3)

    def test_kancha_in_reply_uses_the_station_in_quoted_message(self):
        source = self.message(1, 'Чоштепа навбат кам', 990)
        question = self.message(2, 'канча', 1000, reply=source)
        propanbot.handle_message(self.api, self.db, question)
        self.api.call.assert_not_called()
        propanbot.handle_message(self.api, self.db, self.message(3, '8200', 1020, reply=question, author=20))
        self.assertIn('8 200', station_directory.detail(self.db, '11/1')['text'])
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()

    def test_price_confirmation_is_a_human_answer(self):
        question = self.ask(text='8 заправка 8200данми?')
        propanbot.handle_message(self.api, self.db, self.message(2, 'Ҳа шунақа', 1020, reply=question, author=20))
        group_wait.tick(self.api, self.db, now=1031)
        self.api.call.assert_not_called()
        self.assertIn('8 200', station_directory.detail(self.db, 'bridge8')['text'])

    def test_other_topic_or_group_cannot_cancel(self):
        question = self.ask()
        answer = self.message(2, '8200', 1020, reply=question, author=20)
        answer['message_thread_id'] = 5
        propanbot.handle_message(self.api, self.db, answer)
        group_wait.tick(self.api, self.db, now=1031)
        self.assertEqual(self.api.call.call_count, 1)
