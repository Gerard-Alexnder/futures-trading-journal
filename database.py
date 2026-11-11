"""SQLite local, inicialización explícita y transacciones de escritura."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from contracts import CONTRACTS

DEFAULT_PATH = Path(__file__).resolve().parent / 'instance' / 'journal.sqlite3'
SCHEMA_VERSION = 1


class DatabaseError(RuntimeError):
    pass


def connect(path=DEFAULT_PATH):
    connection = sqlite3.connect(str(path), timeout=5, isolation_level=None)
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
    connection = connect(path)
    try:
        with transaction(connection):
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version == SCHEMA_VERSION:
                verify(connection)
                return
            if version != 0:
                raise DatabaseError(f'Versión de esquema no soportada: {version}.')
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
            connection.execute(f'PRAGMA user_version = {SCHEMA_VERSION}')
    finally:
        connection.close()


def verify(connection):
    if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
        raise DatabaseError('Versión de esquema incompatible.')
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'accounts', 'trades', 'executions'} <= tables:
        raise DatabaseError('Esquema incompleto.')
    if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise DatabaseError('Falló integrity_check.')
    if connection.execute('PRAGMA foreign_key_check').fetchone():
        raise DatabaseError('Existen referencias inválidas.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'verify'))
    parser.add_argument('--path', type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    if args.command == 'init':
        args.path.parent.mkdir(parents=True, exist_ok=True)
        initialize(args.path)
    else:
        # No crear accidentalmente una base al intentar verificarla.
        connection = sqlite3.connect(args.path.resolve().as_uri() + '?mode=ro', uri=True)
        try:
            verify(connection)
        finally:
            connection.close()
    print(f'{args.command}: OK — {args.path}')


if __name__ == '__main__':
    main()
