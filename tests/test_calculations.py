import unittest
from decimal import Decimal

from calculations import ValidationError, calculate_risk
from contracts import CONTRACTS


def inputs(**changes):
    data = dict(instrument="MNQ", risk_budget="100", stop_points="20", commission="2.50", include_slippage=False, slippage_ticks="0")
    data.update(changes)
    return data


class CalculationTests(unittest.TestCase):
    def test_required_examples(self):
        cases = [("MNQ", "100", "20", "2.50", 2), ("NQ", "200", "10", "5.00", 0), ("MES", "150", "10", "2.50", 2), ("ES", "500", "5", "5.00", 1), ("MNQ", "200", "25", "2.50", 3)]
        for symbol, budget, stop, commission, count in cases:
            with self.subTest(symbol=symbol, budget=budget):
                result = calculate_risk(inputs(instrument=symbol, risk_budget=budget, stop_points=stop, commission=commission))
                self.assertEqual(result['contracts'], count)
                self.assertLessEqual(result['total_risk'], Decimal(budget))
        result = calculate_risk(inputs(include_slippage=True, slippage_ticks="2"))
        self.assertEqual(result['contracts'], 2)
        for key, expected in [('risk_per_contract', '43.50'), ('total_risk', '87.00'), ('remaining_budget', '13.00')]:
            self.assertEqual(result[key], Decimal(expected))

    def test_budget_invariant_and_slippage_monotonicity(self):
        for symbol in CONTRACTS:
            for budget in ['0.000001', '1', '42.499999', '42.5', '100', '1000', '1000000000']:
                for stop in ['0.25', '20', '1000000000']:
                    baseline = calculate_risk(inputs(instrument=symbol, risk_budget=budget, stop_points=stop))
                    for ticks in ['0', '1', '2', '1000000000']:
                        result = calculate_risk(inputs(instrument=symbol, risk_budget=budget, stop_points=stop, include_slippage=True, slippage_ticks=ticks))
                        with self.subTest(symbol=symbol, budget=budget, stop=stop, ticks=ticks):
                            self.assertLessEqual(result['contracts'], baseline['contracts'])
                            self.assertGreaterEqual(result['remaining_budget'], 0)
                            self.assertLessEqual(result['total_risk'], Decimal(budget))
                            self.assertGreater(result['total_risk'] + result['risk_per_contract'], Decimal(budget))

    def test_budget_boundaries(self):
        for budget, count in [('42.499999', 0), ('42.50', 1), ('85', 2)]:
            result = calculate_risk(inputs(risk_budget=budget))
            self.assertEqual(result['contracts'], count)
            self.assertEqual(bool(result['warning']), count == 0)

    def test_no_premature_rounding(self):
        result = calculate_risk(inputs(stop_points='0.25', commission='0.000001', risk_budget='1'))
        self.assertEqual(result['risk_per_contract'], Decimal('0.500001'))
        self.assertEqual(result['contracts'], 1)
        self.assertEqual(result['remaining_budget'], Decimal('0.499999'))

    def test_disabled_slippage_ignores_every_residual(self):
        for residual in ['999', '-1', 'NaN', '1.5', None, [], {}]:
            result = calculate_risk(inputs(slippage_ticks=residual))
            self.assertEqual(result['slippage_usd'], Decimal(0))
            self.assertEqual(result['contracts'], 2)

    def test_invalid_numeric_fields(self):
        for field in ['risk_budget', 'stop_points', 'commission']:
            for invalid in ['', '-1', 'abc', 'NaN', 'Infinity', '-Infinity', '1e3', '0.0000001', '1000000001', '1' * 33, None, True, [], {}, 100]:
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ValidationError) as caught:
                        calculate_risk(inputs(**{field: invalid}))
                    self.assertIn(field, caught.exception.errors)
        for field in ['risk_budget', 'stop_points']:
            with self.assertRaises(ValidationError):
                calculate_risk(inputs(**{field: '0'}))

    def test_invalid_tick_instrument_and_checkbox(self):
        for changes in [dict(stop_points='0.1'), dict(instrument='UNKNOWN'), dict(instrument=[]), dict(include_slippage='false'), dict(include_slippage=1)]:
            with self.assertRaises(ValidationError):
                calculate_risk(inputs(**changes))
        for ticks in ['-1', '1.5', '', 'NaN', 'Infinity', None]:
            with self.assertRaises(ValidationError):
                calculate_risk(inputs(include_slippage=True, slippage_ticks=ticks))

    def test_missing_fields_and_invalid_object(self):
        for field in ['instrument', 'risk_budget', 'stop_points', 'commission']:
            data = inputs()
            del data[field]
            with self.assertRaises(ValidationError):
                calculate_risk(data)
        for value in [None, [], 'text', 42]:
            with self.assertRaises(ValidationError):
                calculate_risk(value)

    def test_server_catalog_cannot_be_overridden(self):
        result = calculate_risk(inputs(point_value='0.01', tick_value='0'))
        self.assertEqual(result['point_value'], Decimal('2'))
        self.assertEqual(result['tick_value'], Decimal('0.50'))
