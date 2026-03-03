-- ============================================
-- Migration 046: user_strikes and user_lock for non-receipt uploads
-- ============================================
-- Purpose: 1h window strike count; 3 strikes -> 12h lock. See RECEIPT_WORKFLOW_CASCADE.md §9 TODO.
--
-- Run after: 045
-- ============================================

BEGIN;

-- One row per strike (user confirmed "clear receipt" but Vision+TxtOpenAI still failed / not a receipt)
CREATE TABLE IF NOT EXISTS user_strikes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  receipt_id uuid REFERENCES receipt_status(id) ON DELETE SET NULL,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX user_strikes_user_id_idx ON user_strikes(user_id);
CREATE INDEX user_strikes_created_at_idx ON user_strikes(created_at);

COMMENT ON TABLE user_strikes IS
  'Strikes when user confirmed receipt but result was not a receipt; 3 in 1h -> 12h lock';

-- One row per user when locked (12h from first strike of the 3rd)
CREATE TABLE IF NOT EXISTS user_lock (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE UNIQUE,
  locked_until timestamptz NOT NULL,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX user_lock_user_id_idx ON user_lock(user_id);
CREATE INDEX user_lock_locked_until_idx ON user_lock(locked_until);

COMMENT ON TABLE user_lock IS
  'User upload lock until locked_until (12h from 3 strikes in 1h)';

COMMIT;
