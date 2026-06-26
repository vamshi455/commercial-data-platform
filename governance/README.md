# Governance — Unity Catalog setup for the Commercial Data Platform

This folder holds the parameterized SQL that establishes Unity Catalog
structure and governance for each environment (`cdp_dev` / `cdp_qa` /
`cdp_prod`). The scripts are **idempotent** and are normally executed by the
`job_platform_setup` job (see `resources/setup.job.yml`), which runs the
notebook wrappers under `notebooks/setup/`. They can also be run by hand in a
SQL editor by substituting the `${catalog}` placeholder.

## Parameterization

Every script begins with `USE CATALOG ${catalog};`. The setup notebooks read a
`catalog` widget (defaulted from `${var.catalog}` per bundle target) and pass
it in. When running manually, replace `${catalog}` with the target catalog name
(`cdp_dev`, `cdp_qa`, or `cdp_prod`).

## Run order

| # | File | What it does |
|---|------|--------------|
| 1 | `catalogs_schemas.sql` | Creates the env catalog, the `landing/bronze/silver/gold/ops` schemas (`+sandbox` in dev), and the `landing.files` volume. |
| 2 | `grants.sql` | Applies the persona RBAC matrix (USE CATALOG/SCHEMA, SELECT, MODIFY, EXECUTE, APPLY TAG) for all `cdp_*` groups. |
| 3 | `masking_functions.sql` | Creates `mask_email` / `mask_phone` / `mask_tax_id` / `mask_free_text` UDFs and binds them as column masks on silver/gold PII columns. |
| 4 | `row_filters.sql` | Creates `territory_filter` and binds it as a row filter so sales analysts see only their territory; finance/stewards see all. |
| 5 | `tags_classification.sql` | Applies the `sensitivity` tag taxonomy (pii / financial_sensitive / restricted_free_text / internal_only / public_reference) to representative tables and columns. |

> Order matters: schemas before grants; masking/row-filter UDFs must exist
> before tables are bound to them; tables must exist (created by the ingestion/
> transformation pipelines) before `SET MASK` / `SET ROW FILTER` / `SET TAGS`
> in steps 3–5 will succeed. Run steps 1–2 at platform bootstrap; run 3–5 after
> the first pipeline run has materialized the silver/gold tables.

## Who must run these

| Step | Required role |
|------|---------------|
| `CREATE CATALOG` (step 1) | **Metastore admin** (or `CREATE CATALOG` on the metastore). |
| Schemas / volume (step 1) | Catalog owner / workspace admin. |
| Grants (step 2) | Catalog owner or a principal with `MANAGE` on the catalog. |
| Masking / row filters / tags (steps 3–5) | Catalog owner / `cdp_platform_engineers`; tag changes need `APPLY TAG`. |

In `qa`/`prod` the setup job runs as the deploy **service principal**, which
must hold these privileges (metastore-admin or pre-granted) in the target
workspace.

## Environment notes

- **dev only:** `catalogs_schemas.sql` creates a `sandbox` schema. The notebook
  gates this on the catalog name; skip the sandbox block for `qa`/`prod`.
- Column masks and row filters layer on top of table grants: a persona may hold
  `SELECT` yet still see masked PII / filtered rows.
- `ai_app_users` only ever receive `SELECT` on approved `*_curated` gold views.
