# Pull Request

## Summary

<!-- What does this PR change and why? -->

## Type of change

- [ ] Pipeline / transformation logic (bronze / silver / gold)
- [ ] Data quality / expectations
- [ ] Governance (catalogs, tags, masking, grants)
- [ ] CI/CD / bundle config
- [ ] Agents / observability / analytics
- [ ] Docs only

## Checklist

- [ ] `databricks bundle validate -t dev` passes locally
- [ ] `pytest tests/` passes locally (unit + bundle-config tests)
- [ ] Data quality / expectation rules updated for any new or changed columns
- [ ] Docs updated (`docs/`, relevant `README.md`, data contracts)
- [ ] Governance reviewed — no raw bronze / unmasked PII exposed to
      `cdp_ai_app_users` or curated gold/silver consumers; tags & masking intact
- [ ] Backward compatibility considered for downstream gold products and agents
- [ ] No secrets, tokens, or credentials committed

## Validation evidence

<!-- Paste validate output, test summary, or screenshots of run results. -->

## Rollout / risk notes

<!-- QA UAT done? Any migration, backfill, or schema change to flag for prod? -->
