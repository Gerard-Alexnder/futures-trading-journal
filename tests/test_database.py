import sqlite3
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path

from database import connect, initialize, verify, transaction, DatabaseError


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'test.sqlite3'
        initialize(self.path)
        self.connection = connect(self.path)
        self.addCleanup(self.connection.close)

    def test_initialize_version_strict_foreign_keys(self):
        initialize(self.path)
        verify(self.connection)
        self.assertEqual(self.connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(self.connection.execute('PRAGMA user_version').fetchone()[0], 1)
        if sqlite3.sqlite_version_info >= (3, 37, 0):
            rows = self.connection.execute('PRAGMA table_list').fetchall()
            self.assertTrue(all(row['strict'] for row in rows if row['name'] in ('accounts', 'trades', 'executions')))
        self.connection.execute('PRAGMA user_version=2')
        with self.assertRaises(DatabaseError):
            initialize(self.path)

    def test_restrict_checks_and_rollback(self):
        c = self.connection
        c.execute("INSERT INTO accounts VALUES(1,'A','personal',NULL,'2026-01-01T00:00:00.000000Z',1)")
        c.execute("INSERT INTO trades VALUES(1,1,'MNQ','long',NULL,NULL,'2026-01-01T00:00:00.000000Z')")
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute('DELETE FROM accounts WHERE id=1')
        for statement in ["UPDATE accounts SET account_type='other'", "UPDATE trades SET account_id=99", "UPDATE trades SET symbol='ABC'"]:
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute(statement)
        with self.assertRaises(RuntimeError):
            with transaction(c):
                c.execute("UPDATE accounts SET name='changed'")
                raise RuntimeError('forced')
        self.assertEqual(c.execute('SELECT name FROM accounts').fetchone()[0], 'A')
        initialize(self.path)
        self.assertEqual(c.execute('SELECT count(*) FROM trades').fetchone()[0], 1)

    def test_refuse_unversioned_existing_database(self):
        path = Path(self.directory.name) / 'unknown.sqlite3'
        connection = sqlite3.connect(path)
        try:
            connection.execute('CREATE TABLE personal_data(id INTEGER)')
        finally:
            connection.close()
        with self.assertRaises(DatabaseError):
            initialize(path)

    def test_cli_init_verify_and_missing_path(self):
        path = Path(self.directory.name) / 'nested' / 'cli.sqlite3'
        for command in ('init', 'init', 'verify'):
            result = subprocess.run([sys.executable, '-m', 'database', command, '--path', str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        missing = Path(self.directory.name) / 'missing.sqlite3'
        result = subprocess.run([sys.executable, '-m', 'database', 'verify', '--path', str(missing)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(missing.exists())
