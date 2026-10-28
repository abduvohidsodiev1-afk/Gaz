"""Guard and harness tests; not local-model accuracy measurements."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ai_cases import DATA
import ai_benchmark
import hybrid_core
import hybrid_benchmark


class HybridTests(unittest.TestCase):
    def test_known_59_guard_regression_cases(self):
        for case in DATA['cases']:
            actual=hybrid_core.apply(case['messages'])
            self.assertEqual(actual,case['expected'],case['id'])

    def test_model_cannot_invent_price_or_status(self):
        actual=hybrid_core.apply([{'id':1,'text':'майорский 8200'}],{'intent':'price_report','price_uzs':12500,'status':'closed'})
        self.assertEqual(actual['price_uzs'],8200)
        self.assertIsNone(actual['status'])
        greeting=hybrid_core.apply([{'id':1,'text':'Ассалому алайкум'}],{'intent':'status_report','status':'closed'})
        self.assertIsNone(greeting['status'])

    def test_checking_question_is_not_a_price_even_if_model_says_so(self):
        actual=hybrid_core.apply([{'id':1,'text':'Майорский 8200данми'}],{'intent':'price_report','price_uzs':8200})
        self.assertEqual(actual['intent'],'price_question')
        self.assertIsNone(actual['price_uzs'])

    def test_explicit_closed_fact_is_preserved(self):
        actual=hybrid_core.apply([{'id':1,'text':'Майорский ёпиқ'}],{'intent':'status_report','status':None})
        self.assertEqual(actual['intent'],'status_report')
        self.assertEqual(actual['status'],'closed')

    def test_ai_can_help_an_unlisted_question_form_without_writing_facts(self):
        actual=hybrid_core.apply([{'id':1,'text':'Mayorskiyda holatga oydinlik kiriting'}],{'intent':'status_question'})
        self.assertEqual(actual['station_id'],'14')
        self.assertEqual(actual['intent'],'status_question')
        self.assertIsNone(actual['price_uzs'])
        self.assertIsNone(actual['status'])

    def test_model_unavailable_does_not_fake_an_ai_approved_write(self):
        actual=hybrid_core.apply([{'id':1,'text':'майорский 8200'}],{})
        self.assertTrue(actual['needs_review'])
        self.assertIsNone(actual['price_uzs'])

    def test_explicit_tagged_price_is_not_overridden_by_bad_ai_question_guess(self):
        messages=[{'id':1,'author_id':10,'text':'майорский канча'}, {'id':2,'author_id':20,'mentions':[10],'text':'@asker 8200'}]
        result=hybrid_core.apply(messages,{'intent':'price_question','price_uzs':None,'status':None})
        self.assertEqual(result['intent'],'price_report')
        self.assertEqual(result['station_id'],'14')
        self.assertEqual(result['price_uzs'],8200)
        self.assertEqual(result['reply_to'],1)

    def test_ambiguous_tag_is_not_promoted_to_trusted_answer(self):
        messages=[{'id':1,'author_id':10,'text':'майорский канча'}, {'id':2,'author_id':10,'text':'Чоштепа канча'}, {'id':3,'mentions':[10],'text':'@asker 8200'}]
        result=hybrid_core.apply(messages,{'intent':'price_report','price_uzs':8200})
        self.assertTrue(result['needs_review'])
        self.assertIsNone(result['price_uzs'])
        self.assertIsNone(result['station_id'])

    def test_reply_that_is_itself_a_question_does_not_update_price(self):
        messages=[{'id':1,'text':'майорский канча'}, {'id':2,'reply_to':1,'text':'8200данми'}]
        result=hybrid_core.apply(messages,{'intent':'price_report','price_uzs':8200})
        self.assertEqual(result['intent'],'price_question')
        self.assertIsNone(result['price_uzs'])

    def test_expected_answers_are_not_sent(self):
        for task in ('intent','price','status'):
            payload=hybrid_benchmark.payload(DATA['cases'][0],task)
            user=json.loads(payload['messages'][1]['content'])
            self.assertEqual(set(user),{'messages'})
            self.assertNotIn('expected',payload['messages'][1]['content'])

    def test_unavailable_model_preserves_previous_results(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(hybrid_benchmark,'request',side_effect=OSError), contextlib.redirect_stdout(io.StringIO()):
            dest=Path(folder)/'ai-test-results'
            dest.mkdir()
            (dest/'AI_DIAG_RESULTS.json').write_text('original')
            self.assertEqual(hybrid_benchmark.run(folder),1)
            report=json.loads((dest/'AI_HYBRID_RESULTS.json').read_text())
            self.assertFalse(report['model_executed'])
            self.assertEqual(report['status'],'unavailable')
            self.assertEqual((dest/'AI_DIAG_RESULTS.json').read_text(),'original')
