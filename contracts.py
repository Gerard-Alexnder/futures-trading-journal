"""Catálogo de contratos: importes en USD y distancias en puntos."""
from decimal import Decimal

CONTRACTS = {
    "ES": {"point_value": Decimal("50"), "tick_size": Decimal("0.25"), "tick_value": Decimal("12.50")},
    "MES": {"point_value": Decimal("5"), "tick_size": Decimal("0.25"), "tick_value": Decimal("1.25")},
    "NQ": {"point_value": Decimal("20"), "tick_size": Decimal("0.25"), "tick_value": Decimal("5")},
    "MNQ": {"point_value": Decimal("2"), "tick_size": Decimal("0.25"), "tick_value": Decimal("0.50")},
}
