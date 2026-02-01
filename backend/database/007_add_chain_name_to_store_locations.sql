-- ============================================
-- 007_add_chain_name_to_store_locations.sql
-- Add chain_name column to store_locations table for human-readable reference
-- ============================================

-- Add chain_name column to store_locations table
ALTER TABLE store_locations 
ADD COLUMN chain_name TEXT;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS store_locations_chain_name_idx ON store_locations(chain_name);

-- Add comment
COMMENT ON COLUMN store_locations.chain_name IS 
  'Human-readable chain name for reference. Should match store_chains.name. Updated via trigger.';

-- ============================================
-- Create trigger function to automatically update chain_name
-- ============================================
-- This trigger will automatically keep chain_name in sync with store_chains.name
CREATE OR REPLACE FUNCTION update_store_location_chain_name()
RETURNS TRIGGER AS $$
BEGIN
    -- Update chain_name when chain_id changes
    IF NEW.chain_id IS NOT NULL THEN
        SELECT name INTO NEW.chain_name
        FROM store_chains
        WHERE id = NEW.chain_id;
    ELSE
        NEW.chain_name = NULL;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger for INSERT and UPDATE
DROP TRIGGER IF EXISTS trigger_update_store_location_chain_name ON store_locations;
CREATE TRIGGER trigger_update_store_location_chain_name
    BEFORE INSERT OR UPDATE OF chain_id ON store_locations
    FOR EACH ROW
    EXECUTE FUNCTION update_store_location_chain_name();

-- ============================================
-- Data Backfill Notes
-- ============================================
-- NOTE: Data backfill operations have been moved to:
-- - backend/database/2026-01-31_MIGRATION_NOTES.md (Section 6.1)
-- 
-- To backfill chain_name from store_chains, see the migration notes.
