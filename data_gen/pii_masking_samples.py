"""PII masking / tokenization demonstration for downstream governance.

This module documents the masking approach the commercial data platform uses
when sensitive raw fields land and are promoted through the medallion layers.
Techniques shown:

  * hash-based tokenization      (deterministic, non-reversible join key)
  * partial email mask           (a***@domain)
  * last-4 only                  (account / bank reference)
  * tax-id mask                  (tokenized body + last 2 chars)

Run it directly to print before/after examples and write a small samples
file that governance / data-stewardship can review.

    python data_gen/pii_masking_samples.py --out data_gen/output/governance
"""

from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    SENSITIVITY,
    last4,
    mask_email,
    mask_tax_id,
    sensitivity_tag,
    tokenize,
    write_json_doc,
)

SAMPLE_RECORDS: list[dict[str, str]] = [
    {
        "first_name": "Priya", "last_name": "Patel",
        "work_email": "priya.patel@apex.com",
        "phone": "+1-415-555-0192",
        "tax_id": "DE811234567",
        "bank_reference": "GB29NWBK60161331926819",
        "employee_id": "EMP-0099812",
    },
    {
        "first_name": "Mateo", "last_name": "Garcia",
        "work_email": "mateo.garcia@summit.com.br",
        "phone": "+1-512-555-7741",
        "tax_id": "BR12345678000199",
        "bank_reference": "0044556677",
        "employee_id": "EMP-0123456",
    },
]


def mask_record(rec: dict[str, str]) -> dict[str, str]:
    """Apply the platform's standard masking policy to one raw record."""
    return {
        # direct identifiers tokenized to a stable, non-reversible key
        "first_name_token": tokenize(rec["first_name"]),
        "last_name_token": tokenize(rec["last_name"]),
        # contact fields partially masked so they remain human-recognizable
        "work_email_masked": mask_email(rec["work_email"]),
        "phone_last4": last4(rec["phone"]),
        # financial identifiers
        "tax_id_masked": mask_tax_id(rec["tax_id"]),
        "bank_reference_last4": last4(rec["bank_reference"]),
        "employee_id_token": tokenize(rec["employee_id"]),
    }


def governance_manifest() -> list[dict[str, str]]:
    """Field-level sensitivity tags for the masked schema."""
    return [
        sensitivity_tag("first_name", "PII_DIRECT"),
        sensitivity_tag("last_name", "PII_DIRECT"),
        sensitivity_tag("work_email", "PII_CONTACT"),
        sensitivity_tag("phone", "PII_CONTACT"),
        sensitivity_tag("tax_id", "FINANCIAL"),
        sensitivity_tag("bank_reference", "FINANCIAL"),
        sensitivity_tag("employee_id", "PII_DIRECT"),
        sensitivity_tag("sales_notes", "FREE_TEXT"),
        sensitivity_tag("case_comment", "FREE_TEXT"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="PII masking demo + samples file.")
    parser.add_argument("--out", default="data_gen/output/governance",
                        help="Output directory for the samples file")
    args = parser.parse_args()

    print("=== PII masking before/after ===\n")
    masked_records: list[dict[str, object]] = []
    for rec in SAMPLE_RECORDS:
        masked = mask_record(rec)
        masked_records.append({"raw": rec, "masked": masked})
        print(f"Raw email   : {rec['work_email']:<32} -> {masked['work_email_masked']}")
        print(f"Raw phone   : {rec['phone']:<32} -> {masked['phone_last4']}")
        print(f"Raw tax_id  : {rec['tax_id']:<32} -> {masked['tax_id_masked']}")
        print(f"Raw bank ref: {rec['bank_reference']:<32} -> {masked['bank_reference_last4']}")
        print(f"Raw name    : {rec['first_name']} {rec['last_name']:<24} -> "
              f"{masked['first_name_token']} / {masked['last_name_token']}")
        print("-" * 70)

    print("\n=== Sensitivity vocabulary ===")
    for k, v in SENSITIVITY.items():
        print(f"  {k:<12} -> {v}")

    out = Path(args.out)
    doc = {
        "description": "PII masking/tokenization samples for governance review.",
        "sensitivity_vocabulary": SENSITIVITY,
        "field_sensitivity": governance_manifest(),
        "examples": masked_records,
    }
    path = write_json_doc(doc, out / "pii_masking_samples.json")
    print(f"\nWrote samples file: {path}")


if __name__ == "__main__":
    main()
