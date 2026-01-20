-- Create merchant_prompts table for RAG (Retrieval-Augmented Generation)
-- Stores merchant-specific prompts for LLM processing

create table if not exists merchant_prompts (
  id bigint generated always as identity primary key,
  merchant_id bigint references merchants(id) on delete cascade,
  merchant_name text,  -- denormalized for quick lookup
  
  -- Prompt configuration
  prompt_template text not null,  -- The prompt template with placeholders
  system_message text,  -- Optional system message
  model_name text,  -- OpenAI model to use (defaults to OPENAI_MODEL env var)
  temperature numeric(3, 2) default 0.0,  -- Temperature for generation
  
  -- Schema definition
  output_schema jsonb,  -- JSON schema for expected output
  
  -- Metadata
  version int default 1,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index merchant_prompts_merchant_id_idx on merchant_prompts(merchant_id);
create index merchant_prompts_merchant_name_idx on merchant_prompts(merchant_name);
create index merchant_prompts_active_idx on merchant_prompts(is_active) where is_active = true;

-- Partial unique index: ensure only one active prompt per merchant
create unique index merchant_prompts_merchant_unique_active 
  on merchant_prompts(merchant_id) 
  where is_active = true;

-- Function to update updated_at timestamp
create or replace function update_merchant_prompts_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger merchant_prompts_updated_at
  before update on merchant_prompts
  for each row
  execute function update_merchant_prompts_updated_at();
