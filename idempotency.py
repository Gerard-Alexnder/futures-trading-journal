"""Solicitudes confirmadas en la misma transacción que su efecto de negocio."""
import hashlib
import json
import re
from datetime import datetime, timezone

from trade_calculations import TradeValidationError


class ConflictError(TradeValidationError):
    pass


def execute_once(connection, request_key, action, payload, operation):
    """payload ya normalizado; operation devuelve solo IDs/estados no sensibles.

    El llamador debe abrir BEGIN IMMEDIATE y propagar los fallos para rollback.
    No guarda el payload, solo su hash. No utilizar floats/secretos en el payload.
    """
    if not connection.in_transaction:
        raise RuntimeError('La idempotencia requiere una transacción de negocio.')
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_key):
        raise TradeValidationError('Clave de solicitud inválida.')
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    previous = connection.execute('SELECT action,payload_hash,result_json FROM write_requests WHERE request_key=?', (request_key,)).fetchone()
    if previous is not None:
        if previous['action'] != action or previous['payload_hash'] != fingerprint:
            raise ConflictError('La clave ya se utilizó para otra solicitud. Recarga el formulario.')
        return json.loads(previous['result_json'])
    result = operation()
    serialized = json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False)
    connection.execute('INSERT INTO write_requests VALUES(?,?,?,?,?)',
                       (request_key, action, fingerprint, serialized,
                        datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')))
    return result
