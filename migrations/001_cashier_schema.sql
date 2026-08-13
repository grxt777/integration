-- Cashier Intelligence — initial PostgreSQL schema
-- Tables are also created automatically on first startup via init_cashier_tables().

CREATE TABLE IF NOT EXISTS cashier_imports (
    id          SERIAL PRIMARY KEY,
    filename    TEXT,
    imported_at TEXT NOT NULL,
    rows_count  INTEGER NOT NULL,
    report_label TEXT
);

CREATE TABLE IF NOT EXISTS cashier_reports (
    id                   SERIAL PRIMARY KEY,
    import_id            INTEGER NOT NULL REFERENCES cashier_imports(id) ON DELETE CASCADE,
                    tab_number           TEXT,
                    employee_number      TEXT,
                    full_name            TEXT NOT NULL,
                    position             TEXT,
                    days_worked          REAL,
                    std_days             REAL NOT NULL DEFAULT 0,
                    operations_count     REAL NOT NULL DEFAULT 0,
    operations_minutes   REAL NOT NULL DEFAULT 0,
    bek_count            REAL NOT NULL DEFAULT 0,
    bek_minutes          REAL NOT NULL DEFAULT 0,
                    front_count          REAL NOT NULL DEFAULT 0,
                    front_minutes        REAL NOT NULL DEFAULT 0,
                    load_percent         REAL NOT NULL DEFAULT 0,
                    load_difference      REAL NOT NULL DEFAULT 0,
                    branch_name          TEXT,
    raw_note             TEXT,
    hr_status_code       TEXT,
    hr_status_label      TEXT,
    replacing_full_name  TEXT,
    replaced_by_full_name TEXT,
    has_replacement      INTEGER DEFAULT 1,
    metrics_json         TEXT NOT NULL DEFAULT '{}',
    discipline_type      TEXT,
    discipline_date_order TEXT,
    discipline_reason    TEXT
);

CREATE TABLE IF NOT EXISTS cashier_status_imports (
    id          SERIAL PRIMARY KEY,
    filename    TEXT,
    imported_at TEXT NOT NULL,
    rows_count  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS cashier_statuses (
    id                    SERIAL PRIMARY KEY,
    import_id             INTEGER NOT NULL REFERENCES cashier_status_imports(id) ON DELETE CASCADE,
    branch_name           TEXT,
    position              TEXT,
    full_name             TEXT NOT NULL,
    status_code           TEXT NOT NULL,
    status_label          TEXT NOT NULL,
    raw_note              TEXT,
    replacing_full_name   TEXT,
    replaced_by_full_name TEXT,
    has_replacement       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cashier_reports_import   ON cashier_reports(import_id);
CREATE INDEX IF NOT EXISTS idx_cashier_reports_status   ON cashier_reports(hr_status_code);
CREATE INDEX IF NOT EXISTS idx_cashier_reports_position ON cashier_reports(position);
CREATE INDEX IF NOT EXISTS idx_cashier_statuses_import  ON cashier_statuses(import_id);
CREATE INDEX IF NOT EXISTS idx_cashier_statuses_status  ON cashier_statuses(status_code);
