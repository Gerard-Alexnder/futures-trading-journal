import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from database import initialize, connect
from trade_service import TradeService, DraftValidationError
from test_trade_service import fill


class JournalHistoryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'history.sqlite3'; initialize(self.path)
        self.service=TradeService(self.path)
        self.account=self.service.create_account('Same <name>','personal')
        self.other=self.service.create_account('Same <name>','funded')

    def trade(self, rows=None, account=None, direction='long', symbol='MNQ'):
        trade=self.service.create_trade(account or self.account,symbol,direction,strategy='<plan>')
        if rows: self.service.add_executions(trade,rows)
        return trade

    def test_logical_rows_lifetime_and_quantities(self):
        trade=self.trade([fill(quantity=2,time='2026-11-10T14:00:00Z'),fill(time='2026-11-10T15:00:00Z'),fill('exit',3,'20010',time='2026-11-12T12:00:00Z')])
        result=self.service.query_journal(date_from='2026-11-10',date_to='2026-11-10')
        self.assertEqual(result['pagination']['total'],1)
        item=result['items'][0]
        self.assertEqual(item['entry_quantity'],3); self.assertEqual(item['summary']['open_quantity'],0)
        self.assertEqual(item['summary']['net_pnl'],Decimal('60'))
        actual=self.service.get_trade(trade)['summary']; actual.pop('realized_by_execution')
        self.assertEqual(item['summary'],actual)
        self.assertFalse(item['date_is_creation'])

    def test_statistics_costs_winners_zero_short_and_archive(self):
        for price in ['20010','19990','20000']:
            self.trade([fill(),fill('exit',price=price)])
        self.trade([fill(commission='1.25')])
        self.trade(account=self.other)
        self.trade([fill(),fill('exit',price='19990')],account=self.other,direction='short',symbol='MES')
        self.service.set_account_active(self.other,False)
        result=self.service.query_journal()
        self.assertEqual(result['statistics']['closed_count'],4)
        self.assertEqual(result['statistics']['winning_count'],2)
        self.assertEqual(result['statistics']['win_rate'],Decimal(50))
        self.assertEqual(result['statistics']['net_pnl'],Decimal('48.75'))
        self.assertEqual(result['statistics']['open_count'],1)
        filtered=self.service.query_journal(account_id=self.other,symbol='MES',direction='short',status='closed')
        self.assertEqual(filtered['pagination']['total'],1)
        self.assertFalse(filtered['items'][0]['account']['is_active'])
        self.assertIsNone(self.service.query_journal(status='pending')['statistics']['win_rate'])
        self.assertEqual(self.service.query_journal(status='open')['statistics']['net_pnl'],Decimal('-1.25'))
        self.assertEqual(self.service.query_journal(symbol='NQ')['pagination']['total'],0)
        self.assertEqual(self.service.query_journal(direction='short')['pagination']['total'],1)

    def test_pending_creation_retroactive_and_date_boundaries(self):
        pending=self.trade()
        c=connect(self.path)
        try:c.execute('UPDATE trades SET created_at=? WHERE id=?',('2026-11-10T00:00:00.000000Z',pending))
        finally:c.close()
        trade=self.trade([fill(time='2026-11-12T00:00:00Z')])
        self.service.add_execution(trade,**fill(time='2026-11-09T18:30:00Z'))
        result=self.service.query_journal(date_from='2026-11-10',date_to='2026-11-10',utc_offset='+05:30')
        self.assertEqual({i['id'] for i in result['items']},{pending,trade})
        self.assertTrue(next(i for i in result['items'] if i['id']==pending)['date_is_creation'])
        self.trade([fill(time='2026-11-10T18:30:00Z')]) # next local midnight excluded
        self.assertEqual(self.service.query_journal(date_from='2026-11-10',date_to='2026-11-10',utc_offset='+05:30')['pagination']['total'],2)
        self.assertEqual(self.service.query_journal(date_from='2026-11-10',date_to='2026-11-10',utc_offset='+00:00')['pagination']['total'],2)

    def test_pagination_order_and_statistics(self):
        ids=[self.trade([fill(commission='0.000001')]) for _ in range(27)]
        first=self.service.query_journal(); second=self.service.query_journal(page=2)
        self.assertEqual([i['id'] for i in first['items']],list(reversed(ids))[:25])
        self.assertEqual([i['id'] for i in second['items']],list(reversed(ids))[25:])
        self.assertEqual(first['statistics'],second['statistics'])
        self.assertEqual(first['statistics']['net_pnl'],Decimal('-0.000027'))
        self.assertEqual(self.service.query_journal(page=99)['pagination']['page'],2)
        self.assertEqual(self.service.query_journal(page_size=50)['pagination']['pages'],1)
        empty=self.service.query_journal(symbol='ES',page=9)['pagination']
        self.assertEqual((empty['page'],empty['pages']),(1,0))

    def test_validation(self):
        for name,values in {'account_id':[True,0,999], 'page':[-1,'1.2',True], 'page_size':[1,101],
                            'symbol':['bad',[]], 'direction':['both'], 'status':['bad'],
                            'utc_offset':['UTC','+14:01','-15:00','+01:60',''],
                            'date_from':['2026-02-30','0001-01-01'], 'date_to':['9999-12-31','bad']}.items():
            for value in values:
                args={name:value}
                if value=='0001-01-01': args['utc_offset']='+14:00'
                with self.subTest(args=args), self.assertRaises(DraftValidationError): self.service.query_journal(**args)
        with self.assertRaises(DraftValidationError):self.service.query_journal(date_from='2026-11-12',date_to='2026-11-10')
        for offset in ['+14:00','-14:00','+05:45']:self.service.query_journal(utc_offset=offset)

    def test_readonly_snapshot_once_and_concurrent_writer(self):
        trade=self.trade([fill()]); before=self.path.read_bytes()
        with patch.object(self.service,'_revalidate',wraps=self.service._revalidate) as replay:
            result=self.service.query_journal(); self.assertEqual(replay.call_count,1)
        self.assertEqual(before,self.path.read_bytes())
        c=connect(self.path); c.execute('PRAGMA journal_mode=WAL'); c.close()
        original=self.service._revalidate
        def interleave(t,rows):
            writer=TradeService(self.path)
            writer.add_execution(trade,**fill('exit',price='20010'))
            writer.set_account_active(self.account,False)
            return original(t,rows)
        with patch.object(self.service,'_revalidate',side_effect=interleave):
            during=self.service.query_journal()
        self.assertEqual(result,during)
        after=self.service.query_journal()
        self.assertEqual(after['statistics']['closed_count'],1)
        self.assertFalse(after['items'][0]['account']['is_active'])

    def test_decimal_sum_not_default_context_and_classification(self):
        for _ in range(3): self.trade([fill()])
        original=self.service._revalidate
        values=iter([Decimal('100000000000000000000000000000.000001'),Decimal('-100000000000000000000000000000'),Decimal('0.000001')])
        def summary(t,rows):return {**original(t,rows),'net_pnl':next(values),'status':'closed'}
        with patch.object(self.service,'_revalidate',side_effect=summary):
            result=self.service.query_journal()
        self.assertEqual(result['statistics']['net_pnl'],Decimal('0.000002'))
        self.assertEqual(result['statistics']['winning_count'],2)

    def test_tiny_actual_profit_is_winner_before_display_rounding(self):
        self.trade([fill(),fill('exit',price='20010',commission='19.999999')])
        result=self.service.query_journal()
        self.assertEqual(result['statistics']['net_pnl'],Decimal('0.000001'))
        self.assertEqual(result['statistics']['winning_count'],1)
        self.assertEqual(result['statistics']['win_rate'],Decimal(100))

    def test_snapshot_across_execution_batches(self):
        ids=[self.trade([fill()]) for _ in range(401)]
        connection=connect(self.path)
        connection.execute('PRAGMA journal_mode=WAL');connection.close()
        original=self.service._revalidate
        calls=0
        def interleave(trade,history):
            nonlocal calls
            calls+=1
            if calls==1:
                TradeService(self.path).add_execution(ids[-1],**fill('exit'))
            return original(trade,history)
        with patch.object(self.service,'_revalidate',side_effect=interleave):
            result=self.service.query_journal()
        self.assertEqual(calls,401)
        self.assertEqual(result['statistics']['open_count'],401)
        self.assertEqual(result['statistics']['closed_count'],0)
        self.assertEqual(self.service.query_journal()['statistics']['closed_count'],1)
