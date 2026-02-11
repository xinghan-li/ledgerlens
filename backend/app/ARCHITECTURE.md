# LedgerLens Backend 架构说明

本文档描述 `app/` 目录下的代码组织结构与分类原则，便于扩展至 200–400 家门店时保持清晰可维护。

---

## 1. 架构分层概览

```
app/
├── core/                    # 应用级核心：工作流、批量处理
├── processors/              # 小票处理核心
│   ├── core/                # 通用数据结构与校验逻辑（与门店无关）
│   ├── validation/          # 通用 Pipeline 步骤 + 坐标流程
│   ├── stores/              # 按 layout 的 Store 专用 Processor
│   ├── merchants/           # LLM 后处理（已有）
│   ├── enrichment/          # 地址、支付类型等增强
│   └── text/                # 文本清洗
├── pipelines/               # 可配置的 LLM 后处理流水线
├── prompts/                 # 提示词、RAG
├── services/                # OCR、LLM、数据库、RAG
├── exporters/               # CSV 导出
└── config.py, models.py, main.py
```

---

## 2. 分类说明

### 2.1 `processors/core/` — 通用核心

与具体门店无关，所有小票流程共享：

| 文件 | 说明 |
|------|------|
| `structures.py` | 统一数据结构：TextBlock, PhysicalRow, ReceiptRegions, ExtractedItem, TotalsSequence, AmountUsageTracker 等 |
| `math_validator.py` | 数学校验：item 行级 qty×unit_price≈line_total；总体 items_sum≈subtotal、subtotal+fees+tax≈total |
| `sum_checker.py` | LLM 结果校验：sum(line_total)≈subtotal、subtotal+tax≈total；支持 package price 促销检测 |

### 2.2 `processors/validation/` — 通用 Pipeline 步骤

| 文件 | 分类 | 说明 |
|------|------|------|
| `pipeline.py` | 主入口 | 编排 Steps 0–7，triage 到 stores（Costco 等）或通用流程 |
| `item_extractor.py` | 通用 | 按金额列提取商品；商品名=金额左侧文本；支持多行、AmountUsageTracker |
| `row_reconstructor.py` | 通用 | 将 TextBlock 按 Y 聚合成 PhysicalRow |
| `column_detector.py` | 通用 | 检测主金额列 X |
| `region_splitter.py` | 通用 | 划分 header/items/totals/payment 四区；含 Costco 专用 markers |
| `totals_extractor.py` | 通用 | 找 SUBTOTAL/TOTAL，收集中间金额 |
| `tax_fee_classifier.py` | 通用 | 分类并提取 tax 与 fees |
| `skew_corrector.py` | 通用 | 倾斜校正 |
| `store_config_loader.py` | 配置 | 加载 store JSON、按 merchant 匹配 chain_id |
| `fuzzy_label_matcher.py` | 工具 | 标签模糊匹配 |
| `receipt_structures.py` | 兼容层 | Re-export 自 core.structures |
| `math_validator.py` | 兼容层 | Re-export 自 core.math_validator |
| `sum_checker.py` | 兼容层 | Re-export 自 core.sum_checker |

### 2.3 `processors/validation/` — 坐标流程（旧/并行）

基于坐标的校验流程，用于部分端点：

| 文件 | 说明 |
|------|------|
| `coordinate_extractor.py` | 从 Document AI 提取 text blocks 与 amount blocks |
| `coordinate_item_extractor.py` | 从坐标数据提取 items |
| `coordinate_sum_checker.py` | 基于坐标的 sum check |
| `receipt_partitioner.py` | 按坐标与 markers 划分为四区 |
| `receipt_body_detector.py` | 过滤 receipt body 外 blocks |
| `relative_positioning.py` | 相对定位（S 折小票） |

### 2.4 `processors/stores/` — 按 layout 的 Store 专用 Processor

| 目录 | layout | 说明 |
|------|--------|------|
| `costco_digital/` | costco_digital | Costco 数字小票：SKU\|Name\|Amount 列、TPD 合并、专有 totals 序列 |

**Triage 逻辑**：`store_config.layout == "costco_digital"` → 使用 `stores.costco_digital.processor`；否则走通用 `validation.pipeline`。

### 2.5 其他模块

| 路径 | 说明 |
|------|------|
| `core/` | 工作流编排、批量处理、receipt_parser（T&T 文本解析） |
| `processors/merchants/` | LLM 后处理：按 merchant 应用（如 T&T clean） |
| `processors/enrichment/` | 地址匹配、支付类型标准化 |
| `processors/text/` | LLM 结果清洗 |
| `pipelines/` | StandardPipeline：清洗 → merchant → 地址 → sum 校验 |
| `services/` | OCR、LLM、数据库、RAG |

---

## 3. v1/v2 整合说明

| 原文件 | 处理 |
|--------|------|
| `item_extractor_v2.py` | 已合并为 `item_extractor.py`（无 v1） |
| `receipt_pipeline_v2.py` | 已重命名为 `pipeline.py`（无 v1） |

---

## 4. 配置与 Triage

- **Config**：`backend/config/store_receipts/*.json`，按 chain_id 加载
- **Triage**：OCR → 识别 merchant name → `find_chain_id_by_merchant_name()` → `load_store_config(chain_id)` → `store_config.layout` 决定 Processor
- **Layout 复用**：多门店可共享同一 layout（如 Costco CA/US），仅 config 不同

---

## 5. 扩展建议

- **新门店**：主要新增 JSON config；layout 相同则无需新代码
- **新 layout**：在 `processors/stores/` 下新建目录（如 `tt_supermarket/`），实现 processor，并在 `pipeline.py` 中增加 triage 分支
- **通用逻辑**：尽量放在 `processors/core/` 或 `validation/`，store 专用逻辑仅保留差异化部分
