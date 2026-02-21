-- ============================================
-- Migration 039: Batch update record_items for sync_receipt_items
-- ============================================
-- Purpose: Update many record_items in one roundtrip during item sync (manual correction).
-- Input: jsonb array of {id, product_name?, product_name_clean?, quantity?, unit?, unit_price?, line_total?, on_sale?, original_price?, discount_amount?, item_index?, category_id?}.
--
-- Run after: 038
-- ============================================

BEGIN;

CREATE OR REPLACE FUNCTION sync_record_items_batch_update(updates jsonb)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  rec jsonb;
  cnt integer := 0;
  v_id uuid;
BEGIN
  FOR rec IN SELECT * FROM jsonb_array_elements(updates)
  LOOP
    v_id := (rec->>'id')::uuid;
    IF v_id IS NULL THEN
      CONTINUE;
    END IF;

    UPDATE record_items
    SET
      product_name       = CASE WHEN rec ? 'product_name'       THEN (rec->>'product_name')            ELSE product_name       END,
      product_name_clean = CASE WHEN rec ? 'product_name_clean' THEN (rec->>'product_name_clean')       ELSE product_name_clean END,
      quantity           = CASE WHEN rec ? 'quantity'           THEN (rec->'quantity')::bigint         ELSE quantity           END,
      unit               = CASE WHEN rec ? 'unit'               THEN (rec->>'unit')                    ELSE unit               END,
      unit_price         = CASE WHEN rec ? 'unit_price'         THEN (rec->'unit_price')::bigint       ELSE unit_price         END,
      line_total         = CASE WHEN rec ? 'line_total'         THEN (rec->'line_total')::bigint       ELSE line_total         END,
      on_sale            = CASE WHEN rec ? 'on_sale'            THEN (rec->'on_sale')::boolean         ELSE on_sale            END,
      original_price     = CASE WHEN rec ? 'original_price'     THEN (rec->'original_price')::bigint   ELSE original_price     END,
      discount_amount    = CASE WHEN rec ? 'discount_amount'    THEN (rec->'discount_amount')::bigint  ELSE discount_amount    END,
      item_index         = CASE WHEN rec ? 'item_index'         THEN (rec->'item_index')::integer      ELSE item_index         END,
      category_id        = CASE WHEN rec ? 'category_id'
                                THEN CASE WHEN rec->'category_id' IS NULL OR rec->'category_id' = 'null'::jsonb THEN NULL ELSE (rec->>'category_id')::uuid END
                                ELSE category_id END
    WHERE id = v_id;

    IF FOUND THEN
      cnt := cnt + 1;
    END IF;
  END LOOP;
  RETURN cnt;
END;
$$;

COMMENT ON FUNCTION sync_record_items_batch_update IS 'Batch update record_items for sync: product_name, product_name_clean, quantity, unit, unit_price, line_total, on_sale, original_price, discount_amount, item_index, category_id. Input: jsonb array of {id, ...}. Returns number of rows updated.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 039 completed: sync_record_items_batch_update() RPC created';
END $$;
