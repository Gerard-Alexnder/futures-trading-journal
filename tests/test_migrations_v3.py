import sqlite3
import unittest
from unittest.mock import patch
import database
import test_migrations


class MigrationV3Tests(unittest.TestCase):
    def setUp(self):
        fixture=test_migrations.MigrationTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.path=fixture.path
        c=database.connect(self.path)
        try:
            database._upgrade_v1(c);c.execute('PRAGMA user_version=2')
            c.execute("INSERT INTO write_requests VALUES('old-request-00001','old','"+'a'*64+"','{}','2026-01-01T00:00:00.000000Z')")
            self.before={table:[tuple(r) for r in c.execute('SELECT * FROM '+table)] for table in ('accounts','trades','executions','write_requests')}
        finally:c.close()

    def test_backup_exclusion_and_integrity_in_delete_and_wal(self):
        for mode in ('DELETE','WAL'):
            with self.subTest(mode=mode):
                # Independent copy per journal mode, preserving the source fixture.
                source=sqlite3.connect(self.path);path=self.path.with_name(mode+'.sqlite3');target=sqlite3.connect(path)
                try:source.backup(target)
                finally:source.close();target.close()
                c=database.connect(path);c.execute('PRAGMA journal_mode='+mode);c.close()
                original=database._backup_verified
                def inspect(path,backup,version):
                    writer=sqlite3.connect(path,timeout=.05)
                    try:
                        with self.assertRaises(sqlite3.OperationalError):writer.execute("UPDATE accounts SET name='unexpected'")
                    finally:writer.close()
                    original(path,backup,version)
                with patch('database._backup_verified',side_effect=inspect):backup=database.migrate(path)
                for p,version in ((path,3),(backup,2)):
                    c=database.connect(p)
                    try:
                        database.verify(c,expected_version=version)
                        for table,rows in self.before.items():
                            actual=[tuple(r) for r in c.execute('SELECT * FROM '+table)]
                            self.assertEqual(actual,[r+(0,) for r in rows] if table=='executions' and version==3 else rows)
                        if version==3:self.assertEqual(c.execute('SELECT count(*) FROM execution_audit').fetchone()[0],0)
                    finally:c.close()
                self.assertIsNone(database.migrate(path))

    def test_failure_after_ddl_rolls_back_and_keeps_backup(self):
        original=database._upgrade_v2
        def fail(c):original(c);raise RuntimeError('after DDL')
        with patch('database._upgrade_v2',side_effect=fail),self.assertRaises(RuntimeError):database.migrate(self.path)
        c=database.connect(self.path)
        try:
            database.verify(c,expected_version=2)
            self.assertEqual([tuple(r) for r in c.execute('SELECT * FROM executions')],self.before['executions'])
            self.assertNotIn('is_voided',[r[1] for r in c.execute('PRAGMA table_info(executions)')])
        finally:c.close()
        self.assertEqual(len(list(self.path.parent.glob('*.bak'))),1)

    def test_backup_failure_and_invalid_backup_prevent_migration(self):
        with patch('database._backup_verified',side_effect=OSError('disk full')),self.assertRaises(OSError):database.migrate(self.path)
        c=database.connect(self.path)
        try:database.verify(c,expected_version=2)
        finally:c.close()
        original=database.verify
        calls=0
        def fail_backup(c,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:raise database.DatabaseError('invalid backup')
            return original(c,**kwargs)
        with patch('database.verify',side_effect=fail_backup),self.assertRaises(database.DatabaseError):database.migrate(self.path)
        c=database.connect(self.path)
        try:database.verify(c,expected_version=2)
        finally:c.close()

    def test_new_v3_verifies_audit_guards(self):
        database.migrate(self.path)
        c=database.connect(self.path)
        try:
            database.verify(c)
            c.execute('DROP TRIGGER execution_audit_no_delete')
            with self.assertRaises(database.DatabaseError):database.verify(c)
        finally:c.close()
