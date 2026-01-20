-- Create merchants table

create table merchants (
  id bigint generated always as identity primary key,
  name text not null,
  normalized_name text not null,
  external_id text,
  created_at timestamptz default now()
);

create unique index merchants_normalized_name_idx
  on merchants (normalized_name);

-- Create products table (no FK to merchants)

create table products (
  id bigint generated always as identity primary key,
  merchant_id bigint,              -- 暂不加 FK
  display_name text not null,
  category text,
  unit text,
  created_at timestamptz default now()
);

-- Create receipts table

create table receipts (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id),

  merchant_id bigint,
  merchant_name_raw text,

  purchase_time timestamptz,
  currency_code text default 'USD',
  subtotal numeric(12, 2),
  tax numeric(12, 2),
  total numeric(12, 2),

  item_count int,
  payment_method text,

  status text default 'pending',

  image_url text,
  ocr_raw_json jsonb,

  created_at timestamptz default now()
);

create index receipts_user_id_idx on receipts(user_id);

-- Create receipt_items table(no FK to mapped_product_id)

create table receipt_items (
  id bigint generated always as identity primary key,
  receipt_id bigint not null references receipts(id) on delete cascade,

  line_index int not null,
  raw_text text not null,
  normalized_text text,

  quantity numeric(12, 3),
  unit_price numeric(12, 2),
  line_total numeric(12, 2),

  is_taxable boolean,
  mapped_product_id bigint,           -- 暂不加 FK
  confidence numeric,

  status text default 'unresolved',

  created_at timestamptz default now()
);

create index receipt_items_receipt_id_idx on receipt_items(receipt_id);

-- Create item_mappings table(no FK to merchant_id or product_id)

create table item_mappings (
  id bigint generated always as identity primary key,
  merchant_id bigint,
  normalized_text text not null,
  product_id bigint,
  confidence numeric default 1.0,
  source text default 'system',
  created_at timestamptz default now()
);

create index item_mappings_lookup_idx
  on item_mappings (merchant_id, normalized_text);

-- Create pending_items

create table pending_items (
  id bigint generated always as identity primary key,
  receipt_item_id bigint not null references receipt_items(id) on delete cascade,
  user_id uuid not null references auth.users(id),

  suggested_product_name text,
  suggested_category text,
  suggested_line_total numeric(12, 2),

  reason text,
  resolved boolean default false,
  resolved_at timestamptz,

  created_at timestamptz default now()
);

create index pending_items_user_idx on pending_items(user_id);

-- Create low_confidence_learning table

create table low_confidence_learning (
  id bigint generated always as identity primary key,
  merchant_id bigint,
  normalized_text text not null,
  user_product_name text not null,
  user_category text,
  occurrences int default 1,
  last_seen_at timestamptz default now()
);

create index low_conf_learning_key_idx
  on low_confidence_learning (merchant_id, normalized_text, user_product_name);

-- Add foreign keys

alter table products
  add constraint products_merchant_fk
  foreign key (merchant_id) references merchants(id);

alter table receipts
  add constraint receipts_merchant_fk
  foreign key (merchant_id) references merchants(id);

alter table receipt_items
  add constraint receipt_items_product_fk
  foreign key (mapped_product_id) references products(id);

alter table item_mappings
  add constraint item_mappings_merchant_fk
  foreign key (merchant_id) references merchants(id);

alter table item_mappings
  add constraint item_mappings_product_fk
  foreign key (product_id) references products(id);

alter table low_confidence_learning
  add constraint low_conf_learning_merchant_fk
  foreign key (merchant_id) references merchants(id);

