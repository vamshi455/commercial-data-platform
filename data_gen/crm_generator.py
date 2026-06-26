"""CRM (Salesforce-like) synthetic data generator.

Generates ALL CRM entities with referential integrity and lifecycle behavior:

  users, territories, accounts, contacts, leads, opportunities,
  opportunity_line_items, quotes, contracts, activities, cases

Key behaviors modeled:
  * leads convert into accounts + contacts + opportunities
  * opportunities progress through stages across dated snapshots
    (Prospecting -> Qualification -> Proposal -> Negotiation ->
     Closed Won / Closed Lost)
  * closed-won opportunities generate quotes and contracts
  * cases link to accounts and contacts
  * PII fields included throughout; free-text notes/comments included
  * a CRM<->ERP crosswalk is written so ERP customers can be aligned to
    CRM accounts for identity resolution downstream

Output layout:
  Dimensions (full snapshot):   <out>/<entity>/<entity>.csv
  Incremental (dated):          <out>/<entity>/dt=YYYY-MM-DD/<entity>.csv

Usage:
    python data_gen/crm_generator.py --out data_gen/output/crm --days 7 \
        --seed 42 --accounts 50 --format csv
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from common import (
    Crosswalk,
    SF_PREFIX,
    address,
    address_str,
    company_name,
    full_name,
    job_title,
    make_rng,
    phone_number,
    random_datetime_on,
    salesforce_id,
    save_crosswalk,
    work_email,
    write_entity,
    write_json_doc,
)

OPP_STAGES: list[str] = [
    "Prospecting", "Qualification", "Proposal", "Negotiation",
]
CLOSED_WON = "Closed Won"
CLOSED_LOST = "Closed Lost"

INDUSTRIES = ["Manufacturing", "Retail", "Energy", "Healthcare", "Technology",
              "Logistics", "Financial Services", "Public Sector"]
ACCOUNT_TYPES = ["Customer", "Prospect", "Partner"]
ACCOUNT_RATINGS = ["Hot", "Warm", "Cold"]
LEAD_SOURCES = ["Web", "Trade Show", "Referral", "Outbound", "Webinar", "Partner"]
LEAD_STATUSES = ["New", "Working", "Nurturing", "Qualified", "Converted", "Unqualified"]
CASE_PRIORITIES = ["Low", "Medium", "High", "Critical"]
CASE_STATUSES = ["New", "In Progress", "Escalated", "Closed"]
CASE_ORIGINS = ["Phone", "Email", "Web", "Portal"]
ACTIVITY_TYPES = ["Call", "Email", "Meeting", "Demo", "Follow-up"]
PRODUCTS = [
    ("Edge Server", 8500.0), ("Rack Server", 14200.0), ("Switch 24p", 3200.0),
    ("Router XL", 5400.0), ("Centrifugal Pump", 2100.0), ("Ball Valve", 320.0),
    ("HEPA Filter", 95.0), ("Synthetic Oil 5L", 60.0), ("Gateway Pro", 1800.0),
]

SALES_NOTE_TEMPLATES = [
    "Spoke with {name} ({title}). Budget approved for Q{q}, decision by EOM.",
    "{name} raised concerns about delivery lead times; needs reassurance.",
    "Competitor incumbent. {name} is the champion, CFO is the blocker.",
    "Renewal at risk - {name} unhappy with last support ticket. Escalate.",
    "Expansion opportunity: {name} wants to roll out to 3 more plants.",
]
CASE_COMMENT_TEMPLATES = [
    "Customer {name} reports unit overheating under load. Replacement shipped.",
    "{name} called re: invoice mismatch; routed to billing. Awaiting RMA.",
    "Firmware bug confirmed by engineering. Patch ETA 5 business days.",
    "{name} satisfied with workaround; will close after confirmation.",
]


def gen_users(rng, n: int) -> list[dict[str, Any]]:
    rows = []
    for _ in range(n):
        first, last = full_name(rng)
        rows.append({
            "user_id": salesforce_id(rng, SF_PREFIX["user"]),
            "first_name": first,
            "last_name": last,
            "work_email": f"{first.lower()}.{last.lower()}@ourcompany.com",
            "phone": phone_number(rng),
            "job_title": rng.choice(["Account Executive", "Sales Manager",
                                     "SDR", "Solutions Engineer", "CSM"]),
            "is_active": rng.random() > 0.1,
        })
    return rows


def gen_territories(rng, n: int) -> list[dict[str, Any]]:
    regions = ["AMER-West", "AMER-East", "EMEA-North", "EMEA-South", "APAC", "LATAM"]
    rows = []
    for i in range(n):
        rows.append({
            "territory_id": salesforce_id(rng, SF_PREFIX["territory"]),
            "territory_name": regions[i % len(regions)] + f"-{i // len(regions) + 1}",
            "region": regions[i % len(regions)].split("-")[0],
        })
    return rows


def _build_account(rng, users, territories, created_on: date,
                   converted_from_lead: str | None = None) -> dict[str, Any]:
    name = company_name(rng)
    addr = address(rng)
    owner = rng.choice(users)
    terr = rng.choice(territories)
    return {
        "account_id": salesforce_id(rng, SF_PREFIX["account"]),
        "account_name": name,
        "account_type": rng.choice(ACCOUNT_TYPES),
        "industry": rng.choice(INDUSTRIES),
        "rating": rng.choice(ACCOUNT_RATINGS),
        "annual_revenue": rng.randint(1_000_000, 500_000_000),
        "employees": rng.randint(50, 50_000),
        "office_address": address_str(addr),
        "billing_country": addr["country_code"],
        "phone": phone_number(rng),
        "owner_user_id": owner["user_id"],
        "territory_id": terr["territory_id"],
        "converted_from_lead_id": converted_from_lead or "",
        "created_date": created_on.isoformat(),
        "_company_key": name.lower().replace(" ", "_"),
        "_country": addr["country_code"],
    }


def _build_contact(rng, account: dict[str, Any], created_on: date,
                   is_primary: bool = False) -> dict[str, Any]:
    first, last = full_name(rng)
    return {
        "contact_id": salesforce_id(rng, SF_PREFIX["contact"]),
        "account_id": account["account_id"],
        "first_name": first,
        "last_name": last,
        "work_email": work_email(rng, first, last, account["account_name"],
                                 account.get("_country", "US")),
        "phone": phone_number(rng),
        "mobile_phone": phone_number(rng),
        "job_title": job_title(rng),
        "office_address": account["office_address"],
        "is_primary": is_primary,
        "created_date": created_on.isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CRM synthetic data.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--accounts", type=int, default=50)
    parser.add_argument("--format", choices=["csv", "json"], default="csv")
    parser.add_argument("--start", default=None,
                        help="First batch date YYYY-MM-DD (default: today - days + 1)")
    args = parser.parse_args()

    rng = make_rng(args.seed)
    out = Path(args.out)
    fmt = args.format

    if args.start:
        start = date.fromisoformat(args.start)
    else:
        start = date.today() - timedelta(days=args.days - 1)
    batch_dates = [start + timedelta(days=i) for i in range(args.days)]

    # --- Dimensions: users + territories (full snapshot) ---------------------
    users = gen_users(rng, max(5, args.accounts // 8))
    territories = gen_territories(rng, max(3, args.accounts // 12))
    write_entity(users, out, "users", fmt=fmt)
    write_entity(territories, out, "territories", fmt=fmt)

    # --- Accounts & contacts: roughly 70% pre-existing, 30% lead-converted ---
    accounts: list[dict[str, Any]] = []
    contacts: list[dict[str, Any]] = []
    leads: list[dict[str, Any]] = []

    # Each account gets a creation date within the batch window so accounts
    # also flow as incremental records.
    accounts_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    contacts_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    leads_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}

    n_converted = int(args.accounts * 0.3)

    for i in range(args.accounts):
        created_on = rng.choice(batch_dates)
        converted_lead_id = ""
        if i < n_converted:
            # create a lead that converts into this account
            lf, ll = full_name(rng)
            lead_addr = address(rng)
            lead_company = company_name(rng)
            lead_id = salesforce_id(rng, SF_PREFIX["lead"])
            lead_created = max(start, created_on - timedelta(days=rng.randint(1, 5)))
            lead = {
                "lead_id": lead_id,
                "first_name": lf,
                "last_name": ll,
                "company": lead_company,
                "work_email": work_email(rng, lf, ll, lead_company,
                                         lead_addr["country_code"]),
                "phone": phone_number(rng),
                "job_title": job_title(rng),
                "office_address": address_str(lead_addr),
                "lead_source": rng.choice(LEAD_SOURCES),
                "status": "Converted",
                "rating": rng.choice(ACCOUNT_RATINGS),
                "created_date": lead_created.isoformat(),
                "converted_date": created_on.isoformat(),
                "converted_account_id": "",  # filled below
            }
            converted_lead_id = lead_id
        acct = _build_account(rng, users, territories, created_on, converted_lead_id or None)
        accounts.append(acct)
        accounts_by_date[created_on].append(acct)

        if converted_lead_id:
            lead["converted_account_id"] = acct["account_id"]
            leads.append(lead)
            lead_part = lead_created if lead_created in leads_by_date else created_on
            leads_by_date[lead_part].append(lead)

        # 1-4 contacts per account
        n_contacts = rng.randint(1, 4)
        for c in range(n_contacts):
            contact = _build_contact(rng, acct, created_on, is_primary=(c == 0))
            contacts.append(contact)
            contacts_by_date[created_on].append(contact)

    # Add some non-converting (open) leads that never became accounts.
    n_open_leads = int(args.accounts * 0.4)
    for _ in range(n_open_leads):
        lf, ll = full_name(rng)
        lead_addr = address(rng)
        lead_company = company_name(rng)
        created_on = rng.choice(batch_dates)
        lead = {
            "lead_id": salesforce_id(rng, SF_PREFIX["lead"]),
            "first_name": lf,
            "last_name": ll,
            "company": lead_company,
            "work_email": work_email(rng, lf, ll, lead_company, lead_addr["country_code"]),
            "phone": phone_number(rng),
            "job_title": job_title(rng),
            "office_address": address_str(lead_addr),
            "lead_source": rng.choice(LEAD_SOURCES),
            "status": rng.choice([s for s in LEAD_STATUSES if s != "Converted"]),
            "rating": rng.choice(ACCOUNT_RATINGS),
            "created_date": created_on.isoformat(),
            "converted_date": "",
            "converted_account_id": "",
        }
        leads.append(lead)
        leads_by_date[created_on].append(lead)

    # --- Opportunities: one or more per account, staged over snapshots -------
    # Each opportunity has a "current stage per day" snapshot row so the
    # opportunity entity is a dated, incremental, slowly-progressing feed.
    opp_snapshots_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    line_items_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    quotes_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    contracts_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}

    crosswalk = Crosswalk(meta={"source": "crm_generator", "seed": args.seed})
    all_line_items_master: list[dict[str, Any]] = []

    for acct in accounts:
        # ~60% of accounts have an active opportunity
        if rng.random() > 0.6:
            continue
        opp_id = salesforce_id(rng, SF_PREFIX["opportunity"])
        acct_contacts = [c for c in contacts if c["account_id"] == acct["account_id"]]
        primary_contact = acct_contacts[0] if acct_contacts else None
        amount = 0.0

        # Build line items once (referential integrity to product list).
        n_items = rng.randint(1, 4)
        item_rows = []
        for _ in range(n_items):
            prod, unit = rng.choice(PRODUCTS)
            qty = rng.randint(1, 25)
            line_total = round(unit * qty, 2)
            amount += line_total
            item_rows.append({
                "line_item_id": salesforce_id(rng, SF_PREFIX["line_item"]),
                "opportunity_id": opp_id,
                "product_name": prod,
                "quantity": qty,
                "unit_price": unit,
                "total_price": line_total,
            })
        all_line_items_master.extend(item_rows)

        # Determine final outcome and a progression timeline.
        will_close = rng.random() > 0.35
        won = will_close and rng.random() > 0.4
        # pick the index in batch_dates where the opp starts surfacing
        start_idx = rng.randint(0, max(0, args.days - 2))
        owner = acct["owner_user_id"]
        note = rng.choice(SALES_NOTE_TEMPLATES).format(
            name=(primary_contact["first_name"] if primary_contact else "the buyer"),
            title=(primary_contact["job_title"] if primary_contact else "buyer"),
            q=rng.randint(1, 4),
        )

        close_date_target = batch_dates[-1] + timedelta(days=rng.randint(5, 30))

        for offset, d in enumerate(batch_dates[start_idx:]):
            # progress one stage roughly every couple of days
            stage_idx = min(offset // 1, len(OPP_STAGES) - 1)
            stage = OPP_STAGES[stage_idx]
            is_last_day = (d == batch_dates[-1])
            is_closed = False
            if will_close and is_last_day:
                stage = CLOSED_WON if won else CLOSED_LOST
                is_closed = True
            probability = {
                "Prospecting": 10, "Qualification": 25, "Proposal": 50,
                "Negotiation": 75, CLOSED_WON: 100, CLOSED_LOST: 0,
            }[stage]
            opp_snapshots_by_date[d].append({
                "opportunity_id": opp_id,
                "account_id": acct["account_id"],
                "primary_contact_id": primary_contact["contact_id"] if primary_contact else "",
                "opportunity_name": f"{acct['account_name']} - New Business",
                "stage": stage,
                "probability": probability,
                "amount": round(amount, 2),
                "currency": "USD",
                "owner_user_id": owner,
                "close_date": close_date_target.isoformat(),
                "is_closed": is_closed,
                "is_won": (stage == CLOSED_WON),
                "snapshot_date": d.isoformat(),
                "sales_notes": note,
            })

        # Line items surface on the opp's first visible day.
        first_day = batch_dates[start_idx]
        for it in item_rows:
            line_items_by_date[first_day].append(it)

        # Closed-won -> quote + contract on the last day.
        if won:
            last_day = batch_dates[-1]
            signer_first, signer_last = full_name(rng)
            quote_id = salesforce_id(rng, SF_PREFIX["quote"])
            quotes_by_date[last_day].append({
                "quote_id": quote_id,
                "opportunity_id": opp_id,
                "account_id": acct["account_id"],
                "quote_total": round(amount, 2),
                "currency": "USD",
                "status": "Accepted",
                "expiration_date": (last_day + timedelta(days=30)).isoformat(),
                "created_date": last_day.isoformat(),
            })
            contracts_by_date[last_day].append({
                "contract_id": salesforce_id(rng, SF_PREFIX["contract"]),
                "account_id": acct["account_id"],
                "opportunity_id": opp_id,
                "quote_id": quote_id,
                "contract_value": round(amount, 2),
                "currency": "USD",
                "start_date": last_day.isoformat(),
                "end_date": (last_day + timedelta(days=365)).isoformat(),
                "term_months": 12,
                "status": "Activated",
                "contract_signer_name": f"{signer_first} {signer_last}",
                "created_date": last_day.isoformat(),
            })

        # Register account in crosswalk; ~55% of accounts also exist in ERP.
        crosswalk.add_account(
            acct["_company_key"],
            company_name=acct["account_name"],
            crm_account_id=acct["account_id"],
            country=acct["_country"],
            in_erp=rng.random() < 0.55,
        )

    # --- Activities: tied to accounts/contacts/opps, dated ------------------
    activities_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    for _ in range(args.accounts * 3):
        acct = rng.choice(accounts)
        acct_contacts = [c for c in contacts if c["account_id"] == acct["account_id"]]
        contact = rng.choice(acct_contacts) if acct_contacts else None
        d = rng.choice(batch_dates)
        when = random_datetime_on(rng, d)
        activities_by_date[d].append({
            "activity_id": salesforce_id(rng, SF_PREFIX["activity"]),
            "account_id": acct["account_id"],
            "contact_id": contact["contact_id"] if contact else "",
            "owner_user_id": acct["owner_user_id"],
            "activity_type": rng.choice(ACTIVITY_TYPES),
            "subject": rng.choice(["Intro call", "Pricing discussion",
                                   "Technical demo", "QBR", "Renewal check-in"]),
            "activity_datetime": when.isoformat(),
            "is_completed": rng.random() > 0.3,
        })

    # --- Cases: link to accounts/contacts, dated ----------------------------
    cases_by_date: dict[date, list[dict[str, Any]]] = {d: [] for d in batch_dates}
    for _ in range(args.accounts):
        acct = rng.choice(accounts)
        acct_contacts = [c for c in contacts if c["account_id"] == acct["account_id"]]
        contact = rng.choice(acct_contacts) if acct_contacts else None
        d = rng.choice(batch_dates)
        cname = contact["first_name"] if contact else "the customer"
        cases_by_date[d].append({
            "case_id": salesforce_id(rng, SF_PREFIX["case"]),
            "account_id": acct["account_id"],
            "contact_id": contact["contact_id"] if contact else "",
            "case_number": f"CS-{rng.randint(100000, 999999)}",
            "priority": rng.choice(CASE_PRIORITIES),
            "status": rng.choice(CASE_STATUSES),
            "origin": rng.choice(CASE_ORIGINS),
            "subject": rng.choice(["Product defect", "Billing question",
                                   "Shipping delay", "Firmware issue",
                                   "Account access"]),
            "case_comment": rng.choice(CASE_COMMENT_TEMPLATES).format(name=cname),
            "opened_date": d.isoformat(),
        })

    # --- Write dated/incremental entities -----------------------------------
    for d in batch_dates:
        write_entity(accounts_by_date[d], out, "accounts", fmt=fmt, partition_date=d)
        write_entity(contacts_by_date[d], out, "contacts", fmt=fmt, partition_date=d)
        write_entity(leads_by_date[d], out, "leads", fmt=fmt, partition_date=d)
        write_entity(opp_snapshots_by_date[d], out, "opportunities", fmt=fmt, partition_date=d)
        write_entity(line_items_by_date[d], out, "opportunity_line_items", fmt=fmt, partition_date=d)
        write_entity(quotes_by_date[d], out, "quotes", fmt=fmt, partition_date=d)
        write_entity(contracts_by_date[d], out, "contracts", fmt=fmt, partition_date=d)
        write_entity(activities_by_date[d], out, "activities", fmt=fmt, partition_date=d)
        write_entity(cases_by_date[d], out, "cases", fmt=fmt, partition_date=d)

    # --- Crosswalk + manifest ------------------------------------------------
    save_crosswalk(crosswalk, out)
    write_json_doc(
        {
            "generated": "crm",
            "seed": args.seed,
            "batch_dates": [d.isoformat() for d in batch_dates],
            "counts": {
                "users": len(users),
                "territories": len(territories),
                "accounts": len(accounts),
                "contacts": len(contacts),
                "leads": len(leads),
                "opportunity_snapshots": sum(len(v) for v in opp_snapshots_by_date.values()),
                "line_items": len(all_line_items_master),
                "quotes": sum(len(v) for v in quotes_by_date.values()),
                "contracts": sum(len(v) for v in contracts_by_date.values()),
                "activities": sum(len(v) for v in activities_by_date.values()),
                "cases": sum(len(v) for v in cases_by_date.values()),
            },
        },
        out / "_manifest" / "crm_manifest.json",
    )

    print(f"CRM data written to {out} across {args.days} dated batches "
          f"(accounts={len(accounts)}, contacts={len(contacts)}, leads={len(leads)}). "
          f"Crosswalk saved for CRM<->ERP identity resolution.")


if __name__ == "__main__":
    main()
