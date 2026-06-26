"""Reference-data ingestion: Auto Loader -> streaming bronze reference tables.

Inputs
------
Small, slowly-changing reference/lookup files under::

    <landing>/reference/<entity>/*.csv        (full snapshots, usually unpartitioned)
    <landing>/reference/<entity>/dt=YYYY-MM-DD/*.csv   (if a generator dates them)

Entities (``REFERENCE_ENTITIES``):
  * fiscal_calendar    -- fiscal year/period <-> calendar date mapping
  * product_hierarchy  -- product category/family/line rollup
  * currency_rates     -- FX rates per currency per date (also emitted by ERP)
  * country_codes      -- ISO country code / region lookup

Outputs
-------
One streaming Delta bronze table per entity, ``bronze_ref_<entity>``, in the
target ``bronze`` schema, with standard audit columns. Downstream silver/gold
join these for conformance (fiscal periods, FX conversion, geo standardisation).

Notes
-----
Reference files are tiny and may be re-published as *full snapshots*. We still
ingest them as Auto Loader streaming tables for uniformity and incremental file
discovery; because Auto Loader only processes *new files*, replacing a snapshot
file with a new one is picked up as a new file. (If a true "latest snapshot only"
semantic were required we'd materialise a downstream SCD/overwrite in silver —
done for ``currency_rates``/``product_hierarchy`` there.)

See ``crm_autoloader.py`` for the full Auto Loader concept walk-through.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F

from src.pipelines._common import (
    REFERENCE_ENTITIES,
    landing_glob,
    schema_location,
    with_audit_columns,
)

SOURCE_SYSTEM = "reference"


def _make_bronze_table(entity: str) -> None:
    """Register one streaming bronze reference table for ``entity``."""

    @dlt.table(
        name=f"bronze_ref_{entity}",
        comment=f"Reference data: {entity} landed via Auto Loader (bronze).",
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
            .option("cloudFiles.allowOverwrites", "true")  # snapshots may be overwritten
            .load(landing_glob(SOURCE_SYSTEM, entity))
        )
        return with_audit_columns(df).withColumn(
            "_source_system", F.lit(SOURCE_SYSTEM)
        )


# Factory loop — one streaming bronze table per reference entity.
for _entity in REFERENCE_ENTITIES:
    _make_bronze_table(_entity)
