-- ============================================
-- Migration 072: Confidence score — string → numeric (0-1 float)
-- ============================================
-- Changes confidence output from "high"/"medium"/"low" strings to a 0-1 float.
-- This enables the backend to gate on confidence threshold:
--   sum check PASS + confidence < CONFIDENCE_THRESHOLD → escalation.
--
-- Affected prompts: vision_primary (Rule 6, Rule 11, schema example),
--                   vision_escalation (Rule 6, schema example).
-- Uses DO $$ blocks with dollar-quoted strings to avoid E'...' escaping issues.
-- ============================================

BEGIN;

-- --------------------------------------------
-- vision_primary: 3 replacements
-- --------------------------------------------
DO $migrate_vp$
DECLARE
  _content TEXT;
BEGIN
  SELECT content INTO _content
  FROM prompt_library
  WHERE key = 'vision_primary' AND is_active = TRUE;

  IF _content IS NULL THEN
    RAISE NOTICE 'vision_primary not found or inactive — skipping';
    RETURN;
  END IF;

  -- 1) Rule 6: confidence tier → numeric decrement
  _content := REPLACE(
    _content,
    $$     → Lower _metadata.confidence by one tier (high→medium, medium→low).$$,
    $$     → Lower _metadata.confidence by 0.15.$$
  );

  -- 2) Rule 11: full rewrite of confidence definition
  _content := REPLACE(
    _content,
    $$11. Set _metadata.validation_status and _metadata.confidence with detailed reasoning:
   - Start with validation_status="pass" and confidence="high".
   - Downgrade to confidence="medium" if:
     * Any item has a price discrepancy ≤ 3% (Rule 6 soft warning)
     * Any field is unclear but best-effort readable
   - Downgrade to confidence="low" if:
     * Any item has a price discrepancy > 3% (Rule 6 hard warning)
     * Image is blurry or partially obscured for any section
   - Set validation_status="needs_review" if:
     * Sum check cannot pass after honest re-examination (Rule 9)
     * Item count on receipt does not match items extracted (see Rule 12)
     * confidence="low" AND sum_check_passed=false
   - Set _metadata.reasoning to a plain-English explanation of your validation_status
     and confidence decisions. Be specific: name which items or fields caused issues. Use dollar amounts in reasoning (e.g. $198.59), not cents.$$,
    $$11. Set _metadata.validation_status and _metadata.confidence with detailed reasoning:
   - confidence is a FLOAT between 0.0 and 1.0 representing your overall certainty
     that all fields are extracted correctly, no items are missing, and sum check self-verifies.
   - Start with validation_status="pass" and confidence=0.95.
   - Subtract 0.10 if any item has a price discrepancy ≤ 3% (Rule 6 soft warning).
   - Subtract 0.10 if any field is unclear but best-effort readable.
   - Subtract 0.20 if any item has a price discrepancy > 3% (Rule 6 hard warning).
   - Subtract 0.20 if image is blurry or partially obscured for any section.
   - Set validation_status="needs_review" if:
     * Sum check cannot pass after honest re-examination (Rule 9)
     * Item count on receipt does not match items extracted (see Rule 12)
     * confidence < 0.50 AND sum_check_passed=false
   - Set _metadata.reasoning to a plain-English explanation of your validation_status
     and confidence decisions. Be specific: name which items or fields caused issues. Use dollar amounts in reasoning (e.g. $198.59), not cents.$$
  );

  -- 3) Schema example: "confidence": "high" → 0.95
  _content := REPLACE(
    _content,
    '"confidence": "high"',
    '"confidence": 0.95'
  );

  UPDATE prompt_library
  SET content = _content, updated_at = NOW()
  WHERE key = 'vision_primary' AND is_active = TRUE;

  RAISE NOTICE 'vision_primary updated';
END;
$migrate_vp$;

-- --------------------------------------------
-- vision_escalation: 2 replacements
-- --------------------------------------------
DO $migrate_ve$
DECLARE
  _content TEXT;
BEGIN
  SELECT content INTO _content
  FROM prompt_library
  WHERE key = 'vision_escalation' AND is_active = TRUE;

  IF _content IS NULL THEN
    RAISE NOTICE 'vision_escalation not found or inactive — skipping';
    RETURN;
  END IF;

  -- 1) Rule 6: confidence tier → numeric decrement
  _content := REPLACE(
    _content,
    $$     → Lower confidence by one tier.$$,
    $$     → Lower confidence by 0.15.$$
  );

  -- 2) Schema example: "confidence": "high" → 0.95
  _content := REPLACE(
    _content,
    '"confidence": "high"',
    '"confidence": 0.95'
  );

  UPDATE prompt_library
  SET content = _content, updated_at = NOW()
  WHERE key = 'vision_escalation' AND is_active = TRUE;

  RAISE NOTICE 'vision_escalation updated';
END;
$migrate_ve$;

COMMIT;

-- Verification
DO $$
DECLARE
  vp_check TEXT;
  ve_check TEXT;
BEGIN
  SELECT substring(content from '"confidence": ([0-9.]+)') INTO vp_check
  FROM prompt_library WHERE key = 'vision_primary' AND is_active = TRUE;
  SELECT substring(content from '"confidence": ([0-9.]+)') INTO ve_check
  FROM prompt_library WHERE key = 'vision_escalation' AND is_active = TRUE;
  RAISE NOTICE 'Migration 072 verify: vision_primary confidence=%, vision_escalation confidence=%', vp_check, ve_check;
END $$;
