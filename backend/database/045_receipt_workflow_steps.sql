-- ============================================
-- Migration 045: receipt_workflow_steps 表
--
-- 注意：本文件原来还包含 ALTER TABLE receipt_status 扩展 current_stage 的操作，
-- 以及对 receipt_status.current_stage 约束的修改。这些已合并到
-- 001_schema_v2.sql（receipt_status 建表时直接使用最终枚举值）。
--
-- 本文件现在只创建 receipt_workflow_steps 表。
--
-- PREREQUISITES: 001 (receipt_status, receipt_processing_runs)
-- ============================================

BEGIN;

CREATE TABLE IF NOT EXISTS receipt_workflow_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id uuid NOT NULL REFERENCES receipt_status(id) ON DELETE CASCADE,
  sequence int NOT NULL,
  step_name text NOT NULL,
  result text,
  run_id uuid REFERENCES receipt_processing_runs(id) ON DELETE SET NULL,
  details jsonb,
  created_at timestamptz DEFAULT now(),
  UNIQUE (receipt_id, sequence)
);

CREATE INDEX receipt_workflow_steps_receipt_id_idx ON receipt_workflow_steps(receipt_id);
CREATE INDEX receipt_workflow_steps_step_name_idx ON receipt_workflow_steps(step_name);

COMMENT ON TABLE receipt_workflow_steps IS
  'Ordered log of workflow steps/decisions per receipt for View workflow debug UI';
COMMENT ON COLUMN receipt_workflow_steps.step_name IS
  'e.g. rate_limit, dup_check, ocr, valid, addr_match, in_chain, rule_clean, llm_primary, vision_retry, etc.';
COMMENT ON COLUMN receipt_workflow_steps.result IS
  'pass|fail|yes|no|ok|reject|pending etc.';
COMMENT ON COLUMN receipt_workflow_steps.run_id IS
  'Link to receipt_processing_runs.id when this step produced a run';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 045 completed: receipt_workflow_steps table created (stage constraints already in 001)';
END $$;
