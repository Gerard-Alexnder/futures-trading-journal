import json
import unittest
import tempfile
from pathlib import Path
from database import initialize
from decimal import Decimal

from app import app
from test_calculations import inputs


class RouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'routes.sqlite3'
        initialize(path)
        old = dict(app.config)
        self.addCleanup(lambda: app.config.update(old))
        app.config.update(TESTING=True, SECRET_KEY='test-only-session-key', DATABASE=str(path))
        self.client = app.test_client()

    def test_existing_pages_and_assets(self):
        for path in ['/', '/journal', '/calendar', '/calculator', '/accounts', '/settings']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertEqual(html.count('aria-current="page"'), 1)
            self.assertIn(f'href="{path}" class="activo"', html)
        for path, mime in [('/static/style.css', 'text/css'), ('/static/calculator.js', 'text/javascript')]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(response.mimetype, [mime, 'application/javascript'])
            response.close()
        html = self.client.get('/calculator').get_data(as_text=True)
        self.assertIn('action="/api/calculate-risk"', html)
        self.assertNotIn(' checked', html)

    def test_json_result_and_exact_decimal_strings(self):
        response = self.client.post('/api/calculate-risk', json=inputs(include_slippage=True, slippage_ticks='2'))
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['ok'])
        result = data['result']
        self.assertEqual(result['contracts'], 2)
        self.assertIsInstance(result['total_risk'], str)
        self.assertEqual(Decimal(result['total_risk']), Decimal('87'))
        self.assertEqual(Decimal(result['remaining_budget']), Decimal('13'))

    def test_zero_contracts_is_success_with_warning(self):
        response = self.client.post('/api/calculate-risk', json=inputs(risk_budget='1'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['result']['contracts'], 0)
        self.assertTrue(response.json['result']['warning'])

    def test_structured_validation_errors(self):
        for data in [{}, [], None, inputs(commission='NaN'), inputs(stop_points='0.1'), inputs(include_slippage=True, slippage_ticks='0.5')]:
            response = self.client.post('/api/calculate-risk', data=json.dumps(data), content_type='application/json')
            self.assertEqual(response.status_code, 400)
            self.assertFalse(response.json['ok'])
            self.assertTrue(response.json['errors'])
            self.assertNotIn('Traceback', response.get_data(as_text=True))

    def test_disabled_slippage_at_api(self):
        response = self.client.post('/api/calculate-risk', json=inputs(slippage_ticks='invalid'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.json['result']['slippage_usd']), 0)

    def test_bad_json_media_type_and_size(self):
        response = self.client.post('/api/calculate-risk', data='{', content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/calculate-risk', data='hello')
        self.assertEqual(response.status_code, 415)
        response = self.client.post('/api/calculate-risk', json={'padding': 'x' * 4096})
        self.assertEqual(response.status_code, 413)
        self.assertTrue(response.json['errors'])
