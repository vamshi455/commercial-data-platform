"""Generate Rheinhardt Industrial contract PDFs — the unstructured RAG corpus.

Why this exists: the contract corpus used to be a handful of oil & gas trade docs
dropped into the Volume by hand — not version-controlled, not reproducible, and
domain-mismatched once the platform pivoted to industrial equipment. This module
makes the corpus a **generated, auditable artifact** like every other source.

Output: real PDFs (text-only) under --out, named to the convention
metadata_extract.py expects:
    01_Master_Sales_Agreement_CD-2025-0142.pdf

Pure stdlib on purpose (see requirements-dev.txt: generators take no third-party
deps), so we ship a minimal PDF writer rather than pulling in reportlab. Text-only
PDFs are a small, well-bounded slice of the format.

The documents are written to exercise the whole downstream pipeline:
  * `by and between X and Y`  -> metadata_extract._PARTIES_RE (counterparty)
  * `Effective Date: <ISO>`   -> _EFFECTIVE_RE
  * `CD-2025-0142` style ids  -> _ID_RE  (filename first, text fallback)
  * ARTICLE / SECTION headers -> chunking.py separator ladder
  * real emails + phones      -> gives the PII masking gate something to mask
  * multi-page                -> real page numbers (once _page_for is implemented)

Run:
    python data_gen/contract_generator.py --out data_gen/output_contracts

Output lives OUTSIDE data_gen/output/ on purpose: generate_and_land.sh uploads that
whole tree to the *landing* Volume, but contracts belong in a different Volume
(<catalog>.contracts.raw_contract_files). Keeping them separate stops PDFs from
being swept into the CSV landing zone.
"""
from __future__ import annotations

import argparse
import os
import textwrap
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Minimal PDF writer (text-only, Helvetica, US Letter)
# --------------------------------------------------------------------------- #
_PAGE_W, _PAGE_H = 612, 792
_MARGIN_X, _TOP_Y = 72, 720
_FONT_SIZE, _LEADING = 10, 13
_LINES_PER_PAGE = 48


def _escape(s: str) -> str:
    """Escape the three characters that are special inside a PDF string."""
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    """Build a page content stream that draws `lines` top-down."""
    out = ["BT", f"/F1 {_FONT_SIZE} Tf", f"{_MARGIN_X} {_TOP_Y} Td", f"{_LEADING} TL"]
    for i, line in enumerate(lines):
        # First line is placed by Td; subsequent lines advance with T*.
        if i:
            out.append("T*")
        out.append(f"({_escape(line)}) Tj")
    out.append("ET")
    return "\n".join(out).encode("latin-1", "replace")


# Helvetica 10pt averages ~5pt/char, and the text column is 612 - 2*72 = 468pt,
# so ~93 chars fit. Unwrapped lines silently run off the right edge and the PDF
# parser truncates them mid-word (that is how "Halstead Manufacturing Inc."
# reached the index as "Halstead Manufacturi"). Wrap before drawing.
_MAX_CHARS = 92


def _wrap(lines: list[str]) -> list[str]:
    """Wrap to the text column, preserving blank lines and leading indent."""
    out: list[str] = []
    for line in lines:
        if len(line) <= _MAX_CHARS:
            out.append(line)
            continue
        indent = " " * (len(line) - len(line.lstrip(" ")))
        out.extend(textwrap.wrap(
            line, width=_MAX_CHARS, subsequent_indent=indent,
            break_long_words=False, break_on_hyphens=False,
        ) or [line])
    return out


def _paginate(lines: list[str]) -> list[list[str]]:
    lines = _wrap(lines)
    return [lines[i:i + _LINES_PER_PAGE] for i in range(0, len(lines), _LINES_PER_PAGE)] or [[""]]


def write_pdf(path: str, lines: list[str]) -> int:
    """Write a text-only PDF. Returns the page count.

    Object layout: 1=Catalog, 2=Pages, 3=Font, then per page a Page + Contents.
    """
    pages = _paginate(lines)
    n_pages = len(pages)
    objects: list[bytes] = []

    page_ids = [4 + 2 * i for i in range(n_pages)]        # 4, 6, 8, ...
    content_ids = [5 + 2 * i for i in range(n_pages)]     # 5, 7, 9, ...

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for pg, cid in zip(pages, content_ids):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>".encode()
        )
        stream = _content_stream(pg)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
                       + stream + b"\nendstream")

    # Serialize with an xref table (byte offsets must be exact).
    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(buf)
    total = len(objects) + 1
    buf += f"xref\n0 {total}\n".encode()
    buf += b"0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += (f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n").encode()

    with open(path, "wb") as fh:
        fh.write(buf)
    return n_pages


# --------------------------------------------------------------------------- #
# Rheinhardt Industrial contract corpus
# --------------------------------------------------------------------------- #
SELLER = "Rheinhardt Industrial GmbH"
SELLER_ADDR = "Werkstrasse 14, 80331 Munich, Germany"


@dataclass(frozen=True)
class ContractSpec:
    seq: int
    contract_id: str
    type_label: str      # must map to metadata_extract._TYPE_KEYWORDS
    filename_type: str   # underscored form used in the filename
    counterparty: str
    effective: str
    expiry: str
    notice_days: int
    body: list[str]

    @property
    def filename(self) -> str:
        return f"{self.seq:02d}_{self.filename_type}_{self.contract_id}.pdf"


def _header(c: ContractSpec) -> list[str]:
    return [
        SELLER.upper(),
        SELLER_ADDR,
        "",
        c.type_label.upper(),
        f"Contract Reference: {c.contract_id}",
        "",
        f"This {c.type_label} (the \"Agreement\") is made by and between "
        f"{SELLER} and {c.counterparty}.",
        "",
        f"Effective Date: {c.effective}",
        f"Expiration Date: {c.expiry}",
        "",
    ]


def _footer(c: ContractSpec) -> list[str]:
    # Real PII on purpose: the silver PII mask must convert these to [EMAIL]/[PHONE].
    return [
        "",
        "ARTICLE IX - NOTICES",
        "",
        "All notices under this Agreement shall be delivered to the addresses below.",
        "",
        f"For {SELLER}:",
        "  Attn: Contracts Administration",
        "  Email: contracts@rheinhardt-industrial.com",
        "  Phone: +49 89 5550 0142",
        "",
        f"For {c.counterparty}:",
        "  Attn: Procurement",
        "  Email: procurement@onyxlogistics.example.com",
        "  Phone: +1 (415) 555-0199",
        "",
        "IN WITNESS WHEREOF, the parties have executed this Agreement as of the",
        "Effective Date first written above.",
        "",
        f"{SELLER}                    {c.counterparty}",
        "By: ____________________              By: ____________________",
    ]


def _contracts() -> list[ContractSpec]:
    """The corpus. Each doc covers a distinct contract_type in the taxonomy."""
    return [
        ContractSpec(
            seq=1, contract_id="CD-2025-0142",
            type_label="Master Sales Agreement", filename_type="Master_Sales_Agreement",
            counterparty="Onyx Logistics GmbH",
            effective="2025-01-15", expiry="2028-01-14", notice_days=90,
            body=[
                "ARTICLE I - SCOPE OF SUPPLY",
                "",
                "Seller shall manufacture and supply industrial rotating equipment,",
                "including centrifugal pumps, diaphragm pumps, and ball valves, together",
                "with associated spare parts and documentation, as ordered by Buyer under",
                "individual purchase orders referencing this Agreement.",
                "",
                "ARTICLE II - PRICING AND PAYMENT",
                "",
                "Prices are as set out in the then-current price list. Payment terms are",
                "net thirty (30) days from date of invoice. Late amounts accrue interest",
                "at one percent (1%) per month.",
                "",
                "ARTICLE III - DELIVERY",
                "",
                "Delivery shall be DAP Buyer's designated facility (Incoterms 2020).",
                "Title and risk of loss pass to Buyer upon delivery. Lead time for",
                "standard centrifugal pump configurations is twelve (12) weeks.",
                "",
                "ARTICLE IV - TERM AND TERMINATION",
                "",
                "This Agreement commences on the Effective Date and continues for three (3)",
                "years. Either party may terminate for convenience upon ninety (90) days",
                "prior written notice. Either party may terminate immediately for material",
                "breach that remains uncured thirty (30) days after written notice.",
                "",
                "ARTICLE V - WARRANTY",
                "",
                "Seller warrants equipment against defects in material and workmanship for",
                "eighteen (18) months from delivery or twelve (12) months from",
                "commissioning, whichever occurs first.",
            ],
        ),
        ContractSpec(
            seq=2, contract_id="CD-2025-0197",
            type_label="Distributor Agreement", filename_type="Distributor_Agreement",
            counterparty="Meridian Logistics Ltd",
            effective="2025-03-01", expiry="2027-02-28", notice_days=60,
            body=[
                "ARTICLE I - APPOINTMENT",
                "",
                "Seller appoints Distributor as a non-exclusive distributor of Rheinhardt",
                "Flow and Power division products within the United Kingdom (the",
                "\"Territory\"). Distributor shall not solicit sales outside the Territory.",
                "",
                "ARTICLE II - DISTRIBUTOR OBLIGATIONS",
                "",
                "Distributor shall maintain adequate stock of fast-moving spare parts,",
                "employ trained service technicians, and achieve the annual minimum",
                "purchase commitment of EUR 2,500,000.",
                "",
                "ARTICLE III - DISCOUNT SCHEDULE",
                "",
                "Distributor receives a thirty-two percent (32%) discount off list price",
                "on Flow division products and twenty-eight percent (28%) on Power",
                "division products. Care division consumables are discounted at twenty",
                "percent (20%).",
                "",
                "ARTICLE IV - TERM AND TERMINATION",
                "",
                "The initial term is two (2) years. Either party may terminate upon sixty",
                "(60) days written notice. Seller may terminate immediately if Distributor",
                "fails to meet the minimum purchase commitment for two consecutive quarters.",
            ],
        ),
        ContractSpec(
            seq=3, contract_id="CF-2025-3081",
            type_label="Supply Agreement", filename_type="Supply_Agreement",
            counterparty="Vertex Components AG",
            effective="2025-02-10", expiry="2027-02-09", notice_days=120,
            body=[
                "ARTICLE I - SUPPLIED GOODS",
                "",
                "Supplier shall supply precision bearing sets and mechanical seal kits",
                "conforming to Rheinhardt drawing specifications for incorporation into",
                "Seller's pump and compressor product lines.",
                "",
                "ARTICLE II - QUALITY AND INSPECTION",
                "",
                "All goods shall conform to ISO 9001 quality standards. Seller may inspect",
                "at Supplier's facility upon reasonable notice. Non-conforming goods may be",
                "rejected within thirty (30) days of receipt.",
                "",
                "ARTICLE III - CAPACITY AND FORECAST",
                "",
                "Supplier shall reserve capacity for a minimum of 5,000 bearing sets per",
                "quarter. Seller shall provide a rolling six (6) month non-binding forecast.",
                "",
                "ARTICLE IV - TERM AND TERMINATION",
                "",
                "This Agreement continues for two (2) years and renews automatically for",
                "successive one (1) year terms unless either party gives one hundred twenty",
                "(120) days written notice of non-renewal.",
            ],
        ),
        ContractSpec(
            seq=4, contract_id="CD-2025-0233",
            type_label="Pricing Agreement", filename_type="Pricing_Agreement",
            counterparty="Halstead Manufacturing Inc",
            effective="2025-04-01", expiry="2026-03-31", notice_days=30,
            body=[
                "ARTICLE I - FIXED PRICING",
                "",
                "The following unit prices are firm for the term of this Agreement:",
                "",
                "  Centrifugal Pump (standard configuration)     USD 2,100.00 per unit",
                "  Diaphragm Pump                                USD 1,650.00 per unit",
                "  AC Induction Motor                            USD 1,850.00 per unit",
                "  Rotary Screw Compressor                       USD 12,500.00 per unit",
                "  Mechanical Seal Kit                           USD   240.00 per unit",
                "",
                "ARTICLE II - VOLUME REBATE",
                "",
                "Buyer earns a retroactive rebate of three percent (3%) on annual purchases",
                "exceeding USD 1,000,000 and five percent (5%) above USD 2,500,000.",
                "",
                "ARTICLE III - PRICE ADJUSTMENT",
                "",
                "Prices are fixed for twelve (12) months. Thereafter Seller may adjust",
                "prices upon thirty (30) days notice, capped at the published producer",
                "price index for machinery.",
            ],
        ),
        ContractSpec(
            seq=5, contract_id="EX-2025-0076",
            type_label="NDA", filename_type="Non-Disclosure_Agreement",
            counterparty="Caldwell Engineering Partners",
            effective="2025-05-20", expiry="2030-05-19", notice_days=0,
            body=[
                "ARTICLE I - CONFIDENTIAL INFORMATION",
                "",
                "Confidential Information includes pump impeller designs, compressor",
                "efficiency data, manufacturing process parameters, customer lists, and",
                "pricing, whether disclosed orally, in writing, or by inspection.",
                "",
                "ARTICLE II - OBLIGATIONS",
                "",
                "Receiving Party shall use Confidential Information solely to evaluate a",
                "potential engineering collaboration and shall protect it with no less than",
                "reasonable care. Disclosure to employees is permitted on a need-to-know",
                "basis under equivalent written obligations.",
                "",
                "ARTICLE III - EXCLUSIONS",
                "",
                "Obligations do not apply to information that is publicly available, was",
                "already known without restriction, or is independently developed.",
                "",
                "ARTICLE IV - TERM",
                "",
                "Confidentiality obligations survive for five (5) years from the Effective",
                "Date. This Agreement has no termination-for-convenience right.",
            ],
        ),
        ContractSpec(
            seq=6, contract_id="TD-2025-0210",
            type_label="Warranty / SLA", filename_type="Warranty_SLA_Agreement",
            counterparty="Onyx Logistics GmbH",
            effective="2025-06-01", expiry="2028-05-31", notice_days=60,
            body=[
                "ARTICLE I - WARRANTY COVERAGE",
                "",
                "Seller warrants that Flow and Power division equipment shall be free from",
                "defects in material and workmanship for twenty-four (24) months from the",
                "date of commissioning. Care division consumables carry a ninety (90) day",
                "warranty.",
                "",
                "ARTICLE II - SERVICE LEVEL COMMITMENTS",
                "",
                "  Response time, critical outage        4 hours",
                "  Response time, standard request       1 business day",
                "  On-site attendance, critical          24 hours",
                "  Spare parts availability              95% from regional stock",
                "",
                "ARTICLE III - REMEDIES",
                "",
                "Seller shall, at its option, repair or replace defective equipment. If",
                "Seller fails to meet the critical response commitment in three (3)",
                "consecutive months, Buyer receives a service credit equal to five percent",
                "(5%) of the quarterly service fee.",
                "",
                "ARTICLE IV - EXCLUSIONS",
                "",
                "The warranty excludes damage from improper installation, operation outside",
                "published performance curves, use of non-genuine spare parts, or failure to",
                "perform scheduled maintenance.",
                "",
                "ARTICLE V - TERM",
                "",
                "This Agreement runs concurrently with the Master Sales Agreement and may be",
                "terminated on sixty (60) days written notice.",
            ],
        ),
    ]


def generate(out_dir: str) -> list[tuple[str, int]]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for c in _contracts():
        lines = _header(c) + c.body + _footer(c)
        path = os.path.join(out_dir, c.filename)
        pages = write_pdf(path, lines)
        written.append((c.filename, pages))
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Rheinhardt Industrial contract PDFs.")
    ap.add_argument("--out", default="data_gen/output_contracts", help="output directory")
    args = ap.parse_args()
    written = generate(args.out)
    total = sum(p for _, p in written)
    for name, pages in written:
        print(f"  {name}  ({pages}p)")
    print(f"Contracts written to {args.out} (docs={len(written)}, pages={total})")


if __name__ == "__main__":
    main()
