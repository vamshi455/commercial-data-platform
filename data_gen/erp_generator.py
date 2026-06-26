"""ERP (SAP-like) synthetic data generator.

Generates ALL ERP entities with referential integrity:

  customers, vendors, products, sales_orders, sales_order_items,
  billing_documents, invoices, payments, purchase_orders, gl_entries,
  cost_centers, profit_centers, currency_rates

Key behaviors modeled:
  * order -> order items -> billing document -> invoice -> payment chain
  * payment anomalies: paid on time, paid late, partial payment, disputed,
    or still open
  * SCD (slowly changing dimension) history for products and org units
    (cost/profit centers) with effective-dated versions
  * daily currency_rates (a small random walk vs USD)
  * masked/tokenized tax_id, bank references, payment contact emails (PII)
  * reads the CRM crosswalk (if present) to align some ERP customers to CRM
    accounts, sharing company name / country for identity resolution

Output layout:
  Dimensions (full snapshot):   <out>/<entity>/<entity>.csv
  Incremental (dated):          <out>/<entity>/dt=YYYY-MM-DD/<entity>.csv

Usage:
    python data_gen/erp_generator.py --out data_gen/output/erp --days 7 \
        --seed 42 --customers 60 --format csv \
        --crm-out data_gen/output/crm
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import (
    CURRENCIES,
    CURRENCY_BASE_PER_USD,
    address,
    address_str,
    company_name,
    find_crosswalk,
    full_name,
    last4,
    make_rng,
    mask_email,
    mask_tax_id,
    phone_number,
    seq_sap_id,
    tokenize,
    work_email,
    write_entity,
    write_json_doc,
)

PAYMENT_TERMS = ["NET30", "NET45", "NET60", "NET15"]
PAYMENT_OUTCOMES = ["on_time", "late", "partial", "disputed", "open"]
# weights for realism
PAYMENT_WEIGHTS = [0.55, 0.20, 0.10, 0.05, 0.10]

PRODUCTS = [
    # (material_desc, base_price, division, profit_center_seed)
    ("Edge Server", 8500.0, "Hardware"),
    ("Rack Server", 14200.0, "Hardware"),
    ("Switch 24p", 3200.0, "Hardware"),
    ("Router XL", 5400.0, "Hardware"),
    ("Centrifugal Pump", 2100.0, "Industrial"),
    ("Ball Valve", 320.0, "Industrial"),
    ("HEPA Filter", 95.0, "Consumables"),
    ("Synthetic Oil 5L", 60.0, "Consumables"),
    ("Gateway Pro", 1800.0, "Hardware"),
]

GL_ACCOUNTS = {
    "revenue": "0000400000",
    "ar": "0000140000",
    "cash": "0000113000",
    "ap": "0000160000",
    "expense": "0000500000",
}


def _payment_term_days(term: str) -> int:
    return int(term.replace("NET", ""))


def gen_cost_centers(rng, n: int, batch_dates: list[date]) -> list[dict[str, Any]]:
    """Cost centers with SCD2-style effective-dated versions (org changes)."""
    names = ["Sales", "Marketing", "R&D", "Operations", "Finance", "IT", "Support"]
    rows = []
    for i in range(n):
        cc_id = f"CC{1000 + i}"
        base_name = names[i % len(names)]
        # initial version
        eff_start = batch_dates[0]
        rows.append({
            "cost_center_id": cc_id,
            "cost_center_name": base_name,
            "manager_employee_id": tokenize(f"emp-{cc_id}"),
            "company_code": "1000",
            "valid_from": eff_start.isoformat(),
            "valid_to": "9999-12-31",
            "is_current": True,
            "scd_version": 1,
        })
        # mid-window reorg for ~30%: close v1, open v2
        if rng.random() < 0.3 and len(batch_dates) > 2:
            change_day = batch_dates[len(batch_dates) // 2]
            rows[-1]["valid_to"] = (change_day - timedelta(days=1)).isoformat()
            rows[-1]["is_current"] = False
            rows.append({
                "cost_center_id": cc_id,
                "cost_center_name": base_name + " (Reorg)",
                "manager_employee_id": tokenize(f"emp-{cc_id}-v2"),
                "company_code": "1000",
                "valid_from": change_day.isoformat(),
                "valid_to": "9999-12-31",
                "is_current": True,
                "scd_version": 2,
            })
    return rows


def gen_profit_centers(rng, n: int) -> list[dict[str, Any]]:
    divisions = ["Hardware", "Industrial", "Consumables", "Services"]
    rows = []
    for i in range(n):
        rows.append({
            "profit_center_id": f"PC{2000 + i}",
            "profit_center_name": divisions[i % len(divisions)] + f"-{i // len(divisions) + 1}",
            "division": divisions[i % len(divisions)],
            "company_code": "1000",
        })
    return rows


def gen_products_scd(rng, batch_dates: list[date]) -> list[dict[str, Any]]:
    """Product master with SCD price changes over the batch window."""
    rows = []
    for idx, (desc, price, division) in enumerate(PRODUCTS):
        matnr = seq_sap_id(idx, width=8, base=80000000)
        # version 1
        rows.append({
            "material_id": matnr,
            "material_desc": desc,
            "division": division,
            "list_price_usd": price,
            "base_unit": "EA",
            "valid_from": batch_dates[0].isoformat(),
            "valid_to": "9999-12-31",
            "is_current": True,
            "scd_version": 1,
        })
        # ~25% get a price change partway through
        if rng.random() < 0.25 and len(batch_dates) > 2:
            change_day = batch_dates[len(batch_dates) // 2]
            new_price = round(price * rng.uniform(1.03, 1.12), 2)
            rows[-1]["valid_to"] = (change_day - timedelta(days=1)).isoformat()
            rows[-1]["is_current"] = False
            rows.append({
                "material_id": matnr,
                "material_desc": desc,
                "division": division,
                "list_price_usd": new_price,
                "base_unit": "EA",
                "valid_from": change_day.isoformat(),
                "valid_to": "9999-12-31",
                "is_current": True,
                "scd_version": 2,
            })
    return rows


def gen_currency_rates(rng, batch_dates: list[date]) -> dict[date, list[dict[str, Any]]]:
    out: dict[date, list[dict[str, Any]]] = {}
    drift = {c: CURRENCY_BASE_PER_USD[c] for c in CURRENCIES}
    for d in batch_dates:
        rows = []
        for cur in CURRENCIES:
            if cur == "USD":
                rate = 1.0
            else:
                base = CURRENCY_BASE_PER_USD[cur]
                drift[cur] += rng.uniform(-0.01, 0.01) * base
                drift[cur] = max(base * 0.85, min(base * 1.15, drift[cur]))
                rate = round(drift[cur], 6)
            rows.append({
                "rate_date": d.isoformat(),
                "from_currency": cur,
                "to_currency": "USD",
                "units_per_usd": rate,
                "rate_to_usd": round(1.0 / rate, 8) if rate else 1.0,
            })
        out[d] = rows
    return out


def _build_customer(rng, idx, batch_dates, crm_account=None) -> dict[str, Any]:
    if crm_account is not None:
        name = crm_account["company_name"]
        country = crm_account.get("country", "US")
        crm_id = crm_account["crm_account_id"]
    else:
        name = company_name(rng)
        country = address(rng)["country_code"]
        crm_id = ""
    addr = address(rng)
    addr["country_code"] = country
    first, last = full_name(rng)
    raw_tax_id = f"{country}{rng.randint(100000000, 999999999)}"
    currency = rng.choice([c for c in CURRENCIES])
    return {
        "customer_id": seq_sap_id(idx, width=10, base=1000000),  # KUNNR-style
        "customer_name": name,
        "country": country,
        "currency": currency,
        "billing_contact_name": f"{first} {last}",
        "billing_address": address_str(addr),
        "payment_contact_email": mask_email(work_email(rng, first, last, name, country)),
        "payment_contact_email_token": tokenize(work_email(rng, first, last, name, country)),
        "phone": phone_number(rng),
        "tax_id_masked": mask_tax_id(raw_tax_id),
        "payment_terms": rng.choice(PAYMENT_TERMS),
        "credit_limit_usd": rng.randint(50_000, 5_000_000),
        "crm_account_id": crm_id,  # crosswalk linkage
        "created_date": rng.choice(batch_dates).isoformat(),
    }


def _build_vendor(rng, idx, batch_dates) -> dict[str, Any]:
    name = company_name(rng) + " Supply"
    addr = address(rng)
    first, last = full_name(rng)
    raw_tax_id = f"{addr['country_code']}{rng.randint(100000000, 999999999)}"
    return {
        "vendor_id": seq_sap_id(idx, width=10, base=5000000),  # LIFNR-style
        "vendor_name": name,
        "country": addr["country_code"],
        "vendor_contact_name": f"{first} {last}",
        "vendor_address": address_str(addr),
        "payment_contact_email": mask_email(work_email(rng, first, last, name, addr["country_code"])),
        "tax_id_masked": mask_tax_id(raw_tax_id),
        "bank_reference_last4": last4(f"{rng.randint(10000000, 99999999)}{rng.randint(1000, 9999)}"),
        "payment_terms": rng.choice(PAYMENT_TERMS),
        "created_date": rng.choice(batch_dates).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ERP synthetic data.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--customers", type=int, default=60)
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--start", default=None,
                        help="First batch date YYYY-MM-DD (default: today - days + 1)")
    parser.add_argument("--crm-out", default=None,
                        help="CRM output dir to read the crosswalk from")
    args = parser.parse_args()

    rng = make_rng(args.seed)
    out = Path(args.out)
    fmt = args.format

    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = date.today() - timedelta(days=args.days - 1)
    batch_dates = [start + timedelta(days=i) for i in range(args.days)]

    # --- Read CRM crosswalk to align some ERP customers ---------------------
    candidate_dirs = []
    if args.crm_out:
        candidate_dirs.append(args.crm_out)
    candidate_dirs += [str(out.parent / "crm"), str(out), str(out.parent)]
    xwalk = find_crosswalk(*candidate_dirs)
    crm_aligned = []
    if xwalk:
        crm_aligned = [a for a in xwalk.accounts.values() if a.get("in_erp")]

    # --- Dimensions ---------------------------------------------------------
    products = gen_products_scd(rng, batch_dates)
    cost_centers = gen_cost_centers(rng, max(4, args.customers // 8), batch_dates)
    profit_centers = gen_profit_centers(rng, max(4, args.customers // 10))
    write_entity(products, out, "products", fmt=fmt)
    write_entity(cost_centers, out, "cost_centers", fmt=fmt)
    write_entity(profit_centers, out, "profit_centers", fmt=fmt)

    current_products = [p for p in products if p["is_current"]]
    current_pc = [p for p in profit_centers]
    current_cc = [c for c in cost_centers if c["is_current"]]

    # --- Customers (some aligned to CRM accounts) ---------------------------
    customers: list[dict[str, Any]] = []
    n_aligned = min(len(crm_aligned), int(args.customers * 0.4))
    for i in range(args.customers):
        crm_acct = crm_aligned[i] if i < n_aligned else None
        customers.append(_build_customer(rng, i, batch_dates, crm_acct))
    write_entity(customers, out, "customers", fmt=fmt)

    # --- Vendors ------------------------------------------------------------
    vendors = [_build_vendor(rng, i, batch_dates) for i in range(max(5, args.customers // 4))]
    write_entity(vendors, out, "vendors", fmt=fmt)

    # --- Dated transactional entities ---------------------------------------
    orders_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    order_items_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    billing_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    invoices_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    payments_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    gl_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    po_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}

    order_counter = 0
    invoice_counter = 0
    payment_counter = 0
    gl_counter = 0
    po_counter = 0
    billing_counter = 0

    totals = {"orders": 0, "invoices": 0, "payments": 0, "gl": 0, "pos": 0}

    # Sales order -> items -> billing -> invoice -> payment chain.
    for d in batch_dates:
        n_orders_today = rng.randint(args.customers // 3, args.customers)
        for _ in range(n_orders_today):
            customer = rng.choice(customers)
            order_id = seq_sap_id(order_counter, width=10, base=4500000000)  # VBELN
            order_counter += 1
            pc = rng.choice(current_pc)
            cc = rng.choice(current_cc)
            order_total = 0.0
            n_items = rng.randint(1, 5)
            for line in range(n_items):
                prod = rng.choice(current_products)
                qty = rng.randint(1, 40)
                net = round(prod["list_price_usd"] * qty, 2)
                order_total += net
                order_items_by_date[d].append({
                    "order_id": order_id,
                    "item_number": (line + 1) * 10,
                    "material_id": prod["material_id"],
                    "material_desc": prod["material_desc"],
                    "quantity": qty,
                    "unit_price_usd": prod["list_price_usd"],
                    "net_amount_usd": net,
                    "profit_center_id": pc["profit_center_id"],
                })
            order_total = round(order_total, 2)
            orders_by_date[d].append({
                "order_id": order_id,
                "customer_id": customer["customer_id"],
                "customer_name": customer["customer_name"],
                "order_date": d.isoformat(),
                "currency": "USD",
                "net_total_usd": order_total,
                "payment_terms": customer["payment_terms"],
                "profit_center_id": pc["profit_center_id"],
                "cost_center_id": cc["cost_center_id"],
                "status": "Open",
            })
            totals["orders"] += 1

            # Billing document
            billing_id = seq_sap_id(billing_counter, width=10, base=9000000000)
            billing_counter += 1
            billing_by_date[d].append({
                "billing_doc_id": billing_id,
                "order_id": order_id,
                "customer_id": customer["customer_id"],
                "billing_date": d.isoformat(),
                "net_amount_usd": order_total,
                "tax_amount_usd": round(order_total * 0.1, 2),
                "gross_amount_usd": round(order_total * 1.1, 2),
                "currency": "USD",
            })

            # Invoice
            invoice_id = seq_sap_id(invoice_counter, width=10, base=8000000000)
            invoice_counter += 1
            gross = round(order_total * 1.1, 2)
            term_days = _payment_term_days(customer["payment_terms"])
            due_date = d + timedelta(days=term_days)
            invoices_by_date[d].append({
                "invoice_id": invoice_id,
                "billing_doc_id": billing_id,
                "order_id": order_id,
                "customer_id": customer["customer_id"],
                "billing_contact_name": customer["billing_contact_name"],
                "billing_address": customer["billing_address"],
                "payment_contact_email": customer["payment_contact_email"],
                "invoice_date": d.isoformat(),
                "due_date": due_date.isoformat(),
                "amount_usd": gross,
                "currency": "USD",
                "status": "Posted",
            })
            totals["invoices"] += 1

            # GL entries (revenue + AR), double-entry
            for acct_key, dc, amt in [("ar", "D", gross), ("revenue", "C", order_total),
                                      ("revenue", "C", round(gross - order_total, 2))]:
                gl_by_date[d].append({
                    "gl_doc_id": seq_sap_id(gl_counter, width=10, base=100000000),
                    "gl_account": GL_ACCOUNTS[acct_key],
                    "invoice_id": invoice_id,
                    "posting_date": d.isoformat(),
                    "debit_credit": dc,
                    "amount_usd": amt,
                    "cost_center_id": cc["cost_center_id"],
                    "profit_center_id": pc["profit_center_id"],
                    "currency": "USD",
                })
                gl_counter += 1
                totals["gl"] += 1

            # Payment with anomalies
            outcome = rng.choices(PAYMENT_OUTCOMES, weights=PAYMENT_WEIGHTS, k=1)[0]
            if outcome == "open":
                continue  # no payment record yet
            if outcome == "on_time":
                pay_date = due_date - timedelta(days=rng.randint(0, term_days))
                paid = gross
                status = "Cleared"
            elif outcome == "late":
                pay_date = due_date + timedelta(days=rng.randint(1, 45))
                paid = gross
                status = "Cleared (Late)"
            elif outcome == "partial":
                pay_date = due_date + timedelta(days=rng.randint(0, 20))
                paid = round(gross * rng.uniform(0.3, 0.8), 2)
                status = "Partial"
            else:  # disputed
                pay_date = due_date + timedelta(days=rng.randint(5, 60))
                paid = 0.0
                status = "Disputed"

            # only emit the payment if its date falls in the window; otherwise
            # clamp to the last batch date so it still surfaces incrementally.
            pay_part = pay_date if pay_date in orders_by_date else batch_dates[-1]
            payment_id = seq_sap_id(payment_counter, width=10, base=7000000000)
            payment_counter += 1
            payments_by_date[pay_part].append({
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "customer_id": customer["customer_id"],
                "payment_date": pay_date.isoformat(),
                "amount_paid_usd": paid,
                "invoice_amount_usd": gross,
                "balance_usd": round(gross - paid, 2),
                "days_late": max(0, (pay_date - due_date).days),
                "outcome": outcome,
                "status": status,
                "bank_reference_last4": last4(str(rng.randint(10**11, 10**12))),
                "currency": "USD",
            })
            totals["payments"] += 1

            if status != "Disputed":
                gl_by_date[pay_part].append({
                    "gl_doc_id": seq_sap_id(gl_counter, width=10, base=100000000),
                    "gl_account": GL_ACCOUNTS["cash"],
                    "invoice_id": invoice_id,
                    "posting_date": pay_date.isoformat(),
                    "debit_credit": "D",
                    "amount_usd": paid,
                    "cost_center_id": cc["cost_center_id"],
                    "profit_center_id": pc["profit_center_id"],
                    "currency": "USD",
                })
                gl_counter += 1
                totals["gl"] += 1

        # Purchase orders to vendors (procurement side)
        for _ in range(rng.randint(1, max(2, args.customers // 10))):
            vendor = rng.choice(vendors)
            prod = rng.choice(current_products)
            qty = rng.randint(10, 200)
            po_total = round(prod["list_price_usd"] * 0.6 * qty, 2)
            po_by_date[d].append({
                "purchase_order_id": seq_sap_id(po_counter, width=10, base=4100000000),
                "vendor_id": vendor["vendor_id"],
                "vendor_name": vendor["vendor_name"],
                "material_id": prod["material_id"],
                "quantity": qty,
                "unit_cost_usd": round(prod["list_price_usd"] * 0.6, 2),
                "net_total_usd": po_total,
                "po_date": d.isoformat(),
                "payment_terms": vendor["payment_terms"],
                "currency": "USD",
                "status": rng.choice(["Open", "Received", "Invoiced"]),
            })
            po_counter += 1
            totals["pos"] += 1

    # --- Currency rates (daily) ---------------------------------------------
    rates_by_date = gen_currency_rates(rng, batch_dates)

    # --- Write dated entities -----------------------------------------------
    for d in batch_dates:
        write_entity(orders_by_date[d], out, "sales_orders", fmt=fmt, partition_date=d)
        write_entity(order_items_by_date[d], out, "sales_order_items", fmt=fmt, partition_date=d)
        write_entity(billing_by_date[d], out, "billing_documents", fmt=fmt, partition_date=d)
        write_entity(invoices_by_date[d], out, "invoices", fmt=fmt, partition_date=d)
        write_entity(payments_by_date[d], out, "payments", fmt=fmt, partition_date=d)
        write_entity(gl_by_date[d], out, "gl_entries", fmt=fmt, partition_date=d)
        write_entity(po_by_date[d], out, "purchase_orders", fmt=fmt, partition_date=d)
        write_entity(rates_by_date[d], out, "currency_rates", fmt=fmt, partition_date=d)

    write_json_doc(
        {
            "generated": "erp",
            "seed": args.seed,
            "batch_dates": [d.isoformat() for d in batch_dates],
            "crm_crosswalk_used": bool(xwalk),
            "customers_aligned_to_crm": n_aligned,
            "counts": {
                "customers": len(customers),
                "vendors": len(vendors),
                "products_scd_rows": len(products),
                "cost_centers_scd_rows": len(cost_centers),
                "profit_centers": len(profit_centers),
                **totals,
            },
        },
        out / "_manifest" / "erp_manifest.json",
    )

    print(f"ERP data written to {out} across {args.days} dated batches "
          f"(customers={len(customers)}, orders={totals['orders']}, "
          f"invoices={totals['invoices']}, payments={totals['payments']}). "
          f"CRM crosswalk {'used' if xwalk else 'not found'}; "
          f"{n_aligned} customers aligned to CRM accounts.")


if __name__ == "__main__":
    main()
