"""Benchmark plumbing tests, not evidence of local-model accuracy."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ai_benchmark as bench
from ai_cases import DATA


class BenchmarkTests(unittest.TestCase):
    def test_all_59_expected_cases_are_valid(self):
        self.assertEqual(len(DATA['cases']), 59)
        self.assertEqual(len({case['id'] for case in DATA['cases']}), 59)
        for case in DATA['cases']:
            bench.validate(case['expected'])

    def test_expected_answers_are_not_given_to_model(self):
        case=DATA['cases'][0]
        payload=bench.model_payload(case)
        user=json.loads(payload['messages'][1]['content'])
        self.assertEqual(set(user), {'stations','messages'})
        self.assertNotIn('expected', user)
        self.assertFalse(payload['stream'])
        self.assertEqual(payload['options']['temperature'], 0)

    def test_invented_station_and_invalid_price_are_rejected(self):
        sample=copy.deepcopy(DATA['cases'][0]['expected'])
        sample['station_id']='made-up'
        with self.assertRaises(ValueError): bench.validate(sample)
        sample['station_id']='14'
        sample['price_uzs']=True
        with self.assertRaises(ValueError): bench.validate(sample)
        sample['price_uzs']=999999
        with self.assertRaises(ValueError): bench.validate(sample)

    def test_wrong_station_or_invented_price_is_flagged_unsafe(self):
        expected=copy.deepcopy(DATA['cases'][0]['expected'])
        actual=copy.deepcopy(expected)
        actual['price_uzs']=8200
        self.assertTrue(bench.judge(actual,expected)['unsafe'])
        expected.update(intent='price_report',price_uzs=8200,station_id='14')
        actual=copy.deepcopy(expected)
        actual['station_id']='19'
        self.assertTrue(bench.judge(actual,expected)['unsafe'])

    def test_unavailable_model_is_not_reported_as_tested(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(bench,'request',side_effect=OSError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bench.run(folder),1)
            result=json.loads((Path(folder)/'ai-test-results/AI_TEST_RESULTS.json').read_text())
            self.assertFalse(result['model_executed'])
            self.assertEqual(result['status'],'unavailable')
            self.assertEqual(result['cases'],[])

    def test_simulated_transport_is_scored_and_saved(self):
        # Predetermined fixture validates scoring only. No real model is run by this test.
        subset={'stations':DATA['stations'],'cases':[DATA['cases'][0]]}
        expected=subset['cases'][0]['expected']
        responses=[{'version':'fixture'}, {'details':{'quantization_level':'fixture'}},
                   {'message':{'content':json.dumps(expected)},'eval_count':50}, {'models':[]}]
        with tempfile.TemporaryDirectory() as folder, patch.object(bench,'DATA',subset), patch.object(bench,'request',side_effect=responses), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bench.run(folder),0)
            result=json.loads((Path(folder)/'ai-test-results/AI_TEST_RESULTS.json').read_text())
            self.assertEqual(result['status'],'completed')
            self.assertEqual(len(result['cases']),1)
            self.assertTrue(result['cases'][0]['passed'])
