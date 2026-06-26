"""data_steward agent — STUB.

Function-calling agent for governance / stewardship. Reads METADATA ONLY:
Unity Catalog system lineage tables, information_schema, and UC tags
(metadata / lineage / freshness / sensitivity). It never reads business row data.

This is a STUB. `run_sql()` is a placeholder for a databricks-sql-connector
warehouse connection running as the read-only `cdp_ai_app_users` principal.
No secrets are embedded.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Metadata-only objects. information_schema / tag tables are catalog-scoped.
APPROVED_OBJECTS = [
    "system.access.table_lineage",
    "system.access.column_lineage",
    "information_schema.tables",
    "information_schema.columns",
    "information_schema.table_tags",
    "information_schema.column_tags",
]

SYSTEM_PROMPT = """\
You are the Data Steward agent for the Commercial Data Platform.

SCOPE: lineage, metadata, freshness, and sensitivity governance. You read
METADATA ONLY:
  - system.access.table_lineage / system.access.column_lineage
  - <catalog>.information_schema.tables / columns
  - UC tags via information_schema.table_tags / column_tags (metadata, lineage,
    freshness, sensitivity)

GUARDRAILS:
  - Read-only, metadata-only. Never query business row data from bronze/silver/
    gold tables; never return PII values.
  - Decline analytics questions that need business data (route to the right agent).
  - Answer only from tool results.
"""


def run_sql(query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Placeholder for parameterized SQL against a governed warehouse.

    Real implementation (commented):
        # from databricks import sql
        # with sql.connect(server_hostname=..., http_path=...,
        #                  credentials_provider=oauth_m2m_provider) as conn, \
        #      conn.cursor() as cur:
        #     cur.execute(query, params or {})
        #     cols = [c[0] for c in cur.description]
        #     return [dict(zip(cols, r)) for r in cur.fetchall()]
    """
    raise NotImplementedError("stub: wire run_sql() to databricks-sql-connector")


def downstream_dependencies(catalog: str, schema: str, table: str) -> List[Dict[str, Any]]:
    """What depends on a table: distinct downstream entities from table_lineage."""
    query = """
        SELECT DISTINCT target_table_catalog, target_table_schema, target_table_name,
               entity_type
        FROM system.access.table_lineage
        WHERE source_table_catalog = :catalog
          AND source_table_schema = :schema
          AND source_table_name = :table
        ORDER BY target_table_schema, target_table_name
    """
    return run_sql(query, {"catalog": catalog, "schema": schema, "table": table})


def column_lineage_for(catalog: str, schema: str, table: str, column: str) -> List[Dict[str, Any]]:
    """Upstream column-to-column lineage feeding a target column."""
    query = """
        SELECT source_table_catalog, source_table_schema, source_table_name,
               source_column_name
        FROM system.access.column_lineage
        WHERE target_table_catalog = :catalog
          AND target_table_schema = :schema
          AND target_table_name = :table
          AND target_column_name = :column
    """
    return run_sql(query, {"catalog": catalog, "schema": schema, "table": table, "column": column})


def tables_by_tag(catalog: str, tag_name: str, tag_value: str) -> List[Dict[str, Any]]:
    """Columns/tables carrying a given UC tag, e.g. sensitivity = pii."""
    query = f"""
        SELECT catalog_name, schema_name, table_name, column_name,
               tag_name, tag_value
        FROM {catalog}.information_schema.column_tags
        WHERE tag_name = :tag_name AND tag_value = :tag_value
        ORDER BY schema_name, table_name, column_name
    """
    return run_sql(query, {"tag_name": tag_name, "tag_value": tag_value})


def freshness_report(catalog: str, schema: str = "gold") -> List[Dict[str, Any]]:
    """Last-altered timestamp per table for a schema (freshness proxy)."""
    query = f"""
        SELECT table_schema, table_name, table_type, last_altered
        FROM {catalog}.information_schema.tables
        WHERE table_schema = :schema
        ORDER BY last_altered ASC
    """
    return run_sql(query, {"schema": schema})


def get_tools() -> List[Dict[str, Any]]:
    return [
        {"name": "downstream_dependencies",
         "description": "Distinct downstream entities that depend on a table (impact analysis).",
         "parameters": {"catalog": "string", "schema": "string", "table": "string"},
         "fn": downstream_dependencies},
        {"name": "column_lineage_for",
         "description": "Upstream column-to-column lineage feeding a target column.",
         "parameters": {"catalog": "string", "schema": "string", "table": "string", "column": "string"},
         "fn": column_lineage_for},
        {"name": "tables_by_tag",
         "description": "Find columns/tables carrying a UC tag (e.g. sensitivity=pii).",
         "parameters": {"catalog": "string", "tag_name": "string", "tag_value": "string"},
         "fn": tables_by_tag},
        {"name": "freshness_report",
         "description": "Last-altered timestamp per table in a schema (freshness proxy).",
         "parameters": {"catalog": "string", "schema": "string"},
         "fn": freshness_report},
    ]


def _demo() -> None:
    print(SYSTEM_PROMPT)
    print("Approved metadata objects:", APPROVED_OBJECTS)
    for tool in get_tools():
        print(f"- tool: {tool['name']}: {tool['description']}")
    print("\nThis is a stub; run_sql() is not wired to a warehouse.")


if __name__ == "__main__":
    _demo()
