"""Group routing: silence for discussion; real stored workshop contacts for requests."""
import json
import unittest
from unittest.mock import Mock, patch
import propanbot
import group_wait
import local_ai
import catalog


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = propanbot.connect_db(':memory:')
        self.addCleanup(self.db.close)
        self.api = Mock()
        for ident, region in [('t', 'Toshkent'), ('s', 'Sirdaryo')]:
            item = dict(id=ident, name='Test workshop '+ident, region=region,
                        address='Test address', phone='+99890000000'+('1' if ident=='t' else '2'), specialty='Propan installation')
            self.db.execute('INSERT INTO catalog VALUES (?,?,?)', ('masters', ident, json.dumps(item)))
        self.db.commit()

    def msg(self, mid, text):
        return dict(chat=dict(id=-1, type='supergroup', username='propan_uzbekistan_2026'),
                    message_id=mid, date=1793266900+mid, text=text, **{'from': {'id': 1}})

    def test_discussion_stays_silent_even_with_station_or_ai_hint(self):
        examples = [
            'Но тез тез испитания ва техник томонлама курсатиб туриш керак хохлесизми укми ..метан пропан шунака булади...',
            'Сирдарё пропан буйича Анча олдин иш бошлаган Тошкентга нисбатан Тошкент барибир киммат Чунки хамма нарса киммат Ман хам сирдарёга куйдирганман пропан Лекин ишлавоти 47 талик Малибуга...',
            'Кимга пропан куйса кандай Булади яхши томонларини Айтинглар илтимос',
            'mayorskiy propan foydasi qanday', 'Майорский пропан зарари борми',
            'Choshtepa propan quysa qanday boladi', 'Майорскийда моторга зарари борми',
        ]
        for mid, text in enumerate(examples, 1):
            m = self.msg(mid, text);m['_ai_question'] = 'price_question'
            self.assertFalse(local_ai.candidate(m))
            propanbot.handle_message(self.api, self.db, m)
        group_wait.tick(self.api, self.db, now=9999999999)
        self.api.call.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM pending_questions').fetchone()[0], 0)

    def test_installation_who_to_visit_and_which_master_return_contacts(self):
        examples = ['қаерда ўрнатсам бўлади', 'кимга борсам бўлади', 'қайси уста',
                    'qayerda ornatsam boladi', 'kimga borsam boladi', 'qaysi usta',
                    'Майорскийда пропан ўрнатиш учун қайси устага борсам бўлади',
                    'Пропан ўрнатиш қанча', 'Пропан куйдириш учун кимга борсам булади']
        for mid, text in enumerate(examples, 1):
            self.api.reset_mock()
            propanbot.handle_message(self.api, self.db, self.msg(mid, text))
            self.api.call.assert_called_once()
            payload = self.api.call.call_args.args[1]
            self.assertIn('+99890000000', payload['text'])
            self.assertNotIn('reply_markup', payload)
            self.assertEqual(payload['reply_parameters']['message_id'], mid)

    def test_region_limits_workshop_results_and_unknown_region_not_invented(self):
        for mid, region, expected, excluded in [(1, 'Тошкентда', '+998900000001', '+998900000002'), (2, 'Sirdaryoda', '+998900000002', '+998900000001')]:
            propanbot.handle_message(self.api, self.db, self.msg(mid, region+' пропан қаерда ўрнатсам бўлади'))
            text = self.api.call.call_args.args[1]['text']
            self.assertIn(expected, text);self.assertNotIn(excluded, text)
        propanbot.handle_message(self.api, self.db, self.msg(3, 'Бухорода пропан қаерда ўрнатсам бўлади'))
        self.assertNotIn('+99890000000', self.api.call.call_args.args[1]['text'])

    def test_price_and_opening_questions_keep_thirty_second_station_route(self):
        with patch('group_wait.time.time', return_value=1000):
            propanbot.handle_message(self.api, self.db, self.msg(1, 'Майорский нарх қанча'))
            propanbot.handle_message(self.api, self.db, self.msg(2, 'sassu kopri ochiqmi'))
        self.api.call.assert_not_called()
        group_wait.tick(self.api, self.db, now=1030)
        self.assertEqual(self.api.call.call_count, 2)
        self.assertIn('inline_keyboard', self.api.call.call_args.args[1]['reply_markup'])

    def test_private_routes_follow_same_scope(self):
        self.assertEqual(catalog.responses(self.db, {'text': 'Пропан зарари борми'}), [])
        self.assertIn('+99890000000', catalog.responses(self.db, {'text': 'кимга борсам бўлади'})[0])
