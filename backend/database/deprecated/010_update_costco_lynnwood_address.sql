-- 010_update_costco_lynnwood_address.sql
-- Update Costco Lynnwood store address to canonical format: 18109 33rd Ave W, Lynnwood, WA 98037
-- Run against store_locations where name matches Lynnwood and chain is Costco Wholesale

UPDATE store_locations sl
SET
  address_line1 = '18109 33rd Ave W',
  address_line2 = NULL,
  city = 'Lynnwood',
  state = 'WA',
  zip_code = '98037',
  country_code = 'US',
  updated_at = now()
FROM store_chains sc
WHERE sl.chain_id = sc.id
  AND (sc.name ILIKE '%Costco%' OR sc.name ILIKE '%costco%')
  AND (sl.name ILIKE '%Lynnwood%' OR sl.name ILIKE '%lynnwood%');
