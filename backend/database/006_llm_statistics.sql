-- LLM Statistics Table: 记录每天 LLM 调用的统计信息

create table if not exists llm_statistics (
  id bigint generated always as identity primary key,
  date date not null unique,  -- 日期（UTC）
  
  -- Gemini 统计
  gemini_total_calls int default 0,
  gemini_sum_check_passed int default 0,
  gemini_accuracy numeric(5, 4),  -- 正确率（0.0000 - 1.0000）
  
  -- GPT-4o-mini 统计
  gpt_total_calls int default 0,
  gpt_sum_check_passed int default 0,
  gpt_accuracy numeric(5, 4),  -- 正确率（0.0000 - 1.0000）
  
  -- 错误统计
  error_count int default 0,
  manual_review_count int default 0,
  
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- 创建索引
create index llm_statistics_date_idx on llm_statistics(date);

-- 自动更新 updated_at
create or replace function update_llm_statistics_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger llm_statistics_updated_at
  before update on llm_statistics
  for each row
  execute function update_llm_statistics_updated_at();
