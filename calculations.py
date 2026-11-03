"""Validación y cálculos puros, sin depender de Flask ni de la interfaz."""
import re
from decimal import Decimal, localcontext

from contracts import CONTRACTS

MAX_VALUE = Decimal("1000000000")
# Hasta seis decimales, sin notación científica; precisión acotada y previsible.
DECIMAL_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]{1,6})?\Z")


class ValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Revisa los datos del formulario.")


def validate_inputs(data):
    """Devuelve valores Decimal validados o errores asociados a cada campo."""
    if not isinstance(data, dict):
        raise ValidationError({"form": "Envía un objeto JSON."})
    errors = {}
    symbol = data.get("instrument")
    if not isinstance(symbol, str) or symbol not in CONTRACTS:
        errors["instrument"] = "Selecciona ES, MES, NQ o MNQ."
    enabled = data.get("include_slippage", False)
    if not isinstance(enabled, bool):
        errors["include_slippage"] = "El indicador de slippage debe ser booleano."

    def number(field, positive=False):
        raw = data.get(field)
        if not isinstance(raw, str) or len(raw) > 32:
            errors[field] = "Introduce un número decimal como texto."
            return None
        raw = raw.strip()
        if not DECIMAL_PATTERN.fullmatch(raw):
            errors[field] = "Usa un número no negativo con punto decimal y hasta 6 decimales."
            return None
        value = Decimal(raw)
        if not value.is_finite() or value > MAX_VALUE or (positive and value <= 0):
            errors[field] = "Debe ser mayor que cero y hasta 1000000000." if positive else "Debe estar entre 0 y 1000000000."
            return None
        return value

    budget = number("risk_budget", positive=True)
    stop = number("stop_points", positive=True)
    commission = number("commission")
    ticks = number("slippage_ticks") if enabled is True else Decimal("0")
    if enabled is True and ticks is not None and ticks != ticks.to_integral_value():
        errors["slippage_ticks"] = "El slippage debe ser un número entero de ticks."
    if stop is not None and "instrument" not in errors:
        if stop % CONTRACTS[symbol]["tick_size"] != 0:
            errors["stop_points"] = "El stop debe ser múltiplo de 0.25 puntos."
    if errors:
        raise ValidationError(errors)
    return symbol, budget, stop, commission, ticks


def calculate_risk(data):
    """Calcula el máximo entero de contratos sin redondear importes."""
    symbol, budget, stop, commission, ticks = validate_inputs(data)
    contract = CONTRACTS[symbol]
    # Los límites de entrada mantienen todos los productos exactos con 50 dígitos.
    with localcontext() as context:
        context.prec = 50
        market_risk = stop * contract["point_value"]
        slippage = ticks * contract["tick_value"]
        per_contract = market_risk + commission + slippage
        count = int(budget // per_contract)
        total = count * per_contract
        return {
            "instrument": symbol,
            "contracts": count,
            "point_value": contract["point_value"],
            "tick_size": contract["tick_size"],
            "tick_value": contract["tick_value"],
            "market_risk": market_risk,
            "commission": commission,
            "slippage_usd": slippage,
            "risk_per_contract": per_contract,
            "total_risk": total,
            "remaining_budget": budget - total,
            "warning": "Presupuesto insuficiente para operar un contrato." if count == 0 else None,
        }
