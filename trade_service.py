"""API de negocio sin Flask; una conexión independiente por llamada."""
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3

from contracts import CONTRACTS
from idempotency import ConflictError, execute_once
from database import DEFAULT_PATH, connect, transaction, SCHEMA_VERSION, DatabaseError
from trade_calculations import (
    TradeValidationError, calculate_trade, integer, money_units, price_units,
)


class NotFoundError(TradeValidationError):
    pass


class ArchivedAccountError(TradeValidationError):
    pass


class PersistenceError(RuntimeError):
    pass


def timestamp(value=None):
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise TradeValidationError('Timestamp inválido.') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TradeValidationError('La fecha debe incluir zona horaria.')
    try:
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (OverflowError, ValueError):
        raise TradeValidationError('Timestamp fuera de rango.') from None


def text_field(value, name, optional=False, limit=200):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise TradeValidationError(f'{name}: texto no vacío de hasta {limit} caracteres.')
    return value.strip()


class TradeService:
    def __init__(self, path=DEFAULT_PATH):
        self.path = path

    @contextmanager
    def _connection(self, write=False):
        connection = None
        try:
            connection = connect(self.path)
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise DatabaseError('Base incompatible. Para v1 ejecuta uv run --no-sync python -m database migrate; para versiones futuras utiliza una aplicación compatible.')
            if write:
                with transaction(connection):
                    yield connection
            else:
                yield connection
        except sqlite3.IntegrityError as error:
            raise ConflictError('Conflicto de unicidad o integridad de datos.') from error
        except sqlite3.Error as error:
            raise PersistenceError('No se pudo completar la operación SQLite.') from error
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _account(connection, account_id, writable=False):
        integer(account_id, 'account_id')
        row = connection.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        if row is None:
            raise NotFoundError('Cuenta inexistente.')
        if writable and not row['is_active']:
            raise ArchivedAccountError('Reactiva la cuenta antes de modificarla.')
        return dict(row)

    @staticmethod
    def _trade(connection, trade_id):
        integer(trade_id, 'trade_id')
        row = connection.execute('SELECT * FROM trades WHERE id=?', (trade_id,)).fetchone()
        if row is None:
            raise NotFoundError('Operación inexistente.')
        return dict(row)

    @staticmethod
    def _executions(connection, trade_id):
        return [dict(row) for row in connection.execute(
            'SELECT * FROM executions WHERE trade_id=? ORDER BY executed_at, sequence', (trade_id,))]

    @staticmethod
    def _revalidate(trade, candidate_history):
        # Punto común para futuras correcciones atómicas, incluso de trades cerrados.
        # La restricción de añadir a un trade cerrado pertenece al comando de alta.
        return calculate_trade(trade['symbol'], trade['direction'], candidate_history)

    def create_account(self, name, account_type, platform=None, *, request_id=None):
        name = text_field(name, 'name')
        platform = text_field(platform, 'platform', optional=True)
        if account_type not in ('funded', 'personal'):
            raise TradeValidationError('Tipo de cuenta inválido.')
        with self._connection(write=True) as connection:
            def create():
                return connection.execute(
                    'INSERT INTO accounts(name,account_type,platform,created_at) VALUES(?,?,?,?)',
                    (name, account_type, platform, timestamp())).lastrowid
            if request_id is None:
                return create()
            return execute_once(connection, request_id, 'create_account',
                                dict(name=name, account_type=account_type, platform=platform), create)

    def get_account(self, account_id, *, require_active=False):
        with self._connection() as connection:
            return self._account(connection, account_id, writable=require_active)

    def list_accounts(self):
        with self._connection() as connection:
            return [dict(row) for row in connection.execute('SELECT * FROM accounts ORDER BY id')]

    def set_account_active(self, account_id, active, *, request_id=None):
        if type(active) is not bool:
            raise TradeValidationError('active debe ser booleano.')
        with self._connection(write=True) as connection:
            self._account(connection, account_id)
            def change():
                connection.execute('UPDATE accounts SET is_active=? WHERE id=?', (int(active), account_id))
                return {'account_id': account_id, 'active': active}
            if request_id is None:
                change()
            else:
                execute_once(connection, request_id, 'set_account_active',
                             dict(account_id=account_id, active=active), change)

    def create_trade(self, account_id, symbol, direction, strategy=None, notes=None):
        with self._connection(write=True) as connection:
            return self._create_trade(connection, account_id, symbol, direction, strategy, notes)

    def _create_trade(self, connection, account_id, symbol, direction, strategy=None, notes=None):
        self._account(connection, account_id, writable=True)
        if not isinstance(symbol, str) or symbol not in CONTRACTS or direction not in ('long', 'short'):
            raise TradeValidationError('Símbolo o dirección inválidos.')
        strategy = text_field(strategy, 'strategy', optional=True)
        notes = text_field(notes, 'notes', optional=True, limit=10000)
        return connection.execute(
            'INSERT INTO trades(account_id,symbol,direction,strategy,notes,created_at) VALUES(?,?,?,?,?,?)',
            (account_id, symbol, direction, strategy, notes, timestamp())).lastrowid

    def update_trade_metadata(self, trade_id, strategy=None, notes=None):
        strategy = text_field(strategy, 'strategy', optional=True)
        notes = text_field(notes, 'notes', optional=True, limit=10000)
        with self._connection(write=True) as connection:
            trade = self._trade(connection, trade_id)
            self._account(connection, trade['account_id'], writable=True)
            connection.execute('UPDATE trades SET strategy=?, notes=? WHERE id=?', (strategy, notes, trade_id))

    def get_trade(self, trade_id):
        with self._connection() as connection:
            trade = self._trade(connection, trade_id)
            executions = self._executions(connection, trade_id)
            return {**trade, 'executions': executions, 'summary': self._revalidate(trade, executions)}

    def list_trades(self, account_id):
        with self._connection() as connection:
            self._account(connection, account_id)
            return [dict(row) for row in connection.execute(
                'SELECT * FROM trades WHERE account_id=? ORDER BY created_at,id', (account_id,))]

    def add_execution(self, trade_id, **execution):
        return self.add_executions(trade_id, [execution])[0]

    def add_executions(self, trade_id, executions):
        with self._connection(write=True) as connection:
            return self._add_executions(connection, trade_id, executions)

    def _add_executions(self, connection, trade_id, executions):
        trade = self._trade(connection, trade_id)
        self._account(connection, trade['account_id'], writable=True)
        history = self._executions(connection, trade_id)
        if self._revalidate(trade, history)['status'] == 'closed':
            raise ConflictError('No se pueden añadir ejecuciones a una operación cerrada.')
        if not isinstance(executions, (list, tuple)) or not executions:
            raise TradeValidationError('Se requiere un lote no vacío de ejecuciones.')
        sequence = max((row['sequence'] for row in history), default=0)
        candidates = []
        allowed = {'executed_at', 'execution_type', 'quantity', 'price', 'commission', 'fees',
                   'source', 'external_execution_id', 'external_namespace'}
        for raw in executions:
            if not isinstance(raw, dict) or set(raw) - allowed:
                raise TradeValidationError('Campos de ejecución desconocidos.')
            if not {'executed_at', 'execution_type', 'quantity', 'price'} <= raw.keys():
                raise TradeValidationError('Faltan campos obligatorios de ejecución.')
            sequence += 1
            integer(sequence, 'sequence')
            source = raw.get('source', 'manual')
            if source not in ('manual', 'imported'):
                raise TradeValidationError('Origen inválido.')
            external_id = text_field(raw.get('external_execution_id'), 'external_execution_id', optional=True)
            namespace = text_field(raw.get('external_namespace'), 'external_namespace', optional=True)
            if (external_id is None) != (namespace is None):
                raise TradeValidationError('El ID externo requiere namespace y viceversa.')
            if raw['executed_at'] is None:
                raise TradeValidationError('La fecha de ejecución es obligatoria.')
            candidates.append(dict(
                trade_id=trade_id, account_id=trade['account_id'],
                executed_at=timestamp(raw['executed_at']), sequence=sequence,
                execution_type=raw['execution_type'], quantity=integer(raw['quantity'], 'quantity'),
                price_ticks=price_units(raw['price'], trade['symbol']),
                commission_microusd=money_units(raw.get('commission', '0'), 'commission'),
                fees_microusd=money_units(raw.get('fees', '0'), 'fees'), source=source,
                external_execution_id=external_id, external_namespace=namespace, created_at=timestamp(),
            ))
        self._revalidate(trade, history + candidates)
        ids = []
        for row in candidates:
            fields = ','.join(row)
            placeholders = ','.join('?' for _ in row)
            ids.append(connection.execute(
                f'INSERT INTO executions({fields}) VALUES({placeholders})', tuple(row.values())).lastrowid)
        return ids

    def record_reversal(self, trade_id, closing_execution, opening_execution):
        """Registra dos partes explícitas; no reconstruye ni reparte órdenes importadas."""
        with self._connection(write=True) as connection:
            original = self._trade(connection, trade_id)
            if closing_execution.get('execution_type') != 'exit' or opening_execution.get('execution_type') != 'entry':
                raise TradeValidationError('La reversión requiere cierre y nueva entrada explícitos.')
            if timestamp(closing_execution.get('executed_at')) != timestamp(opening_execution.get('executed_at')):
                raise TradeValidationError('Las partes deben compartir fecha de ejecución.')
            self._add_executions(connection, trade_id, [closing_execution])
            summary = self._revalidate(original, self._executions(connection, trade_id))
            if summary['status'] != 'closed':
                raise TradeValidationError('La reversión debe cerrar completamente la posición original.')
            new_id = self._create_trade(connection, original['account_id'], original['symbol'],
                                        'short' if original['direction'] == 'long' else 'long')
            self._add_executions(connection, new_id, [opening_execution])
            return new_id
