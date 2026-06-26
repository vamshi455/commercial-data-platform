"""ERP ingestion: Auto Loader -> streaming bronze tables (one per ERP entity).

Inputs
------
Raw CSV files from the ERP generator under::

    <landing>/erp/<entity>/dt=YYYY-MM-DD/*.csv

for each entity in ``ERP_ENTITIES`` (customers, vendors, products,
sales_orders, sales_order_items, billing_documents, invoices, payments,
purchase_orders, gl_entries, cost_centers, profit_centers, currency_rates).

Outputs
-------
One streaming Delta bronze table per entity, ``bronze_erp_<entity>``, published
to the pipeline's UC target ``bronze`` schema. Append-only, incrementally
loaded, with standard bronze audit columns. No transformation here.

This mirrors ``crm_autoloader.py`` exactly (same Auto Loader options, same
factory pattern) — only the source-system prefix and entity list differ. See
that file's docstring for a full explanation of the DLT + Auto Loader concepts
(streaming tables, schemaLocation, schema evolution, rescuedDataColumn).
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F

from src.pipelines._common import (
    ERP_ENTITIES,
    landing_glob,
    schema_location,
    with_audit_columns,
)

SOURCE_SYSTEM = "erp"


def _make_bronze_table(entity: str) -> None:
    """Register one streaming bronze table for an ERP ``entity``."""

    @dlt.table(
        name=f"bronze_erp_{entity}",
        comment=f"Raw ERP {entity} landed via Auto Loader (append-only bronze).",
        table_properties={
            "quality": "bronze",
            "pipelines.reset.allowed": "false",
            "delta.enableChangeDataFeed": "true",
        },
    )
    @dlt.expect("valid_source_file", "_source_file IS NOT NULL")
    def _bronze_table():
        df = (
            spark.readStream.format("cloudFiles")  # noqa: F821
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.schemaLocation", schema_location(SOURCE_SYSTEM, entity))
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
            .option("cloudFiles.inferColumnTypes", "true")
            .option("header", "true")
            .option("rescuedDataColumn", "_rescued_data")
            .option("cloudFiles.allowOverwrites", "false")
            .load(landing_glob(SOURCE_SYSTEM, entity))
        )
        return with_audit_columns(df).withColumn(
            "_source_system", F.lit(SOURCE_SYSTEM)
        )


# Factory loop — one streaming bronze table per ERP entity.
for _entity in ERP_ENTITIES:
    _make_bronze_table(_entity)
