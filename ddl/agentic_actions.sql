-- Databricks notebook source
-- =============================================================================
-- ddl/agentic_actions.sql — shared human-in-the-loop infra for action agents
-- -----------------------------------------------------------------------------
-- The action_queue + action_feedback tables are the SHARED surface for every
-- "agent beyond BI" (collections, revenue-leakage, churn, ...): agents write
-- PROPOSALS; humans approve/reject/edit; decisions + outcomes feed the feedback
-- loop that improves the agents. Idempotent. Parameterized on :catalog.
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS ${catalog}.ops
  COMMENT 'Operational + agentic-action tables (queues, feedback, run logs).';

-- Proposed actions awaiting human approval ------------------------------------
CREATE TABLE IF NOT EXISTS ${catalog}.ops.action_queue (
  action_id           STRING    COMMENT 'sha2(account_id::run_id) — stable per run',
  agent               STRING    COMMENT 'which agent proposed (e.g. collections)',
  account_id          STRING,
  account_name        STRING,
  master_customer_id  STRING,
  signal              STRING    COMMENT 'one-line trigger summary',
  priority            STRING    COMMENT 'P1 / P2 / P3',
  action_type         STRING    COMMENT 'dunning_email / csm_escalation / watch',
  diagnosis           STRING    COMMENT 'agent root-cause explanation',
  draft               STRING    COMMENT 'drafted action (email/task) — NEVER auto-sent',
  status              STRING    COMMENT 'pending / approved / rejected / edited / sent',
  reviewer            STRING,
  reviewed_at         TIMESTAMP,
  run_id              STRING,
  _created_at         TIMESTAMP
)
COMMENT 'Human-in-the-loop queue: agent proposals awaiting approval. Draft-only.';

-- Human decisions + downstream outcomes (the feedback / learning signal) ------
CREATE TABLE IF NOT EXISTS ${catalog}.ops.action_feedback (
  action_id     STRING,
  account_id    STRING,
  decision      STRING   COMMENT 'approved / rejected / edited',
  edited_draft  STRING   COMMENT 'human-corrected draft, if edited (few-shot signal)',
  reviewer      STRING,
  comment       STRING   COMMENT 'why — feeds prompt/eval improvement',
  outcome       STRING   COMMENT 'later: paid / partial / no_response / disputed',
  _feedback_at  TIMESTAMP
)
COMMENT 'Approvals/edits/outcomes — the feedback loop that tunes the action agents.';
