-- =============================================================================
-- governance/abac_policies.sql
-- -----------------------------------------------------------------------------
-- Attribute-Based Access Control (ABAC, GA 2026). Tag-driven row-filter & column
-- -mask policies that REPLACE the per-column ALTER ... SET MASK binds in
-- masking_functions.sql PART B. Define the mask UDFs once (masking_functions.sql
-- PART A), tag columns by treatment, and these policies apply the mask wherever
-- the tag appears — no per-column wiring, auto-covers new tables.
--
-- REQUIRES: DBR 16.4+ or serverless. Run with USE CATALOG ${catalog}.
-- DO NOT auto-apply (needs compute) — run intentionally.
--
-- TAGGING MODEL: governed tag `mask` ∈ {email, phone, tax_id} identifies the
--   treatment per column (kept separate from the `sensitivity` classification
--   tag). Governed-tag values must be defined first (Catalog UI / account admin).
--   Apply with: ALTER TABLE ... ALTER COLUMN c SET TAGS ('mask'='email'); etc.
--   The ABAC policy then matches columns via has_tag_value('mask', ...).
--
-- WHO SEES CLEAR TEXT: the policy TO/EXCEPT clause decides — privileged groups
--   are EXCEPTed (unmasked). This moves the "who" out of the UDF body; the mask
--   functions still carry the is_prod() guard so dev/qa stay relaxed.
-- =============================================================================

USE CATALOG ${catalog};

-- ---------------------------------------------------------------------------
-- GOVERNED TAG — REQUIRED before the policies: ABAC only matches GOVERNED tags
-- (registered key + allowed values), not ad-hoc tags. Needs account admin.
-- (May take a few seconds to propagate before policies referencing it compile.)
-- ---------------------------------------------------------------------------
CREATE GOVERNED TAG mask DESCRIPTION 'Masking treatment for a PII column' VALUES ('email','phone','tax_id');

-- ---------------------------------------------------------------------------
-- COLUMN MASKS — one policy per treatment, matched by the `mask` tag.
-- TO `account users` = everyone; EXCEPT lists the personas that may unmask.
-- ---------------------------------------------------------------------------

-- Email: customer_success may contact customers → unmasked; everyone else masked.
CREATE OR REPLACE POLICY mask_email_by_tag ON CATALOG ${catalog}
COMMENT 'ABAC mask for columns tagged mask=email, clear for stewards/platform/customer_success.'
COLUMN MASK gold.mask_email
  TO `account users`
  EXCEPT `cdp_data_stewards`, `cdp_platform_engineers`, `cdp_customer_success`
  FOR TABLES
  MATCH COLUMNS has_tag_value('mask', 'email') AS c
  ON COLUMN c;

-- Phone: same unmask set as email.
CREATE OR REPLACE POLICY mask_phone_by_tag ON CATALOG ${catalog}
COMMENT 'ABAC mask for columns tagged mask=phone, clear for stewards/platform/customer_success.'
COLUMN MASK gold.mask_phone
  TO `account users`
  EXCEPT `cdp_data_stewards`, `cdp_platform_engineers`, `cdp_customer_success`
  FOR TABLES
  MATCH COLUMNS has_tag_value('mask', 'phone') AS c
  ON COLUMN c;

-- Tax id: finance may unmask for invoicing/compliance.
CREATE OR REPLACE POLICY mask_tax_id_by_tag ON CATALOG ${catalog}
COMMENT 'ABAC mask for columns tagged mask=tax_id, clear for stewards/platform/finance.'
COLUMN MASK gold.mask_tax_id
  TO `account users`
  EXCEPT `cdp_data_stewards`, `cdp_platform_engineers`, `cdp_finance_analysts`
  FOR TABLES
  MATCH COLUMNS has_tag_value('mask', 'tax_id') AS c
  ON COLUMN c;

-- ---------------------------------------------------------------------------
-- ROW FILTER — territory scoping for sales (placeholder; needs a territory
-- row-filter UDF + a `row_scope=territory` tag on the filterable tables).
-- Sales analysts see only rows in their territory; other personas exempt.
-- ---------------------------------------------------------------------------
-- CREATE OR REPLACE POLICY territory_scope ON SCHEMA gold
-- COMMENT 'ABAC: restrict sales analysts to their own territory rows.'
-- ROW FILTER gold.territory_filter
--   TO `cdp_sales_analysts`
--   FOR TABLES
--   WHEN has_tag_value('row_scope', 'territory')
--   MATCH COLUMNS has_tag('territory_col') AS t
--   USING COLUMNS (t);

-- ---------------------------------------------------------------------------
-- COLUMN TAGS that drive the masks above (apply once columns exist; Track A).
-- These supersede masking_functions.sql PART B binds.
-- ---------------------------------------------------------------------------
-- ALTER TABLE silver.silver_contact  ALTER COLUMN work_email    SET TAGS ('mask'='email');
-- ALTER TABLE silver.silver_contact  ALTER COLUMN mobile_phone  SET TAGS ('mask'='phone');
-- ALTER TABLE gold.gold_customer_360 ALTER COLUMN primary_email SET TAGS ('mask'='email');
-- ALTER TABLE gold.gold_customer_360 ALTER COLUMN primary_phone SET TAGS ('mask'='phone');
-- ALTER TABLE gold.gold_customer_360 ALTER COLUMN tax_id        SET TAGS ('mask'='tax_id');
-- ALTER TABLE bronze.bronze_erp_customers ALTER COLUMN tax_id_masked SET TAGS ('mask'='tax_id');

-- Inspect active policies:  SHOW POLICIES ON CATALOG ${catalog};
