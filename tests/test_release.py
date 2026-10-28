"""Distribution privacy and existing SQLite migration contracts."""
import contextlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import propanbot

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('distribution', ROOT/'scripts/build_distribution.py')
distribution=importlib.util.module_from_spec(spec)
spec.loader.exec_module(distribution)


class ReleaseTests(unittest.TestCase):
    def prepare(self,base):
        source=base/'source'
        source.mkdir()
        for name in distribution.FILES:
            (source/name).write_bytes((ROOT/name).read_bytes())
        exe=base/'compiled-fixture.exe'
        exe.write_bytes(b'MZ packaging-test fixture; not a runnable executable')
        return source,exe

    def test_package_does_not_include_env_database_sessions_or_results(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source,exe=self.prepare(base)
            (source/'.env').write_text('PRIVATE-FIXTURE')
            (source/'data').mkdir()
            (source/'data/private.sqlite3').write_text('PRIVATE-FIXTURE')
            (source/'client.session').write_text('PRIVATE-FIXTURE')
            (source/'AI_TEST_RESULTS.json').write_text('PRIVATE-FIXTURE')
            dest=base/'output'
            manifest=distribution.build(source,exe,dest,'test-commit')
            self.assertEqual(set(p.name for p in dest.iterdir()),set(distribution.FILES)|{'PropanBot.exe','RELEASE_INFO.json'})
            self.assertEqual(manifest['keep_from_previous_install'],['.env','data/'])
            self.assertFalse(manifest['ai_in_live_bot'])
            self.assertEqual(manifest['commit'],'test-commit')

    def test_nonempty_destination_and_nonempty_token_template_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source,exe=self.prepare(base)
            dest=base/'output';dest.mkdir();(dest/'.env').write_text('do not overwrite')
            with self.assertRaises(ValueError): distribution.build(source,exe,dest)
            self.assertEqual((dest/'.env').read_text(),'do not overwrite')
            (source/'.env.example').write_text('TELEGRAM_BOT_TOKEN=PRIVATE-FIXTURE')
            with self.assertRaises(ValueError): distribution.build(source,exe,base/'new')

    def test_old_sqlite_state_and_catalog_survive_opening_new_version(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.sqlite3'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE state (key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
            db.execute("INSERT INTO state VALUES ('offset',123456)")
            db.execute('CREATE TABLE catalog (kind TEXT NOT NULL,id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(kind,id))')
            item={'id':'existing','name':'Existing test workshop','region':'Test','address':'Test address','phone':'fixture','specialty':'Test'}
            db.execute('INSERT INTO catalog VALUES (?,?,?)',('masters','existing',json.dumps(item)))
            db.commit();db.close()
            with contextlib.closing(propanbot.connect_db(path)) as upgraded:
                self.assertEqual(propanbot.offset(upgraded),123456)
                self.assertEqual(json.loads(upgraded.execute("SELECT body FROM catalog WHERE id='existing'").fetchone()[0]),item)

