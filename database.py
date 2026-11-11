"""SQLite local, inicialización explícita y transacciones de escritura."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

from contracts import CONTRACTS

DEFAULT_PATH = Path(__file__).resolve().parent / 'instance' / 'journal.sqlite3'
SCHEMA_VERSION = 2


class DatabaseError(RuntimeError):
    pass


def connect(path=DEFAULT_PATH, *, create=False):
    path = Path(path).resolve()
    if not create and not path.is_file():
        raise DatabaseError('Base ausente. Ejecuta uv run --no-sync python -m database init (con --path si corresponde).')
    connection = sqlite3.connect(path.as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                                 uri=True, timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys = ON')
    if connection.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        connection.close()
        raise DatabaseError('No fue posible activar las claves foráneas.')
    return connection


@contextmanager
def transaction(connection):
    if connection.in_transaction:
        raise DatabaseError('No se admiten transacciones anidadas.')
    connection.execute('BEGIN IMMEDIATE')
    try:
        yield connection
        connection.execute('COMMIT')
    except BaseException:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        raise


def initialize(path=DEFAULT_PATH):
    connection = connect(path, create=True)
    try:
        with transaction(connection):
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version == SCHEMA_VERSION:
                verify(connection)
                return
            if version != 0:
                raise DatabaseError(f'Versión {version}: utiliza el comando migrate para una base v1; no se admiten versiones futuras.')
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():
                raise DatabaseError('Base sin versión pero con tablas: requiere migración explícita.')
            suffix = ' STRICT' if sqlite3.sqlite_version_info >= (3, 37, 0) else ''
            symbols = ','.join("'" + symbol.replace("'", "''") + "'" for symbol in CONTRACTS)
            statements = [
                """CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 200),
                    account_type TEXT NOT NULL CHECK(account_type IN ('funded','personal')),
                    platform TEXT CHECK(platform IS NULL OR length(trim(platform)) BETWEEN 1 AND 200),
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK(typeof(is_active)='integer' AND is_active IN (0,1))
                )""",
                f"""CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
                    symbol TEXT NOT NULL CHECK(symbol IN ({symbols})),
                    direction TEXT NOT NULL CHECK(direction IN ('long','short')),
                    strategy TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(id, account_id)
                )""",
                """CREATE TABLE executions (
                    id INTEGER PRIMARY KEY,
                    trade_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    executed_at TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(typeof(sequence)='integer' AND sequence BETWEEN 1 AND 1000000000),
                    execution_type TEXT NOT NULL CHECK(execution_type IN ('entry','exit')),
                    quantity INTEGER NOT NULL CHECK(typeof(quantity)='integer' AND quantity BETWEEN 1 AND 1000000000),
                    price_ticks INTEGER NOT NULL CHECK(typeof(price_ticks)='integer' AND price_ticks > 0),
                    commission_microusd INTEGER NOT NULL DEFAULT 0 CHECK(typeof(commission_microusd)='integer' AND commission_microusd BETWEEN 0 AND 1000000000000000),
                    fees_microusd INTEGER NOT NULL DEFAULT 0 CHECK(typeof(fees_microusd)='integer' AND fees_microusd BETWEEN 0 AND 1000000000000000),
                    source TEXT NOT NULL CHECK(source IN ('manual','imported')),
                    external_execution_id TEXT,
                    external_namespace TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(trade_id, account_id) REFERENCES trades(id, account_id) ON DELETE RESTRICT,
                    UNIQUE(trade_id, sequence),
                    CHECK((external_execution_id IS NULL AND external_namespace IS NULL) OR
                          (external_execution_id IS NOT NULL AND external_namespace IS NOT NULL AND
                           length(trim(external_execution_id)) > 0 AND length(trim(external_namespace)) > 0))
                )""",
            ]
            for statement in statements:
                connection.execute(statement + suffix)
            for statement in (
                'CREATE INDEX trades_account_date ON trades(account_id, created_at, id)',
                'CREATE INDEX executions_order ON executions(trade_id, executed_at, sequence)',
                'CREATE UNIQUE INDEX executions_external ON executions(account_id, external_namespace, external_execution_id) WHERE external_execution_id IS NOT NULL',
            ):
                connection.execute(statement)
            _upgrade_v1(connection)
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
            verify(connection)
    finally:
        connection.close()


def verify(connection, *, expected_version=SCHEMA_VERSION):
    if connection.execute('PRAGMA user_version').fetchone()[0] != expected_version:
        raise DatabaseError('Versión de esquema incompatible.')
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'accounts', 'trades', 'executions'} <= tables:
        raise DatabaseError('Esquema incompleto.')
    expected = {
        'accounts': {'id', 'name', 'account_type', 'platform', 'created_at', 'is_active'},
        'trades': {'id', 'account_id', 'symbol', 'direction', 'strategy', 'notes', 'created_at'},
        'executions': {'id', 'trade_id', 'account_id', 'executed_at', 'sequence', 'execution_type',
                       'quantity', 'price_ticks', 'commission_microusd', 'fees_microusd', 'source',
                       'external_execution_id', 'external_namespace', 'created_at'},
    }
    if expected_version == 2:
        expected['trades'].add('revision')
        expected['write_requests'] = {'request_key', 'action', 'payload_hash', 'result_json', 'created_at'}
    for table, columns in expected.items():
        actual = {row[1] for row in connection.execute(f'PRAGMA table_info({table})')}
        if not columns <= actual:
            raise DatabaseError('Columnas de esquema incompletas.')
    indices = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    if not {'trades_account_date', 'executions_order', 'executions_external'} <= indices:
        raise DatabaseError('Índices de esquema incompletos.')
    if not list(connection.execute('PRAGMA foreign_key_list(trades)')) or not list(connection.execute('PRAGMA foreign_key_list(executions)')):
        raise DatabaseError('Faltan claves foráneas.')
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise DatabaseError('Falló integrity_check.')
    if connection.execute('PRAGMA foreign_key_check').fetchone():
        raise DatabaseError('Existen referencias inválidas.')


def _upgrade_v1(connection):
    connection.execute("ALTER TABLE trades ADD COLUMN revision INTEGER NOT NULL DEFAULT 0 CHECK(typeof(revision)='integer' AND revision >= 0)")
    suffix = ' STRICT' if sqlite3.sqlite_version_info >= (3, 37, 0) else ''
    connection.execute("""CREATE TABLE write_requests (
        request_key TEXT PRIMARY KEY NOT NULL CHECK(length(request_key) BETWEEN 16 AND 128),
        action TEXT NOT NULL CHECK(length(action) BETWEEN 1 AND 100),
        payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
        result_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""" + suffix)
    connection.execute('CREATE INDEX write_requests_created ON write_requests(created_at)')


def migrate(path=DEFAULT_PATH):
    """Reserva la escritura antes del respaldo para mantener la misma versión fuente."""
    path = Path(path).resolve()
    connection = connect(path)
    backup_path = None
    try:
        with transaction(connection):
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version not in (1, 2):
                raise DatabaseError(f'Versión no soportada: {version}.')
            verify(connection, expected_version=version)
            if version == 2:
                return None
            backup_path = path.with_name(path.name + '.' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.' + uuid4().hex + '.bak')
            # Una conexión lectora separada permite backup con la reserva de escritura vigente.
            source = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
            target = None
            try:
                backup_path.touch(mode=0o600, exist_ok=False)
                target = sqlite3.connect(str(backup_path))
                source.backup(target)
                verify(target, expected_version=1)
            finally:
                source.close()
                if target is not None:
                    target.close()
            _upgrade_v1(connection)
            connection.execute('PRAGMA user_version=2')
            verify(connection)
        return backup_path
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'verify', 'migrate'))
    parser.add_argument('--path', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    try:
        if args.command == 'init':
            args.path.parent.mkdir(parents=True, exist_ok=True)
            initialize(args.path)
        elif args.command == 'migrate':
            backup = migrate(args.path)
            print(f'Respaldo: {backup}' if backup else 'Ya está en v2; sin respaldo adicional.')
        else:
            connection = sqlite3.connect(args.path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                verify(connection)
            finally:
                connection.close()
    except (DatabaseError, sqlite3.Error, OSError) as error:
        parser.exit(1, f'No se completó {args.command}: {error}\n')
    print(f'{args.command}: OK — versión {SCHEMA_VERSION} — {args.path}')


if __name__ == '__main__':
    main()
