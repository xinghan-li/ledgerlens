-- ============================================
-- 044_rls_policies.sql
-- RLS Migration: Row-Level Security for LedgerLens
-- Run in Supabase SQL Editor (public schema)
--
-- Ensures: premium/free users see only their own data;
-- super_admin and admin can read (and where needed, manage) all rows.
-- ============================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Helper: true if current user is super_admin or admin
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.users
    WHERE id = auth.uid() AND user_class IN ('super_admin', 'admin')
  );
$$;

COMMENT ON FUNCTION public.is_admin() IS 'True if current JWT user is super_admin or admin; used by RLS policies.';

-- ============================================
-- 1. USERS
-- ============================================
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_own_row"
  ON public.users FOR ALL
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

CREATE POLICY "users_admin_read_all"
  ON public.users FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 2. RECEIPT_STATUS (user_id)
-- ============================================
ALTER TABLE public.receipt_status ENABLE ROW LEVEL SECURITY;

CREATE POLICY "receipt_status_own"
  ON public.receipt_status FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "receipt_status_admin_read_all"
  ON public.receipt_status FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 3. RECORD_SUMMARIES (user_id)
-- ============================================
ALTER TABLE public.record_summaries ENABLE ROW LEVEL SECURITY;

CREATE POLICY "record_summaries_own"
  ON public.record_summaries FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "record_summaries_admin_read_all"
  ON public.record_summaries FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 4. RECORD_ITEMS (user_id)
-- ============================================
ALTER TABLE public.record_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "record_items_own"
  ON public.record_items FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

CREATE POLICY "record_items_admin_read_all"
  ON public.record_items FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 5. RECEIPT_PROCESSING_RUNS (via receipt_id)
-- ============================================
ALTER TABLE public.receipt_processing_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "receipt_processing_runs_own"
  ON public.receipt_processing_runs FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM public.receipt_status rs
      WHERE rs.id = receipt_processing_runs.receipt_id
        AND rs.user_id = auth.uid()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.receipt_status rs
      WHERE rs.id = receipt_processing_runs.receipt_id
        AND rs.user_id = auth.uid()
    )
  );

CREATE POLICY "receipt_processing_runs_admin_read_all"
  ON public.receipt_processing_runs FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 6. API_CALLS (via receipt_id)
-- ============================================
ALTER TABLE public.api_calls ENABLE ROW LEVEL SECURITY;

CREATE POLICY "api_calls_own"
  ON public.api_calls FOR ALL
  USING (
    receipt_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM public.receipt_status rs
      WHERE rs.id = api_calls.receipt_id
        AND rs.user_id = auth.uid()
    )
  )
  WITH CHECK (
    receipt_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM public.receipt_status rs
      WHERE rs.id = api_calls.receipt_id
        AND rs.user_id = auth.uid()
    )
  );

CREATE POLICY "api_calls_admin_read_all"
  ON public.api_calls FOR SELECT
  USING (public.is_admin());

-- ============================================
-- 7. STORE_CANDIDATES (via receipt_id)
-- ============================================
ALTER TABLE public.store_candidates ENABLE ROW LEVEL SECURITY;

CREATE POLICY "store_candidates_own"
  ON public.store_candidates FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM public.receipt_status rs
      WHERE rs.id = store_candidates.receipt_id
        AND rs.user_id = auth.uid()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.receipt_status rs
      WHERE rs.id = store_candidates.receipt_id
        AND rs.user_id = auth.uid()
    )
  );

CREATE POLICY "store_candidates_admin_all"
  ON public.store_candidates FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 8. CLASSIFICATION_REVIEW (via source_record_item_id → record_items.user_id)
-- ============================================
ALTER TABLE public.classification_review ENABLE ROW LEVEL SECURITY;

CREATE POLICY "classification_review_own"
  ON public.classification_review FOR SELECT
  USING (
    source_record_item_id IS NOT NULL
    AND EXISTS (
      SELECT 1 FROM public.record_items ri
      WHERE ri.id = classification_review.source_record_item_id
        AND ri.user_id = auth.uid()
    )
  );

CREATE POLICY "classification_review_admin_all"
  ON public.classification_review FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 9. PRODUCT_CATEGORIZATION_RULES (created_by; read for all, write admin)
-- ============================================
ALTER TABLE public.product_categorization_rules ENABLE ROW LEVEL SECURITY;

CREATE POLICY "product_categorization_rules_select_authenticated"
  ON public.product_categorization_rules FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "product_categorization_rules_admin_write"
  ON public.product_categorization_rules FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 10. CATEGORIES (global tree; read all authenticated, write admin)
-- ============================================
ALTER TABLE public.categories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "categories_select_authenticated"
  ON public.categories FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "categories_admin_write"
  ON public.categories FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 11. PRODUCTS (global catalog; read all authenticated, write admin)
-- ============================================
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;

CREATE POLICY "products_select_authenticated"
  ON public.products FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "products_admin_write"
  ON public.products FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 12. STORE_CHAINS (global; read authenticated, write admin)
-- ============================================
ALTER TABLE public.store_chains ENABLE ROW LEVEL SECURITY;

CREATE POLICY "store_chains_select_authenticated"
  ON public.store_chains FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "store_chains_admin_write"
  ON public.store_chains FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 13. STORE_LOCATIONS (global; read authenticated, write admin)
-- ============================================
ALTER TABLE public.store_locations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "store_locations_select_authenticated"
  ON public.store_locations FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "store_locations_admin_write"
  ON public.store_locations FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 14. PRICE_SNAPSHOTS (global; read authenticated, write admin)
-- ============================================
ALTER TABLE public.price_snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY "price_snapshots_select_authenticated"
  ON public.price_snapshots FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "price_snapshots_admin_write"
  ON public.price_snapshots FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 15. PROMPT_LIBRARY (global config; read authenticated, write admin)
-- ============================================
ALTER TABLE public.prompt_library ENABLE ROW LEVEL SECURITY;

CREATE POLICY "prompt_library_select_authenticated"
  ON public.prompt_library FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "prompt_library_admin_write"
  ON public.prompt_library FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

-- ============================================
-- 16. PROMPT_BINDING (global config; read authenticated, write admin)
-- ============================================
ALTER TABLE public.prompt_binding ENABLE ROW LEVEL SECURITY;

CREATE POLICY "prompt_binding_select_authenticated"
  ON public.prompt_binding FOR SELECT
  USING (auth.uid() IS NOT NULL);

CREATE POLICY "prompt_binding_admin_write"
  ON public.prompt_binding FOR ALL
  USING (public.is_admin())
  WITH CHECK (public.is_admin());

COMMIT;
