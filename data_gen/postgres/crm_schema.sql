-- =============================================================================
-- CRM data model — PostgreSQL DDL
-- =============================================================================
-- This schema mirrors the synthetic data generator at
--   data_gen/crm_generator.py
-- It is the Postgres source-of-truth for the Databricks BRONZE ingestion layer:
-- columns and their emission order match the dict keys the generator writes to
-- CSV, so a straight load into these tables aligns with what bronze expects.
--
-- Typing rules applied (per the generator's emitted values):
--   *_id / *_key / email / name / status / address / phone / country /
--     source / title / region / subject / notes / comment       -> TEXT
--   money (revenue / amount / price / total / value)            -> NUMERIC(18,2)
--   counts (employees / quantity / probability / term_months)   -> INTEGER
--   *_date / converted_date / close_date                        -> DATE (ISO date strings)
--   *_datetime                                                  -> TIMESTAMP (ISO datetime string)
--   is_* / *_active / is_primary                                -> BOOLEAN
--   helper/underscore columns (_company_key, _country)          -> TEXT
--
-- IMPORTANT modeling note on dated/incremental feeds:
--   `accounts`, `opportunities`, and other dated entities are emitted as
--   per-partition (per-date) snapshots in the generator. In particular,
--   `opportunities` writes ONE ROW PER DAY per opportunity_id (a slowly
--   progressing snapshot feed), so opportunity_id is NOT unique in that feed.
--   The CREATE TABLEs below still declare each entity's own id as PRIMARY KEY
--   per the task spec; loaders that replay the raw multi-date snapshot stream
--   should land into a staging/bronze table without this PK (or de-dup first).
--
-- Operational column:
--   Every table has an `updated_at TIMESTAMPTZ DEFAULT now()` appended at the
--   END. This is an ADDED operational/CDC convenience column and is NOT emitted
--   by the generator.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS crm;

-- -----------------------------------------------------------------------------
-- users  (gen_users)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.users (
    user_id     TEXT PRIMARY KEY,
    first_name  TEXT,
    last_name   TEXT,
    work_email  TEXT,
    phone       TEXT,
    job_title   TEXT,
    is_active   BOOLEAN,
    -- added operational column (not from generator)
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- territories  (gen_territories)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.territories (
    territory_id    TEXT PRIMARY KEY,
    territory_name  TEXT,
    region          TEXT,
    -- added operational column (not from generator)
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- accounts  (_build_account)
-- Dated/incremental feed: one row per account on its created_date partition.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.accounts (
    account_id              TEXT PRIMARY KEY,
    account_name            TEXT,
    account_type            TEXT,
    industry                TEXT,
    rating                  TEXT,
    annual_revenue          NUMERIC(18,2),
    employees               INTEGER,
    office_address          TEXT,
    billing_country         TEXT,
    phone                   TEXT,
    owner_user_id           TEXT,
    territory_id            TEXT,
    converted_from_lead_id  TEXT,  -- "" when not lead-converted; see NOTE below
    created_date            DATE,
    _company_key            TEXT,  -- generator helper column
    _country                TEXT,  -- generator helper column
    -- added operational column (not from generator)
    updated_at              TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_accounts_owner_user
        FOREIGN KEY (owner_user_id) REFERENCES crm.users (user_id),
    CONSTRAINT fk_accounts_territory
        FOREIGN KEY (territory_id) REFERENCES crm.territories (territory_id)
    -- NOTE: no FK on converted_from_lead_id -> leads.lead_id: the generator
    -- emits "" (empty string) for non-converted accounts, which would violate
    -- the FK. Also, open leads exist that are never converted, and not every
    -- referenced lead is guaranteed present in a given partition load.
);

-- -----------------------------------------------------------------------------
-- contacts  (_build_contact)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.contacts (
    contact_id      TEXT PRIMARY KEY,
    account_id      TEXT,
    first_name      TEXT,
    last_name       TEXT,
    work_email      TEXT,
    phone           TEXT,
    mobile_phone    TEXT,
    job_title       TEXT,
    office_address  TEXT,
    is_primary      BOOLEAN,
    created_date    DATE,
    -- added operational column (not from generator)
    updated_at      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_contacts_account
        FOREIGN KEY (account_id) REFERENCES crm.accounts (account_id)
);

-- -----------------------------------------------------------------------------
-- leads  (inline in main loop)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.leads (
    lead_id               TEXT PRIMARY KEY,
    first_name            TEXT,
    last_name             TEXT,
    company               TEXT,
    work_email            TEXT,
    phone                 TEXT,
    job_title             TEXT,
    office_address        TEXT,
    lead_source           TEXT,
    status                TEXT,
    rating                TEXT,
    created_date          DATE,
    converted_date        DATE,  -- "" for open leads; load empty string as NULL
    converted_account_id  TEXT,  -- "" when not converted; see NOTE below
    -- added operational column (not from generator)
    updated_at            TIMESTAMPTZ DEFAULT now()
    -- NOTE: no FK on converted_account_id -> accounts.account_id: it is ""
    -- (empty string) for open/unconverted leads, which would violate the FK.
);

-- -----------------------------------------------------------------------------
-- opportunities  (inline snapshot rows)
-- DATED SNAPSHOT FEED: one row per day per opportunity_id. opportunity_id is
-- NOT unique across the raw feed. PRIMARY KEY declared per task spec; raw
-- multi-date snapshots should be staged without this constraint.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.opportunities (
    opportunity_id      TEXT PRIMARY KEY,
    account_id          TEXT,
    primary_contact_id  TEXT,  -- "" when account has no contact; see NOTE below
    opportunity_name    TEXT,
    stage               TEXT,
    probability         INTEGER,
    amount              NUMERIC(18,2),
    currency            TEXT,
    owner_user_id       TEXT,
    close_date          DATE,
    is_closed           BOOLEAN,
    is_won              BOOLEAN,
    snapshot_date       DATE,
    sales_notes         TEXT,
    -- added operational column (not from generator)
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_opportunities_account
        FOREIGN KEY (account_id) REFERENCES crm.accounts (account_id),
    CONSTRAINT fk_opportunities_owner_user
        FOREIGN KEY (owner_user_id) REFERENCES crm.users (user_id)
    -- NOTE: no FK on primary_contact_id -> contacts.contact_id: emitted as ""
    -- when the account has no contacts, which would violate the FK.
);

-- -----------------------------------------------------------------------------
-- opportunity_line_items  (inline)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.opportunity_line_items (
    line_item_id    TEXT PRIMARY KEY,
    opportunity_id  TEXT,
    product_name    TEXT,
    quantity        INTEGER,
    unit_price      NUMERIC(18,2),
    total_price     NUMERIC(18,2),
    -- added operational column (not from generator)
    updated_at      TIMESTAMPTZ DEFAULT now()
    -- NOTE: no FK on opportunity_id -> opportunities.opportunity_id: the
    -- opportunities feed is a dated snapshot where opportunity_id is not unique
    -- (repeats per day), so it is not a reliable single-row FK target.
);

-- -----------------------------------------------------------------------------
-- quotes  (inline)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.quotes (
    quote_id         TEXT PRIMARY KEY,
    opportunity_id   TEXT,
    account_id       TEXT,
    quote_total      NUMERIC(18,2),
    currency         TEXT,
    status           TEXT,
    expiration_date  DATE,
    created_date     DATE,
    -- added operational column (not from generator)
    updated_at       TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_quotes_account
        FOREIGN KEY (account_id) REFERENCES crm.accounts (account_id)
    -- NOTE: no FK on opportunity_id -> opportunities.opportunity_id: dated
    -- snapshot feed, opportunity_id is not unique (see opportunities table).
);

-- -----------------------------------------------------------------------------
-- contracts  (inline)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.contracts (
    contract_id          TEXT PRIMARY KEY,
    account_id           TEXT,
    opportunity_id       TEXT,
    quote_id             TEXT,
    contract_value       NUMERIC(18,2),
    currency             TEXT,
    start_date           DATE,
    end_date             DATE,
    term_months          INTEGER,
    status               TEXT,
    contract_signer_name TEXT,
    created_date         DATE,
    -- added operational column (not from generator)
    updated_at           TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_contracts_account
        FOREIGN KEY (account_id) REFERENCES crm.accounts (account_id),
    CONSTRAINT fk_contracts_quote
        FOREIGN KEY (quote_id) REFERENCES crm.quotes (quote_id)
    -- NOTE: no FK on opportunity_id -> opportunities.opportunity_id: dated
    -- snapshot feed, opportunity_id is not unique (see opportunities table).
);

-- -----------------------------------------------------------------------------
-- activities  (inline)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.activities (
    activity_id        TEXT PRIMARY KEY,
    account_id         TEXT,
    contact_id         TEXT,  -- "" when account has no contact; see NOTE below
    owner_user_id      TEXT,
    activity_type      TEXT,
    subject            TEXT,
    activity_datetime  TIMESTAMP,  -- generator emits ISO datetime string
    is_completed       BOOLEAN,
    -- added operational column (not from generator)
    updated_at         TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_activities_account
        FOREIGN KEY (account_id) REFERENCES crm.accounts (account_id),
    CONSTRAINT fk_activities_owner_user
        FOREIGN KEY (owner_user_id) REFERENCES crm.users (user_id)
    -- NOTE: no FK on contact_id -> contacts.contact_id: emitted as "" when the
    -- chosen account has no contacts, which would violate the FK.
);

-- -----------------------------------------------------------------------------
-- cases  (inline)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS crm.cases (
    case_id        TEXT PRIMARY KEY,
    account_id     TEXT,
    contact_id     TEXT,  -- "" when account has no contact; see NOTE below
    case_number    TEXT,
    priority       TEXT,
    status         TEXT,
    origin         TEXT,
    subject        TEXT,
    case_comment   TEXT,
    opened_date    DATE,
    -- added operational column (not from generator)
    updated_at     TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT fk_cases_account
        FOREIGN KEY (account_id) REFERENCES crm.accounts (account_id)
    -- NOTE: no FK on contact_id -> contacts.contact_id: emitted as "" when the
    -- chosen account has no contacts, which would violate the FK.
);
