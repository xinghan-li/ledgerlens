-- ============================================
-- Migration 018: Add price_snapshots table (PricePeek)
-- ============================================
-- Purpose: Aggregated price data for PricePeek (GasBuddy for groceries)
--
-- This table is:
-- - Derived from receipt_items (not source of truth)
-- - Updated via scheduled jobs
-- - Optimized for fast price queries
--
-- Use cases:
-- 1. "What's the current price of Dole Banana at Costco?"
-- 2. "Which store has the cheapest milk this week?"
-- 3. Price trends over time
-- 4. Sale notifications
--
-- PREREQUISITES: Migration 016 (products catalog) must be run first
-- ============================================

BEGIN;

-- ============================================
-- 1. Create price_snapshots table
-- ============================================
CREATE TABLE price_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- What and where
  product_id UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  store_location_id UUID NOT NULL REFERENCES store_locations(id) ON DELETE CASCADE,
  
  -- Price information (all in cents for precision)
  latest_price_cents INT NOT NULL,        -- Most recent price
  currency TEXT DEFAULT 'USD',
  
  -- Time window
  snapshot_date DATE NOT NULL,            -- Date of this snapshot
  last_seen_date DATE NOT NULL,           -- Last time this price was observed
  
  -- Aggregated statistics (within snapshot window)
  sample_count INT DEFAULT 1,             -- Number of observations
  avg_price_cents INT,                    -- Average price in time window
  min_price_cents INT,                    -- Minimum price seen
  max_price_cents INT,                    -- Maximum price seen
  
  -- Price change indicators
  previous_price_cents INT,               -- Price from previous snapshot
  price_change_cents INT,                 -- Change from previous
  price_change_percent NUMERIC(5, 2),    -- % change
  
  -- Sale information
  is_on_sale BOOLEAN DEFAULT FALSE,
  sale_count INT DEFAULT 0,               -- How many times on sale in window
  avg_discount_cents INT,                 -- Average discount when on sale
  
  -- Confidence and quality
  confidence_score NUMERIC(3, 2),         -- 0.00 - 1.00 (based on sample size)
  data_quality TEXT,                      -- 'high', 'medium', 'low'
  
  -- Contributors (for gamification)
  contributor_count INT DEFAULT 0,        -- Unique users who contributed
  
  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  
  -- Uniqueness: one snapshot per product per store per date
  CONSTRAINT price_snapshots_unique UNIQUE(product_id, store_location_id, snapshot_date),
  
  -- Validations
  CHECK (latest_price_cents > 0),
  CHECK (sample_count > 0),
  CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
  CHECK (data_quality IS NULL OR data_quality IN ('high', 'medium', 'low'))
);

-- ============================================
-- 2. Indexes for fast queries
-- ============================================
CREATE INDEX price_snapshots_product_idx ON price_snapshots(product_id);
CREATE INDEX price_snapshots_location_idx ON price_snapshots(store_location_id);
CREATE INDEX price_snapshots_date_idx ON price_snapshots(snapshot_date DESC);
CREATE INDEX price_snapshots_product_location_idx ON price_snapshots(product_id, store_location_id);
CREATE INDEX price_snapshots_product_date_idx ON price_snapshots(product_id, snapshot_date DESC);
CREATE INDEX price_snapshots_latest_idx ON price_snapshots(snapshot_date DESC, latest_price_cents);
CREATE INDEX price_snapshots_on_sale_idx ON price_snapshots(is_on_sale) WHERE is_on_sale = TRUE;

-- Trigger
CREATE TRIGGER price_snapshots_updated_at 
  BEFORE UPDATE ON price_snapshots
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================
-- 3. Comments
-- ============================================
COMMENT ON TABLE price_snapshots IS 'Aggregated price data for PricePeek price comparison (derived from receipt_items)';
COMMENT ON COLUMN price_snapshots.snapshot_date IS 'Date of this price snapshot (typically daily aggregation)';
COMMENT ON COLUMN price_snapshots.sample_count IS 'Number of receipt observations contributing to this snapshot';
COMMENT ON COLUMN price_snapshots.confidence_score IS 'Confidence in price accuracy (based on sample size, recency, etc.)';
COMMENT ON COLUMN price_snapshots.contributor_count IS 'Number of unique users who contributed price data';

-- ============================================
-- 4. Create materialized view for latest prices
-- ============================================
CREATE MATERIALIZED VIEW latest_prices AS
SELECT DISTINCT ON (product_id, store_location_id)
  ps.id,
  ps.product_id,
  ps.store_location_id,
  ps.latest_price_cents,
  ps.snapshot_date,
  ps.last_seen_date,
  ps.sample_count,
  ps.is_on_sale,
  ps.confidence_score,
  
  -- Denormalize for fast access
  p.normalized_name as product_name,
  sl.name as store_name,
  sl.city,
  sl.state
  
FROM price_snapshots ps
JOIN products p ON ps.product_id = p.id
JOIN store_locations sl ON ps.store_location_id = sl.id
ORDER BY product_id, store_location_id, snapshot_date DESC;

-- Index on materialized view
CREATE UNIQUE INDEX latest_prices_product_location_idx 
  ON latest_prices(product_id, store_location_id);
CREATE INDEX latest_prices_product_idx ON latest_prices(product_id);
CREATE INDEX latest_prices_location_idx ON latest_prices(store_location_id);
CREATE INDEX latest_prices_price_idx ON latest_prices(latest_price_cents);

COMMENT ON MATERIALIZED VIEW latest_prices IS 'Quick lookup for latest price of each product at each store (refresh daily)';

-- ============================================
-- 5. Aggregation function (called by cron job)
-- ============================================
CREATE OR REPLACE FUNCTION aggregate_prices_for_date(target_date DATE)
RETURNS INT AS $$
DECLARE
  rows_inserted INT := 0;
BEGIN
  -- Aggregate receipt_items data into price_snapshots
  INSERT INTO price_snapshots (
    product_id,
    store_location_id,
    latest_price_cents,
    snapshot_date,
    last_seen_date,
    sample_count,
    avg_price_cents,
    min_price_cents,
    max_price_cents,
    is_on_sale,
    sale_count,
    avg_discount_cents,
    contributor_count,
    confidence_score,
    data_quality
  )
  SELECT
    ri.product_id,
    rs.store_location_id,
    
    -- Latest price (from most recent receipt)
    (ARRAY_AGG(ROUND(ri.unit_price * 100) ORDER BY rs.receipt_date DESC))[1]::INT as latest_price_cents,
    
    target_date as snapshot_date,
    MAX(rs.receipt_date) as last_seen_date,
    COUNT(*) as sample_count,
    
    -- Statistical aggregations
    ROUND(AVG(ri.unit_price * 100))::INT as avg_price_cents,
    ROUND(MIN(ri.unit_price * 100))::INT as min_price_cents,
    ROUND(MAX(ri.unit_price * 100))::INT as max_price_cents,
    
    -- Sale information
    BOOL_OR(ri.on_sale) as is_on_sale,
    COUNT(*) FILTER (WHERE ri.on_sale) as sale_count,
    ROUND(AVG(ri.discount_amount * 100) FILTER (WHERE ri.on_sale))::INT as avg_discount_cents,
    
    -- Contributors
    COUNT(DISTINCT ri.user_id) as contributor_count,
    
    -- Confidence score (based on sample size)
    CASE 
      WHEN COUNT(*) >= 20 THEN 1.0
      WHEN COUNT(*) >= 10 THEN 0.9
      WHEN COUNT(*) >= 5 THEN 0.8
      WHEN COUNT(*) >= 2 THEN 0.6
      ELSE 0.4
    END as confidence_score,
    
    -- Data quality assessment
    CASE
      WHEN COUNT(*) >= 10 AND COUNT(DISTINCT ri.user_id) >= 3 THEN 'high'
      WHEN COUNT(*) >= 5 AND COUNT(DISTINCT ri.user_id) >= 2 THEN 'medium'
      ELSE 'low'
    END as data_quality
    
  FROM receipt_items ri
  JOIN receipts r ON ri.receipt_id = r.id
  JOIN receipt_summaries rs ON r.id = rs.receipt_id
  WHERE ri.product_id IS NOT NULL
    AND rs.store_location_id IS NOT NULL
    AND rs.receipt_date = target_date
    AND ri.unit_price IS NOT NULL
    AND ri.unit_price > 0
  GROUP BY ri.product_id, rs.store_location_id
  
  ON CONFLICT (product_id, store_location_id, snapshot_date) 
  DO UPDATE SET
    latest_price_cents = EXCLUDED.latest_price_cents,
    last_seen_date = EXCLUDED.last_seen_date,
    sample_count = price_snapshots.sample_count + EXCLUDED.sample_count,
    avg_price_cents = EXCLUDED.avg_price_cents,
    min_price_cents = LEAST(price_snapshots.min_price_cents, EXCLUDED.min_price_cents),
    max_price_cents = GREATEST(price_snapshots.max_price_cents, EXCLUDED.max_price_cents),
    is_on_sale = EXCLUDED.is_on_sale,
    sale_count = price_snapshots.sale_count + EXCLUDED.sale_count,
    avg_discount_cents = EXCLUDED.avg_discount_cents,
    contributor_count = EXCLUDED.contributor_count,
    confidence_score = EXCLUDED.confidence_score,
    data_quality = EXCLUDED.data_quality,
    updated_at = NOW();
  
  GET DIAGNOSTICS rows_inserted = ROW_COUNT;
  
  -- Refresh materialized view (if exists)
  BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY latest_prices;
  EXCEPTION WHEN OTHERS THEN
    -- Ignore if materialized view doesn't support concurrent refresh yet
    REFRESH MATERIALIZED VIEW latest_prices;
  END;
  
  RETURN rows_inserted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION aggregate_prices_for_date IS 'Aggregate receipt_items into price_snapshots for a given date. Run daily via cron job.';

-- ============================================
-- 6. Helper function to aggregate all historical dates
-- ============================================
CREATE OR REPLACE FUNCTION backfill_all_price_snapshots()
RETURNS TABLE (
  date_processed DATE,
  rows_inserted INT
) AS $$
DECLARE
  start_date DATE;
  end_date DATE;
  process_date DATE;
  rows INT;
BEGIN
  -- Get date range from receipt_summaries
  SELECT MIN(receipt_date), MAX(receipt_date) 
  INTO start_date, end_date
  FROM receipt_summaries
  WHERE store_location_id IS NOT NULL;
  
  IF start_date IS NULL THEN
    RAISE NOTICE 'No receipts with store_location_id found, nothing to backfill';
    RETURN;
  END IF;
  
  RAISE NOTICE 'Backfilling price snapshots from % to %', start_date, end_date;
  
  process_date := start_date;
  
  WHILE process_date <= end_date LOOP
    rows := aggregate_prices_for_date(process_date);
    
    RETURN QUERY SELECT process_date, rows;
    
    process_date := process_date + INTERVAL '1 day';
  END LOOP;
  
  RAISE NOTICE 'Backfill completed';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION backfill_all_price_snapshots IS 'Backfill all historical price snapshots (run once after migration)';

-- ============================================
-- 7. Verification
-- ============================================
DO $$
BEGIN
  RAISE NOTICE 'Migration 018 completed successfully.';
  RAISE NOTICE 'Created price_snapshots table and aggregation functions';
  RAISE NOTICE '';
  RAISE NOTICE 'Next steps:';
  RAISE NOTICE '1. After backfilling products and receipt_items.product_id:';
  RAISE NOTICE '   SELECT * FROM backfill_all_price_snapshots();';
  RAISE NOTICE '';
  RAISE NOTICE '2. Set up daily cron job to run:';
  RAISE NOTICE '   SELECT aggregate_prices_for_date(CURRENT_DATE);';
  RAISE NOTICE '';
  RAISE NOTICE '3. Refresh materialized view is automatic in aggregation function';
END $$;

COMMIT;

-- ============================================
-- Example queries for PricePeek
-- ============================================

-- Get latest price of a product across all stores
-- SELECT 
--   p.normalized_name,
--   b.name as brand,
--   sl.name as store,
--   lp.latest_price_cents / 100.0 as price,
--   lp.last_seen_date,
--   lp.is_on_sale,
--   lp.confidence_score
-- FROM latest_prices lp
-- JOIN products p ON lp.product_id = p.id
-- LEFT JOIN brands b ON p.brand_id = b.id
-- JOIN store_locations sl ON lp.store_location_id = sl.id
-- WHERE p.normalized_name = 'banana'
-- ORDER BY lp.latest_price_cents;

-- Price trend for a product at a specific store
-- SELECT 
--   snapshot_date,
--   latest_price_cents / 100.0 as price,
--   sample_count,
--   is_on_sale
-- FROM price_snapshots
-- WHERE product_id = 'some-uuid'
--   AND store_location_id = 'some-uuid'
-- ORDER BY snapshot_date DESC
-- LIMIT 30;

-- Best deals today
-- SELECT 
--   p.normalized_name,
--   b.name as brand,
--   sl.name as store,
--   ps.latest_price_cents / 100.0 as current_price,
--   ps.avg_price_cents / 100.0 as avg_price,
--   ps.price_change_percent,
--   ps.confidence_score
-- FROM price_snapshots ps
-- JOIN products p ON ps.product_id = p.id
-- LEFT JOIN brands b ON p.brand_id = b.id
-- JOIN store_locations sl ON ps.store_location_id = sl.id
-- WHERE ps.snapshot_date = CURRENT_DATE
--   AND ps.is_on_sale = TRUE
--   AND ps.confidence_score >= 0.6
-- ORDER BY ps.price_change_percent
-- LIMIT 20;
