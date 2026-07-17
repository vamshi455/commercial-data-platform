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


def test_workspace_host_is_not_declared_in_bundle():
    """No target may declare workspace.host.

    Workspace URLs are deliberately not stored in this repo. The CLI rejects
    ${var.*} interpolation on workspace.host (it configures auth), so the field
    is omitted entirely and the host is injected as DATABRICKS_HOST by
    scripts/deploy.sh (local, from .env) or by CI (repo variable).
    """
    text = _read_bundle_text()
    host_lines = [
        line for line in text.splitlines()
        if re.match(r"\s+host:", line) and "pg_host" not in line
    ]
    assert not host_lines, (
        "workspace.host must not be committed; inject DATABRICKS_HOST instead. "
        f"Found: {host_lines}"
    )


def test_no_workspace_host_literal_committed():
    """Guard against a real workspace URL being reintroduced anywhere in the repo.

    This is the check that keeps the scrub from silently regressing.
    """
    import pathlib
    import subprocess

    repo_root = pathlib.Path(__file__).resolve().parents[2]
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.split("\0")

    # A real Azure Databricks workspace host: adb-<digits>.<digits>
    pattern = re.compile(r"adb-\d{10,}\.\d+")
    offenders = []
    for rel in filter(None, tracked):
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — no host literal to find
        for match in pattern.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            offenders.append(f"{rel}:{line_no}: {match.group()}")

    assert not offenders, (
        "workspace host literal(s) committed — use ${var.workspace_host} or a "
        "placeholder instead:\n  " + "\n  ".join(offenders)
    )
