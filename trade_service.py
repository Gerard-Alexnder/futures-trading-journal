"""API de negocio sin Flask; una conexión independiente por llamada."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, localcontext
import sqlite3
import re
import json
from preview_tokens import canonical, issue as issue_preview, validate as validate_preview, verify_binding

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


class StaleRevisionError(ConflictError):
    pass


class TradeClosedError(ConflictError):
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
    def __init__(self, path=DEFAULT_PATH, *, preview_secret=None):
        self.path = path
        self.preview_secret = preview_secret

    @contextmanager
    def _connection(self, write=False):
        connection = None
        try:
            connection = connect(self.path)
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise DatabaseError('Base incompatible. Para v1/v2 ejecuta uv run --no-sync python -m database migrate; para versiones futuras utiliza una aplicación compatible.')
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

    @contextmanager
    def _snapshot(self):
        """Una transacción de lectura: revisión, cuenta e historia del mismo instante."""
        with self._connection() as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            try:
                yield connection
            finally:
                if connection.in_transaction:
                    connection.execute('ROLLBACK')

    @staticmethod
    def _validate_revision(revision):
        if type(revision) is not int or not 0 <= revision < 9223372036854775807:
            raise DraftValidationError({'fields': {'expected_revision': 'Revisión entera no negativa requerida.'}, 'rows': {}})

    @staticmethod
    def _bump_revision(connection, trade_id, expected_revision):
        TradeService._validate_revision(expected_revision)
        cursor = connection.execute('UPDATE trades SET revision=revision+1 WHERE id=? AND revision=?',
                                    (trade_id, expected_revision))
        if cursor.rowcount != 1:
            raise StaleRevisionError('La posición cambió. Actualízala y vuelve a previsualizar.')
        return expected_revision + 1

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
        return calculate_trade(trade['symbol'], trade['direction'], [r for r in candidate_history if not r.get('is_voided', 0)])

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
            self._bump_revision(connection, trade_id, trade['revision'])

    def get_trade(self, trade_id):
        with self._snapshot() as connection:
            trade = self._trade(connection, trade_id)
            account = self._account(connection, trade['account_id'])
            executions = self._executions(connection, trade_id)
            audit = []
            for row in connection.execute('SELECT * FROM execution_audit WHERE trade_id=? ORDER BY id', (trade_id,)):
                event = dict(row)
                for side in ('before','after'):
                    event[side] = json.loads(row[side+'_json'])
                    event[side+'_display'] = self._display_executions(trade['symbol'], [event[side]])[0]
                audit.append(event)
            return {**trade, 'account': account, 'executions': self._display_executions(trade['symbol'], executions),
                    'summary': self._revalidate(trade, executions), 'audit':audit}

    def query_journal(self, *, account_id=None, symbol=None, direction=None, status=None,
                      date_from=None, date_to=None, utc_offset='-04:00', page=1, page_size=25):
        """Resultados de vida completa, filtrados por primera entrada, en un snapshot."""
        errors = {}
        def number(value, name, default=None):
            if value is None or (value == '' and default is None):
                return default
            if isinstance(value, str) and re.fullmatch(r'[0-9]{1,10}', value):
                value = int(value)
            if type(value) is not int or not 1 <= value <= 1_000_000_000:
                errors[name] = 'Utiliza un entero positivo de hasta 1000000000.'
            return value
        account_id = number(account_id, 'account_id')
        page = number(page, 'page', 1)
        page_size = number(page_size, 'page_size', 25)
        if page_size not in (25, 50, 100): errors['page_size'] = 'Tamaños permitidos: 25, 50 y 100.'
        selected = {}
        for name, value, choices in [('symbol', symbol, CONTRACTS), ('direction', direction, ('long','short')),
                                     ('status', status, ('pending','open','closed'))]:
            value = None if value in (None, '') else value
            if value is not None and (not isinstance(value, str) or value not in choices):
                errors[name] = 'Opción no válida.'
            selected[name] = value
        zone = None
        if isinstance(utc_offset, str) and re.fullmatch(r'[+-][0-9]{2}:[0-9]{2}', utc_offset):
            hours, minutes = map(int, utc_offset[1:].split(':'))
            if minutes < 60 and hours <= 14 and (hours < 14 or minutes == 0):
                zone = timezone(timedelta(minutes=(hours*60+minutes)*(1 if utc_offset[0]=='+' else -1)))
        if zone is None: errors['utc_offset'] = 'Offset ±HH:MM válido, hasta ±14:00.'
        dates, bounds = {}, {}
        for name, value in [('date_from', date_from), ('date_to', date_to)]:
            dates[name] = None
            bounds[name] = None
            if value in (None, ''): continue
            try:
                if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value): raise ValueError()
                day = datetime.strptime(value, '%Y-%m-%d')
                dates[name] = value
                if zone is not None:
                    if name == 'date_to': day += timedelta(days=1)
                    bounds[name] = day.replace(tzinfo=zone).astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
            except (ValueError, OverflowError): errors[name] = 'Fecha imposible o límite fuera del calendario admitido.'
        if dates['date_from'] and dates['date_to'] and dates['date_from'] > dates['date_to']:
            errors['date_to'] = 'La fecha final debe ser igual o posterior a la inicial.'
        if errors: raise DraftValidationError({'fields':errors, 'rows':{}})
        filters = dict(account_id=account_id, **selected, **dates, utc_offset=utc_offset)
        with self._snapshot() as connection:
            accounts = [dict(r) for r in connection.execute('SELECT * FROM accounts ORDER BY id')]
            by_account = {a['id']:a for a in accounts}
            if account_id is not None and account_id not in by_account:
                raise DraftValidationError({'fields':{'account_id':'Cuenta inexistente.'},'rows':{}})
            clauses, params = [], []
            for name, value in [('account_id',account_id),('symbol',selected['symbol']),('direction',selected['direction'])]:
                if value is not None:
                    clauses.append(f't.{name}=?'); params.append(value)
            sql = 'SELECT t.* FROM trades t' + (' WHERE '+' AND '.join(clauses) if clauses else '') + ' ORDER BY t.id'
            trades = [dict(r) for r in connection.execute(sql, params)]
            items = []
            for start in range(0, len(trades), 400):
                batch = trades[start:start+400]
                histories = {t['id']:[] for t in batch}
                placeholders = ','.join('?' for _ in batch)
                for r in connection.execute(f'SELECT * FROM executions WHERE trade_id IN ({placeholders}) ORDER BY trade_id,executed_at,sequence', list(histories)):
                    histories[r['trade_id']].append(dict(r))
                for trade in batch:
                    history = [r for r in histories[trade['id']] if not r['is_voided']]
                    first = next((r['executed_at'] for r in history if r['execution_type']=='entry'), None)
                    if history and first is None:
                        raise PersistenceError('Historia sin entrada; requiere verificación.')
                    effective = first or trade['created_at']
                    if bounds['date_from'] and effective < bounds['date_from']: continue
                    if bounds['date_to'] and effective >= bounds['date_to']: continue
                    summary = self._revalidate(trade, history)
                    if selected['status'] and summary['status'] != selected['status']: continue
                    # No transportar la historia ni realized_by_execution al listado.
                    compact = {k:v for k,v in summary.items() if k != 'realized_by_execution'}
                    try:
                        local_date = datetime.fromisoformat(effective.replace('Z','+00:00')).astimezone(zone).isoformat()
                    except (ValueError, OverflowError) as error:
                        raise PersistenceError('Fecha fuera del calendario de presentación.') from error
                    items.append(dict(id=trade['id'], revision=trade['revision'], symbol=trade['symbol'],
                                      direction=trade['direction'], strategy=trade['strategy'],
                                      account=by_account[trade['account_id']], effective_at=effective,
                                      date_is_creation=not history,
                                      effective_local=local_date,
                                      entry_quantity=sum(r['quantity'] for r in history if r['execution_type']=='entry'),
                                      summary=compact))
            values = [i['summary']['net_pnl'] for i in items]
            # Exact addition of finite Decimal outputs, including cancellation and long fractions.
            precision = max(50, max((v.adjusted() for v in values), default=0)
                            - min((v.as_tuple().exponent for v in values), default=0)
                            + len(str(max(1,len(values)))) + 2)
            with localcontext() as context:
                context.prec = precision
                net = sum(values, Decimal(0))
                closed = sum(i['summary']['status']=='closed' for i in items)
                winners = sum(i['summary']['status']=='closed' and i['summary']['net_pnl']>0 for i in items)
                win_rate = Decimal(winners)*100/closed if closed else None
            statistics = dict(net_pnl=net, open_count=sum(i['summary']['status']=='open' for i in items),
                              closed_count=closed, winning_count=winners, win_rate=win_rate)
            items.sort(key=lambda i:(i['effective_at'],i['id']), reverse=True)
            total = len(items); pages = (total+page_size-1)//page_size
            effective_page = min(page, pages) if pages else 1
            offset = (effective_page-1)*page_size
            return dict(items=items[offset:offset+page_size], statistics=statistics, accounts=accounts, filters=filters,
                        pagination=dict(requested_page=page, page=effective_page, page_size=page_size,
                                        total=total, pages=pages, adjusted=page!=effective_page))

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

    def _add_executions(self, connection, trade_id, executions, *, bump_revision=True):
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
        ids = self._insert_executions(connection, candidates)
        if bump_revision:
            self._bump_revision(connection, trade_id, trade['revision'])
        return ids

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
        normalized = TradeService._normalize_execution_rows(symbol, executions)
        return dict(account_id=account_id, symbol=symbol, direction=direction,
                    strategy=strategy, notes=notes, mode=mode, executions=normalized)

    @staticmethod
    def _normalize_execution_rows(symbol, executions):
        if not isinstance(executions, list) or not 1 <= len(executions) <= 200:
            raise DraftValidationError({'fields': {'executions': 'Incluye entre 1 y 200 ejecuciones.'}, 'rows': {}})
        errors = {'fields': {}, 'rows': {}}
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
        return normalized

    def _preview_normalized(self, draft):
        ordered = sorted(draft['executions'], key=lambda row: (row['executed_at'], row['sequence']))
        # Reutiliza el motor por prefijos para localizar la fila que invalida la historia.
        for index, row in enumerate(ordered, 1):
            try:
                summary = self._revalidate(draft, ordered[:index])
            except TradeValidationError as error:
                raise DraftValidationError({'fields': {}, 'rows': {
                    row['row_id']: {'history': str(error)}}}) from error
        return {'summary': summary, 'executions': self._display_executions(draft['symbol'], ordered)}

    @staticmethod
    def _display_executions(symbol, rows):
        # Conversión de unidades para presentación; no duplica el motor financiero.
        with localcontext() as context:
            context.prec = 50
            return [{**row, 'is_voided': row.get('is_voided', 0),
                     'price': format(Decimal(row['price_ticks']) * CONTRACTS[symbol]['tick_size'], 'f'),
                     'commission': format(Decimal(row['commission_microusd']) / 1_000_000, 'f'),
                     'fees': format(Decimal(row['fees_microusd']) / 1_000_000, 'f')}
                    for row in rows]

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

    def _preview_batch(self, trade, history, normalized, expected_revision):
        if trade['revision'] != expected_revision:
            raise StaleRevisionError('La posición cambió. Actualízala y vuelve a previsualizar.')
        current = self._revalidate(trade, history)
        if current['status'] == 'closed':
            raise TradeClosedError('La operación está cerrada; no admite nuevas ejecuciones.')
        maximum = max((row['sequence'] for row in history), default=0)
        candidates = [{**row, 'sequence': integer(maximum + index, 'sequence')}
                      for index, row in enumerate(normalized, 1)]
        combined = sorted([*history, *candidates], key=lambda row: (row['executed_at'], row['sequence']))
        try:
            projected = self._revalidate(trade, combined)
        except TradeValidationError as error:
            # Solo localizar por prefijos cuando el replay completo falla.
            for index, row in enumerate(combined, 1):
                try:
                    self._revalidate(trade, combined[:index])
                except TradeValidationError as located:
                    if 'row_id' in row:
                        details = {'fields': {}, 'rows': {row['row_id']: {'history': str(located)}}}
                    else:
                        details = {'fields': {'executions': f"El lote invalida la ejecución existente #{row['id']}: {located}"},
                                   'rows': {item['row_id']: {'history': 'Revisa la inserción retroactiva y la historia combinada.'}
                                            for item in candidates}}
                    raise DraftValidationError(details) from located
            raise error
        retroactive = bool(history) and any(row['executed_at'] < max(h['executed_at'] for h in history) for row in candidates)
        return {'trade_id': trade['id'], 'revision': trade['revision'], 'current': current, 'projected': projected,
                'executions': self._display_executions(trade['symbol'], combined),
                'new_executions': self._display_executions(trade['symbol'], candidates),
                'retroactive': retroactive,
                'warning': ('Inserción retroactiva: se recalculará toda la operación, incluido el P&L de salidas posteriores ya registradas. No se modifican sus ejecuciones originales.'
                            if retroactive else None)}

    def preview_execution_batch(self, trade_id, executions, *, expected_revision):
        self._validate_revision(expected_revision)
        with self._snapshot() as connection:
            trade = self._trade(connection, trade_id)
            self._account(connection, trade['account_id'], writable=True)
            normalized = self._normalize_execution_rows(trade['symbol'], executions)
            history = self._executions(connection, trade_id)
            return self._preview_batch(trade, history, normalized, expected_revision)

    def append_execution_batch(self, trade_id, executions, *, expected_revision, request_id):
        self._validate_revision(expected_revision)
        with self._connection(write=True) as connection:
            trade = self._trade(connection, trade_id)
            self._account(connection, trade['account_id'], writable=True)
            normalized = self._normalize_execution_rows(trade['symbol'], executions)
            # Orden RELATIVO estable: no depende del max(sequence) posterior al commit.
            canonical = {'trade_id': trade_id, 'expected_revision': expected_revision,
                         'executions': [{key: value for key, value in row.items() if key != 'row_id'}
                                        for row in normalized]}

            def append():
                history = self._executions(connection, trade_id)
                preview = self._preview_batch(trade, history, normalized, expected_revision)
                candidates = [{key: value for key, value in row.items()
                               if key not in ('row_id', 'price', 'commission', 'fees')}
                              for row in preview['new_executions']]
                for row in candidates:
                    row.update(trade_id=trade_id, account_id=trade['account_id'], source='manual',
                               external_execution_id=None, external_namespace=None, created_at=timestamp())
                ids = self._insert_executions(connection, candidates)
                revision = self._bump_revision(connection, trade_id, expected_revision)
                return {'trade_id': trade_id, 'execution_ids': ids, 'revision': revision}

            # Reintentos confirmados se resuelven antes de comprobar revisión/cierre.
            return execute_once(connection, request_id, 'append_execution_batch', canonical, append)

    def _amendment_request(self, trade, execution_id, replacement, expected_revision, reason, action):
        self._validate_revision(expected_revision)
        integer(execution_id, 'execution_id')
        reason = text_field(reason, 'reason', limit=2000)
        normalized = None
        if action == 'correction':
            required = {'executed_at','execution_type','quantity','price','commission','fees'}
            if not isinstance(replacement, dict) or set(replacement) != required:
                raise DraftValidationError({'fields':{'replacement':'Incluye exactamente los seis campos corregibles.'},'rows':{}})
            row = self._normalize_execution_rows(trade['symbol'], [{**replacement, 'row_id':'correction'}])[0]
            normalized = {k:v for k,v in row.items() if k not in ('row_id','sequence')}
        return dict(action=action, trade_id=trade['id'], execution_id=execution_id,
                    expected_revision=expected_revision, reason=reason, replacement=normalized)

    @staticmethod
    def _target(history, execution_id):
        target = next((r for r in history if r['id']==execution_id), None)
        if target is None:
            raise NotFoundError('La ejecución no pertenece a esta operación.')
        return target

    def _project_amendment(self, trade, history, request):
        if trade['revision'] != request['expected_revision']:
            raise StaleRevisionError('La operación cambió. Actualiza y previsualiza de nuevo.')
        before = self._target(history, request['execution_id'])
        if before['is_voided']:
            raise ConflictError('La ejecución ya está anulada; no admite cambios ni restauración.')
        after = {**before, **(request['replacement'] or {'is_voided':1})}
        if after == before:
            raise DraftValidationError({'fields':{'replacement':'La corrección no cambia valores efectivos.'},'rows':{}})
        candidate = [after if r['id']==before['id'] else r for r in history]
        current = self._revalidate(trade, history)
        try:
            projected = self._revalidate(trade, candidate)
        except TradeValidationError as error:
            raise DraftValidationError({'fields':{'history':str(error)},'rows':{str(before['id']):{'history':str(error)}}}) from error
        def order(rows):
            return [r['id'] for r in sorted(rows,key=lambda r:(r['executed_at'],r['sequence'])) if not r['is_voided']]
        warnings = ['Se recalcula toda la historia vigente, incluidos resultados posteriores. No se modifican otras ejecuciones.']
        if current['status']=='closed' and projected['status']=='open':
            warnings.append('La operación cerrada volverá a open y admitirá nuevas ejecuciones válidas.')
        if projected['status']=='pending':
            warnings.append('No quedarán ejecuciones vigentes: estado pending, posición y neto cero.')
        if request['action']=='void':
            warnings.append('La anulación excluye también los costos de esta ejecución. No hay restauración en esta fase.')
        return dict(trade_id=trade['id'], execution_id=before['id'], revision=trade['revision'],
                    current=current, projected=projected, before=before, after=after,
                    current_order=order(history), projected_order=order(candidate), warnings=warnings)

    def _preview_amendment(self, trade_id, execution_id, replacement, expected_revision, reason, action):
        with self._snapshot() as connection:
            trade = self._trade(connection, trade_id)
            self._account(connection, trade['account_id'], writable=True)
            request = self._amendment_request(trade, execution_id, replacement, expected_revision, reason, action)
            result = self._project_amendment(trade, self._executions(connection, trade_id), request)
            token = issue_preview(self.preview_secret, {'request':request, 'result':result})
            return {**result, 'preview_token':token, 'expires_in':600,
                    'before_display':self._display_executions(trade['symbol'], [result['before']])[0],
                    'after_display':self._display_executions(trade['symbol'], [result['after']])[0]}

    def preview_execution_correction(self, trade_id, execution_id, replacement, *, expected_revision, reason):
        return self._preview_amendment(trade_id, execution_id, replacement, expected_revision, reason, 'correction')

    def preview_execution_void(self, trade_id, execution_id, *, expected_revision, reason):
        return self._preview_amendment(trade_id, execution_id, None, expected_revision, reason, 'void')

    def _commit_amendment(self, trade_id, execution_id, replacement, expected_revision, reason, request_id, preview_token, action):
        with self._connection(write=True) as connection:
            trade = self._trade(connection, trade_id)
            self._account(connection, trade['account_id'], writable=True)
            request = self._amendment_request(trade, execution_id, replacement, expected_revision, reason, action)
            # Membership and active account checked even for confirmed retries.
            target = connection.execute('SELECT id FROM executions WHERE id=? AND trade_id=?', (execution_id,trade_id)).fetchone()
            if target is None:
                raise NotFoundError('La ejecución no pertenece a esta operación.')
            def commit():
                if trade['revision'] != expected_revision:
                    raise StaleRevisionError('La operación cambió. Actualiza y previsualiza de nuevo.')
                token = validate_preview(self.preview_secret, preview_token)
                result = self._project_amendment(trade, self._executions(connection, trade_id), request)
                verify_binding(token, {'request':request, 'result':result})
                changes = request['replacement'] or {'is_voided':1}
                columns = ','.join(name+'=?' for name in changes)
                connection.execute(f'UPDATE executions SET {columns} WHERE id=? AND trade_id=?',
                                   (*changes.values(),execution_id,trade_id))
                audit_id = connection.execute('''INSERT INTO execution_audit
                    (trade_id,execution_id,action,occurred_at,reason,before_json,after_json,
                     previous_revision,new_revision,request_id,snapshot_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,1)''',
                    (trade_id,execution_id,action,timestamp(),request['reason'],canonical(result['before']),
                     canonical(result['after']),expected_revision,expected_revision+1,request_id)).lastrowid
                revision = self._bump_revision(connection, trade_id, expected_revision)
                return dict(trade_id=trade_id, execution_id=execution_id, audit_id=audit_id, revision=revision)
            # Token excluded: semantic command is stable across expiry/reissued proofs.
            return execute_once(connection, request_id, action+'_execution', request, commit)

    def correct_execution(self, trade_id, execution_id, replacement, *, expected_revision, reason, request_id, preview_token):
        return self._commit_amendment(trade_id, execution_id, replacement, expected_revision, reason, request_id, preview_token, 'correction')

    def void_execution(self, trade_id, execution_id, *, expected_revision, reason, request_id, preview_token):
        return self._commit_amendment(trade_id, execution_id, None, expected_revision, reason, request_id, preview_token, 'void')

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
            self._add_executions(connection, new_id, [opening_execution], bump_revision=False)
            return new_id
