-- ============================================
-- 001_schema_v2.sql
-- 全新设计的数据库架构
--
-- 已合并以下迁移（新库直接建到最终形态，无需再单独运行）：
--   003_add_file_hash.sql                              → receipt_status.file_hash
--   006_add_validation_status.sql                      → receipt_processing_runs.validation_status
--   007_add_chain_name_to_store_locations.sql          → store_locations.chain_name + trigger
--   032_store_locations_and_candidates_phone.sql       → store_locations.phone / store_candidates.phone
--   040_receipt_processing_runs_stage_rule_based_cleaning.sql → stage check 最终值
--   048_receipt_status_pipeline_version.sql            → receipt_status.pipeline_version
--   049_receipt_processing_runs_stage_vision.sql       → stage check 最终值
--   050_receipt_status_stage_vision.sql                → current_stage check 最终值
--   045_receipt_workflow_steps.sql (部分)              → current_stage check 最终值
--
-- 注：004_update_user_class.sql 在此文件中已是最终约束值，无需合并。
-- ============================================

-- ============================================
-- 1. STORE_CHAINS 表
-- ============================================
create table store_chains (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  normalized_name text not null,
  aliases text[] default '{}',
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create unique index store_chains_normalized_name_idx on store_chains(normalized_name);
create index store_chains_aliases_idx on store_chains using gin(aliases);
create index store_chains_active_idx on store_chains(is_active) where is_active = true;

comment on table store_chains is 'Store chains (e.g., Costco, T&T Supermarket)';
comment on column store_chains.name is 'Display name of the chain';
comment on column store_chains.normalized_name is 'Normalized name for fuzzy matching (lowercase)';
comment on column store_chains.aliases is 'Array of alternative names for matching';

-- ============================================
-- 2. STORE_LOCATIONS 表
-- 含 chain_name（来自 007）、phone（来自 032）
-- ============================================
create table store_locations (
  id uuid primary key default gen_random_uuid(),
  chain_id uuid not null references store_chains(id) on delete cascade,
  name text not null,
  address_line1 text,
  address_line2 text,
  city text,
  state text,
  zip_code text,
  country_code text,
  latitude numeric(10, 8),
  longitude numeric(11, 8),
  chain_name text,
  phone text,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index store_locations_chain_id_idx on store_locations(chain_id);
create index store_locations_city_state_idx on store_locations(city, state);
create index store_locations_country_idx on store_locations(country_code);
create index store_locations_name_idx on store_locations(name);
create index store_locations_chain_name_idx on store_locations(chain_name);

comment on table store_locations is 'Specific store locations (e.g., Costco Lynnwood)';
comment on column store_locations.chain_name is 'Human-readable chain name; auto-synced from store_chains.name via trigger.';
comment on column store_locations.phone is 'Store phone in canonical form xxx-xxx-xxxx. Use when building information.other_info.merchant_phone.';

-- ============================================
-- 3. USERS 表（扩展 auth.users）
-- ============================================
create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  user_name text,
  email text unique,
  user_class text default 'free',
  status text default 'active',
  stripe_customer_id text,
  subscription_status text,
  subscription_tier text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),

  check (user_class in ('super_admin', 'admin', 'premium', 'free')),
  check (status in ('active', 'suspended', 'deleted'))
);

create index users_email_idx on users(email);
create index users_status_idx on users(status);

comment on table users is 'User profile extension (extends Supabase auth.users). FK to auth.users will be dropped in 013 to support Firebase Auth.';

-- ============================================
-- 4. RECEIPT_STATUS 表（主表）
-- 含 file_hash（来自 003）、pipeline_version（来自 048）
-- current_stage 已包含 045/050 的所有值
-- ============================================
create table receipt_status (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  uploaded_at timestamptz default now(),
  current_status text default 'pending',
  current_stage text default 'ocr',
  pipeline_version text default 'legacy_a',
  raw_file_url text,
  file_hash text,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),

  check (current_stage in (
    'ocr', 'llm_primary', 'llm_fallback', 'manual',
    'rejected_not_receipt', 'pending_receipt_confirm',
    'vision_primary', 'vision_escalation', 'vision_store_specific'
  )),
  check (current_status in ('success', 'failed', 'needs_review', 'pending'))
);

create index receipt_status_user_id_idx on receipt_status(user_id);
create index receipt_status_status_idx on receipt_status(current_status);
create index receipt_status_stage_idx on receipt_status(current_stage);
create index receipt_status_created_at_idx on receipt_status(created_at);
create index receipt_status_file_hash_idx on receipt_status(file_hash);
create unique index receipt_status_user_file_hash_idx on receipt_status(user_id, file_hash) where file_hash is not null;

comment on table receipt_status is 'Receipt upload records - tracks current status and stage';
comment on column receipt_status.current_stage is 'Current processing stage: ocr, llm_primary, llm_fallback, manual, rejected_not_receipt, pending_receipt_confirm, vision_primary, vision_escalation, vision_store_specific';
comment on column receipt_status.pipeline_version is 'Pipeline used: legacy_a (OCR→LLM cascade) or vision_b (Vision-First)';
comment on column receipt_status.file_hash is 'SHA256 hash of the uploaded file for duplicate detection';

-- ============================================
-- 5. RECEIPT_PROCESSING_RUNS 表（处理历史）
-- 含 validation_status（来自 006）
-- stage 已包含 040/049 的所有值
-- ============================================
create table receipt_processing_runs (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null references receipt_status(id) on delete cascade,
  stage text not null,
  model_provider text,
  model_name text,
  model_version text,
  input_payload jsonb,
  output_payload jsonb,
  output_schema_version text,
  validation_status text,
  status text not null,
  error_message text,
  created_at timestamptz default now(),

  check (stage in (
    'ocr', 'llm', 'manual', 'rule_based_cleaning',
    'vision_primary', 'vision_escalation', 'shadow_legacy'
  )),
  check (status in ('pass', 'fail')),
  check (validation_status is null or validation_status in ('pass', 'needs_review', 'unknown'))
);

create index receipt_processing_runs_receipt_id_idx on receipt_processing_runs(receipt_id);
create index receipt_processing_runs_stage_idx on receipt_processing_runs(stage);
create index receipt_processing_runs_provider_idx on receipt_processing_runs(model_provider);
create index receipt_processing_runs_status_idx on receipt_processing_runs(status);
create index receipt_processing_runs_created_at_idx on receipt_processing_runs(created_at);
create index receipt_processing_runs_validation_status_idx
  on receipt_processing_runs(validation_status) where validation_status = 'needs_review';

comment on table receipt_processing_runs is 'Individual processing runs for each receipt';
comment on column receipt_processing_runs.stage is 'Processing stage: ocr, rule_based_cleaning, llm, manual, vision_primary, vision_escalation, shadow_legacy';
comment on column receipt_processing_runs.validation_status is 'From LLM output._metadata.validation_status: pass, needs_review, unknown. NULL for OCR stage.';

-- ============================================
-- 6. API_CALLS 统计表
-- ============================================
create table api_calls (
  id uuid primary key default gen_random_uuid(),
  call_type text not null,
  provider text not null,
  receipt_id uuid references receipt_status(id),
  duration_ms int,
  status text not null,
  error_code text,
  error_message text,
  request_metadata jsonb,
  response_metadata jsonb,
  created_at timestamptz default now(),

  check (call_type in ('ocr', 'llm')),
  check (status in ('success', 'failed'))
);

create index api_calls_type_provider_idx on api_calls(call_type, provider);
create index api_calls_receipt_id_idx on api_calls(receipt_id);
create index api_calls_status_idx on api_calls(status);
create index api_calls_created_at_idx on api_calls(created_at);

comment on table api_calls is 'Statistics for OCR and LLM API calls';

-- ============================================
-- 7. STORE_CANDIDATES 表
-- 含 phone（来自 032）
-- ============================================
create table store_candidates (
  id uuid primary key default gen_random_uuid(),
  raw_name text not null,
  normalized_name text not null,
  source text not null,
  receipt_id uuid references receipt_status(id),
  suggested_chain_id uuid references store_chains(id),
  suggested_location_id uuid references store_locations(id),
  confidence_score numeric(3, 2),
  status text default 'pending',
  rejection_reason text,
  phone text,
  metadata jsonb,
  created_at timestamptz default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references users(id),

  check (source in ('ocr', 'llm', 'user')),
  check (status in ('pending', 'approved', 'rejected'))
);

create index store_candidates_status_idx on store_candidates(status);
create index store_candidates_receipt_id_idx on store_candidates(receipt_id);
create index store_candidates_normalized_name_idx on store_candidates(normalized_name);
create index store_candidates_suggested_chain_idx on store_candidates(suggested_chain_id);

comment on table store_candidates is 'Store candidates waiting for approval before adding to store_chains';
comment on column store_candidates.phone is 'Proposed store phone xxx-xxx-xxxx. Filled when approving or from OCR.';

-- ============================================
-- Triggers for updated_at
-- ============================================
create or replace function update_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger store_chains_updated_at
  before update on store_chains
  for each row execute function update_updated_at();

create trigger store_locations_updated_at
  before update on store_locations
  for each row execute function update_updated_at();

create trigger users_updated_at
  before update on users
  for each row execute function update_updated_at();

create trigger receipt_status_updated_at
  before update on receipt_status
  for each row execute function update_updated_at();

-- ============================================
-- Trigger: 自动同步 store_locations.chain_name（来自 007）
-- ============================================
create or replace function update_store_location_chain_name()
returns trigger as $$
begin
  if new.chain_id is not null then
    select name into new.chain_name
    from store_chains
    where id = new.chain_id;
  else
    new.chain_name = null;
  end if;
  return new;
end;
$$ language plpgsql;

create trigger trigger_update_store_location_chain_name
  before insert or update of chain_id on store_locations
  for each row
  execute function update_store_location_chain_name();
