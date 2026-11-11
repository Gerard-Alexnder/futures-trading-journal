import unittest
from decimal import Decimal, localcontext
from fractions import Fraction

from trade_calculations import calculate_trade, price_units, money_units, TradeValidationError


def execution(kind, quantity, price, sequence, symbol='MNQ', **extra):
    return dict(execution_type=kind, quantity=quantity,
                price_ticks=price_units(price, symbol), sequence=sequence,
                executed_at=f'2026-01-01T00:00:{sequence:02}.000000Z',
                commission_microusd=0, fees_microusd=0, **extra)


class TradeCalculationTests(unittest.TestCase):
    def test_required_examples(self):
        cases = [
            ('MNQ', 'long', [('entry', 1, '20000'), ('exit', 1, '20050')], '100', 0, None),
            ('MES', 'short', [('entry', 1, '6000'), ('exit', 1, '5990')], '50', 0, None),
            ('MNQ', 'long', [('entry', 3, '20000'), ('exit', 1, '20020'), ('exit', 1, '20040'), ('exit', 1, '20060')], '240', 0, None),
            ('MNQ', 'long', [('entry', 1, '20000'), ('entry', 2, '20030'), ('exit', 1, '20050')], '60', 2, '20020'),
            ('MNQ', 'long', [('entry', 1, '20000'), ('entry', 2, '20030'), ('exit', 1, '20050'), ('entry', 1, '19990')], '60', 3, '20010'),
            ('MNQ', 'long', [('entry', 1, '20000'), ('entry', 2, '20030'), ('exit', 1, '20050'), ('entry', 1, '19990'), ('exit', 3, '20020')], '120', 0, None),
        ]
        for symbol, direction, movements, gross, count, average in cases:
            with self.subTest(movements=movements):
                result = calculate_trade(symbol, direction, [execution(*m, i, symbol) for i, m in enumerate(movements, 1)])
                self.assertEqual(result['gross_pnl'], Decimal(gross))
                self.assertEqual(result['open_quantity'], count)
                self.assertEqual(result['average_price'], Decimal(average) if average else None)

    def test_periodic_average_and_conservation(self):
        for direction in ('long', 'short'):
            rows = [execution('entry', 1, '20000.25', 1), execution('entry', 2, '20000', 2)]
            with localcontext() as ctx:
                ctx.prec = 60
                expected = Decimal('60000.25') / 3
                average = calculate_trade('MNQ', direction, rows)['average_price']
                self.assertLess(abs(average - expected), Decimal('1e-44'))
            rows += [execution('exit', 1, '20001', i) for i in (3, 4, 5)]
            result = calculate_trade('MNQ', direction, rows)
            expected_total = Decimal('5.50') * (1 if direction == 'long' else -1)
            self.assertEqual(result['gross_pnl'], expected_total)
            with localcontext() as ctx:
                ctx.prec = 50
                self.assertEqual(sum((r['gross_pnl'] for r in result['realized_by_execution']), Decimal(0)), expected_total)
            self.assertIsNone(result['average_price'])

    def test_costs_partial_and_pending(self):
        rows = [execution('entry', 3, '20000', 1), execution('exit', 1, '20020', 2)]
        rows[0]['commission_microusd'] = 3_000_000
        rows[1]['commission_microusd'] = 1_000_000
        rows[1]['fees_microusd'] = 500_000
        result = calculate_trade('MNQ', 'long', rows)
        self.assertEqual(result['net_pnl'], Decimal('35.50'))
        self.assertEqual(result['open_quantity'], 2)
        self.assertEqual(calculate_trade('MNQ', 'long', rows[:1])['net_pnl'], -3)
        self.assertEqual(calculate_trade('MNQ', 'long', [])['status'], 'pending')

    def test_periodic_partials_with_reentry_against_rational_oracle(self):
        movements = [('entry', 1, '20000.25'), ('entry', 6, '20000'),
                     ('exit', 2, '20001'), ('entry', 2, '19999.75'),
                     ('exit', 3, '20002'), ('exit', 4, '20003')]
        quantity, basis, gross = 0, Fraction(0), Fraction(0)
        rows = []
        for sequence, (kind, count, price) in enumerate(movements, 1):
            p = Fraction(price)
            if kind == 'entry':
                basis += count * p
                quantity += count
            else:
                average = basis / quantity
                gross += (p - average) * 2 * count
                basis -= average * count
                quantity -= count
            rows.append(execution(kind, count, price, sequence))
            actual = calculate_trade('MNQ', 'long', rows)
            with localcontext() as ctx:
                ctx.prec = 60
                expected = Decimal(gross.numerator) / Decimal(gross.denominator)
                self.assertLess(abs(actual['gross_pnl'] - expected), Decimal('1e-43'))
        self.assertEqual(actual['gross_pnl'], Decimal('40.50'))

    def test_exact_conversion_and_rejections(self):
        self.assertEqual(money_units('1.234567', 'commission'), 1234567)
        self.assertEqual(price_units('20000.25', 'MNQ'), 80001)
        for value in ['-1', 'NaN', 'Infinity', '0.0000001', '1.0000000', 1.5, True]:
            with self.subTest(value=value), self.assertRaises(TradeValidationError):
                money_units(value, 'commission')
        for value in ['0', '-1', '20000.1', 'NaN', 1.25, '20000.' + '0' * 50 + '1']:
            with self.assertRaises(TradeValidationError):
                price_units(value, 'MNQ')

    def test_invalid_histories(self):
        for rows in [
            [execution('exit', 1, '20000', 1)],
            [execution('entry', 1, '20000', 1), execution('exit', 2, '20000', 2)],
            [execution('entry', 1, '20000', 1), execution('exit', 1, '20000', 2), execution('entry', 1, '20000', 3)],
        ]:
            with self.assertRaises(TradeValidationError):
                calculate_trade('MNQ', 'long', rows)
