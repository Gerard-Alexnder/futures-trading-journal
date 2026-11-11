"""Tokens de preview HMAC-SHA256, sin persistencia ni dependencia de Flask."""
import base64
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal

from database import DatabaseError
from idempotency import ConflictError


class PreviewTokenError(ConflictError):
    pass


def canonical(value):
    def decimal(item):
        if isinstance(item, Decimal):
            return format(item, 'f')
        raise TypeError('Solo datos canónicos admitidos.')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False, default=decimal)


def _key(secret):
    if not isinstance(secret, (str, bytes)) or not secret:
        raise DatabaseError('Configura SECRET_KEY para confirmar correcciones.')
    raw = secret.encode() if isinstance(secret, str) else secret
    return hmac.digest(raw, b'journal-execution-preview-v1', 'sha256')


def _digest(binding):
    return hashlib.sha256(canonical(binding).encode()).hexdigest()


def issue(secret, binding):
    now = int(time.time())
    payload = dict(version=1, issued_at=now, expires_at=now+600, binding=_digest(binding))
    encoded = base64.urlsafe_b64encode(canonical(payload).encode()).decode().rstrip('=')
    signature = hmac.new(_key(secret), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded+'.'+signature


def validate(secret, token):
    key = _key(secret)
    if not isinstance(token, str) or len(token)>2048 or not re.fullmatch(r'[A-Za-z0-9_-]+\.[a-f0-9]{64}', token):
        raise PreviewTokenError('Preview inválido. Genera una nueva previsualización.')
    encoded, signature = token.split('.')
    expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise PreviewTokenError('Firma de preview inválida.')
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        now = int(time.time())
        if (payload['version'] != 1 or type(payload['expires_at']) is not int
                or type(payload['issued_at']) is not int or not payload['issued_at'] <= now < payload['expires_at']
                or payload['expires_at']-payload['issued_at'] != 600
                or not isinstance(payload['binding'], str)):
            raise ValueError()
    except (ValueError, KeyError, TypeError) as error:
        raise PreviewTokenError('Preview caducado o inválido. Previsualiza nuevamente.') from error
    return payload


def verify_binding(payload, binding):
    if not hmac.compare_digest(payload['binding'], _digest(binding)):
        raise PreviewTokenError('Los datos o la proyección cambiaron. Previsualiza nuevamente.')
