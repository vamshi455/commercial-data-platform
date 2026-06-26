"""Silver invoice + payment conformance and reconciliation.

Inputs
------
* ``bronze_erp_invoices``  -- ERP invoice (billing) documents
* ``bronze_erp_payments``  -- ERP incoming payments / clearings
* ``silver_customer``      -- to attach ``customer_sk``

Outputs
-------
* ``silver_invoice`` -- conformed invoices keyed to customer, with derived
  ``amount_paid``, ``open_amount``, and status flags (``is_partial``,
  ``is_late``, ``is_disputed``, ``is_paid``).
* ``silver_payment`` -- conformed payments keyed to customer + invoice.

Reconciliation logic
--------------------
We aggregate payments per invoice and compare against the invoice gross amount:
  * ``amount_paid``  = sum(applied payments)
  * ``open_amount``  = gross_amount - amount_paid
  * ``is_paid``      = open_amount <= 0 (within a small tolerance)
  * ``is_partial``   = 0 < amount_paid < gross_amount
  * ``is_late``      = unpaid/partial AND due_date < today
  * ``is_disputed``  = carried from source dispute flag if present

Data quality
------------
* invoices: drop rows missing invoice id or gross amount; expect a valid 3-char
  currency, ``invoice_date <= due_date`` sanity, and referential integrity to a
  known customer (warn).
* payments: drop rows missing payment id; expect non-negative amount and a
  payment date not in the future.
"""

from __future__ import annotations

import dlt

from pyspark.sql import functions as F


# ---------------------------------------------------------------------------
# silver_payment (built first so silver_invoice can aggregate it)
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver_payment",
    comment="Conformed ERP payments keyed to customer + invoice.",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_payment_id", "payment_id IS NOT NULL")
@dlt.expect("non_negative_amount", "payment_amount IS NULL OR payment_amount >= 0")
@dlt.expect("sane_payment_date", "payment_date IS NULL OR payment_date <= current_date()")
@dlt.expect("valid_currency", "currency IS NULL OR length(currency) = 3")
def silver_payment():
    p = dlt.read("bronze_erp_payments")
    cust = dlt.read("silver_customer").select("customer_sk", "erp_customer_id")
    return (
        p.join(cust, p.customer_id == cust.erp_customer_id, "left")
        .select(
            F.col("payment_id"),
            F.col("invoice_id") if "invoice_id" in p.columns
            else F.lit(None).cast("string").alias("invoice_id"),
            F.col("customer_sk"),
            F.col("customer_id").alias("erp_customer_id"),
            F.to_date("payment_date").alias("payment_date")
            if "payment_date" in p.columns
            else F.lit(None).cast("date").alias("payment_date"),
            F.col("amount").cast("decimal(18,2)").alias("payment_amount")
            if "amount" in p.columns
            else F.lit(None).cast("decimal(18,2)").alias("payment_amount"),
            F.upper(F.col("currency")).alias("currency") if "currency" in p.columns
            else F.lit(None).cast("string").alias("currency"),
        )
    )


# ---------------------------------------------------------------------------
# silver_invoice (reconciled against payments)
# ---------------------------------------------------------------------------

@dlt.table(
    name="silver_invoice",
    comment="Conformed ERP invoices reconciled against payments (open/partial/late).",
    table_properties={"quality": "silver"},
)
@dlt.expect_or_drop("has_invoice_id", "invoice_id IS NOT NULL")
@dlt.expect_or_drop("has_gross_amount", "gross_amount IS NOT NULL")
@dlt.expect("valid_currency", "currency IS NULL OR length(currency) = 3")
@dlt.expect("date_sanity", "due_date IS NULL OR invoice_date IS NULL OR due_date >= invoice_date")
@dlt.expect("referential_customer", "customer_sk IS NOT NULL")
def silver_invoice():
    inv = dlt.read("bronze_erp_invoices")
    cust = dlt.read("silver_customer").select("customer_sk", "erp_customer_id")

    base = (
        inv.join(cust, inv.customer_id == cust.erp_customer_id, "left")
        .select(
            F.col("invoice_id"),
            F.col("customer_sk"),
            F.col("customer_id").alias("erp_customer_id"),
            F.to_date("invoice_date").alias("invoice_date")
            if "invoice_date" in inv.columns
            else F.lit(None).cast("date").alias("invoice_date"),
            F.to_date("due_date").alias("due_date") if "due_date" in inv.columns
            else F.lit(None).cast("date").alias("due_date"),
            F.col("gross_amount").cast("decimal(18,2)").alias("gross_amount")
            if "gross_amount" in inv.columns
            else F.col("amount").cast("decimal(18,2)").alias("gross_amount"),
            F.upper(F.col("currency")).alias("currency") if "currency" in inv.columns
            else F.lit(None).cast("string").alias("currency"),
            (F.col("is_disputed").cast("boolean")
             if "is_disputed" in inv.columns
             else F.lit(False)).alias("is_disputed"),
        )
    )

    # Aggregate applied payments per invoice.
    pay = (
        dlt.read("silver_payment")
        .where("invoice_id IS NOT NULL")
        .groupBy("invoice_id")
        .agg(F.sum("payment_amount").alias("amount_paid"))
    )

    tol = F.lit(0.01)  # rounding tolerance for "fully paid"
    return (
        base.join(pay, "invoice_id", "left")
        .withColumn("amount_paid", F.coalesce(F.col("amount_paid"), F.lit(0).cast("decimal(18,2)")))
        .withColumn("open_amount", F.col("gross_amount") - F.col("amount_paid"))
        .withColumn("is_paid", F.col("open_amount") <= tol)
        .withColumn(
            "is_partial",
            (F.col("amount_paid") > 0) & (F.col("amount_paid") < F.col("gross_amount") - tol),
        )
        .withColumn(
            "is_late",
            (F.col("open_amount") > tol)
            & F.col("due_date").isNotNull()
            & (F.col("due_date") < F.current_date()),
        )
        .withColumn(
            "days_past_due",
            F.when(
                (F.col("open_amount") > tol) & F.col("due_date").isNotNull(),
                F.datediff(F.current_date(), F.col("due_date")),
            ).otherwise(F.lit(0)),
        )
    )
