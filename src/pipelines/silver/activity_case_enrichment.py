"""Silver activity + case enrichment, joined to account/customer.

Inputs
------
* ``bronze_crm_activities`` -- CRM activities/tasks (calls, emails, meetings)
* ``bronze_crm_cases``      -- CRM support cases
* ``silver_customer``       -- to attach ``customer_sk`` via CRM account id

Outputs
-------
* ``silver_activity`` -- activities keyed to customer, free-text fields tagged
  as restricted-handling.
* ``silver_case``     -- support cases keyed to customer, with derived
  ``is_open`` / ``resolution_hours`` and free-text flags.

Governance / free-text handling
-------------------------------
Activities and cases contain free-text (``description``, ``subject``,
``comments``) that may embed PII. We do NOT cleanse the text here, but we:
  * surface the raw text in dedicated ``*_text`` columns, and
  * add a boolean ``has_restricted_text`` + a ``_restricted_columns`` array
    documenting which columns are restricted.
Unity Catalog column tags (applied out-of-band via governance manifests) and
masking views consume these signals. The convention mirrors the generator's
``SENSITIVITY['FREE_TEXT']`` ("free_text.may_contain_pii") tag.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


def _customer_lookup():
    """CRM-account -> customer_sk lookup used by both tables."""
    return dlt.read("silver.silver_customer").select("customer_sk", "crm_account_id")


# ---------------------------------------------------------------------------
# silver_activity
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver.silver_activity",
    comment="CRM activities enriched to customer; free-text flagged restricted.",
    table_properties={
        "quality": "silver",
        # documents that this table carries free-text that may contain PII.
        "cdp.contains_free_text": "true",
    },
)
@dlt.expect_or_drop("has_activity_id", "activity_id IS NOT NULL")
@dlt.expect("has_customer", "customer_sk IS NOT NULL")
def silver_activity():
    a = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_crm_activities")
    cust = _customer_lookup()

    desc = F.col("description") if "description" in a.columns else F.lit(None).cast("string")
    subj = F.col("subject") if "subject" in a.columns else F.lit(None).cast("string")

    return (
        a.join(cust, a.account_id == cust.crm_account_id, "left")
        .select(
            F.col("activity_id"),
            F.col("customer_sk"),
            F.col("account_id").alias("crm_account_id"),
            (F.col("activity_type") if "activity_type" in a.columns
             else F.lit(None).cast("string")).alias("activity_type"),
            F.to_date("activity_datetime").alias("activity_date")
            if "activity_datetime" in a.columns
            else F.lit(None).cast("date").alias("activity_date"),
            subj.alias("subject_text"),
            desc.alias("description_text"),
            # restricted-handling signals
            ((F.length(F.coalesce(desc, F.lit(""))) > 0)
             | (F.length(F.coalesce(subj, F.lit(""))) > 0)).alias("has_restricted_text"),
            F.array(F.lit("subject_text"), F.lit("description_text")).alias("_restricted_columns"),
        )
    )


# ---------------------------------------------------------------------------
# silver_case
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver.silver_case",
    comment="CRM support cases enriched to customer; free-text flagged restricted.",
    table_properties={
        "quality": "silver",
        "cdp.contains_free_text": "true",
    },
)
@dlt.expect_or_drop("has_case_id", "case_id IS NOT NULL")
@dlt.expect("has_customer", "customer_sk IS NOT NULL")
@dlt.expect("date_sanity", "closed_date IS NULL OR created_date IS NULL OR closed_date >= created_date")
def silver_case():
    c = spark.read.table(f"{spark.conf.get('cdp.catalog', 'cdp_dev')}.bronze.bronze_crm_cases")
    cust = _customer_lookup()

    subj = F.col("subject") if "subject" in c.columns else F.lit(None).cast("string")
    desc = F.col("case_comment") if "case_comment" in c.columns else F.lit(None).cast("string")
    created = (F.to_timestamp("opened_date") if "opened_date" in c.columns
               else F.lit(None).cast("timestamp"))
    # No closed/resolved date column exists on bronze_crm_cases.
    closed = (F.to_timestamp("closed_date") if "closed_date" in c.columns
              else F.lit(None).cast("timestamp"))
    status = F.col("status") if "status" in c.columns else F.lit(None).cast("string")

    return (
        c.join(cust, c.account_id == cust.crm_account_id, "left")
        .select(
            F.col("case_id"),
            F.col("customer_sk"),
            F.col("account_id").alias("crm_account_id"),
            status.alias("status"),
            (F.col("priority") if "priority" in c.columns
             else F.lit(None).cast("string")).alias("priority"),
            created.cast("date").alias("created_date"),
            closed.cast("date").alias("closed_date"),
            # open when not closed/resolved
            (~F.lower(F.coalesce(status, F.lit(""))).isin("closed", "resolved")).alias("is_open"),
            F.when(
                created.isNotNull() & closed.isNotNull(),
                (F.col("closed_date") - F.col("created_date")) if False
                else F.round((F.unix_timestamp(closed) - F.unix_timestamp(created)) / 3600.0, 2),
            ).alias("resolution_hours"),
            subj.alias("subject_text"),
            desc.alias("description_text"),
            ((F.length(F.coalesce(desc, F.lit(""))) > 0)
             | (F.length(F.coalesce(subj, F.lit(""))) > 0)).alias("has_restricted_text"),
            F.array(F.lit("subject_text"), F.lit("description_text")).alias("_restricted_columns"),
        )
    )
