import json
import unittest
from unittest.mock import Mock, patch
import propanbot
import station_directory as directory


class DirectoryTests(unittest.TestCase):
    def setUp(self):
        self.delay_patch = patch('group_wait.WAIT_SECONDS', 0)
        self.delay_patch.start()
        self.addCleanup(self.delay_patch.stop)
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)

    def msg(self, mid, text):
        return {'chat': {'id': -1, 'type': 'supergroup', 'username': 'propan_uzbekistan_2026'}, 'from': {'id': 42}, 'message_id': mid, 'date': 1793100000+mid, 'text': text}

    def test_seed_includes_metadata_only_no_old_price_status_or_phone(self):
        self.assertEqual(len(directory.STATIONS), 28)
        card = directory.detail(self.db, '2')
        self.assertIn('08:00–20:00', card['text'])
        self.assertIn('Нарх базада топилмади', card['text'])
        self.assertNotIn('ЗАКРЫТО', card['text'])
        self.assertNotIn('+998', card['text'])
        self.assertIn('https://clck.ru/3PdaHy', str(card['reply_markup']))
        self.assertEqual(len(card['reply_markup']['inline_keyboard']), 1)

    def test_latest_price_and_status_have_separate_timestamps(self):
        directory.observe(self.db, self.msg(1, 'Назарбек очиқ 8300сум'))
        directory.observe(self.db, self.msg(2, 'Назарбек ёпиқ'))
        directory.observe(self.db, self.msg(0, 'Назарбек очиқ 8100сум'))
        card = directory.detail(self.db, '4')
        self.assertIn('8 300', card['text'])
        self.assertIn('Ёпиқ', card['text'])
        self.assertIn('/1', str(card['reply_markup']))  # Price source link preserved.

    def test_question_is_not_treated_as_status_fact(self):
        directory.observe(self.db, self.msg(1, 'Назарбек очиқми?'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM station_updates').fetchone()[0], 0)

    def test_ambiguous_sergeli_gets_two_distinct_buttons(self):
        response = directory.reply(self.db, self.msg(1, 'Сергелида пропан қанча?'))
        self.assertIn('st:10', str(response['reply_markup']))
        self.assertIn('st:11', str(response['reply_markup']))
        self.assertNotEqual(directory.DATA['10'][3], directory.DATA['11'][3])

    def test_kfc_is_not_merged_with_plain_choshtepa(self):
        self.assertEqual(directory.find('Чоштепа KFC очиқми?'), ['11/2'])
        self.assertEqual(directory.find('Чоштепада пропан қанча?'), ['11/1'])

    def test_group_reply_is_compact_full_name_and_inline_only(self):
        api = Mock()
        propanbot.handle_message(api, self.db, self.msg(2, 'Майорский очиқми?'))
        payload = api.call.call_args.args[1]
        self.assertIn('Майорский — ГАИ пости, Оҳангарон шоссеси', payload['text'])
        self.assertLess(len(payload['text']), 500)
        self.assertEqual(len(payload['reply_markup']['inline_keyboard']), 1)
        self.assertNotIn('keyboard', payload['reply_markup'])

    def test_callback_edits_existing_card_not_a_new_message(self):
        api = Mock()
        directory.callback(api, self.db, {'id': 'callback-id', 'data': 'st:14', 'message': {'chat': {'id': -1, 'username': 'propan_uzbekistan_2026'}, 'message_id': 50, 'text': 'old'}})
        methods = [call.args[0] for call in api.call.call_args_list]
        self.assertEqual(methods, ['answerCallbackQuery', 'editMessageText'])
        self.assertEqual(api.call.call_args.args[1]['message_id'], 50)

    def test_ibr_and_yangi_have_separate_prices_and_locations(self):
        directory.observe(self.db, self.msg(1, 'Янги Узбекистан 8300сум'))
        directory.observe(self.db, self.msg(2, 'IBR 8200сум'))
        yangi = directory.detail(self.db, '6')
        ibr = directory.detail(self.db, '19')
        self.assertIn('8 300', yangi['text'])
        self.assertNotIn('8 200', yangi['text'])
        self.assertIn('8 200', ibr['text'])
        self.assertNotIn('8 300', ibr['text'])
        self.assertIn('https://clck.ru/3PdfBw', str(yangi['reply_markup']))
        self.assertIn('https://clck.ru/3RUB3W', str(ibr['reply_markup']))
        self.assertEqual(directory.find('ИБРда пропан қанча?'), ['19'])

    def test_exact_screenshot_fact_then_question_returns_8200(self):
        api = Mock()
        propanbot.handle_message(api, self.db, self.msg(1, '8 заправкада нарх 8200'))
        api.call.assert_not_called()
        propanbot.handle_message(api, self.db, self.msg(2, '8 заправкада нарх қанча?'))
        payload = api.call.call_args.args[1]
        self.assertIn('8 200', payload['text'])
        self.assertIn('Сассу кўприкка етмасдан', payload['text'])
        self.assertIn('inline_keyboard', payload['reply_markup'])
        self.assertIn('st:bridge8', str(payload['reply_markup']))
        self.assertNotIn('https://clck.ru/3Pdfu3', str(payload))  # Not numbered-list Kumaryk.

    def test_explicit_price_label_and_spaced_thousands(self):
        for text in ['8 заправкада нарх 8200', '8 заправкада нархи 8200', '8 zapravkada narx: 8 200']:
            parsed = __import__('conversation').proposal(text)
            self.assertEqual(parsed['price'], 8200)
            self.assertFalse(parsed['question'])
        self.assertIsNone(__import__('conversation').proposal('8 заправкада нарх қанча?'))

    def test_retained_history_is_reprocessed_without_resending(self):
        import history_import
        history_import.remember(self.db, self.msg(1, '8 заправкада нарх 8200'))
        history_import.replay(self.db)
        self.assertIn('8 200', directory.detail(self.db, 'bridge8')['text'])

    def test_price_and_open_status_have_different_source_buttons(self):
        directory.observe(self.db, self.msg(1, 'Назарбек 8200сум'))
        directory.observe(self.db, self.msg(2, 'Назарбек ёпиқ'))
        buttons = directory.detail(self.db, '4')['reply_markup']['inline_keyboard'][0]
        self.assertEqual([b['text'] for b in buttons], ['💰 Нарх манбаси', '🟢 Ҳолат манбаси', '📍 Мўлжал'])
        self.assertEqual(buttons[0]['url'], 'https://t.me/propan_uzbekistan_2026/1')
        self.assertEqual(buttons[1]['url'], 'https://t.me/propan_uzbekistan_2026/2')

    def test_missing_source_button_does_not_invent_a_link(self):
        api = Mock()
        button = directory.detail(self.db, '14')['reply_markup']['inline_keyboard'][0][1]
        self.assertNotIn('url', button)
        directory.callback(api, self.db, {'id': 'cb', 'data': button['callback_data'], 'message': {'chat': {'id': -1, 'username': 'propan_uzbekistan_2026'}, 'message_id': 42, 'text': 'Майорский'}})
        self.assertEqual(api.call.call_args.args[0], 'answerCallbackQuery')
        self.assertIn('манба ҳали сақланмаган', api.call.call_args.args[1]['text'])

    def test_pagination_at_most_three_rows(self):
        first = directory.page()
        self.assertLessEqual(len(first['reply_markup']['inline_keyboard']), 3)
        self.assertIn('pg:1', str(first['reply_markup']))
        second = directory.page(number=1)
        self.assertIn('pg:0', str(second['reply_markup']))
