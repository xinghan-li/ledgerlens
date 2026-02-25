-- Migration: Support Firebase Auth alongside Supabase Auth
-- 1. Add firebase_uid for users who sign in with Firebase (nullable for existing Supabase users)
-- 2. Drop FK to auth.users so we can create new users from Firebase without a row in auth.users
-- Run after deploying backend that verifies Firebase ID tokens and find-or-creates by firebase_uid.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS firebase_uid TEXT UNIQUE;

CREATE UNIQUE INDEX IF NOT EXISTS users_firebase_uid_key ON users (firebase_uid) WHERE firebase_uid IS NOT NULL;

COMMENT ON COLUMN users.firebase_uid IS 'Firebase Auth UID (sub in ID token). Set when user signs in with Firebase.';

-- Drop FK so new Firebase-only users can be inserted with id = gen_random_uuid()
ALTER TABLE users
  DROP CONSTRAINT IF EXISTS users_id_fkey;

COMMENT ON TABLE users IS 'User profile. id: internal UUID. firebase_uid: set for Firebase-authenticated users.';
