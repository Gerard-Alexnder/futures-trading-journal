import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from database import initialize, connect
from trade_service import (TradeService, ConflictError, DraftValidationError, StaleRevisionError,
                           ArchivedAccountError, NotFoundError)
from preview_tokens import PreviewTokenError
from test_trade_service import fill


def replacement(**changes):
    return dict(executed_at='2026-01-01T12:00:00Z',execution_type='entry',quantity='2',
                price='20000',commission='1.25',fees='0.25',**changes)


class ExecutionCorrectionTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'audit.sqlite3';initialize(self.path)
        self.service=TradeService(self.path,preview_secret='ephemeral-test-only')
        self.account=self.service.create_account('QA','personal')
        self.trade=self.service.create_trade(self.account,'MNQ','long')
        self.entry=self.service.add_execution(self.trade,**fill(quantity=2,commission='1.25',fees='0.25'))
        self.exit=self.service.add_execution(self.trade,**fill('exit',2,'20010',time='2026-01-01T13:00:00Z',commission='1'))

    def detail(self):return self.service.get_trade(self.trade)
    def preview(self, row=None, execution=None):
        execution=execution or self.entry
        args=dict(expected_revision=self.detail()['revision'],reason='Corregir dato original')
        method=self.service.preview_execution_void if row is None else self.service.preview_execution_correction
        return method(self.trade,execution,**args,**({} if row is None else {'replacement':row}))
    def save(self, preview, row=None, key='correction-request-001'):
        args=dict(expected_revision=preview['revision'],reason='Corregir dato original',request_id=key,preview_token=preview['preview_token'])
        method=self.service.void_execution if row is None else self.service.correct_execution
        return method(self.trade,preview['execution_id'],**args,**({} if row is None else {'replacement':row}))

    def test_price_costs_audit_exact_and_readonly_preview(self):
        row={**replacement(),'price':'20001','commission':'1.123456','fees':'0.000001'}
        before=self.path.read_bytes();preview=self.preview(row)
        self.assertEqual(before,self.path.read_bytes())
        self.assertEqual(preview['projected']['gross_pnl'],Decimal('36'))
        receipt=self.save(preview,row);after=self.detail()
        self.assertEqual(after['summary'],preview['projected'])
        self.assertEqual(after['revision'],3)
        self.assertEqual(len(after['audit']),1)
        event=after['audit'][0]
        self.assertEqual(event['id'],receipt['audit_id']);self.assertEqual(event['before']['price_ticks'],80000)
        self.assertEqual(event['after']['price_ticks'],80004)
        self.assertEqual(event['after']['commission_microusd'],1123456)
        for field in ('id','trade_id','account_id','sequence','created_at','source','external_namespace','external_execution_id'):
            self.assertEqual(event['before'][field],event['after'][field])
        self.assertEqual(json.loads(event['after_json']),event['after'])

    def test_void_reopens_pending_excludes_costs_and_sequence_not_reused(self):
        preview=self.preview(execution=self.exit)
        self.assertEqual(preview['projected']['status'],'open')
        self.assertTrue(any('volverá' in w for w in preview['warnings']))
        self.save(preview)
        self.assertEqual(self.detail()['summary']['net_pnl'],Decimal('-1.50'))
        preview=self.preview(execution=self.entry);self.save(preview,key='void-second-request')
        detail=self.detail();self.assertEqual(detail['summary']['status'],'pending')
        self.assertEqual(detail['summary']['net_pnl'],0)
        self.assertEqual(len(detail['executions']),2)
        item=self.service.query_journal()['items'][0]
        self.assertTrue(item['date_is_creation']);self.assertEqual(item['entry_quantity'],0)
        self.service.add_execution(self.trade,**fill())
        self.assertTrue(all(r['is_voided'] for r in self.detail()['executions'] if r['id'] in (self.entry,self.exit)))
        self.assertEqual(max(r['sequence'] for r in self.detail()['executions']),3)
        self.assertEqual(self.detail()['summary']['open_quantity'],1)

    def test_invalid_histories_and_protected_fields(self):
        for row in ({**replacement(),'quantity':'1'}, {**replacement(),'execution_type':'exit'},
                    {**replacement(),'executed_at':'2026-01-01T14:00:00Z'},
                    {**replacement(),'price':'20000.1'}, {**replacement(),'fees':'0.0000001'}):
            with self.subTest(row=row),self.assertRaises(DraftValidationError):self.preview(row)
        with self.assertRaises(DraftValidationError):self.preview(execution=self.entry)
        for field in ('id','execution_id','trade_id','account_id','sequence','created_at','source','external_namespace','external_execution_id','symbol','direction'):
            with self.subTest(field=field),self.assertRaises(DraftValidationError):self.preview({**replacement(),field:'bad'})
        with self.assertRaises(DraftValidationError):self.preview({'price':'20001'})
        with self.assertRaises(DraftValidationError):self.preview(replacement())
        self.assertEqual(self.detail()['audit'],[])

    def test_quantity_timestamp_type_and_ties(self):
        row={**replacement(),'quantity':'3','executed_at':'2026-01-01T11:00:00Z'}
        preview=self.preview(row);self.save(preview,row)
        self.assertEqual(self.detail()['summary']['status'],'open')
        row={**replacement(),'execution_type':'entry','quantity':'1','executed_at':'2026-01-01T11:00:00Z','price':'20010','commission':'1','fees':'0'}
        preview=self.preview(row,self.exit)
        self.assertEqual(preview['projected_order'],[self.entry,self.exit])
        self.save(preview,row,key='correct-type-request')
        self.assertEqual(self.detail()['summary']['open_quantity'],4)
        self.assertEqual(self.detail()['executions'][1]['sequence'],2)

    def test_tokens_binding_expiry_and_confirmed_retry(self):
        row={**replacement(),'price':'20001'};preview=self.preview(row)
        with self.assertRaises(PreviewTokenError):self.save({**preview,'preview_token':preview['preview_token'][:-1]+'x'},row)
        with self.assertRaises(PreviewTokenError):self.save(preview,{**row,'price':'20002'})
        with patch('preview_tokens.time.time',return_value=9999999999),self.assertRaises(PreviewTokenError):self.save(preview,row)
        receipt=self.save(preview,row);before=self.detail()
        with patch('preview_tokens.time.time',return_value=9999999999):self.assertEqual(self.save(preview,row),receipt)
        self.assertEqual(self.detail(),before)
        with self.assertRaises(ConflictError):self.save(preview,{**row,'price':'20002'})
        with self.assertRaises(StaleRevisionError):self.save(preview,row,key='different-request-001')
        self.service.set_account_active(self.account,False)
        with self.assertRaises(ArchivedAccountError):self.save(preview,row)
        self.service.set_account_active(self.account,True)
        self.assertEqual(self.save(preview,row),receipt)

    def test_void_retry_and_second_void_or_correction_rejected(self):
        preview=self.preview(execution=self.exit);receipt=self.save(preview)
        self.assertEqual(self.save(preview),receipt)
        with self.assertRaises(ConflictError):self.preview(execution=self.exit)
        with self.assertRaises(ConflictError):self.preview(replacement(),self.exit)
        self.assertEqual(self.detail()['revision'],3);self.assertEqual(len(self.detail()['audit']),1)

    def test_reason_membership_and_projection_tampering(self):
        with self.assertRaises(ValueError):
            self.service.preview_execution_void(self.trade,self.exit,expected_revision=2,reason='  ')
        with self.assertRaises(NotFoundError):self.preview(execution=999)
        preview=self.preview(execution=self.exit)
        other=self.service.create_trade(self.account,'MNQ','long')
        with self.assertRaises(NotFoundError):
            self.service.void_execution(other,self.exit,expected_revision=0,reason='Corregir dato original',request_id='other-request-12345',preview_token=preview['preview_token'])
        original=self.service._revalidate
        def altered(t,h):return {**original(t,h),'net_pnl':Decimal('999')}
        with patch.object(self.service,'_revalidate',side_effect=altered),self.assertRaises(PreviewTokenError):self.save(preview)
        self.assertEqual(self.detail()['revision'],2)

    def test_atomic_failure_and_append_only(self):
        preview=self.preview(execution=self.exit);before=self.detail()
        c=connect(self.path)
        try:
            for table,operation in [('execution_audit','INSERT'),('trades','UPDATE'),('write_requests','INSERT')]:
                c.execute(f"CREATE TRIGGER fail BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'test'); END")
                with self.assertRaises(ConflictError):self.save(preview)
                self.assertEqual(self.detail(),before)
                self.assertEqual(c.execute('SELECT count(*) FROM write_requests').fetchone()[0],0)
                c.execute('DROP TRIGGER fail')
            self.save(preview)
            for sql in ("UPDATE execution_audit SET reason='changed'",'DELETE FROM execution_audit','UPDATE executions SET is_voided=2'):
                with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)
        finally:c.close()

    def test_concurrent_confirmation(self):
        preview=self.preview(execution=self.exit)
        with ThreadPoolExecutor(max_workers=2) as pool: receipts=list(pool.map(lambda _:self.save(preview),range(2)))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(len(self.detail()['audit']),1)

    def test_void_partial_entry_and_old_new_writers_replay(self):
        # Extra entry makes the original entry dispensable while retaining a valid close.
        row={**replacement(),'quantity':'3'};preview=self.preview(row);self.save(preview,row)
        preview=self.preview(execution=self.exit);self.save(preview,key='void-final-old-0001')
        self.service.add_execution(self.trade,**fill('exit',1, time='2026-01-01T14:00:00Z'))
        partial=self.detail()['executions'][-1]['id']
        preview=self.preview(execution=partial);self.save(preview,key='void-partial-00001')
        from test_execution_batches import row as draft
        rev=self.detail()['revision']
        fillrow=draft('exit','3')
        preview=self.service.preview_execution_batch(self.trade,[fillrow],expected_revision=rev)
        receipt=self.service.append_execution_batch(self.trade,[fillrow],expected_revision=rev,request_id='append-after-void1')
        self.assertEqual(self.detail()['summary'],preview['projected'])
        self.assertEqual(max(r['sequence'] for r in self.detail()['executions']),4)
        self.assertEqual(receipt['revision'],rev+1)

    def test_tokens_bind_reason_execution_trade_and_configuration(self):
        row={**replacement(),'price':'20001'};preview=self.preview(row)
        with self.assertRaises(PreviewTokenError):
            self.service.correct_execution(self.trade,self.entry,row,expected_revision=2,reason='Otro motivo',
                request_id='reason-mismatch-0001',preview_token=preview['preview_token'])
        other=self.service.create_trade(self.account,'MNQ','long')
        target=self.service.add_execution(other,**fill(quantity=2))
        with self.assertRaises(PreviewTokenError):
            self.service.correct_execution(other,target,row,expected_revision=1,reason='Corregir dato original',
                request_id='trade-mismatch-0001',preview_token=preview['preview_token'])
        from database import DatabaseError
        with self.assertRaises(DatabaseError):
            TradeService(self.path).preview_execution_correction(self.trade,self.entry,row,expected_revision=2,reason='Motivo')
        self.assertEqual(self.detail()['revision'],2)

    def test_import_provenance_and_reversal_after_void(self):
        other=self.service.create_trade(self.account,'MNQ','long')
        imported=self.service.add_execution(other,**fill(quantity=2,source='imported',external_namespace='synthetic-provider',external_execution_id='fixture-001'))
        row={**replacement(),'price':'20001'}
        preview=self.service.preview_execution_correction(other,imported,row,expected_revision=1,reason='Precio incorrecto')
        self.service.correct_execution(other,imported,row,expected_revision=1,reason='Precio incorrecto',request_id='import-correction-01',preview_token=preview['preview_token'])
        event=self.service.get_trade(other)['audit'][0]
        self.assertEqual(event['after']['source'],'imported')
        self.assertEqual(event['after']['external_namespace'],'synthetic-provider')
        self.assertEqual(event['after']['external_execution_id'],'fixture-001')
        preview=self.preview(execution=self.exit);self.save(preview)
        reverse=self.service.record_reversal(self.trade,fill('exit',2,time='2026-01-01T14:00:00Z'),fill(time='2026-01-01T14:00:00Z'))
        self.assertEqual(self.detail()['summary']['status'],'closed')
        self.assertEqual(self.detail()['revision'],4)
        self.assertEqual(max(r['sequence'] for r in self.detail()['executions']),3)
        self.assertEqual(self.service.get_trade(reverse)['summary']['status'],'open')
        with self.assertRaises(ConflictError):self.service.add_execution(self.trade,**fill())

    def test_amendment_preview_consistent_with_concurrent_writer(self):
        c=connect(self.path);c.execute('PRAGMA journal_mode=WAL');c.close()
        original=self.service._executions
        def interleave(c,trade_id):
            self.service.update_trade_metadata(trade_id,notes='Concurrent metadata')
            return original(c,trade_id)
        with patch.object(self.service,'_executions',side_effect=interleave):
            result=self.service.preview_execution_void(self.trade,self.exit,expected_revision=2,reason='Corregir dato original')
        self.assertEqual(result['revision'],2)
        with self.assertRaises(StaleRevisionError):self.save(result)
        self.assertEqual(self.detail()['audit'],[])

    def test_void_entry_with_remaining_valid_history_changes_journal_date(self):
        other=self.service.create_trade(self.account,'MNQ','long')
        early=self.service.add_execution(other,**fill(time='2026-01-01T10:00:00Z',commission='2'))
        self.service.add_execution(other,**fill(time='2026-01-02T10:00:00Z',commission='1'))
        preview=self.service.preview_execution_void(other,early,expected_revision=2,reason='Entrada duplicada')
        self.service.void_execution(other,early,expected_revision=2,reason='Entrada duplicada',request_id='void-first-entry01',preview_token=preview['preview_token'])
        item=next(i for i in self.service.query_journal()['items'] if i['id']==other)
        self.assertEqual(item['effective_at'],'2026-01-02T10:00:00.000000Z')
        self.assertEqual(item['entry_quantity'],1)
        self.assertEqual(item['summary']['net_pnl'],Decimal('-1'))
