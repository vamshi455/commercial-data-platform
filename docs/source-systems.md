# Commercial Data Platform — Source Systems

> **Audience:** Data engineers and analytics engineers modeling the CRM and ERP sources into the CDP lakehouse.
> **Scope:** Detailed source-system models, entity fields, relationships, lifecycle behaviors, PII/sensitivity inventory, and the CRM↔ERP identity problem.

**Related docs:**
- [`architecture.md`](./architecture.md) — end-to-end flow, medallion layers, identity resolution approach
- [`data-contracts.md`](./data-contracts.md) — schema/SLA/quality contracts for these entities
- [`naming-conventions.md`](./naming-conventions.md) — table/column naming for source-derived tables

---

## 1. Overview

CDP ingests from two operational systems that mirror real enterprise software:

| System | Analogous to | Role | Entities |
|---|---|---|---|
| **CRM** | Salesforce | Front office: demand generation through deal close + support | accounts, contacts, leads, opportunities, opportunity_line_items, quotes, contracts, activities, cases, users, territories |
| **ERP** | SAP S/4HANA | Back office: order-to-cash, procure-to-pay, finance/GL, master data | customers, vendors, products, sales_orders, sales_order_items, billing_documents, invoices, payments, purchase_orders, gl_entries, cost_centers, profit_centers, currency_rates |

Source tables land as `crm_<entity>` and `erp_<entity>` in bronze (see [`naming-conventions.md`](./naming-conventions.md)).

---

## 2. CRM (Salesforce-like) Model

### 2.1 Entity reference

| Entity | Grain | Key fields | Notable behavior |
|---|---|---|---|
| **accounts** | one row per company | *Emitted today:* `account_id` (PK), `account_name`, `account_type`, `industry`, `rating`, `annual_revenue`, `employees`, `office_address`, `billing_country`, `phone`, `owner_user_id`, `territory_id`, `converted_from_lead_id`, `created_date`. *Planned (MDM M1):* `duns_number`, `lei`, `website`, `tax_id`, structured `billing_address`, `parent_account_id`, `naics_code`, `lifecycle_status`, source-provenance | Hierarchies via `parent_account_id` (planned); ownership/territory reassigned over time. ⚠️ DUNS/parent/tax_id/website **not yet generated** — decisions.md D1/D9 |
| **contacts** | one row per person | `contact_id` (PK), `account_id` (FK), `first_name`, `last_name`, `email`, `phone`, `title` | People churn; email is primary match key to leads |
| **leads** | one row per inbound prospect | `lead_id` (PK), `email`, `company`, `lead_status`, `converted_flag`, `converted_account_id`, `converted_contact_id`, `converted_opportunity_id` | **Converts** into account+contact+opportunity; pre-conversion has no account FK |
| **opportunities** | one row per deal | `opportunity_id` (PK), `account_id` (FK), `stage_name`, `amount`, `currency_code`, `close_date`, `forecast_category`, `owner_user_id`, `is_closed`, `is_won` | **Moves through stages**; amount/close_date revised; terminal = Closed Won / Closed Lost |
| **opportunity_line_items** | one row per product on a deal | `oli_id` (PK), `opportunity_id` (FK), `product_code`, `quantity`, `unit_price`, `total_price` | Links CRM deals to product hierarchy |
| **quotes** | one row per quote | `quote_id` (PK), `opportunity_id` (FK), `quote_status`, `total_amount`, `valid_until` | Multiple quotes per opp; one becomes primary |
| **contracts** | one row per signed agreement | `contract_id` (PK), `account_id` (FK), `opportunity_id` (FK), `start_date`, `end_date`, `contract_value`, `status`, `renewal_date` | Created on **Closed Won**; drives renewals |
| **activities** | one row per interaction | `activity_id` (PK), `related_to_id`, `related_to_type`, `activity_type`, `activity_date`, `owner_user_id` | High-volume; polymorphic relation to account/contact/opp/case |
| **cases** | one row per support ticket | `case_id` (PK), `account_id` (FK), `contact_id` (FK), `subject`, `description`, `priority`, `status`, `created_date`, `closed_date` | Support performance; `description` is free text (sensitive) |
| **users** | one row per CRM user | `user_id` (PK), `user_name`, `email`, `role`, `manager_user_id`, `is_active` | Sales reps/owners; drives ownership and management rollups |
| **territories** | one row per sales territory | `territory_id` (PK), `territory_name`, `region`, `parent_territory_id` | Hierarchical; reassigned to accounts over time |

### 2.2 Lifecycle behaviors

- **Lead conversion:** A `lead` with `converted_flag = true` produces (or links to) an `account`, a `contact`, and an `opportunity`. Pre-conversion leads have no account FK; the conversion event is captured via the `converted_*` columns. Modeling must avoid double-counting the prospect after conversion.
- **Opportunity stage progression:** Opportunities advance through stages (e.g., Prospecting → Qualification → Proposal → Negotiation → Closed Won/Lost). `amount`, `close_date`, and `stage_name` change repeatedly. Silver retains **stage history** for sales-velocity and forecast analytics.
- **Ownership / territory changes:** `owner_user_id` and `territory_id` on accounts and opportunities change as deals are reassigned; these are SCD2-tracked so historical attribution is preserved.
- **Closed-Won → Contract:** Winning an opportunity generates a `contract` with value, term, and `renewal_date`. This is the CRM-side anchor that must reconcile to the ERP order-to-cash chain.
- **Cases → accounts/contacts:** Support `cases` link to both `account_id` and `contact_id`, feeding `support_performance` and `account_health`.
- **Load cadence:** CRM loads are **incremental, daily for most entities and hourly for high-velocity ones** (opportunities, activities, cases). High-velocity entities use CDC-style change capture; slower entities use snapshot+diff.

### 2.3 CRM entity-relationship diagram

```
                         ┌────────────┐
                         │ territories│◄──┐ parent_territory_id (self ref)
                         └─────┬──────┘   │
                               │ territory_id
                  ┌────────────▼─────────┐         ┌──────────┐
        owner ───►│      accounts        │◄────────┤  users   │◄─ manager_user_id (self ref)
                  │  parent_account_id ◄─┼─(self)  └────┬─────┘
                  └───┬─────────┬────────┘               │ owner_user_id
            account_id│         │account_id              │
          ┌───────────▼──┐  ┌───▼──────────┐   ┌─────────▼──────┐
          │   contacts   │  │ opportunities│   │   leads        │
          └───────┬──────┘  └──┬────────┬──┘   │ converted_*_id ┼──► account/contact/opp
                  │            │        │       └────────────────┘
                  │       opp_ │        │ opp_id
                  │       id   ▼        ▼
                  │   ┌────────────┐  ┌──────────┐   ┌──────────┐
                  │   │opp_line_   │  │  quotes  │   │contracts │ (on Closed Won)
                  │   │items       │  └──────────┘   └──────────┘
                  │   └────────────┘
          ┌───────▼──────┐
          │    cases     │   ┌────────────┐
          │ account_id   │   │ activities │  (polymorphic: related_to_id/type ► acct/contact/opp/case)
          │ contact_id   │   └────────────┘
          └──────────────┘
```

---

## 3. ERP (SAP-like) Model

### 3.1 Entity reference

| Entity | Grain | Key fields | Notable behavior |
|---|---|---|---|
| **customers** | one row per sold-to customer | `customer_id` (PK), `customer_name`, `tax_id`, `vat_reg_no`, `duns_number`, `address`, `payment_terms`, `credit_limit` | Customer master; **SCD** attributes; matches to CRM accounts |
| **vendors** | one row per vendor | `vendor_id` (PK), `vendor_name`, `tax_id`, `address`, `payment_terms` | Procure-to-pay side |
| **products** | one row per material/SKU | `product_id` (PK), `product_code`, `description`, `product_family`, `product_line`, `business_unit`, `uom` | **Product hierarchy**; SCD2 on family/line |
| **sales_orders** | one row per order header | `sales_order_id` (PK), `customer_id` (FK), `order_date`, `currency_code`, `order_status`, `net_value`, `crm_opportunity_ref` | Created post-deal; may reference originating CRM opp |
| **sales_order_items** | one row per order line | `so_item_id` (PK), `sales_order_id` (FK), `product_id` (FK), `quantity`, `unit_price`, `net_amount` | Line-level fulfillment |
| **billing_documents** | one row per billing doc | `billing_doc_id` (PK), `sales_order_id` (FK), `billing_date`, `gross_amount`, `currency_code` | Bridge from order to invoice |
| **invoices** | one row per invoice | `invoice_id` (PK), `billing_doc_id` (FK), `customer_id` (FK), `invoice_date`, `due_date`, `invoice_amount`, `currency_code`, `payment_status` | A/R anchor; partial/late/disputed |
| **payments** | one row per payment/clearing | `payment_id` (PK), `invoice_id` (FK), `payment_date`, `amount_paid`, `currency_code`, `payment_method`, `is_disputed` | **Partial, late, disputed**; multiple per invoice |
| **purchase_orders** | one row per PO | `po_id` (PK), `vendor_id` (FK), `po_date`, `total_amount`, `status` | Procure-to-pay |
| **gl_entries** | one row per GL posting line | `gl_entry_id` (PK), `gl_account`, `posting_date`, `amount`, `debit_credit`, `cost_center_id`, `profit_center_id`, `document_ref` | High-volume; **finance-close adjustments** |
| **cost_centers** | one row per cost center | `cost_center_id` (PK), `name`, `parent_cost_center_id`, `responsible_user` | Org dimension; SCD2 |
| **profit_centers** | one row per profit center | `profit_center_id` (PK), `name`, `parent_profit_center_id` | Org dimension; SCD2 |
| **currency_rates** | one row per (from,to,date) | `from_currency`, `to_currency`, `rate_date`, `rate`, `rate_type` | Daily FX; transaction + period-close rate types |

### 3.2 Lifecycle behaviors

- **Order-to-cash chain:** `sales_orders → sales_order_items` are fulfilled, then `billing_documents` are generated, producing `invoices`, which are settled by one or more `payments`. This chain is the ERP revenue spine.
- **Partial / late / disputed payments:** An invoice can be paid in multiple installments (`payments` rows summing to ≤ invoice amount), paid after `due_date` (late), or flagged `is_disputed`. `collections_risk` and DSO analytics depend on modeling these correctly — never assume one payment per invoice.
- **Finance close adjustments:** During period close, `gl_entries` receive adjusting/reclassification postings (accruals, reversals, currency revaluation). Reporting must distinguish operational postings from close adjustments and respect the open/closed status of a fiscal period.
- **Product / org SCD changes:** `products` (family/line/BU), `cost_centers`, and `profit_centers` change over time. These are **SCD2** so historical financials roll up to the hierarchy that was in effect at posting time.
- **Snapshot + CDC mix:** ERP delivers a **daily full snapshot** for master/slow entities (customers, products, vendors, org dims) and **CDC change streams** for transactional, high-volume entities (invoices, payments, gl_entries, sales_orders). Silver merges these via `APPLY CHANGES` / SCD logic.

### 3.3 ERP entity-relationship diagram

```
   ┌──────────┐                                   ┌──────────┐
   │ products │◄── product_id ──┐                 │ vendors  │
   └────┬─────┘                 │                 └────┬─────┘
        │ (hierarchy: family    │                      │ vendor_id
        │  /line/BU, SCD2)      │                 ┌────▼─────────┐
                                │                 │purchase_orders│
   ┌──────────┐  customer_id    │                 └──────────────┘
   │customers │◄────────┬───────┼──────────────────────────┐
   └──────────┘         │       │                           │
                  ┌─────▼───────▼─────┐                     │
                  │   sales_orders    │                     │
                  └─────────┬─────────┘                     │
                  so_id     │                               │
              ┌─────────────▼────────┐                      │
              │  sales_order_items   │                      │
              └──────────────────────┘                      │
                  so_id │                                    │
              ┌─────────▼──────────┐                         │
              │ billing_documents  │                         │
              └─────────┬──────────┘                         │
                billing_doc_id │                             │ customer_id
              ┌────────────────▼───┐◄────────────────────────┘
              │     invoices       │
              └─────────┬──────────┘
                invoice_id │  (1..N, partial/late/disputed)
              ┌───────────▼────────┐
              │     payments       │
              └────────────────────┘

   ┌──────────────┐   ┌──────────────┐
   │ cost_centers │   │profit_centers│  ◄── referenced by gl_entries (cost_center_id, profit_center_id)
   └──────────────┘   └──────────────┘
   ┌──────────────┐   ┌──────────────┐
   │  gl_entries  │   │currency_rates│
   └──────────────┘   └──────────────┘
```

---

## 4. PII / Sensitive Field Inventory

Every column inherits a **sensitivity class** (see [`architecture.md`](./architecture.md) §10.4 and the classes below), applied as Unity Catalog tags and enforced via RBAC/masking.

| Sensitivity class | Meaning | Access posture |
|---|---|---|
| `public_reference` | Non-sensitive reference data | Broadly readable |
| `internal_only` | Internal business data, not personal/financial-restricted | All CDP personas |
| `pii` | Personal data (names, emails, phones, addresses) | Masked except for stewards/owners; column masks applied |
| `financial_sensitive` | Monetary/credit/A-R details | Finance personas; masked for others |
| `restricted_free_text` | Unstructured text that may contain anything (notes, case descriptions) | Most restricted; access logged, often redacted |

### 4.1 CRM sensitive fields

| Entity.column | Class |
|---|---|
| contacts.first_name, contacts.last_name | `pii` |
| contacts.email, leads.email, users.email | `pii` |
| contacts.phone | `pii` |
| accounts.billing_address | `pii` |
| accounts.tax_id, accounts.duns_number | `financial_sensitive` |
| leads.company, accounts.account_name, accounts.industry | `internal_only` |
| opportunities.amount, opportunity_line_items.unit_price, quotes.total_amount, contracts.contract_value | `financial_sensitive` |
| cases.description, activities (notes/body) | `restricted_free_text` |
| accounts.website, territories.*, products mapping | `public_reference` / `internal_only` |

### 4.2 ERP sensitive fields

| Entity.column | Class |
|---|---|
| customers.customer_name, vendors.vendor_name | `internal_only` |
| customers.address, vendors.address | `pii` |
| customers.tax_id, customers.vat_reg_no, customers.duns_number, vendors.tax_id | `financial_sensitive` |
| customers.credit_limit, customers.payment_terms | `financial_sensitive` |
| invoices.invoice_amount, payments.amount_paid, billing_documents.gross_amount, sales_orders.net_value | `financial_sensitive` |
| gl_entries.amount, gl_entries.gl_account | `financial_sensitive` |
| products.*, cost_centers.*, profit_centers.*, currency_rates.* | `internal_only` / `public_reference` |

---

## 5. The CRM↔ERP Identity Problem

The same customer exists as a CRM `account` and an ERP `customer`, with **no shared primary key**.

```
   CRM.accounts                          ERP.customers
   ───────────────                       ────────────────
   account_id   (CRM key, opaque)        customer_id  (ERP key, opaque)
   account_name                          customer_name      ← differ in spelling/legal form
   billing_address                       address            ← differ in format
   tax_id / duns_number                  tax_id / vat_reg_no / duns_number  ← strongest signals
   website / contact email domains       (no website)
```

**Why it is hard:**
- Keys are system-internal and unrelated.
- Names differ ("Acme Inc." vs "ACME INCORPORATED").
- Addresses are formatted differently and change over time.
- One CRM account may map to multiple ERP sold-to/ship-to customers, and vice versa.

**Resolution approach (implemented in silver — see [`architecture.md`](./architecture.md) §8):**
1. **Deterministic** match on tax_id / DUNS / VAT / normalized name+country.
2. **Probabilistic** fuzzy match on name/address/domain for the remainder.
3. **Survivorship** rules build a golden record (ERP wins legal/tax fields; CRM wins commercial/contact fields).
4. **Crosswalk** `silver.xref_customer` maps `(source_system, source_key) → master_customer_id`.
5. **Steward overrides** from `cdp_data_stewards` always win and are auditable.

Output: `silver.dim_customer` carrying `account_id`, `customer_id`, and the stable `master_customer_id` used by all cross-domain gold products (`customer_360`, `bookings_vs_billings`, `collections_risk`, `account_health`, `renewal_risk`).
