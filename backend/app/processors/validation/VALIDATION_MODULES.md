# Validation 文件夹模块说明 / Validation Folder Module Summary

中英双语，便于维护。  
Bilingual (Chinese + English) for maintenance.

---

## 概览 / Overview

`validation` 目录包含小票 OCR 后的**坐标提取、主体检测、分区、行重建、金额列检测、商品/总额提取、税费分类、数学校验**等逻辑。部分模块属于 **Pipeline V2**（以行为中心）；部分被 **coordinate_sum_check** 等旧流程或 API 共用。

This folder contains logic for **coordinate extraction, receipt body detection, partitioning, row reconstruction, amount column detection, item/totals extraction, tax-fee classification, and math validation** after receipt OCR. Some modules belong to **Pipeline V2** (row-based); others are shared by **coordinate_sum_check** or other APIs.

---

## 按文件说明 / Per-File Summary

| 文件 File | 中文简述 | English Summary |
|-----------|----------|-----------------|
| **`__init__.py`** | 包初始化（空）。 | Package init (empty). |
| **`column_detector.py`** | **Pipeline V2 Step 2**：用金额块 X 坐标的直方图做列检测，找到主金额列（通常右对齐），不依赖 subtotal 的 X 作为锚点。 | **Pipeline V2 Step 2**: Detects amount columns via histogram of amount X coordinates; finds main column (usually right-aligned); does not rely on subtotal X as anchor. |
| **`coordinate_extractor.py`** | 从 Document AI 的 `coordinate_data` 里提取带坐标的文本块（含 `center_x/center_y`、`is_amount`、`amount`）；排序后可选调用 `receipt_body_detector` 过滤主体外块。 | Extracts text blocks with coordinates from Document AI `coordinate_data` (center_x/center_y, is_amount, amount); sorts; optionally filters by receipt body. |
| **`coordinate_item_extractor.py`** | 基于坐标从「商品区」提取 item（同行文本+金额配对）；支持相对定位（S 折小票）、首商品标记、subtotal/total 边界；被旧流程/coordinate_sum_check 等使用。 | Extracts items from “item region” by pairing text + amount on same row; supports relative positioning (S-fold), first-item marker, subtotal/total bounds; used by older flow / coordinate_sum_check. |
| **`coordinate_sum_checker.py`** | 基于坐标的金额校验：找 SUBTOTAL 位置、对同一 X 的 item 金额求和、对 SUBTOTAL 下方序列做 subtotal+tax+fees=total 校验；含大量 Y 容差、对齐、标签模糊匹配等逻辑。 | Coordinate-based sum check: find SUBTOTAL, sum items by same X, validate subtotal+tax+fees=total; includes Y tolerance, alignment, fuzzy label matching. |
| **`fuzzy_label_matcher.py`** | 通用 OCR 标签模糊匹配：多特征相似度（Levenshtein、LCS、Skeleton、Token、N-gram）、视觉字符映射（0→o 等）、上下文阈值；用于税费/费用标签标准化。 | Generic fuzzy matching for OCR labels: multi-feature similarity, visual char mapping; used for tax/fee label normalization. |
| **`item_extractor_v2.py`** | **Pipeline V2 Step 4**：在 item 行内按金额列提取商品；商品名=金额左侧文本（排除 section header）；支持多行商品名、AmountUsageTracker 消消乐。 | **Pipeline V2 Step 4**: Extracts items in item rows by amount column; product name = text left of amount (excl. section headers); multi-line names, AmountUsageTracker. |
| **`math_validator.py`** | **Pipeline V2 Step 7**：行级校验 qty×unit_price≈line_total；总体校验 items sum≈subtotal、subtotal+fees+tax≈total；容差可配。 | **Pipeline V2 Step 7**: Row-level (qty×unit_price≈line_total) and global (items sum≈subtotal, subtotal+fees+tax≈total) math validation. |
| **`receipt_body_detector.py`** | 小票主体检测：根据 block 的垂直范围做**内容相对**的 header 判定，估计左右边界（对称+margin），过滤主体外块；提供 `filter_blocks_by_receipt_body` 与 `get_receipt_body_bounds`；可扩展“是否小票”等。 | Receipt body detection: content-relative header, symmetric X bounds; filters blocks outside body; exposes filter + bounds; extensible for “is receipt?” etc. |
| **receipt_partitioner.py** | 将 blocks 按坐标和标记划分为 4 区：header / items / totals / payment；识别 first_item、subtotal、total、payment 等 marker；被 coordinate_sum_check 等使用。 | Partitions blocks into 4 regions (header/items/totals/payment) by coordinates and markers; used by coordinate_sum_check. |
| **receipt_pipeline_v2.py** | **Pipeline V2 入口**：串联 Step 0~7（结构体、行重建、列检测、区域划分、item 提取、totals 提取、税费分类、数学校验）；支持可选 `store_config`（wash_data、markers、section headers）。 | **Pipeline V2 entry**: Orchestrates Steps 0–7; optional store_config for wash_data, markers, section headers. |
| **receipt_structures.py** | **Pipeline V2 数据结构**：TextBlock、PhysicalRow、RowType、ReceiptRegions、AmountColumn(s)、AmountUsageTracker、ExtractedItem、TotalsSequence 等。 | **Pipeline V2 data structures**: TextBlock, PhysicalRow, ReceiptRegions, AmountColumns, AmountUsageTracker, ExtractedItem, TotalsSequence. |
| **region_splitter.py** | **Pipeline V2 Step 3**：按 SUBTOTAL、Payment 等标记把 PhysicalRow 列表切分为 header/item/totals/payment；支持 store_config 的 chain 特定 markers。 | **Pipeline V2 Step 3**: Splits PhysicalRows into regions by SUBTOTAL and payment markers; chain-specific markers via store_config. |
| **relative_positioning.py** | 相对定位工具：在两参考点（如 first_item、subtotal）之间做相对 Y 位置判断，适应 S 折小票、不同区块 Y 偏移；提供 `is_within_relative_bounds`、`filter_blocks_by_relative_position` 等。 | Relative positioning between two reference Y points (e.g. first_item–subtotal); handles S-fold and section offsets. |
| **row_reconstructor.py** | **Pipeline V2 Step 1**：按 Y 坐标将 TextBlock 聚成 PhysicalRow（row_height_eps 控制同行判定），用于后续列检测与区域划分。 | **Pipeline V2 Step 1**: Clusters TextBlocks into PhysicalRows by Y (row_height_eps); feeds column detection and region split. |
| **store_config_loader.py** | 从 `backend/config/store_receipts/` 按 `chain_id` 或商户名（primary_name/aliases/match_keywords）加载 JSON 配置，供 Pipeline V2 的 wash_data、totals 序列、payment 标记等使用。 | Loads store receipt JSON by chain_id or merchant name; used for wash_data, totals sequence, payment markers in Pipeline V2. |
| **sum_checker.py** | 通用金额校验：items 求和≈subtotal、subtotal+tax≈total；支持 package price 促销（如 2/$9.00）检测与校验；与坐标无关，可用于 LLM 结果校验。 | Generic sum check: items sum≈subtotal, subtotal+tax≈total; package price discount detection; no coordinates, for LLM result validation. |
| **`tax_fee_classifier.py`** | **Pipeline V2 Step 6**：用 fuzzy_label_matcher 将 totals 区中间金额行分类为 tax / fee / generic；优先级 explicit tax > generic fee；可做 tax < 20% subtotal 等校验。 | **Pipeline V2 Step 6**: Classifies middle totals rows as tax/fee via fuzzy matching; optional tax < 20% subtotal check. |
| **`totals_extractor.py`** | **Pipeline V2 Step 5**：在 totals_rows 中找 subtotal 与 total、收集二者之间的 middle amounts（税费等）；与 AmountUsageTracker 配合避免重复使用同一金额块。 | **Pipeline V2 Step 5**: Finds subtotal/total in totals_rows, collects middle amounts; uses AmountUsageTracker. |

---

## 依赖关系简图 / Dependency Sketch

```
Document AI coordinate_data
         │
         ▼
  coordinate_extractor ──► receipt_body_detector (filter bounds)
         │
         ├──► receipt_partitioner ──► coordinate_sum_checker (uses coordinate_item_extractor, fuzzy_label_matcher, relative_positioning)
         │
         └──► receipt_pipeline_v2
                    │
                    ├── receipt_structures
                    ├── row_reconstructor (Step 1)
                    ├── column_detector (Step 2)
                    ├── region_splitter (Step 3)
                    ├── item_extractor_v2 (Step 4)
                    ├── totals_extractor (Step 5)
                    ├── tax_fee_classifier (Step 6, uses fuzzy_label_matcher)
                    ├── math_validator (Step 7)
                    └── store_config_loader (optional)
```

---

## 相关文档 / Related Docs

- **`PIPELINE_V2_README.md`**：Pipeline V2 架构与步骤说明（行中心、消消乐、区域隔离等）。  
  Pipeline V2 architecture and steps (row-centric, usage tracker, region isolation).

---

*文档维护：随模块增删或职责变化请更新此文件。*  
*Keep this file updated when adding/removing modules or changing responsibilities.*
