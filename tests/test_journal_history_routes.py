import unittest
from app import app
import test_journal_history
from test_trade_service import fill

class JournalHistoryRouteTests(unittest.TestCase):
    def setUp(self):
        fixture=test_journal_history.JournalHistoryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture
        previous=dict(app.config);self.addCleanup(lambda:app.config.update(previous))
        app.config.update(TESTING=True,SECRET_KEY='test-only',DATABASE=str(fixture.path))
        self.client=app.test_client()

    def test_history_escape_links_and_session_does_not_filter(self):
        f=self.fixture; trade=f.trade([fill()]);f.trade(account=f.other)
        f.service.set_account_active(f.account,False)
        with self.client.session_transaction() as session:session['selected_account_id']=f.other
        response=self.client.get('/journal')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.text.count('data-trade-id='),2)
        self.assertIn('Same &lt;name&gt;',response.text);self.assertIn('&lt;plan&gt;',response.text)
        self.assertIn('Archivada',response.text);self.assertIn(f'href="/journal/{trade}"',response.text)
        self.assertIn('href="/journal/new"',response.text)
        self.assertEqual(response.text.count('aria-current="page"'),1)

    def test_errors_preserve_values_without_false_statistics(self):
        for query in ['symbol=bad&date_from=2026-02-30','page=2&page=3','unknown=x','utc_offset=%2B14%3A30','account_id=999']:
            response=self.client.get('/journal?'+query)
            self.assertEqual(response.status_code,400)
            self.assertNotIn('id="history-statistics"',response.text)
        self.assertIn('value="2026-02-30"',self.client.get('/journal?date_from=2026-02-30').text)
        app.config['DATABASE']=str(self.fixture.path.parent/'missing.sqlite3')
        self.assertEqual(self.client.get('/journal').status_code,503)

    def test_pagination_filters_and_empty_states(self):
        self.assertIn('No hay operaciones registradas',self.client.get('/journal').text)
        self.assertIn('coincidan con estos filtros',self.client.get('/journal?symbol=ES').text)
        for _ in range(26):self.fixture.trade([fill()])
        response=self.client.get('/journal?symbol=MNQ&utc_offset=%2B05%3A30&page_size=25')
        self.assertEqual(response.text.count('data-trade-id='),25)
        self.assertIn('page=2',response.text);self.assertIn('symbol=MNQ',response.text)
        self.assertIn('utc_offset=%2B05:30',response.text)
        self.assertNotIn('name="page"',response.text)
        self.assertIn('fuera de rango',self.client.get('/journal?page=99').text)
