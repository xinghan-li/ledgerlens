# 数据库迁移注意事项

## 已完成的更新

1. ✅ 创建了新的数据库架构 `001_schema_v2.sql`
2. ✅ 删除了旧的 `001_schema_v0.sql` 和 `008_verify_merchant_data.sql`
3. ✅ 更新了 `supabase_client.py` - 添加了 `get_or_create_store_chain` 函数
4. ✅ 更新了 `address_matcher.py` - 改为查询 `store_locations` 表
5. ✅ 更新了 `prompt_manager.py` - 改为查询 `store_chain_prompts` 表
6. ✅ 更新了 `extraction_rule_manager.py` - 改为从 `store_chain_prompts` 获取规则
7. ✅ 更新了 `statistics_manager.py` - 添加了 `record_api_call` 函数

## 需要确认的问题

### 1. `get_or_create_store_chain` 返回值
**问题**: 函数应该返回什么？
- 选项A: 只返回 `chain_id` (UUID)
- 选项B: 如果匹配到location，返回 `location_id`，否则返回 `chain_id`
- 选项C: 返回一个字典包含 `chain_id` 和 `location_id`

**当前实现**: 返回 `chain_id` (UUID string)

**建议**: 如果只需要chain信息，返回chain_id；如果需要location信息，需要另一个函数 `get_or_create_store_location`

---

### 2. `save_receipt_ocr` 和 `save_parsed_receipt` 函数
**问题**: 新schema中receipts表结构已改变，需要确认：
- `ocr_result` 应该存储完整的OCR JSON（包含entities, line_items等）还是只有text？
- 是否需要设置 `processing_stage` 为 'ocr'？
- `save_parsed_receipt` 中的receipt_items是否还需要单独的表？还是都存在 `structured_data` jsonb里？

**当前实现**: 
- `save_receipt_ocr`: 存储 `{"text": text}` 到 `ocr_result` jsonb
- `save_parsed_receipt`: 需要更新以匹配新schema

---

### 3. `get_merchant_prompt` 查询逻辑
**问题**: 查询优先级和参数含义
- `merchant_id` 参数应该是 `chain_id` 还是 `location_id`？
- 查询优先级：location_id + country_code > location_id > chain_id + country_code > chain_id > default
- 如何获取 `location_id` 和 `country_code`？需要从receipt的structured_data中提取吗？

**当前实现**: 
- `merchant_id` 作为 `chain_id` 使用
- 支持 `location_id` 和 `country_code` 参数（但调用方还没有传递）

---

### 4. `update_statistics` vs `record_api_call`
**问题**: 统计方式改变
- 旧的 `update_statistics` 是聚合统计（每天一条记录）
- 新的 `api_calls` 表是每次调用一条记录
- 是否还需要 `update_statistics` 函数？还是完全用 `record_api_call` 替代？

**当前实现**: 
- 添加了 `record_api_call` 函数
- `update_statistics` 标记为deprecated，但保留用于向后兼容

---

### 5. Receipts表 - receipt_items
**问题**: 新schema中没有receipt_items表了
- Items应该存在 `structured_data` jsonb里吗？
- 还是需要保留receipt_items表用于查询和分析？

**建议**: 如果不需要单独查询items，可以存在jsonb里；如果需要，建议保留receipt_items表

---

### 6. 所有调用 `get_or_create_merchant` 的地方
**需要更新的文件**:
- `backend/app/services/llm/receipt_llm_processor.py` (第91行)
- `backend/app/main.py` (第167行)
- `backend/app/core/receipt_parser.py` (多处，但这是旧代码，可能已废弃)

**当前状态**: 已添加向后兼容的 `get_or_create_merchant` 函数，但建议逐步迁移到 `get_or_create_store_chain`

---

### 7. `get_merchant_prompt` 调用
**需要更新的地方**:
- `backend/app/services/llm/receipt_llm_processor.py` (第96行)
- 需要传递 `location_id` 和 `country_code` 参数

**问题**: 如何获取这些参数？
- 从LLM结果中提取？
- 从address_matcher的结果中获取？

---

### 8. `update_statistics` 调用
**需要更新的地方**:
- `backend/app/core/workflow_processor.py` (多处)
- 需要改为调用 `record_api_call`，但需要 `receipt_id` 和 `duration_ms` 参数

**问题**: 
- 如何获取 `duration_ms`？需要从timeline中计算吗？
- `receipt_id` 在workflow中是否可用？

---

### 9. address_matcher 的查询
**问题**: Supabase的join查询语法
- `store_locations.select("*, store_chains(*)")` 是否正确？
- 还是需要分别查询然后合并？

**当前实现**: 已改为分别查询store_locations和store_chains，然后合并数据

---

### 10. 数据库迁移脚本
**需要**: 创建数据迁移脚本
- 从旧的merchants表迁移到store_chains和store_locations
- 从旧的merchant_locations表迁移数据
- 更新所有外键引用

---

## 已完成的迁移

### Migration 008: Update current_stage
**文件**: `008_update_current_stage.sql`

**目的**: 更新 `receipts.current_stage` 列，支持更细粒度的状态值用于调试

**变更**:
- 旧值: `'ocr'`, `'llm_primary'`, `'llm_fallback'`, `'manual'`
- 新值: `'ocr_google'`, `'ocr_aws'`, `'llm_primary'`, `'llm_fallback'`, `'sum_check_failed'`, `'manual_review'`, `'success'`, `'failed'`

**映射规则**:
- `'manual'` → `'manual_review'`
- `'ocr'` → `'ocr_google'`
- `'pending'` → `'ocr_google'`
- NULL → `'ocr_google'`
- 根据 `current_status` 智能映射剩余值

**特性**:
- 使用事务确保原子性
- 先删除约束，再更新数据，最后添加新约束
- 包含验证步骤确保迁移成功
- 幂等性：可以安全地多次运行
