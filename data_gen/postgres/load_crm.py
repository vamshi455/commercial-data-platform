#!/usr/bin/env python3
"""On-demand synthetic CRM loader → local PostgreSQL (cdp_crm.crm.*).

Reuses data_gen/crm_generator.py to produce a CURRENT-STATE snapshot (--days 1)
and UPSERTs each entity into the operational Postgres tables: one current row per
id, last-write-wins. Idempotent — re-run any time to refresh/grow the data.

This is the source that the Databricks Lakeflow JDBC pipeline pulls from (over the
ngrok tunnel) into bronze. It is ON-DEMAND by design — no cron; run it when you
want fresh CRM data:

    python3 data_gen/postgres/load_crm.py --accounts 50 --seed 42

Connection: local unix socket (trust auth) to db cdp_crm as the OS user — no
password needed locally. (The password-protected databricks_reader role is only
for the remote/tunnel path.) Override db with --dbname or PGDATABASE.
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]
GENERATOR = REPO / "data_gen" / "crm_generator.py"

# Parents before children for the ENFORCED foreign keys (see crm_schema.sql).
LOAD_ORDER = [
    "users", "territories", "accounts", "contacts", "leads",
    "opportunities", "quotes", "contracts", "activities", "cases",
    "opportunity_line_items",
]


def generate(out_dir: str, accounts: int, seed: int) -> None:
    """Run the existing CRM generator for a single current-state snapshot."""
    subprocess.run(
        [sys.executable, str(GENERATOR), "--out", out_dir,
         "--days", "1", "--accounts", str(accounts), "--seed", str(seed)],
        check=True,
    )


def table_meta(conn, table: str):
    """Return (ordered columns, primary-key column) for crm.<table>."""
    cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='crm' AND table_name=%s ORDER BY ordinal_position",
        (table,))]
    pk_row = conn.execute(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = ('crm.' || %s)::regclass AND i.indisprimary",
        (table,)).fetchone()
    return cols, (pk_row[0] if pk_row else None)


def find_csvs(out_dir: str, entity: str) -> list[str]:
    """Locate the generator's CSV(s) for an entity (dt=… partitioned or flat)."""
    hits = glob.glob(f"{out_dir}/{entity}/**/*.csv", recursive=True)
    return sorted(hits)


def upsert_entity(conn, entity: str, csv_paths: list[str]) -> int:
    table_cols, pk = table_meta(conn, entity)
    if not csv_paths or not pk:
        return 0
    loaded = 0
    with conn.cursor() as cur:
        for path in csv_paths:
            with open(path, newline="") as fh:
                reader = csv.DictReader(fh)
                header = reader.fieldnames or []
                # load only CSV columns that exist as real columns on the table
                cols = [c for c in header if c in table_cols and c != "updated_at"]
                if pk not in cols:
                    continue
                collist = ", ".join(cols)
                placeholders = ", ".join(["%s"] * len(cols))
                updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
                sql = (f"INSERT INTO crm.{entity} ({collist}, updated_at) "
                       f"VALUES ({placeholders}, now()) "
                       f"ON CONFLICT ({pk}) DO UPDATE SET {updates}, updated_at=now()")
                # empty-string sentinels -> NULL (dates/optional FKs/etc.)
                rows = [[(r[c] if r[c] != "" else None) for c in cols] for r in reader]
                if rows:
                    cur.executemany(sql, rows)
                    loaded += len(rows)
    return loaded


def main() -> None:
    ap = argparse.ArgumentParser(description="Load synthetic CRM data into local Postgres.")
    ap.add_argument("--accounts", type=int, default=50, help="number of accounts to generate")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed (same seed = same data)")
    ap.add_argument("--dbname", default=os.environ.get("PGDATABASE", "cdp_crm"))
    ap.add_argument("--host", default=os.environ.get("PGHOST", "/tmp"),
                    help="PG host or socket dir (default local socket /tmp = trust)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "crm")
        print(f">> generating synthetic CRM (accounts={args.accounts}, seed={args.seed}, current snapshot)")
        generate(out, args.accounts, args.seed)

        with psycopg.connect(host=args.host, dbname=args.dbname, autocommit=False) as conn:
            print(">> upserting into crm.* (operational store: one current row per id)")
            for entity in LOAD_ORDER:
                n = upsert_entity(conn, entity, find_csvs(out, entity))
                print(f"   upsert crm.{entity:<24} {n:>6} rows")
            conn.commit()
            print(">> resulting table counts:")
            for entity in LOAD_ORDER:
                c = conn.execute(f"SELECT count(*) FROM crm.{entity}").fetchone()[0]
                print(f"   crm.{entity:<24} {c:>6}")
    print(">> done — cdp_crm.crm.* refreshed.")


if __name__ == "__main__":
    main()
