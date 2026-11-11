"""API de negocio sin Flask; una conexión independiente por llamada."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import sqlite3
import re

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


class DraftValidationError(TradeValidationError):
    """Errores estructurados: campos generales y filas identificadas por row_id."""
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Revisa los campos indicados y el orden de las ejecuciones.')


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
        return self._insert_executions(connection, candidates)

    @staticmethod
    def _insert_executions(connection, rows):
        ids = []
        for row in rows:
            fields = ','.join(row)
            placeholders = ','.join('?' for _ in row)
            ids.append(connection.execute(
                f'INSERT INTO executions({fields}) VALUES({placeholders})', tuple(row.values())).lastrowid)
        return ids

    @staticmethod
    def _normalize_draft(account_id, symbol, direction, executions, strategy, notes, mode):
        errors = {'fields': {}, 'rows': {}}

        def field(name, operation):
            try:
                return operation()
            except TradeValidationError as error:
                errors['fields'][name] = str(error)

        account_id = field('account_id', lambda: integer(account_id, 'account_id'))
        if not isinstance(symbol, str) or symbol not in CONTRACTS:
            errors['fields']['symbol'] = 'Selecciona ES, MES, NQ o MNQ.'
        if direction not in ('long', 'short'):
            errors['fields']['direction'] = 'Selecciona Long o Short.'
        if mode not in ('progressive', 'historical'):
            errors['fields']['mode'] = 'Modalidad inválida.'
        strategy = field('strategy', lambda: text_field(strategy, 'strategy', optional=True))
        notes = field('notes', lambda: text_field(notes, 'notes', optional=True, limit=10000))
        if not isinstance(executions, list) or not 1 <= len(executions) <= 200:
            errors['fields']['executions'] = 'Incluye entre 1 y 200 ejecuciones.'
        if errors['fields']:
            raise DraftValidationError(errors)
        if mode == 'progressive' and (len(executions) != 1 or not isinstance(executions[0], dict)
                                      or executions[0].get('execution_type') != 'entry'):
            raise DraftValidationError({'fields': {'mode': 'El registro progresivo requiere exactamente una entrada.'}, 'rows': {}})
        normalized = []
        identities = set()
        allowed = {'row_id', 'executed_at', 'execution_type', 'quantity', 'price', 'commission', 'fees'}
        for index, raw in enumerate(executions, 1):
            if not isinstance(raw, dict):
                errors['rows'][str(index)] = {'row_id': 'La fila debe ser un objeto.'}
                continue
            identity = raw.get('row_id')
            if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', identity)
                    or identity in identities):
                errors['fields']['executions'] = 'Cada fila necesita un row_id único de hasta 64 caracteres ASCII.'
                continue
            identities.add(identity)
            row_errors = {}
            if set(raw) - allowed:
                row_errors['row_id'] = 'La fila contiene campos no admitidos (no envíes sequence ni source).'
            row = {'row_id': identity, 'sequence': index}
            kind = raw.get('execution_type')
            if kind not in ('entry', 'exit'):
                row_errors['execution_type'] = 'Selecciona entry o exit.'
            row['execution_type'] = kind
            for name in ('executed_at', 'quantity', 'price', 'commission', 'fees'):
                try:
                    value = raw.get(name, '0' if name in ('commission', 'fees') else None)
                    if not isinstance(value, str) or not value or len(value) > 64:
                        raise TradeValidationError('Envía una cadena no vacía de hasta 64 caracteres.')
                    if name == 'executed_at':
                        # ISO explícito: evita aceptar fechas sin zona o perder submicrosegundos.
                        pattern = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-](?:0\d|1[0-4]):[0-5]\d)'
                        if not re.fullmatch(pattern, value) or (value[-6:-3] in ('+14', '-14') and value[-2:] != '00'):
                            raise TradeValidationError('Usa una fecha ISO con offset explícito y hasta seis decimales de segundo.')
                        row[name] = timestamp(value)
                    elif name == 'quantity':
                        if not re.fullmatch(r'[0-9]{1,10}', value.strip()):
                            raise TradeValidationError('La cantidad debe ser un entero positivo.')
                        row[name] = integer(int(value), name)
                    elif name == 'price':
                        row['price_ticks'] = price_units(value, symbol)
                    else:
                        row[name + '_microusd'] = money_units(value, name)
                except TradeValidationError as error:
                    row_errors[name] = str(error)
            if row_errors:
                errors['rows'][identity] = row_errors
            normalized.append(row)
        if errors['fields'] or errors['rows']:
            raise DraftValidationError(errors)
        return dict(account_id=account_id, symbol=symbol, direction=direction,
                    strategy=strategy, notes=notes, mode=mode, executions=normalized)

    def _preview_normalized(self, draft):
        ordered = sorted(draft['executions'], key=lambda row: (row['executed_at'], row['sequence']))
        # Reutiliza el motor por prefijos para localizar la fila que invalida la historia.
        for index, row in enumerate(ordered, 1):
            try:
                summary = self._revalidate(draft, ordered[:index])
            except TradeValidationError as error:
                raise DraftValidationError({'fields': {}, 'rows': {
                    row['row_id']: {'history': str(error)}}}) from error
        # Conversión de unidades para mostrar los fills, sin otra implementación financiera.
        with localcontext() as context:
            context.prec = 50
            displayed = [{**row,
                          'price': format(Decimal(row['price_ticks']) * CONTRACTS[draft['symbol']]['tick_size'], 'f'),
                          'commission': format(Decimal(row['commission_microusd']) / 1_000_000, 'f'),
                          'fees': format(Decimal(row['fees_microusd']) / 1_000_000, 'f')}
                         for row in ordered]
        return {'summary': summary, 'executions': displayed}

    def preview_trade(self, account_id, symbol, direction, executions, strategy=None, notes=None, *, mode='historical'):
        draft = self._normalize_draft(account_id, symbol, direction, executions, strategy, notes, mode)
        with self._connection() as connection:
            # query_only impide escrituras accidentales en esta conexión de previsualización.
            connection.execute('PRAGMA query_only=ON')
            self._account(connection, draft['account_id'], writable=True)
            return self._preview_normalized(draft)

    def create_trade_with_executions(self, account_id, symbol, direction, executions,
                                     strategy=None, notes=None, *, request_id, mode='historical'):
        draft = self._normalize_draft(account_id, symbol, direction, executions, strategy, notes, mode)
        # row_id es identidad de presentación; la secuencia sí pertenece al contenido económico.
        canonical = {**draft, 'executions': [{k: v for k, v in row.items() if k != 'row_id'}
                                           for row in draft['executions']]}
        with self._connection(write=True) as connection:
            # También en reintentos: una clave previa no permite escribir sobre cuentas archivadas.
            self._account(connection, draft['account_id'], writable=True)

            def create():
                self._preview_normalized(draft)
                trade_id = self._create_trade(connection, draft['account_id'], draft['symbol'],
                                              draft['direction'], draft['strategy'], draft['notes'])
                rows = [{**{k: v for k, v in row.items() if k != 'row_id'},
                         'trade_id': trade_id, 'account_id': draft['account_id'], 'source': 'manual',
                         'external_execution_id': None, 'external_namespace': None, 'created_at': timestamp()}
                        for row in draft['executions']]
                self._insert_executions(connection, rows)
                self._revalidate(draft, self._executions(connection, trade_id))
                return {'trade_id': trade_id}

            return execute_once(connection, request_id, 'create_trade_with_executions', canonical, create)

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
