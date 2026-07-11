-- Databricks notebook source
-- MAGIC %md
-- MAGIC # Collections — Action Review (human-in-the-loop)
-- MAGIC The steward surface for the agentic-action loop: review agent PROPOSALS,
-- MAGIC then **approve / reject / edit**. Decisions record to `ops.action_feedback`
-- MAGIC (the learning signal) and flip the queue status. Nothing is sent by the
-- MAGIC agent — a human is always the gate. (Table-based v1; a Databricks App UI
-- MAGIC is the natural next step.)

-- COMMAND ----------
CREATE WIDGET TEXT catalog DEFAULT 'cdp_dev';
CREATE WIDGET TEXT action_id DEFAULT '';
CREATE WIDGET DROPDOWN decision DEFAULT 'approved' CHOICES SELECT explode(array('approved','rejected','edited'));
CREATE WIDGET TEXT reviewer DEFAULT '';
CREATE WIDGET TEXT comment DEFAULT '';

-- COMMAND ----------
-- MAGIC %md ## 1. Pending proposals (highest priority first)
SELECT priority, account_name, action_type, signal, diagnosis, draft, action_id
FROM ${catalog}.ops.action_queue
WHERE status = 'pending'
ORDER BY priority, account_name;

-- COMMAND ----------
-- MAGIC %md ## 2. Record a decision
-- MAGIC Set the `action_id`, `decision`, `reviewer` (and `comment`) widgets, then run.
-- MAGIC For **edited**, paste the corrected text into `comment` — it's captured as the
-- MAGIC few-shot signal.
INSERT INTO ${catalog}.ops.action_feedback
SELECT getargument('action_id'), account_id, getargument('decision'),
       CASE WHEN getargument('decision')='edited' THEN getargument('comment') END,
       getargument('reviewer'), getargument('comment'), NULL, current_timestamp()
FROM ${catalog}.ops.action_queue
WHERE action_id = getargument('action_id');

-- COMMAND ----------
UPDATE ${catalog}.ops.action_queue
SET status = getargument('decision'),
    reviewer = getargument('reviewer'),
    reviewed_at = current_timestamp()
WHERE action_id = getargument('action_id');

-- COMMAND ----------
-- MAGIC %md ## 3. Feedback so far (the learning signal)
SELECT decision, count(*) AS n FROM ${catalog}.ops.action_feedback GROUP BY decision;
