-- ============================================
-- Migration 038: Batch update record_items for backfill
-- ============================================
-- Purpose: Update many record_items in one roundtrip instead of N single-row updates.
-- Used by record_items_backfill_service: pass array of {id, product_name_clean?, on_sale?, product_id?}.
--
-- Run after: 037
-- ============================================

BEGIN;

CREATE OR REPLACE FUNCTION backfill_record_items_batch(updates jsonb)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  rec jsonb;
  cnt integer := 0;
  v_id uuid;
  v_product_name_clean text;
  v_on_sale boolean;
  v_product_id uuid;
BEGIN
  FOR rec IN SELECT * FROM jsonb_array_elements(updates)
  LOOP
    v_id := (rec->>'id')::uuid;
    IF v_id IS NULL THEN
      CONTINUE;
    END IF;

    v_product_name_clean := NULL;
    IF rec ? 'product_name_clean' THEN
      v_product_name_clean := (rec->>'product_name_clean');
    END IF;

    v_on_sale := NULL;
    IF rec ? 'on_sale' THEN
      v_on_sale := (rec->>'on_sale')::boolean;
    END IF;

    v_product_id := NULL;
    IF rec ? 'product_id' AND rec->'product_id' IS NOT NULL AND rec->'product_id' != 'null'::jsonb THEN
      v_product_id := (rec->>'product_id')::uuid;
    ELSIF rec ? 'product_id' THEN
      v_product_id := NULL;  -- explicit null
    END IF;

    UPDATE record_items
    SET
      product_name_clean = CASE WHEN rec ? 'product_name_clean' THEN v_product_name_clean ELSE product_name_clean END,
      on_sale = CASE WHEN rec ? 'on_sale' THEN v_on_sale ELSE on_sale END,
      product_id = CASE WHEN rec ? 'product_id' THEN v_product_id ELSE product_id END
    WHERE id = v_id;

    IF FOUND THEN
      cnt := cnt + 1;
    END IF;
  END LOOP;
  RETURN cnt;
END;
$$;

COMMENT ON FUNCTION backfill_record_items_batch IS 'Batch update record_items: product_name_clean, on_sale, product_id. Input: jsonb array of {id, product_name_clean?, on_sale?, product_id?}. Returns number of rows updated.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 038 completed: backfill_record_items_batch() RPC created';
END $$;
