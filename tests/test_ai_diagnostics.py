"""Diagnostic harness checks; these do not measure model accuracy."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ai_diagnostics as diag


class DiagnosticTests(unittest.TestCase):
    def test_twelve_cases_and_thirty_two_comparisons(self):
        self.assertEqual(len(diag.CASES),12)
        self.assertEqual(len(diag.jobs()),32)
        self.assertEqual(len({(case[0],mode) for case,mode in diag.jobs()}),32)

    def test_only_one_task_and_no_expected_answer_sent_to_model(self):
        for case,mode in diag.jobs():
            payload=diag.payload(case,mode)
            self.assertEqual(payload['messages'][1]['content'],case[2])
            self.assertEqual(payload['options']['temperature'],0)
            if isinstance(payload['format'],dict):
                self.assertEqual(list(payload['format']['properties']),[diag.FIELDS[case[1]]])

    def test_nullable_and_unknown_formats_stay_distinct(self):
        case=next(case for case in diag.CASES if case[0]=='status-greeting')
        legacy=diag.payload(case,'enum_nullable')['format']['properties']['status']
        explicit=diag.payload(case,'typed_nullable')['format']['properties']['status']
        sentinel=diag.payload(case,'explicit_unknown')['format']['properties']['status']
        self.assertNotIn('type',legacy)
        self.assertEqual(explicit['type'],['string','null'])
        self.assertEqual(sentinel['enum'],['unknown','open','closed'])
        self.assertIsNone(diag.normalize('status','explicit_unknown',{'status':'unknown'}))
        with self.assertRaises(ValueError):
            diag.normalize('status','typed_nullable',{'status':'unknown'})

    def test_bad_values_are_not_silently_corrected(self):
        for value in [True,0,1000000,'8200']:
            with self.assertRaises(ValueError):
                diag.normalize('price','json',{'price_uzs':value})
        with self.assertRaises(ValueError):
            diag.normalize('intent','typed_schema',{'intent':'unknown-made-up'})

    def test_summary_does_not_overwrite_previous_benchmark(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'AI_TEST_RESULTS.json').write_text('original')
            report={'status':'completed','results':[{'task':'status','mode':'typed_nullable','passed':False},{'task':'status','mode':'json','passed':True}]}
            diag.save(path,report)
            self.assertEqual((path/'AI_TEST_RESULTS.json').read_text(),'original')
            saved=json.loads((path/'AI_DIAG_RESULTS.json').read_text())
            self.assertEqual(saved['by_task_format']['status/json'],{'passed':1,'total':1})
            self.assertEqual(saved['by_task_format']['status/typed_nullable'],{'passed':0,'total':1})

    def test_unavailable_local_model_is_reported_honestly(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(diag,'request',side_effect=OSError), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(diag.run(folder),1)
            saved=json.loads((Path(folder)/'ai-test-results/AI_DIAG_RESULTS.json').read_text())
            self.assertFalse(saved['model_executed'])
            self.assertEqual(saved['status'],'unavailable')
            self.assertEqual(saved['results'],[])
