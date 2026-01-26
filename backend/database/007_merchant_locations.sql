-- Merchant Locations: Canonical merchant information with standardized addresses
-- This table stores the "source of truth" for merchant addresses to correct OCR errors

create table if not exists merchant_locations (
  id bigint generated always as identity primary key,
  
  -- Merchant identification
  merchant_name text not null,  -- Canonical merchant name
  merchant_aliases text[],  -- Alternative names for fuzzy matching
  
  -- Address components (standardized)
  address_line1 text not null,  -- Street address
  address_line2 text,  -- Unit, Suite, etc. (optional)
  city text not null,
  state text not null,  -- State/Province
  country text not null,  -- USA, Canada, etc.
  zip_code text not null,
  
  -- Contact information
  phone text,
  
  -- Location metadata
  coordinates point,  -- (latitude, longitude) for geo queries
  timezone text,  -- e.g., "America/Los_Angeles"
  
  -- Matching configuration
  fuzzy_match_threshold numeric(3, 2) default 0.85,  -- Similarity threshold for auto-correction
  
  -- Metadata
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  is_active boolean default true
);

-- Indexes for fast lookup
create index merchant_locations_name_idx on merchant_locations(merchant_name);
create index merchant_locations_aliases_idx on merchant_locations using gin(merchant_aliases);
create index merchant_locations_city_state_idx on merchant_locations(city, state);
create index merchant_locations_coords_idx on merchant_locations using gist(coordinates);

-- Trigger to update updated_at
create or replace function update_merchant_locations_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger merchant_locations_updated_at
  before update on merchant_locations
  for each row
  execute function update_merchant_locations_updated_at();

-- Insert initial data (examples from your receipts)
insert into merchant_locations (merchant_name, merchant_aliases, address_line1, city, state, country, zip_code, phone) values
  (
    'T&T Supermarket - Lynnwood',
    ARRAY['T&T Supermarket US', 'T&T Supermarket US Lynnwood Store', 'TNT Supermarket', 'T & T'],
    '19630 Hwy 99',
    'Lynnwood',
    'WA',
    'USA',
    '98036',
    '(425) 648-2648'
  ),
  (
    'T&T Supermarket - Osaka (Richmond)',
    ARRAY['T&T Supermarket Osaka Store', 'TNT Supermarket - Osaka Branch', 'T&T Osaka'],
    '#1000-3700 No.3 Rd.',
    'Richmond',
    'BC',
    'Canada',
    'V6X 3X2',
    '(604) 276-8808'
  ),
  (
    '99 Ranch Market - Fremont',
    ARRAY['99 Ranch Market', '99 Ranch', 'Ranch 99'],
    '34444 Fremont Blvd',
    'Fremont',
    'CA',
    'USA',
    '94555',
    '(510) 791-8899'
  ),
  (
    'In-N-Out Burger - Fremont',
    ARRAY['In N Out', 'In-N-Out', 'INO', 'In N Out Burger'],
    '43349 Pacific Commons Blvd',
    'Fremont',
    'CA',
    'USA',
    '94538',
    '(800) 786-1000'
  ),
  (
    'Trader Joe''s - Lynnwood',
    ARRAY['Trader Joes', 'TJs'],
    '19715 Highway 99',
    'Lynnwood',
    'WA',
    'USA',
    '98036',
    NULL
  );

-- Helper function to get full address string
create or replace function get_full_address(location_id bigint)
returns text as $$
declare
  loc merchant_locations;
  addr text;
begin
  select * into loc from merchant_locations where id = location_id;
  
  if loc is null then
    return null;
  end if;
  
  addr := loc.address_line1;
  
  if loc.address_line2 is not null then
    addr := addr || ', ' || loc.address_line2;
  end if;
  
  addr := addr || E'\n' || loc.city || ', ' || loc.state || ' ' || loc.zip_code;
  
  if loc.country is not null then
    addr := addr || E'\n' || loc.country;
  end if;
  
  return addr;
end;
$$ language plpgsql;
