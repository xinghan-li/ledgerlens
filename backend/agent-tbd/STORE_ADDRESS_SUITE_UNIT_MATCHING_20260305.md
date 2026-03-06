# 同店多写法地址匹配（Suite / Unit / Suite- 等）

## 问题

同一物理门店（如 19715 Highway 99 Lynnwood, WA 98036）在小票上会出现多种写法：

- `19715 Highway 99, Suite-101 Lynnwood, WA 98036`
- `19715 Highway 99 Unit 101 Lynnwood, WA 98036 US`
- `19715 Highway 99, Suite 101, Lynnwood, WA 98036`

因 Suite / Unit / Suite- / 逗号 / 尾部 US 等差异，**精确或简单归一化**无法把“无 store_location_id”的 record_summary 正确关联到已有的 store_location，导致：

- 部分小票 `store_location_id` 为 NULL
- 统计、地图、门店维度分析不一致

---

## 方案一：地址归一化时剥离 Unit/Suite（已实现）

**做法**：在匹配与 backfill 前，对地址字符串做统一归一化：

- 去掉或规范化：`, Suite 101`、`Suite-101`、` Unit 101`、` Ste 101`、` #101` 等
- 去掉尾部国家词：`US`、`USA`、`CA`、`Canada`
- 再对剩余部分做小写、去多余空白后比较

**已落地点**：

- `supabase_client._normalize_address_for_backfill()`：backfill 时用
- `address_matcher._normalize_address_for_compare()`：实时 match_store 时用
- backfill 端点：`POST /api/admin/store-review/backfill-store-locations`，Admin Store Review 页有「Backfill record_summaries store_location_id」按钮

**优点**：实现简单、不依赖新表；backfill 与实时匹配一致。  
**缺点**：依赖正则覆盖写法，极端写法可能仍漏；若 DB 里同一门店有多条 address_line2 写法，需保证归一化后一致。

---

## 方案二：按“核心地址成分”匹配（可选增强）

**做法**：把地址解析成结构化成分再比较，而不是整串归一化：

- 成分：门牌+街道、城市、州/省、邮编、（可选）国家
- Unit/Suite 视为“同一地址的附加信息”，不参与是否同一门店的判断
- 比较时：`(address_line1 归一化, city, state, zip)` 一致即视为同店

**实现要点**：

- 复用或扩展 `address_matcher.extract_address_components_from_string()`，或单独写 `parse_core_address(addr) -> (street, city, state, zip)`
- store_locations 已有 address_line1 / city / state / zip_code，可直接用
- record_summaries.store_address 需解析得到 street/city/state/zip 再与 store_locations 比较

**优点**：对 Suite/Unit/Ste 写法更鲁棒，逻辑清晰。  
**缺点**：需要可靠的地址解析（OCR 噪声、多行合并等），实现量比方案一大。

---

## 方案三：相似度阈值 + 归一化（当前 backfill 的延伸）

**做法**：在方案一的基础上，对“归一化后仍不完全一致”的地址用相似度（如 token_set_ratio 或 token_sort_ratio）加阈值：

- 先做 Suite/Unit 剥离与尾部国家剥离（方案一）
- 再计算相似度，例如 ≥ 0.85 或 0.90 视为同店
- backfill 与 match_store 使用同一套归一化 + 同一阈值

**实现要点**：

- 当前 backfill 已用 `fuzz.ratio(rec_norm, canonical_norm) >= 0.85`
- 若仍漏配，可尝试：  
  - 使用 `fuzz.token_sort_ratio` 对词序不敏感；或  
  - 适当下调阈值到 0.82，并加日志/审计，避免误绑

**优点**：在方案一基础上进一步容忍 OCR 错字、词序变化。  
**缺点**：阈值需调参；过低可能把不同店绑在一起，需配合人工抽查或只对“同 chain + 同城”做宽松匹配。

---

## 建议

- **短期**：以方案一为主，配合 backfill 端点与按钮，已能解决多数 Suite/Unit/Suite- 导致的未关联问题。
- **若仍有漏配**：在方案一不变的前提下，先尝试方案三（同归一化 + token_sort_ratio 或略降阈值），再考虑方案二做结构化“核心地址”匹配。
