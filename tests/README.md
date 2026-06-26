# Tests — Commercial Data Platform

Fast, dependency-light tests that run under plain `pytest` in CI (no Spark, no
cluster). They guard the things that should fail *before* a deploy.

## Layout

| Path | Covers |
|------|--------|
| `data_quality/test_dq_rules.py` | The DQ rule catalog (`RULES`): not-null sets, enum domains, currency/date sanity, numeric ranges, referential-integrity wiring, finance reconciliation tolerance — plus pure-python validators for each. |
| `pipeline_validation/test_bundle_config.py` | The root `databricks.yml`: targets `dev`/`qa`/`prod` exist, each has the right `catalog` var, `resources/*.yml` is included, landing volume / notifications / workspace host present. Uses PyYAML if available, falls back to substring checks. |
| `conftest.py` | Session fixtures: `repo_root`, `bundle_path`. |

## Run

```bash
# from the repo root
pytest -q tests/

# a single area
pytest -q tests/data_quality
pytest -q tests/pipeline_validation
```

Optional dependency: `pyyaml` (the bundle-config test degrades gracefully to
substring checks without it).

```bash
pip install pytest pyyaml
```

## What is NOT here

Row-level data-quality enforcement, transformation correctness, and end-to-end
medallion behavior run **in Databricks** as DLT expectations and bundle jobs
(`databricks bundle validate/deploy/run`). These unit tests only validate rule
*definitions* and bundle *shape* so CI can fast-fail cheaply. CI runs this suite
plus `databricks bundle validate -t dev` on every pull request (see
`.github/workflows/ci.yml`).
