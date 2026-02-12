# Categorization 架构设计

## 🎯 核心理念

**分离关注点：OCR/LLM 专注解析，Categorization 专注标准化**

---

## 📊 完整数据流

### 阶段 1: OCR + LLM Workflow（不变）

```
小票图片
  ↓
OCR (Google Document AI)
  ↓
清洗 (data cleaning)
  ↓
LLM (Gemini/GPT-4o-mini)
  ↓
Sum Check (验证总额)
  ↓
✅ Pass → 保存到 receipt_processing_runs.output_payload
  ↓
更新 receipts.current_status = 'success'
```

**重要：** 只有通过 sum check 的小票才会被标记为 `success`

---

### 阶段 2: Categorization（独立API）

```
调用: POST /api/receipt/categorize/{receipt_id}
  ↓
前置检查：
  1. Receipt.current_status == 'success' ✅
  2. 有成功的 LLM processing run ✅
  3. output_payload 有效 ✅
  ↓
读取 output_payload:
  {
    "receipt": {...},  ← 小票摘要信息
    "items": [...]     ← 商品列表
  }
  ↓
标准化处理：
  ├─ 商品名标准化 ("DOLE BANANA" → "banana")
  ├─ 品牌匹配 (→ brands 表)
  ├─ 分类匹配 (→ categories 表)
  └─ 商品目录更新 (→ products 表)
  ↓
保存结果：
  ├─ receipt_summaries (商店、日期、总额)
  └─ receipt_items (商品、价格、分类)
```

---

## 🔑 关键设计决策

### 1. **为什么不在 Workflow 中自动保存？**

**原因：**
- ❌ Sum check 通过 ≠ 数据保存成功
- ❌ 无法重试（数据库错误会导致数据丢失）
- ❌ 无法改进算法（已经保存的数据无法重新标准化）

**解决方案：**
- ✅ Categorization 是独立事务
- ✅ 可以重试（`force=true`）
- ✅ 可以改进算法后重新运行

---

### 2. **为什么要求 Sum Check 通过？**

**原因：**
```
用户关心的问题：
"我在 Grocery 花了多少钱？"

如果小票数据有误（sum check 失败）：
  → 总额不对
  → 商品价格可能错误
  → 用户看到的数据不可信
```

**因此：**
- ❌ 失败的小票不应该进入 categorization
- ✅ 只有验证通过的小票才能成为"账本"
- ✅ 保证数据质量 > 数据数量

---

## 📡 API 使用指南

### 1. 检查小票是否可以 Categorize

```bash
GET /api/receipt/categorize/check/{receipt_id}
Authorization: Bearer <token>

# 返回
{
  "receipt_id": "uuid",
  "can_categorize": true,
  "reason": "OK"
}
```

**可能的原因：**
- ❌ `"Receipt not found"`
- ❌ `"Receipt status is 'failed', must be 'success'"`
- ❌ `"No successful LLM processing run found"`
- ❌ `"output_payload missing 'receipt' or 'items' fields"`
- ✅ `"OK"`

---

### 2. Categorize 单张小票

```bash
POST /api/receipt/categorize/{receipt_id}?force=false
Authorization: Bearer <token>

# 返回
{
  "success": true,
  "receipt_id": "uuid",
  "summary_id": "uuid",
  "items_count": 8,
  "message": "Categorization completed successfully"
}
```

**参数：**
- `force=false` (默认): 如果已经 categorize 过，跳过
- `force=true`: 重新 categorize，覆盖旧数据

**使用场景：**
- 用户上传新小票 → 自动调用 categorize
- 改进了标准化算法 → 重新 categorize (`force=true`)
- 数据库出错 → 重试

---

### 3. 批量 Categorize

```bash
POST /api/receipt/categorize-batch
Authorization: Bearer <token>
Content-Type: application/json

{
  "receipt_ids": ["uuid1", "uuid2", "uuid3"],
  "force": false
}

# 返回
{
  "total": 3,
  "success": 2,
  "failed": 1,
  "results": [
    {
      "success": true,
      "receipt_id": "uuid1",
      "summary_id": "...",
      "items_count": 5
    },
    {
      "success": true,
      "receipt_id": "uuid2",
      "summary_id": "...",
      "items_count": 8
    },
    {
      "success": false,
      "receipt_id": "uuid3",
      "message": "Receipt status is 'failed', must be 'success'"
    }
  ]
}
```

**使用场景：**
- Backfill 旧数据
- 批量重新标准化

---

## 🔄 典型工作流

### 场景 1: 用户上传新小票

```javascript
// Frontend
1. POST /api/receipt/workflow (上传图片)
   ↓
   等待处理...
   ↓
2. 轮询或 webhook 获取状态
   if (receipt.current_status === 'success') {
     ↓
3. POST /api/receipt/categorize/{receipt_id}
     ↓
4. GET /api/dashboard/spending-by-category
     (展示给用户)
   }
```

---

### 场景 2: Backfill 旧数据

```python
# Backend script
import requests

# 1. 获取所有 success 的小票
receipts = supabase.table("receipts")\
    .select("id")\
    .eq("current_status", "success")\
    .execute()

# 2. 批量 categorize
for batch in chunks(receipts, 10):
    requests.post("/api/receipt/categorize-batch", json={
        "receipt_ids": [r['id'] for r in batch],
        "force": False  # 跳过已经 categorize 过的
    })
```

---

### 场景 3: 改进算法后重新标准化

```python
# 改进了 product normalization 算法

# 重新 categorize 所有小票
receipts = get_all_categorized_receipts()

for receipt_id in receipts:
    requests.post(f"/api/receipt/categorize/{receipt_id}", 
                  params={"force": True})
```

---

## 📊 数据库状态追踪

### 方案 1: 用 receipt_items 的存在判断

```sql
-- 已经 categorize 过的小票
SELECT r.id, r.current_status
FROM receipts r
WHERE r.current_status = 'success'
  AND EXISTS (
    SELECT 1 FROM receipt_items ri 
    WHERE ri.receipt_id = r.id
  );
```

### 方案 2: 添加 categorization_status 字段（可选）

```sql
ALTER TABLE receipts 
ADD COLUMN categorization_status TEXT DEFAULT 'pending';

-- 'pending', 'completed', 'failed'
```

---

## 🎯 下一步开发

### Phase 1: ✅ 完成
- Categorization API 实现
- Sum check 验证
- 基础数据保存

### Phase 2: Product Normalization（推荐）
```python
# 新文件：backend/app/services/standardization/
├── product_normalizer.py  # "DOLE BANANA" → "banana"
├── brand_matcher.py       # 匹配 brands 表
├── category_matcher.py    # 匹配 categories 表
└── product_catalog.py     # 管理 products 表
```

**目标：**
- 商品名标准化
- Brand 匹配/创建
- Category 匹配
- Product catalog 管理

### Phase 3: Dashboard API
```python
GET /api/dashboard/spending-by-category
GET /api/dashboard/receipts
GET /api/dashboard/receipts/{receipt_id}
```

---

## 🔍 调试和监控

### 查看 Categorization 覆盖率

```sql
-- 总小票数
SELECT COUNT(*) FROM receipts WHERE current_status = 'success';

-- 已 categorize 的
SELECT COUNT(DISTINCT receipt_id) FROM receipt_summaries;

-- 覆盖率
SELECT 
  (SELECT COUNT(DISTINCT receipt_id) FROM receipt_summaries)::FLOAT /
  (SELECT COUNT(*) FROM receipts WHERE current_status = 'success')::FLOAT * 100
  AS coverage_percent;
```

### 查找需要 Categorize 的小票

```sql
SELECT r.id, r.uploaded_at
FROM receipts r
WHERE r.current_status = 'success'
  AND NOT EXISTS (
    SELECT 1 FROM receipt_summaries rs 
    WHERE rs.receipt_id = r.id
  )
ORDER BY r.uploaded_at DESC;
```

---

## ⚠️ 注意事项

1. **只 Categorize 成功的小票**
   - 前提：`receipts.current_status = 'success'`
   - 保证数据质量

2. **Categorization 可以重试**
   - 使用 `force=true` 参数
   - 旧数据会被删除并重新创建

3. **原始数据不变**
   - `receipt_processing_runs.output_payload` 永远保留
   - Categorization 只是从 payload 派生数据

4. **错误处理**
   - Categorization 失败不影响 OCR/LLM workflow
   - 可以单独重试失败的小票

---

## 📚 相关文件

```
backend/
├── app/
│   ├── services/
│   │   ├── categorization/
│   │   │   ├── __init__.py
│   │   │   └── receipt_categorizer.py  ← 核心逻辑
│   │   └── database/
│   │       └── supabase_client.py      ← save_receipt_summary/items
│   ├── main.py                         ← API endpoints
│   └── core/
│       └── workflow_processor.py       ← OCR/LLM (不含 categorization)
├── test_categorization_api.py          ← 测试脚本
└── docs/architecture/
    └── CATEGORIZATION.md               ← 本文档
```

---

## 🎉 总结

**核心优势：**
1. ✅ **解耦**：OCR/LLM 专注解析，Categorization 专注标准化
2. ✅ **可靠**：只处理验证通过的数据
3. ✅ **灵活**：可以重试、重新标准化、改进算法
4. ✅ **可追溯**：保留原始数据 + 标准化结果

**与旧方案对比：**
| 特性 | 自动保存（旧） | 独立API（新） |
|------|----------------|---------------|
| 解耦程度 | ❌ 混在 workflow | ✅ 完全独立 |
| 可重试 | ❌ 不可重试 | ✅ 可以重试 |
| 可改进 | ❌ 无法重新运行 | ✅ 可以重新标准化 |
| 错误处理 | ❌ 错误被吞掉 | ✅ 独立事务 |
| 状态追踪 | ❌ 不清晰 | ✅ 清晰可查询 |

---

🚀 **架构重构完成！现在可以开始实现 Product Normalization 或 Dashboard API。**
