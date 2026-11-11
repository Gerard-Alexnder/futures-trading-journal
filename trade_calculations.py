"""Motor puro: reproduce una historia completa sin acceso a persistencia."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN

from contracts import CONTRACTS

PRECISION = 50
MAX_VALUE = 1_000_000_000
MICROUSD = 1_000_000


class TradeValidationError(ValueError):
    """Datos o historia operativa inválidos."""


def integer(value, field, minimum=1):
    if type(value) is not int or not minimum <= value <= MAX_VALUE:
        raise TradeValidationError(f'{field}: entero entre {minimum} y {MAX_VALUE}.')
    return value


def decimal_value(value, field, positive=False):
    if not isinstance(value, (str, Decimal, int)) or isinstance(value, bool):
        raise TradeValidationError(f'{field}: utiliza texto decimal, Decimal o entero.')
    if isinstance(value, str) and len(value) > 64:
        raise TradeValidationError(f'{field}: máximo 64 caracteres.')
    try:
        number = Decimal(value)
    except (ValueError, ArithmeticError):
        raise TradeValidationError(f'{field}: decimal inválido.') from None
    if not number.is_finite() or number < 0 or number > MAX_VALUE or (positive and number == 0):
        raise TradeValidationError(f'{field}: valor fuera de rango.')
    if len(number.as_tuple().digits) > 32:
        raise TradeValidationError(f'{field}: máximo 32 dígitos significativos.')
    return number


def money_units(value, field):
    number = decimal_value(value, field)
    if number.as_tuple().exponent < -6:
        raise TradeValidationError(f'{field}: máximo seis decimales, sin redondeo.')
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return int(number * MICROUSD)


def price_units(value, symbol):
    if symbol not in CONTRACTS:
        raise TradeValidationError('Símbolo no admitido.')
    number = decimal_value(value, 'price', positive=True)
    if number.as_tuple().exponent < -6:
        raise TradeValidationError('price: máximo seis decimales.')
    with localcontext() as ctx:
        ctx.prec = PRECISION
        ticks = number / CONTRACTS[symbol]['tick_size']
        if ticks != ticks.to_integral_value():
            raise TradeValidationError('price: debe respetar el tick del contrato.')
        return int(ticks)


def calculate_trade(symbol, direction, executions):
    """Orden (executed_at, sequence); Decimal de 50 dígitos, sin cuantización.

    Al cierre se reconcilia el bruto con los flujos exactos de toda la operación.
    Las correcciones futuras deben llamar a esta misma reproducción completa.
    """
    if symbol not in CONTRACTS or direction not in ('long', 'short'):
        raise TradeValidationError('Símbolo o dirección inválidos.')
    rows = sorted(executions, key=lambda row: (row['executed_at'], row['sequence']))
    with localcontext() as ctx:
        ctx.prec = PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        quantity = 0
        basis = gross = commission = fees = cash = Decimal(0)
        average = None
        closed = False
        sequences = set()
        realized = []
        sign = Decimal(1 if direction == 'long' else -1)
        contract = CONTRACTS[symbol]
        for row in rows:
            sequence = integer(row['sequence'], 'sequence')
            if sequence in sequences:
                raise TradeValidationError('Secuencia duplicada.')
            sequences.add(sequence)
            if closed:
                raise TradeValidationError('No se permiten ejecuciones después del cierre.')
            q = integer(row['quantity'], 'quantity')
            ticks = row['price_ticks']
            if type(ticks) is not int or ticks <= 0:
                raise TradeValidationError('Ticks inválidos.')
            price = Decimal(ticks) * contract['tick_size']
            if price > MAX_VALUE:
                raise TradeValidationError('Precio fuera de rango.')
            for field in ('commission_microusd', 'fees_microusd'):
                if type(row[field]) is not int or not 0 <= row[field] <= MAX_VALUE * MICROUSD:
                    raise TradeValidationError('Costos inválidos.')
            commission += Decimal(row['commission_microusd']) / MICROUSD
            fees += Decimal(row['fees_microusd']) / MICROUSD
            notional = price * q * contract['point_value']
            delta = Decimal(0)
            if row['execution_type'] == 'entry':
                if quantity + q > MAX_VALUE:
                    raise TradeValidationError('Posición fuera de rango.')
                basis += price * q
                quantity += q
                average = basis / quantity
                cash -= sign * notional
            elif row['execution_type'] == 'exit':
                if q > quantity:
                    raise TradeValidationError('La salida supera la posición abierta.')
                cash += sign * notional
                if q == quantity:
                    # Evita arrastrar residuos de divisiones periódicas al resultado final.
                    delta = cash - gross
                    gross = cash
                    basis = Decimal(0)
                    quantity = 0
                    average = None
                    closed = True
                else:
                    delta = sign * (price - average) * contract['point_value'] * q
                    gross += delta
                    basis -= average * q
                    quantity -= q
            else:
                raise TradeValidationError('Tipo de ejecución inválido.')
            realized.append({'sequence': sequence, 'gross_pnl': delta})
        return {
            'status': 'closed' if closed else ('open' if rows else 'pending'),
            'open_quantity': quantity, 'average_price': average,
            'gross_pnl': gross, 'commission': commission, 'fees': fees,
            'net_pnl': gross - commission - fees,
            'opened_at': rows[0]['executed_at'] if rows else None,
            'closed_at': rows[-1]['executed_at'] if closed else None,
            'realized_by_execution': realized,
        }
