import unittest
from unittest.mock import patch
from app import app
import test_execution_corrections as fixtures
from trade_service import PersistenceError,TradeService


class CorrectionRouteTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ExecutionCorrectionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        previous=dict(app.config);self.addCleanup(lambda:app.config.update(previous))
        app.config.update(TESTING=True,DATABASE=str(self.f.path),SECRET_KEY='ephemeral-route-only')
        self.client=app.test_client();self.detail=f'/journal/{self.f.trade}'
        self.client.get(self.detail)
        with self.client.session_transaction() as session:self.csrf=session['csrf_token']
        self.base=f'/api/journal/{self.f.trade}/executions/{self.f.exit}/void'
        self.payload=dict(expected_revision=2,reason='Anular salida incorrecta')

    def post(self,path,payload):return self.client.post(path,json=payload,headers={'X-CSRF-Token':self.csrf})

    def test_closed_void_preview_commit_receipt_and_audit(self):
        before=self.f.path.read_bytes();preview=self.post(self.base+'/preview',self.payload)
        self.assertEqual(preview.status_code,200);self.assertEqual(before,self.f.path.read_bytes())
        self.assertEqual(preview.json['result']['projected']['status'],'open')
        data={**self.payload,'request_id':'http-void-0000001','preview_token':preview.json['result']['preview_token']}
        receipt=self.post(self.base,data);self.assertEqual(receipt.status_code,200)
        with patch('trade_service.validate_preview',side_effect=AssertionError('confirmed retry must not validate expired token')):retry=self.post(self.base,data)
        self.assertEqual(receipt.json,retry.json)
        detail=self.client.get(self.detail,headers={'Accept':'application/json'}).json['result']
        self.assertEqual(len(detail['audit']),1);self.assertEqual(detail['revision'],3)
        self.assertEqual(detail['summary']['status'],'open')
        self.assertIn('Anulada',self.client.get(self.detail).text)
        self.assertEqual(self.post(self.base,{**data,'request_id':'new-request-000000'}).status_code,409)

    def test_correction_fields_protocol_csrf_and_token(self):
        url=f'/api/journal/{self.f.trade}/executions/{self.f.entry}/correction'
        data={**self.payload,'replacement':{**fixtures.replacement(),'price':'20001'}}
        preview=self.post(url+'/preview',data);self.assertEqual(preview.status_code,200)
        self.assertEqual(self.client.post(url+'/preview',json=data).status_code,403)
        for changes in ({'symbol':'MES'},{'execution_id':999}):
            self.assertEqual(self.post(url+'/preview',{**data,**changes}).status_code,400)
        self.assertEqual(self.post(url+'/preview',{**data,'replacement':{'price':'20001'}}).status_code,422)
        self.assertEqual(self.post(url,{**data,'request_id':'missing-token-0001'}).status_code,400)
        invalid=self.post(url,{**data,'request_id':'invalid-token-001','preview_token':'bad'})
        self.assertEqual(invalid.status_code,409);self.assertEqual(invalid.json['code'],'invalid_preview')
        body={**data,'request_id':'correct-http-0001','preview_token':preview.json['result']['preview_token']}
        self.assertEqual(self.post(url,body).status_code,200)
        self.assertIn('execution_amendments.js',self.client.get(self.detail).text)

    def test_archived_missing_errors_and_limits(self):
        self.f.service.set_account_active(self.f.account,False)
        self.assertEqual(self.post(self.base+'/preview',self.payload).json['code'],'account_inactive')
        self.assertEqual(self.client.get(self.detail).status_code,200)
        self.f.service.set_account_active(self.f.account,True)
        self.assertEqual(self.post(self.base.replace(str(self.f.exit)+'/void','999/void')+'/preview',self.payload).status_code,404)
        self.assertEqual(self.post(self.base+'/preview',{**self.payload,'reason':' '}).status_code,422)
        self.assertEqual(self.post(self.base+'/preview',{**self.payload,'reason':'x'*(512*1024)}).status_code,413)
        with patch.object(TradeService,'preview_execution_void',side_effect=PersistenceError('private')):
            response=self.post(self.base+'/preview',self.payload)
        self.assertEqual(response.status_code,503);self.assertNotIn('private',response.text)
