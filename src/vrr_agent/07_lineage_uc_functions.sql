-- ============================================================================
-- VRR lineage-graph traversal — governed UC table functions over lineage_edge.
-- The VRR value DAG is exactly 2 hops (vrr -> contrib -> root), so these are
-- bounded 2-join traversals (no recursive-CTE dependency). Declared as agent
-- resources so the served agent can EXECUTE them.
-- ${catalog} substituted by the runner.
-- ============================================================================

-- FORWARD (impact / what-if): given a ROOT input node, which VRR outputs depend
-- on it? "If this pressure/PVT/volume/factor changed, which VRRs move?"
CREATE OR REPLACE FUNCTION ${catalog}.vrr_agent.vrr_impact(in_node STRING)
RETURNS TABLE (vrr_node STRING, pattern_id STRING, grain STRING, vrr_date DATE,
               vrr DOUBLE, via_completion STRING, edge_confidence STRING)
COMMENT 'All VRR outputs downstream of a raw-input node (impact analysis).'
RETURN
  SELECT DISTINCT v.node_id, v.pattern_id, element_at(split(v.node_id, ':'), 3) AS grain,
         v.vrr_date, CAST(get_json_object(v.attrs, '$.vrr') AS DOUBLE) AS vrr,
         c.completion_id, e_in.confidence
  FROM ${catalog}.vrr_agent.lineage_edge e_in                       -- contrib -> root(in_node)
  JOIN ${catalog}.vrr_agent.lineage_edge e_agg
    ON e_agg.dst_id = e_in.src_id AND e_agg.rel = 'aggregates_from' -- vrr -> contrib
  JOIN ${catalog}.vrr_agent.lineage_node v ON v.node_id = e_agg.src_id
  JOIN ${catalog}.vrr_agent.lineage_node c ON c.node_id = e_in.src_id
  WHERE e_in.dst_id = in_node AND e_in.rel LIKE 'input:%';

-- BACKWARD (trace / prove): given a VRR output node, all raw-input roots behind it
-- (the persisted, cross-completion form of the VRR_LINEAGE tool).
CREATE OR REPLACE FUNCTION ${catalog}.vrr_agent.vrr_trace(in_vrr STRING)
RETURNS TABLE (root_node STRING, node_type STRING, label STRING, attrs STRING,
               via_completion STRING, edge_rel STRING, confidence STRING)
COMMENT 'All raw-input roots behind a VRR output node (root-trace / proof of data).'
RETURN
  SELECT DISTINCT r.node_id, r.node_type, r.label, r.attrs, c.completion_id, e_in.rel, e_in.confidence
  FROM ${catalog}.vrr_agent.lineage_edge e_agg                      -- vrr(in) -> contrib
  JOIN ${catalog}.vrr_agent.lineage_edge e_in
    ON e_in.src_id = e_agg.dst_id AND e_in.rel LIKE 'input:%'       -- contrib -> root
  JOIN ${catalog}.vrr_agent.lineage_node r ON r.node_id = e_in.dst_id
  JOIN ${catalog}.vrr_agent.lineage_node c ON c.node_id = e_agg.dst_id
  WHERE e_agg.src_id = in_vrr AND e_agg.rel = 'aggregates_from';
