import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

from database import initialize, connect
from trade_service import TradeService, ConflictError, ArchivedAccountError, NotFoundError
from trade_calculations import TradeValidationError


def fill(kind='entry', quantity=1, price='20000', time='2026-01-01T12:00:00Z', **extra):
    return dict(execution_type=kind, quantity=quantity, price=price, executed_at=time, **extra)


class TradeServiceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'journal.sqlite3'
        initialize(self.path)
        self.service = TradeService(self.path)
        self.account = self.service.create_account('A', 'personal')
        self.trade = self.service.create_trade(self.account, 'MNQ', 'long')

    def test_persistence_costs_and_account_isolation(self):
        self.service.add_execution(self.trade, **fill(commission='1.234567', fees='0.000001'))
        result = TradeService(self.path).get_trade(self.trade)
        self.assertEqual(result['summary']['net_pnl'], Decimal('-1.234568'))
        self.assertEqual(result['executions'][0]['price_ticks'], 80000)
        other = self.service.create_account('A', 'funded', 'Platform')
        self.assertEqual(self.service.list_trades(other), [])
        self.assertEqual(len(self.service.list_accounts()), 2)
        self.service.set_account_active(self.account, False)
        self.assertEqual(self.service.get_trade(self.trade)['summary']['open_quantity'], 1)
        for operation in [lambda: self.service.add_execution(self.trade, **fill()),
                          lambda: self.service.create_trade(self.account, 'MES', 'short'),
                          lambda: self.service.update_trade_metadata(self.trade, notes='x')]:
            with self.assertRaises(ArchivedAccountError):
                operation()
        self.service.set_account_active(self.account, True)
        self.service.update_trade_metadata(self.trade, notes='Plan')
        self.assertEqual(self.service.get_trade(self.trade)['notes'], 'Plan')

    def test_order_equal_times_and_historical_insertions(self):
        self.service.add_executions(self.trade, [fill(quantity=2), fill('exit', price='20010')])
        self.service.add_execution(self.trade, **fill(price='19990', time='2026-01-01T11:00:00Z'))
        rows = self.service.get_trade(self.trade)['executions']
        self.assertEqual([row['sequence'] for row in rows], [3, 1, 2])
        self.service.add_execution(self.trade, **fill(time='2026-01-01T08:00:00-04:00'))
        rows = self.service.get_trade(self.trade)['executions']
        self.assertEqual([row['sequence'] for row in rows], [3, 1, 2, 4])
        self.assertTrue(all(row['executed_at'].endswith('.000000Z') for row in rows))
        with self.assertRaises(TradeValidationError):
            self.service.add_execution(self.trade, **fill('exit', quantity=4, time='2025-01-01T00:00:00Z'))
        self.assertEqual(len(self.service.get_trade(self.trade)['executions']), 4)

    def test_invalid_inputs_and_closed_trade(self):
        invalids = [fill(quantity=q) for q in [0, -1, 1.5, True, '1']]
        invalids += [fill(price=p) for p in ['0', '20000.1', '-1', 'NaN']]
        invalids += [fill(commission='-1'), fill(fees='-1'), fill(commission='0.0000001'),
                     fill(time='2026-01-01'), fill(time=None), fill(sequence=9), fill(direction='short')]
        for raw in invalids:
            with self.subTest(raw=raw), self.assertRaises(TradeValidationError):
                self.service.add_execution(self.trade, **raw)
        self.service.add_executions(self.trade, [fill(), fill('exit', price='20050')])
        for raw in [fill(), fill('exit'), fill(time='2025-01-01T00:00:00Z')]:
            with self.assertRaises(ConflictError):
                self.service.add_execution(self.trade, **raw)
        self.assertEqual(self.service.get_trade(self.trade)['summary']['gross_pnl'], 100)
        with self.assertRaises(NotFoundError):
            self.service.create_trade(999, 'MNQ', 'long')

    def test_external_duplicates_and_atomic_rollback(self):
        external = dict(source='imported', external_namespace='provider:executions', external_execution_id='x')
        self.service.add_execution(self.trade, **fill(**external))
        other_trade = self.service.create_trade(self.account, 'MNQ', 'long')
        with self.assertRaises(ConflictError):
            self.service.add_executions(other_trade, [fill(), fill(**external)])
        self.assertEqual(self.service.get_trade(other_trade)['executions'], [])
        with self.assertRaises(TradeValidationError):
            self.service.add_executions(other_trade, [fill(), fill('exit', quantity=2)])
        other_account = self.service.create_account('B', 'personal')
        other = self.service.create_trade(other_account, 'MNQ', 'long')
        self.service.add_execution(other, **fill(**external))
        self.service.add_execution(other_trade, **fill(**{**external, 'external_namespace': 'different'}))
        with self.assertRaises(TradeValidationError):
            self.service.add_execution(other_trade, **fill(external_execution_id='orphan'))

    def test_reversal_and_failure_atomicity(self):
        self.service.add_execution(self.trade, **fill(quantity=3))
        before = len(self.service.list_trades(self.account))
        with self.assertRaises(TradeValidationError):
            self.service.record_reversal(self.trade, fill('exit', 3), fill(quantity=0))
        self.assertEqual(self.service.get_trade(self.trade)['summary']['open_quantity'], 3)
        self.assertEqual(len(self.service.list_trades(self.account)), before)
        new_id = self.service.record_reversal(self.trade, fill('exit', 3, commission='3'), fill(quantity=2, commission='2'))
        self.assertEqual(self.service.get_trade(self.trade)['summary']['status'], 'closed')
        self.assertEqual(self.service.get_trade(new_id)['direction'], 'short')
        self.assertEqual(self.service.get_trade(new_id)['summary']['open_quantity'], 2)

    def test_database_guards_and_exact_storage(self):
        self.service.add_execution(self.trade, **fill())
        connection = connect(self.path)
        self.addCleanup(connection.close)
        for clause in ['quantity=0', 'quantity=1.5', 'commission_microusd=-1', 'price_ticks=0', 'account_id=99']:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE executions SET ' + clause)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute('DELETE FROM trades WHERE id=?', (self.trade,))
        self.assertEqual(connection.execute('SELECT typeof(price_ticks), typeof(commission_microusd) FROM executions').fetchone()[:], ('integer', 'integer'))

    def test_concurrent_closes(self):
        self.service.add_execution(self.trade, **fill())
        def close_position(_):
            try:
                TradeService(self.path).add_execution(self.trade, **fill('exit'))
                return 'ok'
            except ConflictError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(close_position, range(2))), ['ok', 'conflict'])
        self.assertEqual(len(self.service.get_trade(self.trade)['executions']), 2)
