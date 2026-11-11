import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from database import initialize, connect, transaction
from idempotency import execute_once, ConflictError
from trade_service import TradeService


class IdempotencyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name)/'test.sqlite3'
        initialize(self.path)
        self.service = TradeService(self.path)

    def test_concurrent_requests_and_normalization(self):
        def create(_):
            return TradeService(self.path).create_account(' A ', 'personal', request_id='same-request-123456')
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(create, range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(len(self.service.list_accounts()), 1)
        self.assertEqual(self.service.create_account('A','personal', request_id='same-request-123456'), ids[0])
        with self.assertRaises(ConflictError):
            self.service.create_account('B','personal', request_id='same-request-123456')

    def test_atomic_rollback(self):
        c=connect(self.path)
        try:
            def fail():
                c.execute("INSERT INTO accounts(name,account_type,created_at) VALUES('A','personal','2026-01-01T00:00:00Z')")
                raise RuntimeError('injected')
            with self.assertRaises(RuntimeError):
                with transaction(c):
                    execute_once(c, 'failed-request-12345', 'create', {}, fail)
            self.assertEqual(c.execute('SELECT count(*) FROM accounts').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT count(*) FROM write_requests').fetchone()[0], 0)
            with transaction(c):
                result=execute_once(c, 'failed-request-12345', 'retry', {}, lambda: {'id':7})
            self.assertEqual(result, {'id':7})
        finally: c.close()

    def test_registration_failure_rolls_back_business_write(self):
        c = connect(self.path)
        try:
            c.execute("CREATE TRIGGER fail_request BEFORE INSERT ON write_requests BEGIN SELECT RAISE(ABORT, 'forced'); END")
            from trade_service import ConflictError
            with self.assertRaises(ConflictError):
                self.service.create_account('A', 'personal', request_id='rollback-key-123456')
            self.assertEqual(c.execute('SELECT count(*) FROM accounts').fetchone()[0], 0)
            self.assertEqual(c.execute('SELECT count(*) FROM write_requests').fetchone()[0], 0)
        finally:
            c.close()
