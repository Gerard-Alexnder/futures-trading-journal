import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from database import initialize
from trade_service import TradeService, PersistenceError


class AccountWebTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'web.sqlite3'
        initialize(self.path)
        old = dict(app.config)
        self.addCleanup(lambda: app.config.update(old))
        app.config.update(TESTING=True, SECRET_KEY='test-only-key', DATABASE=str(self.path), SESSION_COOKIE_SECURE=False)
        self.client = app.test_client()
        self.service = TradeService(self.path)
        self.client.get('/accounts')
        with self.client.session_transaction() as session:
            self.csrf = session['csrf_token']

    def post(self, path='/accounts', **values):
        return self.client.post(path, data=dict(csrf_token=self.csrf, request_id='request-key-12345678', **values))

    def test_create_normalize_list_and_idempotency(self):
        for _ in range(2):
            self.assertEqual(self.post(name='  Cuenta  ', account_type='personal', platform=' ').status_code, 303)
        accounts = self.service.list_accounts()
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['name'], 'Cuenta')
        self.assertIsNone(accounts[0]['platform'])
        self.assertEqual(self.post(name='Distinta', account_type='personal').status_code, 409)
        self.assertIn('Cuenta', self.client.get('/accounts').text)

    def test_csrf_absent_wrong_valid_header(self):
        for token in (None, 'invalid'):
            for url in ('/accounts', '/accounts/1/select', '/accounts/1/archive', '/accounts/1/reactivate'):
                data = {} if token is None else {'csrf_token': token}
                self.assertEqual(self.client.post(url, data=data).status_code, 403)
        response = self.client.post('/accounts', headers={'X-CSRF-Token': self.csrf},
                                    data={'name':'A', 'account_type':'personal', 'request_id':'header-request-12345'})
        self.assertEqual(response.status_code, 303)

    def test_validation_keeps_accounts_and_draft(self):
        self.service.create_account('TradeStation Personal', 'personal')
        self.service.create_account('Topstep Evaluation 50K', 'funded')
        # Excede el límite de plataforma conservando un tipo válido en el borrador.
        platform = 'P' * 201
        response = self.post(name='Mi borrador', account_type='funded', platform=platform)
        self.assertEqual(response.status_code, 422)
        self.assertIn('platform: texto no vacío de hasta 200 caracteres.', response.text)
        for name in ('TradeStation Personal', 'Topstep Evaluation 50K'):
            self.assertIn(f'<h2>{name}</h2>', response.text)
        self.assertNotIn('No hay cuentas registradas', response.text)
        self.assertIn('value="Mi borrador"', response.text)
        self.assertIn(f'value="{platform}"', response.text)
        self.assertIn('value="funded" selected', response.text)
        self.assertEqual(len(self.service.list_accounts()), 2)

    def test_idempotency_conflict_keeps_accounts_and_draft(self):
        self.assertEqual(self.post(name='TradeStation Personal', account_type='personal').status_code, 303)
        self.service.create_account('Topstep Evaluation 50K', 'funded')
        response = self.post(name='Otro borrador', account_type='funded', platform='Topstep')
        self.assertEqual(response.status_code, 409)
        self.assertIn('La clave ya se utilizó para otra solicitud.', response.text)
        for name in ('TradeStation Personal', 'Topstep Evaluation 50K'):
            self.assertIn(f'<h2>{name}</h2>', response.text)
        self.assertNotIn('No hay cuentas registradas', response.text)
        self.assertIn('value="Otro borrador"', response.text)
        self.assertIn('value="Topstep"', response.text)
        self.assertIn('value="funded" selected', response.text)
        self.assertEqual(len(self.service.list_accounts()), 2)

    def test_list_failure_during_validation_does_not_claim_empty_accounts(self):
        with patch.object(TradeService, 'list_accounts', side_effect=PersistenceError('private detail')):
            response = self.post(name='', account_type='personal')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('No hay cuentas registradas', response.text)
        self.assertNotIn('private detail', response.text)

    def test_archive_reactivate_selection_and_history(self):
        account = self.service.create_account('A', 'personal')
        trade = self.service.create_trade(account, 'MNQ', 'long')
        self.assertEqual(self.post(f'/accounts/{account}/select').status_code, 303)
        with self.client.session_transaction() as session:
            self.assertEqual(session['selected_account_id'], account)
        self.assertEqual(self.post(f'/accounts/{account}/archive').status_code, 422)
        self.assertEqual(self.post(f'/accounts/{account}/archive', confirm='yes').status_code, 303)
        with self.client.session_transaction() as session:
            self.assertNotIn('selected_account_id', session)
        self.assertEqual(self.post(f'/accounts/{account}/select').status_code, 409)
        self.assertIn('Archivada', self.client.get('/accounts').text)
        self.assertEqual(self.service.get_trade(trade)['account_id'], account)
        response = self.client.post(f'/accounts/{account}/reactivate', data={
            'csrf_token':self.csrf, 'request_id':'reactivate-key-123456'})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(self.service.get_account(account)['is_active'])

    def test_selection_invalidated_after_external_archive(self):
        account = self.service.create_account('A','funded')
        self.post(f'/accounts/{account}/select')
        self.service.set_account_active(account, False)
        self.client.get('/accounts')
        with self.client.session_transaction() as session:
            self.assertNotIn('selected_account_id', session)

    def test_validation_escape_and_not_found(self):
        for name, kind in [('', 'personal'), ('x','other'), ('x'*201,'personal')]:
            self.assertEqual(self.post(name=name, account_type=kind).status_code, 422)
        self.service.create_account('<script>alert(1)</script>', 'personal')
        html = self.client.get('/accounts').text
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>alert', html)
        self.assertEqual(self.post('/accounts/999/select').status_code, 404)
        result = self.post(name='Conservar', account_type='wrong', platform='P')
        self.assertIn('value="Conservar"', result.text)

    def test_missing_database_secret_and_safe_errors(self):
        missing = self.path.parent / 'absent.sqlite3'
        app.config['DATABASE'] = str(missing)
        response = self.client.get('/accounts')
        self.assertEqual(response.status_code, 503)
        self.assertIn('database init', response.text)
        self.assertFalse(missing.exists())
        app.config['DATABASE'] = str(self.path)
        with patch.object(TradeService, 'list_accounts', side_effect=PersistenceError('secret sqlite detail')):
            response = self.client.get('/accounts')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret sqlite detail', response.text)
        app.config['SECRET_KEY'] = None
        self.assertEqual(self.client.get('/accounts').status_code, 503)
        self.assertEqual(self.client.get('/calculator').status_code, 200)

    def test_cookie_configuration(self):
        app.config['SESSION_COOKIE_SECURE'] = True
        response = app.test_client().get('/accounts')
        cookie = response.headers['Set-Cookie']
        for flag in ('HttpOnly', 'SameSite=Lax', 'Secure'):
            self.assertIn(flag, cookie)

    def test_v1_is_not_automatically_migrated(self):
        import sqlite3
        old = self.path.parent / 'legacy.sqlite3'
        connection = sqlite3.connect(old)
        try:
            connection.executescript((Path(__file__).parent/'fixtures/schema_v1.sql').read_text())
        finally:
            connection.close()
        app.config['DATABASE'] = str(old)
        response = self.client.get('/accounts')
        self.assertEqual(response.status_code, 503)
        self.assertIn('database migrate', response.text)
        connection = sqlite3.connect(old)
        try:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
        finally:
            connection.close()
        self.assertEqual(list(self.path.parent.glob('*.bak')), [])
