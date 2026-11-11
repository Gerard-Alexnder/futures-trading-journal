import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from database import initialize, connect
from trade_service import TradeService, PersistenceError
from test_trade_drafts import draft_rows


class JournalRouteTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.path=Path(folder.name)/'routes.sqlite3';initialize(self.path)
        previous=dict(app.config);self.addCleanup(lambda:app.config.update(previous))
        app.config.update(TESTING=True,SECRET_KEY='test-only',DATABASE=str(self.path))
        self.service=TradeService(self.path)
        self.account=self.service.create_account('Journal account','personal')
        self.client=app.test_client()
        self.client.get('/journal/new')
        with self.client.session_transaction() as session:self.csrf=session['csrf_token']
        self.payload=dict(account_id=self.account,symbol='MNQ',direction='long',executions=draft_rows(),strategy='Reversal',mode='historical')

    def post(self,path='/api/journal/preview',payload=None):
        return self.client.post(path,json=self.payload if payload is None else payload,headers={'X-CSRF-Token':self.csrf})

    def test_page_navigation_selection_and_empty_accounts(self):
        with self.client.session_transaction() as session:session['selected_account_id']=self.account
        response=self.client.get('/journal/new')
        self.assertEqual(response.status_code,200)
        self.assertIn(f'value="{self.account}" selected',response.text)
        self.assertEqual(response.text.count('aria-current="page"'),1)
        self.assertIn('href="/journal" class="activo"',response.text)
        self.assertIn('UTC−04:00',response.text)
        self.assertIn('data-field="commission"',response.text)
        self.service.set_account_active(self.account,False)
        self.assertIn('Necesitas una cuenta activa',self.client.get('/journal/new').text)

    def test_preview_and_creation_json_precision_and_retry(self):
        response=self.post();self.assertEqual(response.status_code,200)
        result=response.json['result']
        self.assertEqual(result['summary']['net_pnl'],'257.50')
        self.assertIsInstance(result['summary']['average_price'],type(None))
        self.assertIsInstance(result['executions'][0]['price'],str)
        payload={**self.payload,'request_id':'route-request-123456'}
        first=self.post('/api/journal',payload);self.assertEqual(first.status_code,200)
        retry=self.post('/api/journal',payload)
        self.assertEqual(first.json,retry.json)
        self.assertEqual(len(self.service.list_trades(self.account)),1)
        self.assertEqual(self.post('/api/journal',{**payload,'notes':'different'}).status_code,409)

    def test_bad_json_csrf_and_fields(self):
        for path in ('/api/journal/preview','/api/journal'):
            self.assertEqual(self.client.post(path,json=self.payload).status_code,403)
            self.assertEqual(self.client.post(path,json=self.payload,headers={'X-CSRF-Token':'bad'}).status_code,403)
            self.assertEqual(self.client.post(path,data='{',content_type='application/json',headers={'X-CSRF-Token':self.csrf}).status_code,400)
            self.assertEqual(self.client.post(path,data='text').status_code,400)
        self.assertEqual(self.post(payload=[]).status_code,400)
        self.assertEqual(self.post(payload={}).status_code,400)
        self.assertEqual(self.post(payload={**self.payload,'unknown':True}).status_code,400)
        payload={**self.payload,'executions':[{**draft_rows()[0],'price':'20000.1'}]}
        result=self.post(payload=payload)
        self.assertEqual(result.status_code,422)
        self.assertIn('price',result.json['errors']['rows']['entry'])
        self.assertEqual(payload['executions'][0]['price'],'20000.1')
        self.assertEqual(self.service.list_trades(self.account),[])

    def test_sizes_row_limits_and_calculator_unchanged(self):
        huge=json.dumps({**self.payload,'notes':'x'*(512*1024)})
        result=self.client.post('/api/journal/preview',data=huge,content_type='application/json',headers={'X-CSRF-Token':self.csrf})
        self.assertEqual(result.status_code,413)
        rows=[{**draft_rows()[0],'row_id':f'r{i}','quantity':'1','commission':'0'} for i in range(200)]
        self.assertEqual(self.post(payload={**self.payload,'executions':rows}).status_code,200)
        rows.append({**rows[0],'row_id':'extra'})
        self.assertEqual(self.post(payload={**self.payload,'executions':rows}).status_code,422)
        # Más de 4 KiB es permitido aquí; el endpoint de riesgo conserva su propio límite.
        self.assertEqual(self.post(payload={**self.payload,'notes':'x'*5000}).status_code,200)
        self.assertEqual(self.client.post('/api/calculate-risk',json={'padding':'x'*4096}).status_code,413)

    def test_resource_and_persistence_errors_are_safe(self):
        self.assertEqual(self.post(payload={**self.payload,'account_id':999}).status_code,404)
        self.service.set_account_active(self.account,False)
        self.assertEqual(self.post().status_code,409)
        with patch.object(TradeService,'preview_trade',side_effect=PersistenceError('private SQL')):
            response=self.post()
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private SQL',response.text)
        app.config['DATABASE']=str(self.path.parent/'missing.sqlite3')
        self.assertEqual(self.post().status_code,503)
        self.assertFalse(Path(app.config['DATABASE']).exists())
        app.config['SECRET_KEY']=None
        self.assertEqual(self.client.get('/journal/new').status_code,503)
        self.assertEqual(self.client.get('/calculator').status_code,200)
