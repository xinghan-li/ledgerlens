# 小票校验与认证：关键架构决策（供 LLM/开发参考）

本文档记录从小票校验、状态判定与认证相关修复中沉淀的**架构级约定**，确保后续改代码或排查时行为一致。  
历史诊断与实施细节已归档至 `backend/agent-tbd/archived/`，此处只保留「必须遵守」的结论。

---

## 1. 小票 Sum Check 与状态判定

### 1.1 金额容差

- **规则**：容差为 **max(3 分, 1% × 参考金额)**，单位与金额一致（一律用**分/cents**）。
- **禁止**：不得使用裸数字 `3` 作为容差（在美元场景下会变成 3 美元，导致误判通过）。
- **参考**：`backend/app/processors/core/sum_checker.py`；历史诊断见 `agent-tbd/archived/RECEIPT_TNT_20260304_OCR_AND_SUCCESS_DIAGNOSIS.md`。

### 1.2 LLM validation_status 参与决策

- **规则**：若 LLM 返回 `_metadata.validation_status == "needs_review"`，即使 Sum Check 通过，最终状态也标为 **needs_review**。
- **原因**：避免「模型自报需人工复核」却被判 success 的情况。
- **参考**：同上 T&T 诊断文档；流程见 `docs/architecture/RECEIPT_WORKFLOW_CASCADE.md`。

### 1.3 Item count 校验

- **规则**：若小票底部有 "Item count: N"（或 "Iten count: N" 等），且解析出的商品行数 **少于 N**，则 Sum Check **不通过**，进入 cascade / needs_review。
- **原因**：防止漏行（如漏掉 KO-LE CABBAGE、Cilantro 等）仍被判 success。
- **实现**：在调用 `check_receipt_sums` 前注入 OCR/Vision 的完整 `raw_text`，从中解析 item count；`sum_checker` 或 workflow 层做数量比对。

### 1.4 Subtotal 为空时的 Sum Check

- **规则**：当 `receipt.subtotal` 为 null 时，用 **line_total 之和 + tax ≈ total** 判定，而不是用 line_total 之和直接与 total 比较（因 total 可能含税）。
- **参考**：`agent-tbd/archived/RECEIPT_TNT_20260304_OCR_AND_SUCCESS_DIAGNOSIS.md`；`sum_checker` 已按此修复。

---

## 2. 规则清洗 / Item 提取（Rule-based pipeline）

以下逻辑来自历史 debug，已落地，修改时需保持语义一致。

### 2.1 Section header 行 + 金额

- **规则**：当行左侧**只有** DELI/PRODUCE/MEAT 等 section header、右侧有金额时，该金额**不属于** section header，而属于**下一行第一个商品**。
- **错误做法**：把该金额行直接 skip 或归到 section header。
- **参考**：`agent-tbd/archived/ANALYSIS-DEBUG_LOGIC_DIAGNOSIS.md`。

### 2.2 仅金额行（无左侧文字）

- **规则**：若某行**仅有金额**、无左侧商品名（例如 lone $20.53），**禁止**向上查找 name 并关联到上方商品（否则会误匹配到 GYG 等）。
- **正确做法**：将该行归入 totals 或单独处理，不参与 item 的「向上抓 name」逻辑。
- **参考**：同上。

---

## 3. 认证

### 3.1 当前方案：Firebase Auth

- **规则**：生产与主流程使用 **Firebase Auth**（Email Link 等）。后端优先校验 Firebase ID token，通过 `firebase_uid` 在 `public.users` 中查/建用户。
- **已废弃**：Supabase Magic Link/OTP 作为主登录方式已不再使用；相关说明仅作历史参考，见 `agent-tbd/archived/MAGIC_LINK_REFRESH_LOGIN_AND_SECURITY.md`。
- **配置与迁移**：见 `backend/agent-tbd/FIREBASE_AUTH_MIGRATION.md`（若仍在 agent-tbd 根目录）。

---

## 4. 分类规则匹配（Categorization）

### 4.1 匹配逻辑所在位置

- **规则**：分类匹配（exact / fuzzy / contains / prefix）**全部在后端 Python** 完成；先查表 `product_categorization_rules`，再按需做 universal fuzzy 等。
- **已废弃**：DB 侧的 `find_categorization_rule` RPC（exact/fuzzy/contains）已废弃，逻辑已迁移到后端；**不要**再在 DB 中实现复杂匹配或 prefix。
- **参考**：`docs/categorization-matching.md`；历史分工说明见 `agent-tbd/archived/MATCHING_DB_VS_BACKEND.md`。

---

## 5. 文档与归档

- **agent-tbd 根目录**：只放**尚未完成或待评审**的 TBD（需求草稿、待实现 TODO、进行中设计）。
- **agent-tbd/archived/**：已实现或流程不再需要的文档，顶部有「结论（归档原因）」一行，便于检索。
- 新增与校验/状态/认证相关的约定时，建议在本文档或 `RECEIPT_WORKFLOW_CASCADE.md` 中补充，并在相关代码处注释指向此文档。
