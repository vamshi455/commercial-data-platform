# Specs

Feature/module specifications for the Commercial Data Platform. Each spec is a
self-contained, implementable unit of work. Design/reference docs live one level up
in `docs/`; **this folder is for buildable specs** (what to implement, constraints,
deliverables, open decisions).

## Convention

- One spec per file: `docs/specs/<kebab-case-name>.md`.
- Every spec has a header: `Status` (Draft / Approved / In progress / Done), `Owner`,
  and any placeholders to confirm before build.
- Keep an `Open decisions` section until the forks are resolved.

## Index

| Spec | Status | Summary |
|---|---|---|
| [contract-vector-search.md](contract-vector-search.md) | Built (not yet run) | Incremental PDF contract ingestion → Mosaic AI Vector Search for a RAG agent |

## Candidate specs (not yet written)

Pending project work that should get its own spec file when picked up:
- `growth-app.md` — growth analytics app (project task #5)
- `cost-app.md` — cost/observability app (project task #6)
- `crm-cutover.md` — finish Postgres CRM → bronze cutover
- `governance-schema-reconcile.md` — align governance SQL with the real serving schema
