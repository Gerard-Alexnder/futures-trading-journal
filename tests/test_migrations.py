import sqlite3
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from database import initialize, connect, migrate, verify, DatabaseError, _upgrade_v1


class MigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'old.sqlite3'
        c = sqlite3.connect(self.path)
        try:
            c.executescript((Path(__file__).parent/'fixtures/schema_v1.sql').read_text())
            c.execute("INSERT INTO accounts VALUES(7,'A','personal',NULL,'2026-01-01T00:00:00.000000Z',1)")
            c.execute("INSERT INTO trades VALUES(11,7,'MNQ','long',NULL,NULL,'2026-01-01T00:00:00.000000Z')")
            c.execute("INSERT INTO executions VALUES(13,11,7,'2026-01-01T00:00:00.000000Z',1,'entry',3,80001,1234567,1,'manual',NULL,NULL,'2026-01-01T00:00:00.000000Z')")
            c.commit()
            self.before = tuple(c.execute('SELECT * FROM executions').fetchone())
        finally:
            c.close()

    def test_migrate_preserves_data_backup_and_repeat(self):
        backup = migrate(self.path)
        self.assertTrue(backup.is_file())
        for path, version in [(backup,1), (self.path,2)]:
            c = connect(path)
            try:
                verify(c, expected_version=version)
                self.assertEqual(tuple(c.execute('SELECT * FROM executions').fetchone()), self.before)
                self.assertEqual(c.execute('SELECT id FROM accounts').fetchone()[0], 7)
                self.assertEqual(c.execute('SELECT id FROM trades').fetchone()[0], 11)
                if version == 2:
                    self.assertEqual(c.execute('SELECT revision FROM trades').fetchone()[0], 0)
                    with self.assertRaises(sqlite3.IntegrityError):
                        c.execute('UPDATE trades SET revision=-1')
            finally:
                c.close()
        self.assertIsNone(migrate(self.path))
        self.assertEqual(len(list(self.path.parent.glob('*.bak'))), 1)

    def test_rollback_after_schema_change(self):
        def fail(c):
            _upgrade_v1(c)
            raise RuntimeError('injected')
        with patch('database._upgrade_v1', side_effect=fail), self.assertRaises(RuntimeError):
            migrate(self.path)
        c = connect(self.path)
        try:
            verify(c, expected_version=1)
            self.assertNotIn('revision', [r[1] for r in c.execute('PRAGMA table_info(trades)')])
            self.assertEqual(tuple(c.execute('SELECT * FROM executions').fetchone()), self.before)
        finally:
            c.close()
        self.assertEqual(len(list(self.path.parent.glob('*.bak'))), 1)

    def test_absent_invalid_future_and_explicit_only(self):
        with self.assertRaises(DatabaseError):
            initialize(self.path)
        missing = self.path.parent/'missing.sqlite3'
        with self.assertRaises(DatabaseError):
            migrate(missing)
        self.assertFalse(missing.exists())
        for version in (0,99):
            c = connect(self.path)
            try:
                c.execute(f'PRAGMA user_version={version}')
            finally: c.close()
            with self.assertRaises(DatabaseError):
                migrate(self.path)
        self.path.write_bytes(b'not a database')
        with self.assertRaises(sqlite3.DatabaseError):
            migrate(self.path)

    def test_fresh_v2(self):
        fresh = self.path.parent/'new.sqlite3'
        initialize(fresh)
        c=connect(fresh)
        try: verify(c)
        finally: c.close()
        self.assertIsNone(migrate(fresh))

    def test_cli_and_source_validation(self):
        result = subprocess.run([sys.executable, '-m', 'database', 'migrate', '--path', str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Respaldo:', result.stdout)
        self.assertIn('versión 2', result.stdout)
        c = connect(self.path)
        try:
            c.execute('DROP INDEX executions_external')
        finally:
            c.close()
        with self.assertRaises(DatabaseError):
            migrate(self.path)

    def test_foreign_key_integrity_is_checked_before_backup(self):
        c = sqlite3.connect(self.path)
        try:
            c.execute('UPDATE executions SET account_id=999')
            c.commit()
        finally:
            c.close()
        with self.assertRaises(DatabaseError):
            migrate(self.path)
        self.assertEqual(list(self.path.parent.glob('*.bak')), [])
