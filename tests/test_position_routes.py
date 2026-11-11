import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from database import initialize
from trade_service import TradeService, PersistenceError
from test_execution_batches import row


class PositionRouteTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'http.sqlite3'; initialize(self.path)
        previous=dict(app.config); self.addCleanup(lambda:app.config.update(previous))
        app.config.update(TESTING=True,SECRET_KEY='test-only',DATABASE=str(self.path))
        self.service=TradeService(self.path)
        self.account=self.service.create_account('<script>account</script>','personal')
        self.trade=self.service.create_trade(self.account,'MNQ','long',notes='<script>notes</script>')
        self.client=app.test_client()
        self.url=f'/api/journal/{self.trade}/executions'
        self.detail=f'/journal/{self.trade}'
        self.client.get(self.detail)
        with self.client.session_transaction() as session:self.csrf=session['csrf_token']

    def post(self, rows=None, revision=0, save=False, key='http-request-000001', extra=None):
        payload=dict(expected_revision=revision,executions=rows or [row()])
        if save: payload['request_id']=key
        payload.update(extra or {})
        return self.client.post(self.url+('' if save else '/preview'),json=payload,headers={'X-CSRF-Token':self.csrf})

    def test_acceptance_preview_save_and_lost_response_after_close(self):
        cases=[(row(quantity='2'),'2.50',2,'20000','0','-2.50'),
               (row(price='20030',minute=1),'1.25',3,'20010','0','-3.75'),
               (row('exit',price='20050',minute=2),'1.25',2,'20010','80','75.00'),
               (row('exit','2','20080',3),'2.50',0,None,'360','352.50')]
        from decimal import Decimal
        for revision,(execution,commission,opened,average,gross,net) in enumerate(cases):
            execution['commission']=commission
            preview=self.post([execution],revision); self.assertEqual(preview.status_code,200)
            projected=preview.json['result']['projected']
            receipt=self.post([execution],revision,True,f'http-acceptance-{revision}')
            self.assertEqual(receipt.status_code,200)
            detail=self.client.get(self.detail,headers={'Accept':'application/json'})
            summary=detail.json['result']['summary']
            self.assertEqual(projected,summary)
            self.assertEqual(summary['open_quantity'],opened)
            self.assertEqual(Decimal(summary['average_price']) if average else summary['average_price'],Decimal(average) if average else None)
            self.assertEqual(Decimal(summary['gross_pnl']),Decimal(gross))
            self.assertEqual(Decimal(summary['net_pnl']),Decimal(net))
        retry=self.post([execution],3,True,'http-acceptance-3')
        self.assertEqual(retry.json,receipt.json)
        self.assertEqual(len(self.service.get_trade(self.trade)['executions']),4)
        self.assertIn('solo lectura',self.client.get(self.detail).text.lower())
        self.assertEqual(self.post(revision=4).json['code'],'trade_closed')

    def test_detail_pending_open_archived_and_escaping(self):
        html=self.client.get(self.detail).text
        self.assertIn('pending',html); self.assertIn('&lt;script&gt;notes&lt;/script&gt;',html)
        self.assertNotIn('<script>account</script>',html)
        self.post(save=True)
        self.assertIn('open',self.client.get(self.detail).text)
        self.service.set_account_active(self.account,False)
        html=self.client.get(self.detail).text
        self.assertIn('Archivada',html); self.assertIn('solo lectura',html.lower())
        self.assertEqual(self.post(revision=1).json['code'],'account_inactive')
        self.assertEqual(self.client.get('/journal/999').status_code,404)

    def test_protocol_security_and_errors(self):
        self.assertEqual(self.client.post(self.url,json={}).status_code,403)
        self.assertEqual(self.client.post(self.url,data='text').status_code,400)
        for extra in ({'symbol':'MES'},{'account_id':2},{'direction':'short'}):
            self.assertEqual(self.post(extra=extra).status_code,400)
        self.assertEqual(self.post([{**row(),'price':'20000.1'}]).status_code,422)
        self.assertIn('draft',self.post([row('exit')]).json['errors']['rows'])
        response=self.client.post(self.url+'/preview',data='{',content_type='application/json',headers={'X-CSRF-Token':self.csrf})
        self.assertEqual(response.status_code,400)
        response=self.client.post('/api/journal/999/executions/preview',json={'executions':[row()],'expected_revision':0},headers={'X-CSRF-Token':self.csrf})
        self.assertEqual(response.status_code,404)
        self.post(save=True)
        self.assertEqual(self.post().json['code'],'stale_revision')
        self.assertEqual(self.post([row(price='20001')],save=True).json['code'],'idempotency_conflict')
        with patch.object(TradeService,'preview_execution_batch',side_effect=PersistenceError('private SQL')):
            response=self.post(revision=1)
        self.assertEqual(response.status_code,503); self.assertNotIn('private SQL',response.text)

    def test_limits_and_no_partial_writes(self):
        rows=[{**row(),'row_id':f'r{i}'} for i in range(200)]
        self.assertEqual(self.post(rows).status_code,200)
        rows.append({**row(),'row_id':'extra'})
        self.assertEqual(self.post(rows,save=True).status_code,422)
        response=self.client.post(self.url,json={'padding':'x'*(512*1024)},headers={'X-CSRF-Token':self.csrf})
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.service.get_trade(self.trade)['executions'],[])
        self.assertEqual(self.service.get_trade(self.trade)['revision'],0)
