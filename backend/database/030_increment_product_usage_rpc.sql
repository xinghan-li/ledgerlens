-- ============================================
-- Migration 030: RPC 函数集合
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   038_backfill_record_items_batch_rpc.sql       → backfill_record_items_batch()
--   039_sync_record_items_batch_update_rpc.sql    → sync_record_items_batch_update()
--
-- PREREQUISITES: 012 (record_items)
-- ============================================

BEGIN;

-- ============================================
-- 1. increment_product_usage（来自 030 原始）
-- ============================================
CREATE OR REPLACE FUNCTION increment_product_usage(
  p_product_id UUID,
  p_category_id UUID DEFAULT NULL,
  p_last_seen_date DATE DEFAULT NULL
)
RETURNS VOID AS $$
BEGIN
  UPDATE products
  SET
    usage_count = usage_count + 1,
    category_id = COALESCE(p_category_id, category_id),
    last_seen_date = COALESCE(p_last_seen_date, last_seen_date)
  WHERE id = p_product_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION increment_product_usage IS 'Atomically increment usage_count and optionally set category_id/last_seen_date for a product';

-- ============================================
-- 2. backfill_record_items_batch（来自 038）
-- ============================================
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

COMMENT ON FUNCTION backfill_record_items_batch IS 'Batch update record_items: product_name_clean, on_sale, product_id. Input: jsonb array of {id, product_name_clean?, on_sale?, product_id?}. Returns rows updated.';

-- ============================================
-- 3. sync_record_items_batch_update（来自 039）
-- ============================================
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
      quantity           = CASE WHEN rec ? 'quantity'           THEN (rec->'quantity')::bigint          ELSE quantity           END,
      unit               = CASE WHEN rec ? 'unit'               THEN (rec->>'unit')                     ELSE unit               END,
      unit_price         = CASE WHEN rec ? 'unit_price'         THEN (rec->'unit_price')::bigint        ELSE unit_price         END,
      line_total         = CASE WHEN rec ? 'line_total'         THEN (rec->'line_total')::bigint        ELSE line_total         END,
      on_sale            = CASE WHEN rec ? 'on_sale'            THEN (rec->'on_sale')::boolean          ELSE on_sale            END,
      original_price     = CASE WHEN rec ? 'original_price'     THEN (rec->'original_price')::bigint    ELSE original_price     END,
      discount_amount    = CASE WHEN rec ? 'discount_amount'    THEN (rec->'discount_amount')::bigint   ELSE discount_amount    END,
      item_index         = CASE WHEN rec ? 'item_index'         THEN (rec->'item_index')::integer       ELSE item_index         END,
      category_id        = CASE WHEN rec ? 'category_id'
                                THEN CASE WHEN rec->'category_id' IS NULL OR rec->'category_id' = 'null'::jsonb
                                          THEN NULL
                                          ELSE (rec->>'category_id')::uuid END
                                ELSE category_id END
    WHERE id = v_id;

    IF FOUND THEN
      cnt := cnt + 1;
    END IF;
  END LOOP;
  RETURN cnt;
END;
$$;

COMMENT ON FUNCTION sync_record_items_batch_update IS 'Batch update record_items for sync: product_name, product_name_clean, quantity, unit, unit_price, line_total, on_sale, original_price, discount_amount, item_index, category_id. Returns rows updated.';

COMMIT;

DO $$
BEGIN
  RAISE NOTICE 'Migration 030 completed: increment_product_usage + backfill_record_items_batch + sync_record_items_batch_update (incl. 038+039)';
END $$;
