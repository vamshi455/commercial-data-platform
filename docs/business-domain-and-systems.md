# Business Domain & Systems Landscape

**The company (named 2026-07-15): Rheinhardt Industrial** — a mid-to-large **B2B
industrial-equipment / machinery manufacturer** selling pumps, valves, motors,
compressors, and spare parts to **distributors and direct OEM/end-user customers**,
with after-sales spare parts, warranty, and field service. European heritage
(matches the DE/GB footprint in the customer data); legal entity in contracts:
**Rheinhardt Industrial GmbH**.

**Product divisions** (see `data_gen/reference_data_generator.PRODUCT_TREE`):

| Division | Category | Products |
|---|---|---|
| **Flow** | Pumps · Valves | Centrifugal / Diaphragm / Gear Pump · Ball / Gate / Check Valve |
| **Power** | Motors · Compressors | AC Induction Motor · Servo Motor · Rotary Screw / Reciprocating Compressor |
| **Care** | Filters · Lubricants · Spare Parts | HEPA / Carbon Filter · Synthetic Oil · Grease Cartridge · Mechanical Seal Kit · Bearing Set |
| **Services** | — | Field service, warranty, installation (profit-center division) |

This retires the earlier oil & gas / commodity-trading framing. **No CTRM/ETRM,
no market price feeds (Platts/Argus), no cargo/vessel/inspection.** The platform
models a classic discrete-manufacturing data estate: sell-side (CRM) + back-office
(ERP) + shop floor + supply chain + after-sales.

## What stays / changes / goes

| | |
|---|---|
| **Stays** | CRM (Salesforce-like), ERP (SAP-like), medallion + governance, MDM (customer/product/supplier), Vector Search contract module |
| **Reframes** | Contracts: crude-oil trade docs → **customer master sales agreements (MSA), distributor/reseller agreements, pricing agreements, supplier procurement contracts, NDAs, warranty/SLA terms**. (Follow-up: update `contract_vector_search` type keywords + sample docs + tests.) |
| **Goes** | CTRM/ETRM, Platts/Argus, vessel/cargo/inspection, nominations, oil-grade specs (API gravity, sulfur %) |

## Systems a typical industrial manufacturer operates

Legend: ✅ have · ➕ to add · priority P0–P2.

### Front office (sell side)
- **CRM** ✅ — accounts, contacts, leads, opportunities, quotes, contracts, cases
- **Marketing automation** ➕ P1 (Marketo/HubSpot) — campaigns, lead source & attribution (leads exist today with no source)
- **CPQ** ➕ P2 — configure-price-quote → quote↔order integrity
- **B2B commerce portal + EDI** ➕ P2 — distributor/reseller order intake (EDI 850/855/810)
- **Field service & warranty** ➕ P1 (ServiceNow FSM / Salesforce FS) — installs, service orders, RMA, warranty claims (real data behind `support_performance`)

### Core operations
- **ERP** ✅ — order-to-cash, procure-to-pay, finance/GL, inventory
- **MES** ➕ P0 — production/work orders, OEE, shop-floor yield/scrap (makes it visibly a manufacturer)
- **PLM + BOM** ➕ P0 — product design, **bill of materials**, engineering change orders
- **QMS** ➕ P1 — inspections, non-conformances (NCR), defects, returns
- **WMS / inventory movements** ➕ P0 — warehouse, pick/pack/ship, stock by location (closes order→ship→invoice)
- **Procurement / S2P** ➕ P1 (Ariba/Coupa) — supplier onboarding, POs, procurement contracts (feeds supplier MDM)
- **Supply & demand planning (S&OP)** ➕ P2 — forecast, MRP, supply/demand balance
- **TMS + carriers** ➕ P2 — shipments, freight, delivery tracking

### Enterprise backbone
- **HCM** ➕ P1 (Workday) — employees, sales reps, quotas, territory ownership, org hierarchy
- **IdP** ➕ P1 (Entra ID / Okta) — user & agent identity → drives UC RBAC/ABAC
- **Billing/AR, Tax (Avalara), Treasury** ➕ P2 — deepens `bookings_vs_billings`, `collections_risk`
- **Document mgmt + e-signature** ➕ P2 (DocuSign / SharePoint) — contract lifecycle → Vector Search index
- **D&B (DUNS) / GLEIF (LEI) / credit** ➕ P1 — MDM enrichment (the fields in `mdm-and-governance.md`)

## Integration roadmap (priority order)

1. **P0 — Make it a manufacturer:** MES + PLM/BOM + WMS. Adds production orders,
   bill of materials, and inventory movements → the shop-floor + order→ship→invoice loop.
2. **P1 — Complete the commercial + master-data picture:** Field service/warranty,
   Marketing automation, Procurement/S2P, QMS, HCM, IdP, D&B/GLEIF enrichment.
3. **P2 — Depth & channel realism:** CPQ, B2B portal + EDI, S&OP, TMS, Billing/Tax,
   DocuSign.

Each new system is mocked by a synthetic generator (`data_gen/`) landing files that
Auto Loader ingests to `bronze_<system>_<entity>`, mirroring the current CRM/ERP pattern.

## New gold data products these unlock (examples)
- **Production yield & OEE** (MES) · **On-time-in-full / OTIF** (WMS+TMS) ·
  **Warranty cost & failure rate** (field service+QMS) · **Perfect-order rate** ·
  **BOM cost roll-up & margin** (PLM+ERP) · **Supplier scorecard** (procurement+QMS)
