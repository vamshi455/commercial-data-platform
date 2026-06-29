"""CRM ingestion from local PostgreSQL (over the ngrok tunnel) -> bronze.

Reads each ``crm.*`` table via Postgres JDBC and materialises a bronze table per
entity: ``bronze.crm_pg_<entity>``. This is the **Postgres-sourced** path; it runs
*side-by-side* with the file-based ``crm_autoloader`` (which writes
``bronze_crm_*``) so nothing existing is replaced. Once validated, you can promote
this to be the canonical CRM bronze and retire the file path.

ON-DEMAND by design:
  * Connection ``host``/``port`` are RUN-TIME vars (``cdp.pg_host`` / ``cdp.pg_port``)
    because the ngrok tunnel endpoint changes each restart — passed via
    ``bundle deploy --var`` by ``scripts/pull_crm_from_pg.sh``.
  * The read-only password comes from a Databricks **secret scope**
    (``cdp.pg_password`` is wired to ``{{secrets/cdp/pg_reader_password}}`` in the
    pipeline configuration) — never in code or YAML.

``spark`` is injected as a runtime global in DLT.
"""
from __future__ import annotations

import dlt

from pyspark.sql import functions as F

_HOST = spark.conf.get("cdp.pg_host", "")            # noqa: F821 (spark is a runtime global)
_PORT = spark.conf.get("cdp.pg_port", "5432")        # noqa: F821
_DB   = spark.conf.get("cdp.pg_db", "cdp_crm")       # noqa: F821
_USER = spark.conf.get("cdp.pg_user", "databricks_reader")  # noqa: F821
# DLT pipeline `configuration` does NOT resolve {{secrets/...}} references, so we
# fetch the reader password directly from the secret scope via dbutils (a runtime
# global in DLT). Scope/key are configurable; defaults match scripts/setup.
_PW   = dbutils.secrets.get(                          # noqa: F821
    spark.conf.get("cdp.pg_secret_scope", "cdp"),     # noqa: F821
    spark.conf.get("cdp.pg_secret_key", "pg_reader_password"),  # noqa: F821
)
_URL  = f"jdbc:postgresql://{_HOST}:{_PORT}/{_DB}"

CRM_ENTITIES = [
    "accounts", "contacts", "leads", "opportunities", "opportunity_line_items",
    "quotes", "contracts", "activities", "cases", "users", "territories",
]


def _read(table: str):
    """Batch-read one crm.<table> over JDBC (snapshot pull, not streaming)."""
    return (
        spark.read.format("jdbc")            # noqa: F821
        .option("url", _URL)
        .option("dbtable", f"crm.{table}")
        .option("user", _USER)
        .option("password", _PW)
        .option("driver", "org.postgresql.Driver")
        .load()
    )


def _make(entity: str):
    @dlt.table(
        name=f"crm_pg_{entity}",
        comment=f"Bronze CRM {entity} pulled from local Postgres crm.{entity} via JDBC/tunnel (on-demand).",
        table_properties={"quality": "bronze", "cdp.source": "postgres_jdbc"},
    )
    def _t():
        return (
            _read(entity)
            .withColumn("_ingested_at", F.current_timestamp())
            .withColumn("_source_system", F.lit("crm"))
            .withColumn("_source", F.lit("postgres_jdbc"))
        )
    return _t


# One bronze table per CRM entity (factory loop keeps it DRY).
for _e in CRM_ENTITIES:
    _make(_e)
