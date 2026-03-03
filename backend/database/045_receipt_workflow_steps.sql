-- ============================================
-- Migration 045: receipt_workflow_steps + receipt_status stage values
-- ============================================
-- Purpose: Record every flowchart step/decision for a receipt so the frontend
-- can show the full workflow path (View workflow). Also allow new receipt stages.
-- See docs/architecture/RECEIPT_WORKFLOW_CASCADE.md
--
-- Run after: 044
-- ============================================

BEGIN;

-- Allow additional current_stage values for receipt_status
ALTER TABLE receipt_status
  DROP CONSTRAINT IF EXISTS receipt_status_current_stage_check;

ALTER TABLE receipt_status
  ADD CONSTRAINT receipt_status_current_stage_check
  CHECK (current_stage IN (
    'ocr', 'llm_primary', 'llm_fallback', 'manual',
    'rejected_not_receipt', 'pending_receipt_confirm'
  ));

COMMENT ON COLUMN receipt_status.current_stage IS
  'Current processing stage: ocr, llm_primary, llm_fallback, manual, rejected_not_receipt, pending_receipt_confirm';

-- Table: receipt_workflow_steps — one row per flowchart step/decision
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
  'e.g. rate_limit, dup_check, ocr, valid, addr_match, in_chain, rule_clean, llm_primary, first_ex, vision_retry, fallback_llm, cascade_1, cascade_2, textract_openai, user_confirm';
COMMENT ON COLUMN receipt_workflow_steps.result IS
  'pass|fail|yes|no|ok|reject|pending etc.';
COMMENT ON COLUMN receipt_workflow_steps.run_id IS
  'Link to receipt_processing_runs.id when this step produced a run';

COMMIT;
