"""Validate the root databricks.yml Asset Bundle config without a cluster.

Prefers PyYAML for structured assertions; if PyYAML is unavailable the tests
fall back to robust substring checks over the raw file so they still run in a
bare CI environment.

Full pipeline / resource validation happens via `databricks bundle validate`
in Databricks; this is a fast local guardrail on the bundle's shape.
"""
from __future__ import annotations

import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
BUNDLE_PATH = os.path.join(REPO_ROOT, "databricks.yml")

EXPECTED_TARGETS = ["dev", "qa", "prod"]
EXPECTED_CATALOGS = ["cdp_dev", "cdp_qa", "cdp_prod"]

try:
    import yaml  # type: ignore
    HAVE_YAML = True
except Exception:  # pragma: no cover - environment without pyyaml
    HAVE_YAML = False


def _read_bundle_text() -> str:
    assert os.path.exists(BUNDLE_PATH), f"databricks.yml not found at {BUNDLE_PATH}"
    with open(BUNDLE_PATH, "r", encoding="utf-8") as fh:
        return fh.read()


def _load_bundle():
    if not HAVE_YAML:
        return None
    with open(BUNDLE_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_bundle_file_exists_and_named():
    text = _read_bundle_text()
    assert "commercial-data-platform" in text
    assert re.search(r"^\s*name:\s*commercial-data-platform", text, re.MULTILINE)


def test_targets_exist():
    cfg = _load_bundle()
    if cfg is not None:
        assert "targets" in cfg, "no targets block"
        for t in EXPECTED_TARGETS:
            assert t in cfg["targets"], f"missing target {t}"
    else:
        text = _read_bundle_text()
        assert "targets:" in text
        for t in EXPECTED_TARGETS:
            assert re.search(rf"^\s{{2,}}{t}:", text, re.MULTILINE), f"missing target {t}"


def test_each_target_has_catalog_var():
    cfg = _load_bundle()
    if cfg is not None:
        for t, expected_catalog in zip(EXPECTED_TARGETS, EXPECTED_CATALOGS):
            target = cfg["targets"][t]
            variables = target.get("variables", {})
            assert "catalog" in variables, f"target {t} missing catalog var"
            assert variables["catalog"] == expected_catalog, (
                f"target {t} catalog {variables['catalog']} != {expected_catalog}"
            )
    else:
        text = _read_bundle_text()
        for catalog in EXPECTED_CATALOGS:
            assert catalog in text, f"missing catalog {catalog}"


def test_resources_are_included():
    text = _read_bundle_text()
    # Resources live in resources/*.yml and are pulled in via the include block.
    assert "include:" in text, "no include block"
    assert "resources/" in text, "resources/ not referenced in include"


def test_landing_volume_and_notifications_declared():
    text = _read_bundle_text()
    assert "landing_volume" in text
    assert "notifications_email" in text


def test_workspace_host_present():
    text = _read_bundle_text()
    assert "adb-1234567890123456.7.azuredatabricks.net" in text
