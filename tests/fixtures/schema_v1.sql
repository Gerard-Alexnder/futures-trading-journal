BEGIN TRANSACTION;
CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL CHECK(length(trim(name)) BETWEEN 1 AND 200),
                    account_type TEXT NOT NULL CHECK(account_type IN ('funded','personal')),
                    platform TEXT CHECK(platform IS NULL OR length(trim(platform)) BETWEEN 1 AND 200),
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1 CHECK(typeof(is_active)='integer' AND is_active IN (0,1))
                ) STRICT;
CREATE TABLE executions (
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
                ) STRICT;
CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
                    symbol TEXT NOT NULL CHECK(symbol IN ('ES','MES','NQ','MNQ')),
                    direction TEXT NOT NULL CHECK(direction IN ('long','short')),
                    strategy TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(id, account_id)
                ) STRICT;
CREATE INDEX trades_account_date ON trades(account_id, created_at, id);
CREATE INDEX executions_order ON executions(trade_id, executed_at, sequence);
CREATE UNIQUE INDEX executions_external ON executions(account_id, external_namespace, external_execution_id) WHERE external_execution_id IS NOT NULL;
COMMIT;
PRAGMA user_version=1;
