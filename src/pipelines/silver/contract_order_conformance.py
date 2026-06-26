"""Silver conformance for contracts and sales orders.

Inputs
------
* ``bronze_crm_contracts``     -- CRM contract records
* ``bronze_crm_opportunities`` -- CRM opportunities (we treat ``Closed Won`` as
  bookings that may not yet have a formal contract row)
* ``bronze_erp_sales_orders``  -- ERP sales order headers
* ``silver_customer``          -- to attach the conformed ``customer_sk``

Outputs
-------
* ``silver_contract``     -- conformed contracts (from CRM contracts UNION
  closed-won opportunities that lack a contract), keyed to ``customer_sk``.
* ``silver_sales_order``  -- conformed ERP sales orders, keyed to ``customer_sk``.

Why union opportunities into contracts?
---------------------------------------
In this commercial model, a *booking* is recognised when an opportunity is
Closed Won; a formal ``contract`` row may follow later (or never, for
transactional business). To get a complete "committed revenue" picture we
conform both into ``silver_contract`` with a ``contract_source`` discriminator
(``crm_contract`` vs ``won_opportunity``).

Data quality
------------
* contracts: drop rows missing a contract key or amount; warn on missing dates.
* sales_orders: drop rows missing the order id; expect a positive net amount and
  a sane order date (not in the far future).
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F

from src.pipelines._common import normalize_name


# ---------------------------------------------------------------------------
# silver_contract
# ---------------------------------------------------------------------------

@dlt.view(comment="CRM contracts normalised + keyed to silver customer.")
def stg_crm_contracts():
    c = dlt.read("bronze_crm_contracts")
    cust = dlt.read("silver_customer").select("customer_sk", "crm_account_id")
    return (
        c.join(cust, c.account_id == cust.crm_account_id, "left")
         .select(
             F.col("contract_id"),
             F.lit("crm_contract").alias("contract_source"),
             F.col("customer_sk"),
             F.col("account_id").alias("crm_account_id"),
             F.col("contract_number") if "contract_number" in c.columns
             else F.col("contract_id").alias("contract_number"),
             F.col("status").alias("contract_status") if "status" in c.columns
             else F.lit(None).cast("string").alias("contract_status"),
             F.to_date("start_date").alias("start_date") if "start_date" in c.columns
             else F.lit(None).cast("date").alias("start_date"),
             F.to_date("end_date").alias("end_date") if "end_date" in c.columns
             else F.lit(None).cast("date").alias("end_date"),
             F.col("contract_value").cast("decimal(18,2)").alias("contract_amount")
             if "contract_value" in c.columns
             else F.lit(None).cast("decimal(18,2)").alias("contract_amount"),
             F.col("currency_iso_code").alias("currency")
             if "currency_iso_code" in c.columns
             else F.lit(None).cast("string").alias("currency"),
         )
    )


@dlt.view(comment="Closed-won opportunities treated as bookings without a contract.")
def stg_won_opps():
    o = dlt.read("bronze_crm_opportunities")
    cust = dlt.read("silver_customer").select("customer_sk", "crm_account_id")
    won = o.where(F.lower(F.col("stage_name")).contains("closed won")) \
        if "stage_name" in o.columns else o.where(F.lit(False))
    return (
        won.join(cust, won.account_id == cust.crm_account_id, "left")
        .select(
            F.col("opportunity_id").alias("contract_id"),
            F.lit("won_opportunity").alias("contract_source"),
            F.col("customer_sk"),
            F.col("account_id").alias("crm_account_id"),
            F.col("opportunity_id").alias("contract_number"),
            F.lit("Won").alias("contract_status"),
            F.to_date("close_date").alias("start_date")
            if "close_date" in o.columns else F.lit(None).cast("date").alias("start_date"),
            F.lit(None).cast("date").alias("end_date"),
            F.col("amount").cast("decimal(18,2)").alias("contract_amount")
            if "amount" in o.columns
            else F.lit(None).cast("decimal(18,2)").alias("contract_amount"),
            F.col("currency_iso_code").alias("currency")
            if "currency_iso_code" in o.columns
            else F.lit(None).cast("string").alias("currency"),
        )
    )


@dlt.table(
    name="silver_contract",
    comment="Conformed contracts: CRM contracts UNION closed-won opportunities.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_contract_id", "contract_id IS NOT NULL")
@dlt.expect_or_drop("has_amount", "contract_amount IS NOT NULL")
@dlt.expect("has_customer", "customer_sk IS NOT NULL")
@dlt.expect("non_negative_amount", "contract_amount >= 0")
@dlt.expect("dates_ordered", "end_date IS NULL OR start_date IS NULL OR end_date >= start_date")
def silver_contract():
    return dlt.read("stg_crm_contracts").unionByName(dlt.read("stg_won_opps"))


# ---------------------------------------------------------------------------
# silver_sales_order
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver_sales_order",
    comment="Conformed ERP sales order headers, keyed to silver customer.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_order_id", "sales_order_id IS NOT NULL")
@dlt.expect("has_customer", "customer_sk IS NOT NULL")
@dlt.expect("positive_net_amount", "net_amount IS NULL OR net_amount >= 0")
@dlt.expect("sane_order_date", "order_date IS NULL OR order_date <= current_date()")
def silver_sales_order():
    so = dlt.read("bronze_erp_sales_orders")
    cust = dlt.read("silver_customer").select("customer_sk", "erp_customer_id")
    return (
        so.join(cust, so.customer_id == cust.erp_customer_id, "left")
        .select(
            F.col("sales_order_id"),
            F.col("customer_sk"),
            F.col("customer_id").alias("erp_customer_id"),
            normalize_name(F.col("customer_id").cast("string")).alias("_order_key_dbg"),
            F.to_date("order_date").alias("order_date")
            if "order_date" in so.columns
            else F.lit(None).cast("date").alias("order_date"),
            F.col("net_amount").cast("decimal(18,2)").alias("net_amount")
            if "net_amount" in so.columns
            else F.lit(None).cast("decimal(18,2)").alias("net_amount"),
            F.col("currency").alias("currency")
            if "currency" in so.columns
            else F.lit(None).cast("string").alias("currency"),
            F.col("order_status").alias("order_status")
            if "order_status" in so.columns
            else F.lit(None).cast("string").alias("order_status"),
        )
        .drop("_order_key_dbg")
    )
