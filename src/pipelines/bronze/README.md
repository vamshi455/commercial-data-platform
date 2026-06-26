# Bronze layer

The **bronze** layer is the faithful, append-only landing of raw source data.
There is intentionally **no separate bronze transformation code** in this
folder: bronze tables are produced directly by the **ingestion Auto Loader**
streaming tables in `src/pipelines/ingestion/`:

| Source     | File                                  | Tables                 |
|------------|---------------------------------------|------------------------|
| CRM        | `ingestion/crm_autoloader.py`         | `bronze_crm_<entity>`  |
| ERP        | `ingestion/erp_autoloader.py`         | `bronze_erp_<entity>`  |
| Reference  | `ingestion/reference_autoloader.py`   | `bronze_ref_<entity>`  |

Each ingestion table:

- reads new files incrementally with **Auto Loader** (`cloudFiles`, CSV),
- persists/evolves the inferred schema via `cloudFiles.schemaLocation` +
  `schemaEvolutionMode = addNewColumns`,
- captures anything that does not fit the schema into **`_rescued_data`**
  (`rescuedDataColumn`) instead of dropping it, and
- appends the standard **bronze audit columns**.

## Audit-column convention

Added by `with_audit_columns(df)` in `src/pipelines/_common.py`:

| Column           | Source                              | Meaning                                  |
|------------------|-------------------------------------|------------------------------------------|
| `_ingested_at`   | `current_timestamp()`               | When the row was ingested (processing time) |
| `_source_file`   | `_metadata.file_path`               | The file the row came from               |
| `_batch_id`      | ingest date `yyyy-MM-dd` (default)  | Logical batch label                      |
| `_rescued_data`  | Auto Loader `rescuedDataColumn`     | JSON of fields that didn't fit the schema |
| `_source_system` | literal `crm`/`erp`/`reference`     | Origin system                            |

> `_metadata.file_path` is the modern replacement for the deprecated
> `input_file_name()`.

## Malformed-row handling (quarantine pattern)

Bronze stays permissive — we never reject raw data at the front door. Instead we
*flag* rows whose schema didn't match cleanly so silver can quarantine them. The
signal is a **non-null `_rescued_data`**.

A clean row satisfies:

```python
import dlt

@dlt.table(name="bronze_crm_accounts_clean")
@dlt.expect("no_rescued_data", "_rescued_data IS NULL")          # warn-only metric
def accounts_clean():
    return dlt.read_stream("bronze_crm_accounts")
```

To *physically separate* malformed rows into a quarantine table, branch on the
same predicate (the inverse of the silver `expect_or_drop`):

```python
@dlt.table(name="bronze_crm_accounts_quarantine",
           comment="Rows whose source columns did not fit the schema.")
def accounts_quarantine():
    return dlt.read_stream("bronze_crm_accounts").where("_rescued_data IS NOT NULL")
```

Silver tables then apply hard expectations (`@dlt.expect_or_drop` /
`@dlt.expect_or_fail`) on the *business* keys — bronze only measures and
preserves.
