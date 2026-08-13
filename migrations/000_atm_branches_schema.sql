-- Bank Intelligence Platform — схема домена ATM Monitor (PostgreSQL)
-- Таблицы также создаются автоматически при первом старте через init_db().

CREATE TABLE IF NOT EXISTS atms (
    id              SERIAL PRIMARY KEY,
    terminal_id     TEXT UNIQUE NOT NULL,
    atm_number      TEXT,
    branch_code     TEXT,
    local_code      TEXT,
    region          TEXT,
    branch          TEXT,
    model           TEXT,
    network_type    TEXT,
    serial          TEXT,
    merchant_id     TEXT,
    address         TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    capacity        BIGINT NOT NULL DEFAULT 400000000,
    balance         BIGINT,
    last_balance_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_atms_region ON atms(region);
CREATE INDEX IF NOT EXISTS idx_atms_branch ON atms(branch);
CREATE INDEX IF NOT EXISTS idx_atms_local  ON atms(local_code);

CREATE TABLE IF NOT EXISTS branches (
    id              SERIAL PRIMARY KEY,
    number          TEXT,
    local_code      TEXT UNIQUE,
    region          TEXT,
    address         TEXT,
    lat             DOUBLE PRECISION,
    lon             DOUBLE PRECISION,
    incassation     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_branches_region ON branches(region);
CREATE INDEX IF NOT EXISTS idx_branches_inc    ON branches(incassation);
