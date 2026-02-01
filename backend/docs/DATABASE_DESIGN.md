# 数据库设计说明

## 1. `receipts` 和 `receipt_processing_runs` 两个表的设计原因

### `receipts` 表（主表）
**作用：** 代表一张小票的**整体状态**，是一个**业务实体**。

**字段说明：**
- `id`: 小票的唯一标识
- `user_id`: 属于哪个用户
- `uploaded_at`: 上传时间
- `current_status`: **当前最终状态**（`success`, `failed`, `needs_review`）
- `current_stage`: **当前处理阶段**（`ocr`, `llm_primary`, `llm_fallback`, `manual`）
- `raw_file_url`: 原始文件路径
- `file_hash`: 文件哈希（用于去重）

**特点：**
- 每个小票只有**一条记录**
- 存储的是**当前状态**，不是历史
- 用于快速查询：哪些小票需要人工审核？哪些小票处理成功了？
- 类似于"订单表"，只关心订单的最终状态

### `receipt_processing_runs` 表（历史表）
**作用：** 记录**每次处理尝试**的详细信息，是一个**技术审计表**。

**字段说明：**
- `id`: 处理记录的唯一标识
- `receipt_id`: 关联到哪张小票（外键）
- `stage`: 处理阶段（`ocr`, `llm`, `manual`）
- `model_provider`: 使用的服务商（`google_documentai`, `aws_textract`, `gemini`, `openai`）
- `model_name`: 使用的模型名称（`gpt-4o-mini`, `gemini-1.5-flash`）
- `input_payload`: 输入数据（JSONB，包含 OCR 结果、原始文本等）
- `output_payload`: 输出数据（JSONB，包含结构化 JSON、OCR 结果等）
- `status`: 本次处理是否成功（`pass`, `fail`）
- `error_message`: 如果失败，错误信息

**特点：**
- 每个小票可能有**多条记录**（一次 OCR + 多次 LLM 尝试）
- 存储的是**完整历史**，包括所有尝试
- 用于调试：为什么这个 LLM 调用失败了？Gemini 和 GPT 的结果有什么不同？
- 类似于"订单日志表"，记录订单的每一步操作

### 为什么需要拆成两个表？

#### 1. **职责分离**
- `receipts`: 业务视角 - "这张小票现在是什么状态？"
- `receipt_processing_runs`: 技术视角 - "我们尝试了哪些方法？每一步发生了什么？"

#### 2. **性能优化**
- 查询"所有需要审核的小票"：只需要扫描 `receipts` 表（小表）
- 不需要 JOIN `receipt_processing_runs`（可能很大的表）

#### 3. **数据量差异**
- `receipts`: 每个小票 1 条记录
- `receipt_processing_runs`: 每个小票可能有 3-5 条记录（Google OCR + Gemini LLM + AWS OCR + GPT LLM + 可能的 retry）

#### 4. **查询场景不同**
- **业务查询**（用 `receipts`）：
  - "显示用户的所有小票"
  - "找出所有需要人工审核的小票"
  - "统计今天的成功处理数量"
  
- **技术查询**（用 `receipt_processing_runs`）：
  - "为什么这张小票失败了？查看所有处理记录"
  - "Gemini 和 GPT 的结果对比"
  - "统计每个模型的成功率"

#### 5. **数据完整性**
- 即使 `receipt_processing_runs` 被删除（比如清理旧数据），`receipts` 表仍然保留小票的基本信息
- 可以设置 `ON DELETE CASCADE`，删除小票时自动删除所有处理记录

### 类比理解
- `receipts` = **订单表**：只关心订单的最终状态（已支付、已发货、已取消）
- `receipt_processing_runs` = **订单日志表**：记录每一步操作（创建订单 → 支付 → 发货 → 签收）

## 2. `current_stage` 是否需要更细分？

### 当前设计
```sql
current_stage: 'ocr', 'llm_primary', 'llm_fallback', 'manual'
```

### 问题分析

#### 当前细分度不足的场景：

1. **OCR 阶段细分**
   - `ocr_google` - Google Document AI OCR
   - `ocr_aws` - AWS Textract OCR（fallback）
   - `ocr_failed` - OCR 失败

2. **LLM Primary 阶段细分**
   - `llm_primary_pending` - 等待 LLM 处理
   - `llm_primary_processing` - LLM 处理中
   - `llm_primary_gemini` - 使用 Gemini 处理
   - `llm_primary_openai` - 使用 OpenAI 处理（因为 Gemini 不可用）
   - `llm_primary_sum_check` - LLM 处理完成，正在做 sum check
   - `llm_primary_failed` - Primary LLM 处理失败

3. **LLM Fallback 阶段细分**
   - `llm_fallback_ocr_aws` - 正在用 AWS OCR 做 backup
   - `llm_fallback_processing` - 正在用 GPT 做 backup LLM 处理
   - `llm_fallback_sum_check` - Backup LLM 处理完成，正在做 sum check
   - `llm_fallback_failed` - Backup LLM 也失败了

4. **Manual 阶段细分**
   - `manual_pending` - 等待人工审核
   - `manual_reviewing` - 正在审核中
   - `manual_approved` - 已审核通过
   - `manual_rejected` - 已审核拒绝

### 建议的改进方案

#### 方案 1：保持简单，只增加关键细分（推荐）
```sql
current_stage: 
  'ocr_google',           -- Google OCR 处理中
  'ocr_aws',              -- AWS OCR 处理中（fallback）
  'llm_primary',          -- Primary LLM 处理中
  'llm_fallback_ocr',     -- Backup: AWS OCR 处理中
  'llm_fallback_llm',    -- Backup: GPT LLM 处理中
  'llm_fallback_sum',    -- Backup: Sum check 中
  'manual_pending',       -- 等待人工审核
  'manual_reviewing',     -- 正在审核中
  'success',              -- 处理成功
  'failed'                -- 处理失败
```

**优点：**
- 足够细分，可以定位到具体阶段
- 不会太复杂，易于维护
- 可以快速定位问题（比如卡在 `llm_fallback_ocr` 说明 AWS OCR 很慢）

#### 方案 2：使用状态机（更复杂但更强大）
```sql
current_stage: 
  'uploaded',             -- 已上传
  'ocr_google_started',   -- Google OCR 开始
  'ocr_google_completed', -- Google OCR 完成
  'ocr_aws_started',      -- AWS OCR 开始（fallback）
  'ocr_aws_completed',    -- AWS OCR 完成
  'llm_primary_started',  -- Primary LLM 开始
  'llm_primary_completed',-- Primary LLM 完成
  'sum_check_started',    -- Sum check 开始
  'sum_check_passed',     -- Sum check 通过
  'sum_check_failed',     -- Sum check 失败
  'llm_fallback_started', -- Backup LLM 开始
  'llm_fallback_completed',-- Backup LLM 完成
  'manual_review',        -- 人工审核
  'success',             -- 最终成功
  'failed'                -- 最终失败
```

**优点：**
- 非常详细，可以追踪每一步
- 可以统计每个阶段的耗时

**缺点：**
- 状态太多，维护复杂
- 查询时需要理解状态机流程

#### 方案 3：保持当前设计，但增加 `processing_details` JSONB 字段（推荐）
```sql
-- receipts 表增加字段
processing_details jsonb,  -- 存储详细的处理信息

-- 示例数据：
{
  "current_stage_detail": "llm_fallback_ocr",
  "ocr_provider": "aws_textract",
  "llm_provider": "openai",
  "sum_check_status": "failed",
  "retry_count": 1,
  "last_error": "Sum check failed: difference 2.79"
}
```

**优点：**
- 保持 `current_stage` 简单（4 个值）
- 详细信息存储在 JSONB 中，灵活且可扩展
- 不需要频繁修改数据库 schema

### 我的建议

**推荐方案 1 + 方案 3 的组合：**

1. **扩展 `current_stage` 到方案 1 的细分度**（10 个左右的值）
   - 足够定位问题
   - 不会太复杂

2. **增加 `processing_details` JSONB 字段**
   - 存储更详细的信息（retry count, error details, provider info）
   - 用于高级查询和调试

3. **在 `receipt_processing_runs` 中已经有完整历史**
   - 如果需要查看完整流程，查询 `receipt_processing_runs` 表
   - `receipts.current_stage` 只用于快速状态查询

### 实施建议

1. **先实施方案 1**（扩展 `current_stage`）
   - 创建 migration SQL
   - 更新所有 `update_receipt_status` 调用
   - 测试各个阶段的更新

2. **如果需要，再增加 `processing_details`**
   - 作为补充信息，不影响现有逻辑
