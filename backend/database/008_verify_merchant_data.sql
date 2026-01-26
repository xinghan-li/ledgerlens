-- Verify and update merchant location data
-- This ensures country fields are set correctly for all merchants

-- Update 99 Ranch Market - Fremont: Add country
UPDATE merchant_locations
SET 
  country = 'USA'
WHERE merchant_name = '99 Ranch Market - Fremont' 
  AND (country IS NULL OR country = '');

-- Update T&T Supermarket: Fix name and add aliases for TNT (common OCR error)
UPDATE merchant_locations
SET 
  merchant_name = 'T&T Supermarket Canada',
  merchant_aliases = ARRAY[
    'T&T Supermarket Osaka Store', 
    'TNT Supermarket - Osaka Branch', 
    'T&T Osaka', 
    'TNT', 
    'TNT Supermarket',
    'T & T', 
    'T&T Supermarket',
    'T&T'
  ]
WHERE merchant_name = 'T&T Supermarket - Osaka (Richmond)'
   OR merchant_name LIKE '%T&T%Osaka%'
   OR merchant_name LIKE '%TNT%';

-- Verify all merchants have country set
SELECT 
  id,
  merchant_name,
  country,
  CASE 
    WHEN country IS NULL OR country = '' THEN '⚠️ Missing country'
    ELSE '✓ OK'
  END as status
FROM merchant_locations
ORDER BY merchant_name;

-- Show final data
SELECT 
  merchant_name,
  merchant_aliases,
  address_line1,
  address_line2,
  city,
  state,
  country,
  zip_code
FROM merchant_locations
ORDER BY merchant_name;
