# Setup Notebooks

Databricks SQL notebooks that provision Unity Catalog governance for the
Commercial Data Platform. They are the executable wrappers around the scripts in
`governance/` and are run by the `job_platform_setup` job
(`resources/setup.job.yml`).

## Notebooks

| Order | Notebook | Wraps | Purpose |
|-------|----------|-------|---------|
| 1 | `00_create_catalogs_schemas.sql` | `governance/catalogs_schemas.sql` | Create the env catalog, medallion schemas, `landing.files` volume (`+sandbox` in dev). |
| 2 | `01_grants_personas.sql` | `governance/grants.sql` | Apply the persona RBAC matrix to all `cdp_*` groups. |
| 3 | `02_masking_row_filters.sql` | `governance/masking_functions.sql` + `row_filters.sql` + `tags_classification.sql` | Create masking/row-filter UDFs, bind them, apply sensitivity tags. |

## How they're used

- Each notebook declares a `catalog` widget. The setup job passes
  `catalog = ${var.catalog}` per target (`cdp_dev` / `cdp_qa` / `cdp_prod`) via
  `base_parameters`, so the same notebooks run unchanged in every environment.
- DDL uses `IDENTIFIER(:catalog)` / `:catalog` so the widget value is bound
  safely as the catalog name.
- Run order is enforced by task `depends_on` in `resources/setup.job.yml`.

## Running

Via the bundle (recommended):

```bash
databricks bundle deploy -t dev
databricks bundle run job_platform_setup -t dev
```

Or interactively: attach to serverless SQL, set the `catalog` widget, and run
the notebooks in order `00 -> 01 -> 02`.

## Timing & privileges

- Run `00` and `01` at platform bootstrap.
- Run `02` **after** the ingestion + transformation pipelines have created the
  silver/gold tables, since it binds masks/row filters/tags onto them.
- `CREATE CATALOG` needs **metastore admin**; grants need catalog `MANAGE`;
  masks/filters/tags need catalog ownership / `APPLY TAG`. In qa/prod these run
  as the deploy service principal. See `governance/README.md` for the full
  privilege matrix.
