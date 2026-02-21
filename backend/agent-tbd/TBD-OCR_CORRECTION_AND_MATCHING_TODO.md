# TBD: OCR 纠错 + 规则匹配优化

**状态**: 明确要做，暂不实现；本文档供后续 LLM/开发直接按此实施。  
**日期**: 2026-02-19

---

## 1. 问题与现状

### 1.1 两种不同的匹配

| 类型 | 含义 | 当前实现位置 | 当前状态 |
|------|------|--------------|----------|
| **OCR 纠错** | 把 OCR 错误字符/词洗成「正确写法」（如 M↔N、V↔W、0-O、1-I、截断） | 提取阶段 + 无 categorizer 层 | 仅提取阶段有少量词级纠错，无通用字符级纠错 |
| **规则匹配** | 用归一化商品名查 `product_categorization_rules` 得到 category_id | DB `find_categorization_rule` + 后端调用 | exact → fuzzy → contains；**截断（小票名为规则名前缀）已在后端实现** |

### 1.2 OCR 纠错现状（需补）

- **提取阶段** `backend/app/processors/validation/item_extractor.py`：
  - `_apply_product_name_cleanup`：写死规则（Tere→Tare、`8`→`@`、`16`→`lb`）、store 的 `product_name_typos`、以及 **RECEIPT_WORDS** 的一编辑距离纠错（仅当恰好一个候选时才改）。
  - **RECEIPT_WORDS**：`backend/app/processors/validation/item_extractor.py` 里的 `frozenset`，需手动加词（如 WEIGHT、TAIWANESE、MEAT、ITEM 等）。
- **标签匹配** `backend/app/processors/validation/fuzzy_label_matcher.py`：
  - **VISUAL_MAP**（0→o, 1→l, 5→s, 7→t, $→s, @→a）只用于**标签**，不用于商品名。
- **Categorizer 阶段** `backend/app/services/categorization/receipt_categorizer.py`：
  - 只做 `normalize_name_for_storage`（小写、去尾 s/es），**没有任何 OCR 纠错或字符映射**。

因此：大量「智障 one-off patch」散落在 RECEIPT_WORDS、typos、正则里，难以维护；且 M-N/V-W/0-O/1-I 等字符级纠错在 categorizer 入口不存在。

### 1.3 规则匹配现状（截断已做）

- **截断匹配**：小票截断（如 "KIMBAP KOREAN SEAWEED RI"）匹配规则全名（如 `kimbap korean seaweed riceroll`）已作为**后端 feature** 实现：
  - 在 `find_categorization_rule` RPC 未命中时，后端对 `product_categorization_rules` 做「规则名以当前归一化名开头」的查询，且仅当 `len(receipt_normalized_name) >= 20` 时启用。
- **DB**：`find_categorization_rule` 仅保留 exact → fuzzy → contains，**不**做 prefix 逻辑（由 migration 033 保证）。

---

## 2. OCR 纠错 TODO（实施时按此执行）

### 2.1 目标

- 在 **categorizer 调用 `find_categorization_rule` 之前** 增加一层 OCR 纠错，使「错误词/错误字符」先变成「正确写法」，再查规则。
- 减少对 RECEIPT_WORDS 和零散 typos 的依赖；MVP 用一套「正确名」词库 + 可选字符映射即可。

### 2.2 要改的文件（按顺序）

1. **新建：OCR 纠错模块（推荐路径）**  
   - 路径建议：`backend/app/services/standardization/ocr_correction.py`（或 `backend/app/services/categorization/ocr_correction.py`）。  
   - 职责：
     - 加载「正确名」词库（见下）。
     - 可选：字符级映射（M↔N, V↔W, 0-O, 1-I 等），对输入做一次「尝试替换」得到候选串。
     - 词级纠错：用 **RapidFuzz** 的 `process.extractOne`，对「当前 product_name（或字符替换后的候选）」在词库中找最相似且分数 > 阈值（如 80）的项，返回纠错后的名字。
   - 接口建议：`correct_product_name_for_categorization(raw: str, lexicon: List[str]) -> str`，返回纠错后的名或原串。

2. **词库来源（二选一或组合）**  
   - **方案 A**：直接用现有数据：从 `product_categorization_rules.normalized_name` + `products` 的 name 去重，作为「正确名」列表；后端启动或按需加载到内存。  
   - **方案 B**：新建表 `ref_lexicon`（id, standard_word, category 等），种子数据约 2000–5000 词；加载到内存 List。  
   - 推荐 MVP：**方案 A**，不新建表；若后续要区分「商品名 / 店铺名」再引入 ref_lexicon。

3. **调用点**  
   - 文件：`backend/app/services/categorization/receipt_categorizer.py`。  
   - 函数：`_enrich_items_category_from_rules`。  
   - 在 `normalize_name_for_storage(product_name)` **之前**或**之后**（建议之后）对 `product_name` 做一次 OCR 纠错，用纠错后的串再 `normalize_name_for_storage`，然后和现在一样尝试 `normalized_underscore` / `normalized` 调 `find_categorization_rule`；若纠错后与原名不同，可同时保留「原名归一化」和「纠错后归一化」两次查规则。

4. **可选：字符级映射**  
   - 在 `ocr_correction.py` 中维护一份 `OCR_CHAR_MAP`（如 `{"0":"o","1":"i","M":"N"}` 等），对输入做一次「尝试替换」得到 1～2 个候选，再对候选做 RapidFuzz 匹配；或先 RapidFuzz，未命中再对候选做字符替换后重试。  
   - 避免在 SQL 或存储过程里写复杂逻辑；保持在后端便于调参和扩展。

### 2.3 不要动的地方（除非明确要重构）

- **提取阶段**：`item_extractor.py` 的 `_apply_product_name_cleanup`、RECEIPT_WORDS、store typos 可暂时保留，作为「第一道防线」；categorizer 的 OCR 纠错作为第二道。
- **DB 函数**：`find_categorization_rule` 保持只有 exact / fuzzy / contains；**不要**在 DB 里加 prefix 或 OCR 纠错逻辑。

### 2.4 数据库（仅当采用方案 B 时）

- 新建表示例（可选）：  
  - `ref_lexicon`：id (UUID), standard_word (TEXT), category (TEXT 可选), created_at。  
  - 索引：standard_word。  
- 若用方案 A，**不需要**新 migration。

### 2.5 依赖

- 已有 **RapidFuzz**（见 `backend/app/processors/enrichment/address_matcher.py`、`backend/app/services/admin/classification_review_service.py`）；无需新增依赖。

### 2.6 验收

- 给定带典型 OCR 错误的 product_name（如 R1CE、WH1SKEY、kimbap korean seaweed ri 截断），经 OCR 纠错 + 现有规则匹配（含后端截断匹配）后，能命中对应规则并得到 category_id。
- 不改变「规则表写全名、小票截断由后端前缀匹配」的现有行为。

---

## 3. 规则匹配（截断）— 已完成

- 截断匹配已在后端实现：当 `find_categorization_rule` 无结果且 `len(normalized_name) >= 20` 时，查询 `product_categorization_rules` 中 `normalized_name LIKE receipt_normalized || '%'`，先 store-specific 再 universal，按 priority、times_matched 取第一条。
- DB 通过 **migration 033** 保证 `find_categorization_rule` 仅含 exact/fuzzy/contains，不含 prefix。

---

## 4. 小结

| 项目 | 状态 | 说明 |
|------|------|------|
| agent-tbd 下 .md 分类重命名 | 已完成 | TBD- / ANALYSIS- 前缀已加 |
| 截断匹配 | 已完成 | 后端实现；033 保证 DB 无 prefix |
| OCR 纠错 | **TBD** | 按本文档 2.1–2.6 实施；词库优先用规则表+products，可选 ref_lexicon migration |

下次实现 OCR 纠错时，直接按本 TODO  doc 的「要改的文件」「词库来源」「调用点」「可选字符映射」执行即可。
