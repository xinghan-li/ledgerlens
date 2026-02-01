-- ============================================
-- 001_schema_v2.sql
-- 全新设计的数据库架构
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
-- ============================================
create table store_locations (
  id uuid primary key default gen_random_uuid(),
  chain_id uuid not null references store_chains(id) on delete cascade,
  name text not null,  -- e.g., "Costco Lynnwood"
  address_line1 text,
  address_line2 text,
  city text,
  state text,
  zip_code text,
  country_code text,  -- 'US', 'CA'
  latitude numeric(10, 8),
  longitude numeric(11, 8),
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index store_locations_chain_id_idx on store_locations(chain_id);
create index store_locations_city_state_idx on store_locations(city, state);
create index store_locations_country_idx on store_locations(country_code);
create index store_locations_name_idx on store_locations(name);

comment on table store_locations is 'Specific store locations (e.g., Costco Lynnwood)';
comment on column store_locations.name is 'Location-specific name for matching';

-- ============================================
-- 3. STORE_CHAIN_PROMPTS 表 (已废弃，使用 tag-based RAG 系统)
-- ============================================
-- NOTE: store_chain_prompts 表已被 tag-based RAG 系统替代
-- 新的系统使用 prompt_tags, prompt_snippets, tag_matching_rules 表
-- 参见 009_tag_based_rag_system.sql

-- ============================================
-- 4. USERS 表（扩展auth.users）
-- ============================================
create table users (
  id uuid primary key references auth.users(id) on delete cascade,
  user_name text,
  email text unique,
  user_class text default 'free',  -- super_admin, admin, premium, free
  status text default 'active',  -- active, suspended, deleted
  stripe_customer_id text,
  subscription_status text,  -- active, canceled, past_due
  subscription_tier text,  -- free, premium, enterprise
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  
  check (user_class in ('super_admin', 'admin', 'premium', 'free')),
  check (status in ('active', 'suspended', 'deleted'))
);

create index users_email_idx on users(email);
create index users_status_idx on users(status);

comment on table users is 'User profile extension (extends Supabase auth.users)';

-- ============================================
-- 5. RECEIPTS 表（主表）
-- ============================================
create table receipts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  uploaded_at timestamptz default now(),
  current_status text default 'pending',  -- success, failed, needs_review
  current_stage text default 'ocr',  -- ocr, llm_primary, llm_fallback, manual
  raw_file_url text,  -- 原始文件URL（如果存储在云存储中）
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  
  check (current_stage in ('ocr', 'llm_primary', 'llm_fallback', 'manual')),
  check (current_status in ('success', 'failed', 'needs_review'))
);

create index receipts_user_id_idx on receipts(user_id);
create index receipts_status_idx on receipts(current_status);
create index receipts_stage_idx on receipts(current_stage);
create index receipts_created_at_idx on receipts(created_at);

comment on table receipts is 'Receipt upload records - tracks current status and stage';
comment on column receipts.current_stage is 'Current processing stage: ocr, llm_primary, llm_fallback, manual';
comment on column receipts.current_status is 'Current processing status: success, failed, needs_review';

-- ============================================
-- 6. RECEIPT_PROCESSING_RUNS 表（处理历史）
-- ============================================
create table receipt_processing_runs (
  id uuid primary key default gen_random_uuid(),
  receipt_id uuid not null references receipts(id) on delete cascade,
  stage text not null,  -- ocr | llm | manual
  model_provider text,  -- tesseract, google_documentai, aws_textract, gemini, openai, etc.
  model_name text,  -- e.g., "gpt-4o-mini", "gemini-1.5-flash"
  model_version text,  -- e.g., "2024-01-01"
  input_payload jsonb,  -- 输入数据（OCR结果、原始文本等）
  output_payload jsonb,  -- 输出数据（结构化JSON、OCR结果等）
  output_schema_version text,  -- 输出schema版本
  status text not null,  -- pass | fail
  error_message text,  -- 如果失败，错误信息
  created_at timestamptz default now(),
  
  check (stage in ('ocr', 'llm', 'manual')),
  check (status in ('pass', 'fail'))
);

create index receipt_processing_runs_receipt_id_idx on receipt_processing_runs(receipt_id);
create index receipt_processing_runs_stage_idx on receipt_processing_runs(stage);
create index receipt_processing_runs_provider_idx on receipt_processing_runs(model_provider);
create index receipt_processing_runs_status_idx on receipt_processing_runs(status);
create index receipt_processing_runs_created_at_idx on receipt_processing_runs(created_at);

comment on table receipt_processing_runs is 'Individual processing runs for each receipt - tracks all OCR/LLM/manual processing attempts';
comment on column receipt_processing_runs.input_payload is 'Input data (OCR result, raw text, etc.)';
comment on column receipt_processing_runs.output_payload is 'Output data (structured JSON, OCR result, etc.)';

-- ============================================
-- 7. API_CALLS 统计表
-- ============================================
create table api_calls (
  id uuid primary key default gen_random_uuid(),
  call_type text not null,  -- 'ocr' | 'llm'
  provider text not null,  -- google_documentai, aws_textract, gemini, openai
  receipt_id uuid references receipts(id),
  duration_ms int,  -- 耗时（毫秒）
  status text not null,  -- success, failed
  error_code text,  -- 如果失败
  error_message text,
  request_metadata jsonb,  -- 请求元数据
  response_metadata jsonb,  -- 响应元数据
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
-- 8. STORE_CANDIDATES 表
-- ============================================
create table store_candidates (
  id uuid primary key default gen_random_uuid(),
  raw_name text not null,
  normalized_name text not null,
  source text not null,  -- ocr | llm | user
  receipt_id uuid references receipts(id),
  suggested_chain_id uuid references store_chains(id),
  suggested_location_id uuid references store_locations(id),
  confidence_score numeric(3, 2),  -- 0.00 - 1.00
  status text default 'pending',  -- pending | approved | rejected
  rejection_reason text,
  metadata jsonb,  -- 额外信息（先不用填，未来扩展用）
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

-- store_chain_prompts trigger removed (table deprecated)

create trigger users_updated_at 
  before update on users
  for each row execute function update_updated_at();

create trigger receipts_updated_at 
  before update on receipts
  for each row execute function update_updated_at();
  
-- Note: receipt_processing_runs does not have updated_at (immutable history)
