"""Reference / dimension data generator for the commercial data platform.

Generates the shared reference datasets that both CRM and ERP feeds join to:
  * fiscal_calendar    - daily dates with fiscal year / quarter / period
  * product_hierarchy  - division -> category -> subcategory -> product
  * currency_rates     - daily FX rates per currency vs USD
  * country_codes      - ISO country codes + currency + region

These are full-snapshot dimensions (no date partitioning) except
``currency_rates`` which is emitted as one row per (date, currency).

Pure standard library. Usage:
    python data_gen/reference_data_generator.py --out data_gen/output/reference --years 2
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from common import (
    CURRENCIES,
    CURRENCY_BASE_PER_USD,
    fiscal_period_of,
    fiscal_year_of,
    make_rng,
    write_entity,
    write_json_doc,
)

COUNTRIES: list[dict[str, str]] = [
    {"country_code": "US", "country_name": "United States", "currency": "USD", "region": "AMER"},
    {"country_code": "CA", "country_name": "Canada", "currency": "CAD", "region": "AMER"},
    {"country_code": "BR", "country_name": "Brazil", "currency": "BRL", "region": "AMER"},
    {"country_code": "GB", "country_name": "United Kingdom", "currency": "GBP", "region": "EMEA"},
    {"country_code": "DE", "country_name": "Germany", "currency": "EUR", "region": "EMEA"},
    {"country_code": "FR", "country_name": "France", "currency": "EUR", "region": "EMEA"},
    {"country_code": "SG", "country_name": "Singapore", "currency": "SGD", "region": "APAC"},
    {"country_code": "AU", "country_name": "Australia", "currency": "AUD", "region": "APAC"},
    {"country_code": "JP", "country_name": "Japan", "currency": "JPY", "region": "APAC"},
    {"country_code": "IN", "country_name": "India", "currency": "INR", "region": "APAC"},
]

# Rheinhardt Industrial's catalog — a B2B industrial-equipment manufacturer.
# Three product divisions mirror the business: Flow (pumps + valves), Power
# (motors + compressors), Care (aftermarket consumables + spare parts). The
# retired "Hardware" (Edge Server / Switch / Router) division was IT-vendor
# residue from the pre-2026-07-04 framing — see docs/business-domain-and-systems.md.
PRODUCT_TREE: dict[str, dict[str, list[str]]] = {
    "Flow": {
        "Pumps": ["Centrifugal Pump", "Diaphragm Pump", "Gear Pump"],
        "Valves": ["Ball Valve", "Gate Valve", "Check Valve"],
    },
    "Power": {
        "Motors": ["AC Induction Motor", "Servo Motor"],
        "Compressors": ["Rotary Screw Compressor", "Reciprocating Compressor"],
    },
    "Care": {
        "Filters": ["HEPA Filter", "Carbon Filter"],
        "Lubricants": ["Synthetic Oil 5L", "Grease Cartridge"],
        "Spare Parts": ["Mechanical Seal Kit", "Bearing Set"],
    },
}


def gen_country_codes() -> list[dict[str, str]]:
    return COUNTRIES


def gen_fiscal_calendar(start: date, years: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    end = date(start.year + years, start.month, start.day)
    d = start
    while d < end:
        fy = fiscal_year_of(d)
        period = fiscal_period_of(d)
        quarter = (period - 1) // 3 + 1
        rows.append({
            "date_key": d.isoformat(),
            "calendar_year": d.year,
            "calendar_month": d.month,
            "day_of_week": d.isoweekday(),
            "is_weekend": d.isoweekday() >= 6,
            "fiscal_year": fy,
            "fiscal_quarter": f"FY{fy}-Q{quarter}",
            "fiscal_period": period,
        })
        d += timedelta(days=1)
    return rows


def gen_product_hierarchy() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pid = 0
    for division, cats in PRODUCT_TREE.items():
        for category, subs in cats.items():
            for sub in subs:
                pid += 1
                rows.append({
                    "product_hier_id": f"PH{pid:05d}",
                    "division": division,
                    "category": category,
                    "subcategory": sub,
                    "product_name": sub,
                })
    return rows


def gen_currency_rates(start: date, years: int, seed: int) -> list[dict[str, object]]:
    rng = make_rng(seed)
    rows: list[dict[str, object]] = []
    end = date(start.year + years, start.month, start.day)
    drift: dict[str, float] = {c: CURRENCY_BASE_PER_USD[c] for c in CURRENCIES}
    d = start
    while d < end:
        for cur in CURRENCIES:
            if cur == "USD":
                rate = 1.0
            else:
                # small random walk around base
                base = CURRENCY_BASE_PER_USD[cur]
                drift[cur] += rng.uniform(-0.01, 0.01) * base
                drift[cur] = max(base * 0.85, min(base * 1.15, drift[cur]))
                rate = round(drift[cur], 6)
            rows.append({
                "rate_date": d.isoformat(),
                "from_currency": cur,
                "to_currency": "USD",
                "rate_to_usd": round(1.0 / rate, 8) if rate else 1.0,
                "units_per_usd": rate,
            })
        d += timedelta(days=1)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate reference/dimension data.")
    parser.add_argument("--out", required=True, help="Output base directory")
    parser.add_argument("--years", type=int, default=2, help="Number of years to cover")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--start", default=None,
                        help="Start date YYYY-MM-DD (default: Jan 1, two years ago)")
    args = parser.parse_args()

    out = Path(args.out)
    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = date(date.today().year - 1, 1, 1)

    countries = gen_country_codes()
    fiscal = gen_fiscal_calendar(start, args.years)
    hierarchy = gen_product_hierarchy()
    rates = gen_currency_rates(start, args.years, args.seed)

    write_entity(countries, out, "country_codes", fmt=args.format)
    write_entity(fiscal, out, "fiscal_calendar", fmt=args.format)
    write_entity(hierarchy, out, "product_hierarchy", fmt=args.format)
    write_entity(rates, out, "currency_rates", fmt=args.format)

    write_json_doc(
        {
            "generated": "reference",
            "start": start.isoformat(),
            "years": args.years,
            "counts": {
                "country_codes": len(countries),
                "fiscal_calendar": len(fiscal),
                "product_hierarchy": len(hierarchy),
                "currency_rates": len(rates),
            },
        },
        out / "_manifest" / "reference_manifest.json",
    )
    print(f"Reference data written to {out} "
          f"(countries={len(countries)}, fiscal_days={len(fiscal)}, "
          f"products={len(hierarchy)}, rates={len(rates)})")


if __name__ == "__main__":
    main()
