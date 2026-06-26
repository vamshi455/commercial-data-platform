# Synthetic Data Generators — Commercial Data Platform

Pure standard-library Python 3.10+ generators that produce realistic,
referentially-consistent CRM (Salesforce-like) and ERP (SAP-like) data,
plus shared reference dimensions, for the Databricks medallion pipeline.

No third-party dependencies (no `pandas` / `faker` / `numpy`) so they run
anywhere: a laptop, CI, or a Databricks cluster init/job. Parquet is
intentionally skipped to avoid deps — emit CSV (default) or JSON, then let
Auto Loader / a Spark job convert to Delta on landing.

## Files

| File | Purpose |
|------|---------|
| `common.py` | Shared helpers: seeded RNG, Salesforce/SAP id generators, name/email/phone/address fakers, date helpers, CSV/JSON writers, tax-id tokenizer/mask, sensitivity tagging, CRM↔ERP crosswalk registry. |
| `crm_generator.py` | All CRM entities with lifecycle behavior. Writes the crosswalk. |
| `erp_generator.py` | All ERP entities; reads the crosswalk to align customers to CRM accounts. |
| `reference_data_generator.py` | `fiscal_calendar`, `product_hierarchy`, `currency_rates`, `country_codes`. |
| `pii_masking_samples.py` | Demonstrates masking/tokenization and writes a governance samples file. |

## How to run

Run reference + CRM first (CRM writes the crosswalk), then ERP (reads it):

```bash
# Reference dimensions (2 years)
python data_gen/reference_data_generator.py --out data_gen/output/reference --years 2

# CRM — 7 dated batches, 50 accounts
python data_gen/crm_generator.py --out data_gen/output/crm --days 7 --seed 42 --accounts 50

# ERP — reads the CRM crosswalk to align ~40% of customers
python data_gen/erp_generator.py --out data_gen/output/erp --days 7 --seed 42 \
    --customers 60 --crm-out data_gen/output/crm

# PII masking demo (prints before/after, writes samples file)
python data_gen/pii_masking_samples.py --out data_gen/output/governance
```

Common flags: `--out` (base dir), `--days` (number of dated batches),
`--seed` (reproducibility), `--accounts`/`--customers` (volume),
`--format csv|json`, `--start YYYY-MM-DD` (first batch date).

## Output layout

```
<out>/<entity>/dt=YYYY-MM-DD/<entity>.csv   # incremental / transactional feeds
<out>/<entity>/<entity>.csv                 # full-snapshot dimensions
<out>/_crosswalk/crm_erp_crosswalk.json     # CRM↔ERP identity-resolution map
<out>/_manifest/<source>_manifest.json      # row counts + run metadata
```

Dated partitions (`dt=YYYY-MM-DD`) model incremental loads. Dimensions
(users, territories, customers, vendors, products, cost/profit centers,
reference data) are full snapshots.

## Entities

**CRM:** accounts, contacts, leads, opportunities, opportunity_line_items,
quotes, contracts, activities, cases, users, territories.

**ERP:** customers, vendors, products, sales_orders, sales_order_items,
billing_documents, invoices, payments, purchase_orders, gl_entries,
cost_centers, profit_centers, currency_rates.

**Reference:** fiscal_calendar, product_hierarchy, currency_rates, country_codes.

## Modeled behavior

- Leads convert to accounts + contacts + opportunities (`converted_*` fields).
- Opportunities progress Prospecting → Qualification → Proposal → Negotiation →
  Closed Won/Lost across dated snapshots (`snapshot_date`, `stage`, `probability`).
- Closed-won opportunities create quotes and contracts.
- Cases link to accounts and contacts.
- ERP order → items → billing document → invoice → payment chain with
  referential integrity and double-entry `gl_entries`.
- Payment anomalies: on-time, late, partial, disputed, open.
- SCD versions for products (price changes) and cost centers (reorgs) via
  `valid_from`/`valid_to`/`is_current`/`scd_version`.
- Daily `currency_rates` as a small random walk vs USD.

## PII note

PII is included deliberately so downstream governance (Unity Catalog tags,
masking policies) can be exercised:

- **CRM:** `first_name`, `last_name`, `work_email`, `phone`, `office_address`,
  `job_title`, `contract_signer_name`, free-text `sales_notes` and `case_comment`.
- **ERP:** `billing_contact_name`, `billing_address`, `payment_contact_email`
  (partially masked), `tax_id` (masked/tokenized), `bank_reference` (last-4),
  `employee_id` (tokenized), invoice/payment detail.

`tax_id`, bank references, and contact emails are emitted **already masked /
tokenized** (`mask_tax_id`, `mask_email`, `last4`, `tokenize` in `common.py`).
`pii_masking_samples.py` documents the policy and the field-level sensitivity
vocabulary used by governance.

## CRM ↔ ERP identity resolution

`crm_generator.py` writes `_crosswalk/crm_erp_crosswalk.json` mapping a stable
company key to `crm_account_id` and an `in_erp` flag. `erp_generator.py` reads
it and reuses the same company name / country for a share of ERP `customers`,
carrying `crm_account_id` on the customer row — enabling downstream identity
resolution and CRM↔ERP join tests.

## Feeding Auto Loader

Point an Auto Loader stream at each entity's landing path. The dated layout
is `cloudFiles`-friendly:

```python
(spark.readStream.format("cloudFiles")
   .option("cloudFiles.format", "csv")
   .option("cloudFiles.schemaLocation", "/Volumes/landing/_schema/sales_orders")
   .option("header", "true")
   .load("/Volumes/landing/erp/sales_orders/"))   # discovers dt=YYYY-MM-DD partitions
```

Upload `<out>/<entity>/dt=*/<entity>.csv` into a Unity Catalog landing
**Volume**; Auto Loader incrementally ingests new dated partitions into the
bronze layer. Full-snapshot dimensions can be loaded with `COPY INTO` or a
batch read and merged as SCD2 using the `valid_from`/`valid_to` columns.
```
