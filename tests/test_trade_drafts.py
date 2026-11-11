import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from database import initialize, connect
from trade_service import TradeService, DraftValidationError, ArchivedAccountError, NotFoundError, ConflictError


def draft_rows():
    return [
        dict(row_id='entry', execution_type='entry', executed_at='2026-11-10T10:00:00-04:00', quantity='2', price='20000', commission='2.50', fees='0'),
        dict(row_id='exit-a', execution_type='exit', executed_at='2026-11-10T10:01:00-04:00', quantity='1', price='20050', commission='0', fees='0'),
        dict(row_id='exit-b', execution_type='exit', executed_at='2026-11-10T10:02:00-04:00', quantity='1', price='20080', commission='0', fees='0'),
    ]


class TradeDraftTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'drafts.sqlite3'
        initialize(self.path)
        self.service = TradeService(self.path)
        self.account = self.service.create_account('Personal', 'personal')
        self.payload = dict(account_id=self.account, symbol='MNQ', direction='long', executions=draft_rows(), strategy='Reversal', mode='historical')

    def counts(self):
        c = connect(self.path)
        try:
            return tuple(c.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('trades','executions','write_requests'))
        finally:
            c.close()

    def test_acceptance_preview_and_modes(self):
        for count, gross, net, opened in [(1,'0','-2.50',2), (2,'100','97.50',1), (3,'260','257.50',0)]:
            payload = {**self.payload, 'executions':draft_rows()[:count], 'mode':'progressive' if count == 1 else 'historical'}
            preview = self.service.preview_trade(**payload)
            self.assertEqual(preview['summary']['gross_pnl'], Decimal(gross))
            self.assertEqual(preview['summary']['net_pnl'], Decimal(net))
            self.assertEqual(preview['summary']['open_quantity'], opened)
            self.assertEqual(preview['summary']['status'], 'closed' if count == 3 else 'open')
            saved = self.service.create_trade_with_executions(**payload, request_id=f'acceptance-request-{count}')
            actual = self.service.get_trade(saved['trade_id'])
            self.assertEqual(actual['summary'], preview['summary'])
            self.assertEqual(len(actual['executions']), count)
            if count == 1:
                self.assertEqual(actual['summary']['average_price'], Decimal('20000'))

    def test_preview_writes_nothing_and_is_query_only(self):
        before = self.path.read_bytes()
        self.service.preview_trade(**self.payload)
        self.assertEqual(self.counts(), (0,0,0))
        self.assertEqual(self.path.read_bytes(), before)
        original = self.service._account
        def inspect(connection, *args, **kwargs):
            self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE accounts SET name='Unexpected'")
            return original(connection, *args, **kwargs)
        with patch.object(self.service, '_account', side_effect=inspect):
            self.service.preview_trade(**self.payload)

    def test_multiple_entries_and_short(self):
        rows=draft_rows()
        rows[0].update(quantity='1', commission='0')
        rows[1].update(execution_type='entry', quantity='2', price='20030')
        rows[2].update(price='20050')
        summary=self.service.preview_trade(**{**self.payload, 'executions':rows})['summary']
        self.assertEqual(summary['average_price'], Decimal('20020'))
        self.assertEqual(summary['gross_pnl'], Decimal('60'))
        rows=draft_rows()[:2]
        rows[0].update(quantity='1', price='6000', commission='1.123456', fees='0.000001')
        rows[1].update(price='5990', commission='0.5', fees='0.25')
        result=self.service.create_trade_with_executions(**{**self.payload, 'executions':rows, 'symbol':'MES','direction':'short'},request_id='short-request-12345')
        summary=self.service.get_trade(result['trade_id'])['summary']
        self.assertEqual(summary['gross_pnl'], Decimal('50'))
        self.assertEqual(summary['net_pnl'], Decimal('48.126543'))

    def test_offsets_historical_order_and_equal_timestamps(self):
        rows=draft_rows()
        rows[0]['executed_at']='2026-11-10T14:00:00.123456Z'
        rows[1]['executed_at']='2026-11-10T10:00:00.123456-04:00'
        result=self.service.preview_trade(**{**self.payload,'executions':rows})
        self.assertEqual([r['row_id'] for r in result['executions']], ['entry','exit-a','exit-b'])
        self.assertEqual(result['executions'][0]['executed_at'], result['executions'][1]['executed_at'])
        swapped=[rows[1],rows[0],rows[2]]
        with self.assertRaises(DraftValidationError) as error:
            self.service.preview_trade(**{**self.payload,'executions':swapped})
        self.assertIn('exit-a', error.exception.errors['rows'])
        historical=[rows[2],rows[0],rows[1]]
        preview=self.service.preview_trade(**{**self.payload,'executions':historical})
        saved=self.service.create_trade_with_executions(**{**self.payload,'executions':historical},request_id='order-request-12345')
        actual=self.service.get_trade(saved['trade_id'])
        self.assertEqual([r['sequence'] for r in preview['executions']], [2,3,1])
        self.assertEqual([r['sequence'] for r in actual['executions']], [2,3,1])
        self.assertEqual(actual['summary'], preview['summary'])

    def test_field_errors(self):
        cases={'price':['0','20000.10','-1',1.25,'NaN'],
               'quantity':['0','-1','1.5',True,1],
               'commission':['-1','0.0000001','Infinity',0.5],
               'fees':['-1','1.0000000'],
               'executed_at':['2026-11-10T14:00:00','2026-02-30T14:00:00Z','bad',None,
                              '2026-11-10T14:00:00.1234567Z','2026-11-10T14:00:00+14:30']}
        for field, values in cases.items():
            for value in values:
                rows=draft_rows();rows[0][field]=value
                with self.subTest(field=field,value=value), self.assertRaises(DraftValidationError) as error:
                    self.service.preview_trade(**{**self.payload,'executions':rows})
                self.assertIn(field, error.exception.errors['rows']['entry'])
        self.assertEqual(self.counts(), (0,0,0))

    def test_invalid_histories_and_limits(self):
        too_many=[{**draft_rows()[0],'row_id':f'row{i}'} for i in range(201)]
        over=draft_rows();over[1]['quantity']='3'
        after=draft_rows()+[{**draft_rows()[0],'row_id':'after','executed_at':'2026-11-10T11:00:00-04:00'}]
        for rows in ([], draft_rows()[1:], over, after, too_many):
            with self.assertRaises(DraftValidationError):
                self.service.create_trade_with_executions(**{**self.payload,'executions':rows},request_id='bad-history-123456')
        for rows in (draft_rows(), draft_rows()[1:2]):
            with self.assertRaises(DraftValidationError):
                self.service.preview_trade(**{**self.payload,'mode':'progressive','executions':rows})
        self.assertEqual(self.counts(), (0,0,0))

    def test_metadata_and_untrusted_fields(self):
        for changes in ({'strategy':'x'*201},{'notes':'x'*10001},{'symbol':[]},{'direction':'both'},{'account_id':True}):
            with self.assertRaises(DraftValidationError):
                self.service.preview_trade(**{**self.payload, **changes})
        for field in ('sequence','source','external_execution_id'):
            rows=draft_rows();rows[0][field]='injected'
            with self.assertRaises(DraftValidationError):
                self.service.preview_trade(**{**self.payload,'executions':rows})
        rows=draft_rows();rows[1]['row_id']=rows[0]['row_id']
        with self.assertRaises(DraftValidationError):
            self.service.preview_trade(**{**self.payload,'executions':rows})

    def test_account_state_before_idempotency(self):
        request_id='account-state-123456'
        self.service.create_trade_with_executions(**self.payload,request_id=request_id)
        self.service.set_account_active(self.account,False)
        with self.assertRaises(ArchivedAccountError):
            self.service.preview_trade(**self.payload)
        with self.assertRaises(ArchivedAccountError):
            self.service.create_trade_with_executions(**self.payload,request_id=request_id)
        with self.assertRaises(NotFoundError):
            self.service.preview_trade(**{**self.payload,'account_id':999})
        self.assertEqual(self.counts(), (1,3,1))

    def test_idempotency_normalized_and_conflict(self):
        first=self.service.create_trade_with_executions(**self.payload,request_id='same-request-123456')
        equivalent=copy.deepcopy(self.payload)
        equivalent['strategy']='  Reversal  '
        equivalent['executions'][0].update(price='20000.00',commission='2.500000',quantity='02',row_id='new-id',executed_at='2026-11-10T14:00:00Z')
        retry=self.service.create_trade_with_executions(**equivalent,request_id='same-request-123456')
        self.assertEqual(first,retry)
        self.assertEqual(self.counts(),(1,3,1))
        for changes in ({'notes':'changed'},{'direction':'short'},{'executions':list(reversed(draft_rows()))}):
            with self.assertRaises(ConflictError):
                self.service.create_trade_with_executions(**{**self.payload,**changes},request_id='same-request-123456')

    def test_concurrent_creation_and_account_isolation(self):
        def create(_):
            return TradeService(self.path).create_trade_with_executions(**self.payload,request_id='concurrent-request-123')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(create,range(2)))
        self.assertEqual(results[0],results[1])
        other=self.service.create_account('Other','personal')
        self.assertEqual(self.service.list_trades(other),[])
        self.assertEqual(self.counts(),(1,3,1))

    def test_rollback_mid_batch_and_idempotency_registration(self):
        c=connect(self.path)
        try:
            c.execute("CREATE TRIGGER fail_second BEFORE INSERT ON executions WHEN NEW.sequence=2 BEGIN SELECT RAISE(ABORT,'test'); END")
            with self.assertRaises(ConflictError):
                self.service.create_trade_with_executions(**self.payload,request_id='rollback-request-123')
            self.assertEqual(self.counts(),(0,0,0))
            c.execute('DROP TRIGGER fail_second')
            c.execute("CREATE TRIGGER fail_key BEFORE INSERT ON write_requests BEGIN SELECT RAISE(ABORT,'test'); END")
            with self.assertRaises(ConflictError):
                self.service.create_trade_with_executions(**self.payload,request_id='rollback-request-123')
            self.assertEqual(self.counts(),(0,0,0))
        finally:c.close()
