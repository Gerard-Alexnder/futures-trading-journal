import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from database import connect, initialize
from trade_service import (TradeService, DraftValidationError, ConflictError,
                           StaleRevisionError, TradeClosedError, ArchivedAccountError)
from test_trade_service import fill


def row(kind='entry', quantity='1', price='20000', minute=0, **changes):
    return dict(row_id='draft', execution_type=kind, quantity=quantity, price=price,
                executed_at=f'2026-11-10T10:{minute:02}:00-04:00', commission='0', fees='0', **changes)


class ExecutionBatchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'batches.sqlite3'; initialize(self.path)
        self.service = TradeService(self.path)
        self.account = self.service.create_account('Personal', 'personal')
        self.trade = self.service.create_trade(self.account, 'MNQ', 'long')

    def append(self, rows, revision=0, key='batch-request-000001'):
        return self.service.append_execution_batch(self.trade, rows, expected_revision=revision, request_id=key)

    def snapshot(self):
        return self.service.get_trade(self.trade)

    def test_financial_acceptance_and_persistence(self):
        cases = [
            (row(quantity='2'), '2.50', 2, '20000', '0', '-2.50'),
            (row(price='20030', minute=1), '1.25', 3, '20010', '0', '-3.75'),
            (row('exit', price='20050', minute=2), '1.25', 2, '20010', '80', '75'),
            (row('exit', '2', '20080', 3), '2.50', 0, None, '360', '352.50'),
        ]
        for revision, (execution, commission, opened, average, gross, net) in enumerate(cases):
            execution['commission'] = commission
            preview = self.service.preview_execution_batch(self.trade, [execution], expected_revision=revision)
            receipt = self.append([execution], revision, f'financial-request-{revision}')
            actual = TradeService(self.path).get_trade(self.trade)
            summary = actual['summary']
            self.assertEqual(preview['projected'], summary)
            self.assertEqual(receipt['revision'], revision + 1)
            self.assertEqual(summary['open_quantity'], opened)
            self.assertEqual(summary['average_price'], Decimal(average) if average else None)
            self.assertEqual(summary['gross_pnl'], Decimal(gross))
            self.assertEqual(summary['net_pnl'], Decimal(net))
        self.assertEqual(summary['status'], 'closed')
        self.assertEqual(summary['commission'] + summary['fees'], Decimal('7.50'))

    def test_preview_snapshot_is_read_only(self):
        before = self.path.read_bytes()
        original = self.service._trade
        def inspect(connection, trade_id):
            self.assertTrue(connection.in_transaction)
            self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('UPDATE trades SET revision=1')
            return original(connection, trade_id)
        with patch.object(self.service, '_trade', side_effect=inspect):
            result = self.service.preview_execution_batch(self.trade, [row()], expected_revision=0)
        self.assertEqual(result['current']['status'], 'pending')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.snapshot()['revision'], 0)

    def test_real_snapshot_detail_and_preview_during_writer_commit(self):
        connection = connect(self.path)
        connection.execute('PRAGMA journal_mode=WAL'); connection.close()
        for preview in (False, True):
            before = self.snapshot()
            original = self.service._trade
            def interleave(connection, trade_id):
                result = original(connection, trade_id)  # establish the read snapshot
                writer = TradeService(self.path)
                writer.add_execution(self.trade, **fill())
                writer.set_account_active(self.account, False)
                return result
            with patch.object(self.service, '_trade', side_effect=interleave):
                if preview:
                    result = self.service.preview_execution_batch(self.trade, [row()], expected_revision=before['revision'])
                    self.assertEqual(result['current'], before['summary'])
                    self.assertEqual(result['revision'], before['revision'])
                else:
                    result = self.snapshot()
                    self.assertEqual(result, before)
            self.assertEqual(self.snapshot()['revision'], before['revision'] + 1)
            self.assertFalse(self.snapshot()['account']['is_active'])
            self.service.set_account_active(self.account, True)

    def test_retry_after_close_and_archive_and_changed_content(self):
        rows = [row(), {**row('exit', price='20010', minute=1), 'row_id':'close'}]
        receipt = self.append(rows)
        after = self.snapshot()
        with patch.object(self.service, '_preview_batch', side_effect=AssertionError('replay on retry')):
            self.assertEqual(self.append(rows), receipt)
        self.assertEqual(self.snapshot(), after)
        equivalent = [{**r, 'price':r['price']+'.00', 'row_id':'visual'+str(i)} for i,r in enumerate(rows)]
        self.assertEqual(self.append(equivalent), receipt)
        with self.assertRaises(ConflictError): self.append(list(reversed(rows)))
        with self.assertRaises(StaleRevisionError): self.append([row()], key='new-request-stale00')
        with self.assertRaises(TradeClosedError): self.append([row()], 1, 'new-request-closed0')
        self.service.set_account_active(self.account, False)
        with self.assertRaises(ArchivedAccountError): self.append(rows)
        self.service.set_account_active(self.account, True)
        self.service.update_trade_metadata(self.trade, notes='later metadata')
        self.assertEqual(self.append(rows), receipt)
        self.assertEqual(self.snapshot()['revision'], 2)

    def test_concurrent_closes_and_identical_retries(self):
        self.append([row()])
        def close(index):
            try:
                return TradeService(self.path).append_execution_batch(self.trade, [row('exit',minute=1)], expected_revision=1, request_id=f'parallel-close-{index:04}')
            except StaleRevisionError: return 'stale'
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(close, range(2)))
        self.assertEqual(results.count('stale'), 1)
        self.assertEqual(self.snapshot()['revision'], 2)
        self.assertEqual(len(self.snapshot()['executions']), 2)
        self.trade = self.service.create_trade(self.account, 'MNQ', 'short')
        # Use a fresh key because idempotency is global, including trade_id.
        def same(_):
            return TradeService(self.path).append_execution_batch(self.trade, [row()], expected_revision=0, request_id='parallel-same-00001')
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(same, range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.snapshot()['revision'], 1)

    def test_rollback_insert_revision_and_receipt(self):
        for trigger in (
            "CREATE TRIGGER fail BEFORE INSERT ON executions WHEN NEW.sequence=2 BEGIN SELECT RAISE(ABORT,'test'); END",
            "CREATE TRIGGER fail BEFORE UPDATE OF revision ON trades BEGIN SELECT RAISE(ABORT,'test'); END",
            "CREATE TRIGGER fail BEFORE INSERT ON write_requests BEGIN SELECT RAISE(ABORT,'test'); END",
        ):
            connection = connect(self.path)
            try:
                connection.execute(trigger)
                with self.assertRaises(ConflictError):
                    self.append([row(), {**row(minute=1), 'row_id':'second'}])
                self.assertEqual(self.snapshot()['revision'], 0)
                self.assertEqual(self.snapshot()['executions'], [])
                self.assertEqual(connection.execute('SELECT count(*) FROM write_requests').fetchone()[0], 0)
                connection.execute('DROP TRIGGER fail')
            finally: connection.close()

    def test_old_writers_and_initial_creation_revisions(self):
        self.service.add_execution(self.trade, **fill())
        self.assertEqual(self.snapshot()['revision'], 1)
        self.service.add_executions(self.trade, [fill(), fill()])
        self.assertEqual(self.snapshot()['revision'], 2)
        self.service.update_trade_metadata(self.trade, notes='updated')
        self.assertEqual(self.snapshot()['revision'], 3)
        other = self.service.record_reversal(self.trade, fill('exit', 3), fill())
        self.assertEqual(self.snapshot()['revision'], 4)
        self.assertEqual(self.service.get_trade(other)['revision'], 0)
        created = self.service.create_trade_with_executions(self.account,'MNQ','long',[row()],request_id='initial-create-00001')
        self.assertEqual(self.service.get_trade(created['trade_id'])['revision'], 0)

    def test_retroactive_replay_and_ties_preserve_existing_rows(self):
        self.append([row(quantity='2'), {**row('exit', price='20050',minute=2), 'row_id':'partial'}])
        before = self.snapshot()['executions']
        retro = row(price='20030',minute=1)
        preview = self.service.preview_execution_batch(self.trade, [retro], expected_revision=1)
        self.assertTrue(preview['retroactive']); self.assertIn('P&L', preview['warning'])
        self.assertEqual(preview['current']['gross_pnl'], Decimal('100'))
        self.assertEqual(preview['projected']['gross_pnl'], Decimal('80'))
        self.assertEqual([r['sequence'] for r in preview['executions']], [1,3,2])
        self.append([retro], 1, 'retroactive-valid01')
        actual = self.snapshot()['executions']
        self.assertEqual([r for r in actual if r['id'] in [e['id'] for e in before]], before)
        self.append([row(minute=2)], 2, 'timestamp-tie-00001')
        self.assertEqual([r['sequence'] for r in self.snapshot()['executions']], [1,3,2,4])

    def test_invalid_retroactive_and_pending_histories(self):
        with self.assertRaises(DraftValidationError) as error:
            self.append([row('exit')])
        self.assertIn('draft', error.exception.errors['rows'])
        self.append([row(quantity='2'), {**row('exit',minute=2), 'row_id':'old-exit'}])
        before = self.snapshot()
        with self.assertRaises(DraftValidationError) as error:
            self.append([row('exit','2',minute=1)], 1, 'retroactive-bad-001')
        self.assertIn('executions', error.exception.errors['fields'])
        self.assertIn('draft', error.exception.errors['rows'])
        self.assertEqual(self.snapshot(), before)

    def test_short_cost_precision_and_validation(self):
        self.trade = self.service.create_trade(self.account, 'MES', 'short')
        first = row(price='6000'); first.update(commission='1.123456',fees='0.000001')
        self.append([first, {**row('exit',price='5990',minute=1), 'row_id':'exit'}])
        self.assertEqual(self.snapshot()['summary']['net_pnl'], Decimal('48.876543'))
        self.trade = self.service.create_trade(self.account, 'MNQ', 'long')
        for field, value in [('price','20000.1'),('quantity','0'),('commission','0.0000001'),
                             ('fees','-1'),('executed_at','2026-11-10T10:00:00'),('sequence',7)]:
            with self.subTest(field=field), self.assertRaises(DraftValidationError):
                self.append([{**row(),field:value}], key='invalid-fields-0001')
        for revision in (True, -1, '0'):
            with self.assertRaises(DraftValidationError): self.append([row()], revision)
