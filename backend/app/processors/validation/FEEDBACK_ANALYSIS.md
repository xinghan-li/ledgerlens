# Console 反馈逐条分析 / Feedback Analysis

根据 initial-parse console 结果的反馈：每条对应**出问题的 Step**、**原因**、**修改建议**。

---

## 1. 主体边界（receipt body）移除不够 / 背景草稿纸没去掉

**现象**：扫到约第 [20] 行是 T&T 店名，从这里往下才是 items / totals / payment。左边应约 0.35–0.38、右边约 0.64；应以 TOTAL + 下一行金额等为 benchmark，左右边界约 **0.3–0.7**。商店名称**以上**的 Y 都应去掉（背景草稿纸）。[122] 被移除是对的，但整体移除得少。

**出问题的 Step**：**Receipt body 估计** — `receipt_body_detector.py`（在 `coordinate_extractor` 之后生效，影响进入 pipeline 的 blocks）。

**原因**：
- 当前左右边界是用「header 块中心对称 + 金额列最右 + margin」算的，且被夹在 `[MIN_LEFT_BOUND=0.01, MAX_RIGHT_BOUND=0.99]`，没有用「小票主体」的固定或 benchmark 边界（如 0.3–0.7）。
- Y 方向只用「内容顶部比例」`HEADER_FRACTION` 裁 header，没有「商店名以上全部丢掉」的规则；若背景块和店名一起在内容里，就会保留很多背景。

**修改建议**：
- **Patch 1a**：在 `receipt_body_detector.py` 增加**可选**「硬边界」：例如从 store_config 或常量读 `BODY_X_LEFT=0.3`, `BODY_X_RIGHT=0.7`（或用 TOTAL/金额列做 benchmark 算出来），过滤时用 `max(left_bound, 0.3)` 和 `min(right_bound, 0.7)`，这样 0.3 左、0.7 右一律丢掉。
- **Patch 1b**：Y 方向「商店名以上不要」：若识别到店名行（例如 T&T 的 row），可设 `y_min = 店名行的 center_y`（或店名行 y 减去一小段），只保留 `center_y >= y_min` 的块；或 store_config 里给 T&T 一个 `header_end_after_store_name: true`，在 detector 里用店名位置截断 header。

---

## 2. 分区错误 / Items 没成功 partition 出来 + T&T 会员卡规则未实现

**现象**：Items section 没有正确 partition 出来。你期望的 T&T 规则：看到【24】日期时间和【25】后检查**下一行**；若下一行是 `****00000` 会员卡号 + `$0.00`，说明刷了会员卡，则 **items 从会员卡 $0.00 的下一行开始**；若没有会员卡，则【25】的下一行就是 items 开始。当前流程里没有加这条 T&T 规则。

**出问题的 Step**：**Step 3 区域划分** — `region_splitter.py`（`split_regions`）。当前只靠「见 SUBTOTAL → TOTALS」「见 Visa/Reference# 等 → PAYMENT」和「HEADER 下若 _looks_like_item_row 就切到 ITEM」，**没有**「日期/时间下一行 + 可选会员卡行」的 T&T 逻辑。

**原因**：  
- `region_splitter` 没有读 store_config 的「items 从哪一行开始」（例如 `items_start` / `header.end_markers` 后 + 可选会员行）。  
- T&T 的 `tnt_supermarket_us.json` 里 `header` 有描述和 `membership_pattern`，但 **region_splitter 没有**「在 header 结束后检查下一行是否是 membership（*** + $0.00），若是则再跳过一行再进 ITEM」的实现。

**修改建议**：
- **Patch 2**：在 `region_splitter.py` 中：
  - 若存在 `store_config`，检查是否有 `header.items_start_rule` 或等价配置（例如 `after_date_time_then_optional_membership`）。
  - 实现 T&T 规则：在识别到「日期时间行」（可用现有 end_markers/patterns 或行内正则）和其下一行后，看下一行是否匹配 `membership_pattern` 且该行有 `$0.00`；若是，则 **ITEM 从再下一行开始**；否则 **ITEM 从该下一行开始**。
  - 这样 HEADER 明确在「日期时间行」或「日期时间 + 会员卡行」结束，items section 就能正确 partition 出来。

---

## 3. [29] veight → weight

**现象**：OCR 把 "weight" 识别成 "veight"。

**出问题的 Step**：**Step 4 商品名清理** — `item_extractor_v2.py` 的 `_apply_product_name_cleanup` 使用 `RECEIPT_WORDS` 做**一编辑距离**纠错；`fuzzy_label_matcher` 的 `VISUAL_MAP` 是给标签匹配用的，不直接改商品名。

**原因**：`RECEIPT_WORDS` 里没有 "WEIGHT"，所以 `_one_edit_correct("VEIGHT", RECEIPT_WORDS)` 不会纠正。

**修改建议**：
- **Patch 3**：在 `item_extractor_v2.py` 的 `RECEIPT_WORDS` 中加入 `"WEIGHT"`。这样 "veight" 会在一编辑距离内被纠正为 "weight"。

---

## 4. [31] Tere → Tare，16 → lb

**现象**：Tere 应为 Tare；16 应为 lb（单位）。

**出问题的 Step**：  
- **Tere→Tare**：Step 4 的 `_apply_product_name_cleanup` 里已有 **store typo 表**（`product_name_typos`）；T&T 配置里已有 `["Tere","Tare"]`，所以若 store_config 正确加载应已生效；若仍未生效，可能是 typo 应用顺序或匹配方式（大小写/整词）问题。  
- **16→lb**：当前没有「数字 16 在重量/单位语境下替换为 lb」的规则，属于 OCR 误识 + 语义规则缺失。

**修改建议**：
- **Patch 4a**：确认 T&T 的 `product_name_typos` 包含 `["Tere","Tare"]`（已有），并确认 typo 是整词替换且先于其他清理执行；若行内是 "Tere removed" 等形式，确保正则/整词匹配能命中 "Tere"。
- **Patch 4b**：在 store_config 的 typo 表或单独「单位误识」规则中加一条：在明确「重量/单位」语境（例如 `\d+\s*16\s*@`、`/16`、`removed: "0.08 16'`）下将 `16` 替换为 `lb`；或加 `["16","lb"]` 的上下文相关替换（仅在与 @、/lb、removed 等相邻时替换），避免误改其他 "16"。

---

## 5. [33] Taiwanese

**现象**：OCR 打出 TAIVANESE，应为 Taiwanese。

**出问题的 Step**：Step 4 商品名清理，`RECEIPT_WORDS` 一编辑距离纠错。

**原因**：`RECEIPT_WORDS` 里已有 "TAIWANESE"，但当前是「全大写」比较；"TAIVANESE" 与 "TAIWANESE" 差一个字符（V→W），应能被 `_one_edit_correct` 纠正。若未纠正，可能是大小写或字典命中逻辑问题。

**修改建议**：
- **Patch 5**：确认 `RECEIPT_WORDS` 包含 "TAIWANESE"（已有）；确认 `_one_edit_correct` 对全大写词能命中（代码里已有 `wu = word.upper()`）。若仍不生效，检查是否该 token 被拆成多段或带标点，导致没有进纠错分支。

---

## 6. [35] Meat

**现象**：OCR 打出 NEAT，应为 Meat。

**出问题的 Step**：Step 4 商品名清理，`RECEIPT_WORDS` + section headers。

**原因**：`SECTION_HEADERS` 和 `RECEIPT_WORDS` 里都有 "MEAT"；"NEAT" 与 "MEAT" 一编辑距离（N→M），应可纠正。若未纠正，同上，检查 token 是否进了一编辑纠错。

**修改建议**：
- **Patch 6**：确认 "MEAT" 在 `RECEIPT_WORDS` 或 section 相关逻辑里；确保 section header 行（如 "NEAT"）在显示/提取时也走 `_apply_product_name_cleanup`，这样 "NEAT" → "MEAT"。

---

## 7. [41] 3 @ 3/$1.98 — '@' 被识别成 8

**现象**：`@` 被 OCR 成 `8`，出现类似 `3 8 3/$1.98`。

**出问题的 Step**：  
- **OCR 输出**：Document AI 直接给出错误字符，后续 Step 4 解析 quantity / x-for-y 时会把 `8` 当数字或分隔符。  
- **纠错**：`fuzzy_label_matcher.VISUAL_MAP` 里有 `"@": "a"`，是给标签匹配用的，不会在商品名/金额解析前把 `8` 还原成 `@`。

**原因**：没有在「数量/单价/促销」解析前，对「数字 8 在 @ 语境（如 `3 8 3/$1.98`）」做 8→@ 的还原。

**修改建议**：
- **Patch 7**：在解析 quantity / x-for-y 的路径（例如 `item_extractor_v2` 或 `coordinate_extractor` 的 amount/quantity 逻辑）中，对匹配到的「数字 数字 8 数字/$\d」这类模式，尝试把中间的 `8` 当 `@` 再解析一次（例如 `3 8 3/$1.98` → `3 @ 3/$1.98`）；或在 `_apply_product_name_cleanup` 之后、解析前，用一条正则/规则：在 `\d+\s+8\s+\d+` 且后面有 `/$` 或 `$` 时，将 ` 8 ` 替换为 ` @ `。

---

## 8. [44] @ 3.99/lb — 逗号要自动 correct

**现象**：价格里逗号当小数（如 3,99）应自动改成点号 3.99。

**出问题的 Step**：**金额解析** — `coordinate_extractor.py` 的 `_extract_amount` 已有「逗号当小数」逻辑（`eu_match`），会识别 `3,99` 并转为 3.99 并打 `comma_decimal_corrected`；若 [44] 是整块文本（如 "1.19 lb @ $12,88/1b"），可能逗号在「单价」部分，需要确保该块或相邻块也走同一套 comma-decimal 逻辑。

**原因**：要么该 block 没被当成 amount 块、要么只对「纯数字+逗号」做了替换，而 `@ $12,88/lb` 这种需要在整个 token/行里把 `,88` 规范成 `.88`。

**修改建议**：
- **Patch 8**：在 `coordinate_extractor._extract_amount` 或调用前，对整段 text 做一次「欧洲小数」规范化：`\d+,\d{2}` → `\d+.\d{2}`（仅当不是千分位时），再跑金额解析；并保持 `comma_decimal_corrected` 标记，这样 [44] 这类会统一 correct。

---

## 9. [64] 和 [65] Y 差距很小却被识别成两行

**现象**：两行 y 非常接近，却被拆成两个 physical row。

**出问题的 Step**：**Step 1 行重建** — `row_reconstructor.py`（`build_physical_rows`），用 `row_height_eps`（默认 `DEFAULT_ROW_HEIGHT_EPS = 0.0025`）判断「同一行」。

**原因**：若 [64] 和 [65] 的 `center_y` 差大于 0.0025（归一化），会被判成两行。0.0025 很紧，但若 OCR 对同一行两段文字给出略有偏差的 y，就会拆行。

**修改建议**：
- **Patch 9**：适当增大行高容差，例如把 `DEFAULT_ROW_HEIGHT_EPS` 从 `0.0025` 调到 `0.004` 或 `0.005`，或改为「动态」：用同一行内 block 的典型高度（如 height 或 center_y - y）的某个倍数作为 eps，这样同一行内 y 略差的 block 会并成一行。注意不要调得过大，否则真正相邻的两行会被合并。

---

## 10. [68] 和 [69] 同样问题

**现象**：同 9，y 很近却是两行。

**出问题的 Step**：同上，Step 1 `row_reconstructor.py`。

**修改建议**：同 **Patch 9**，统一用更大的 `row_height_eps` 或动态 eps。

---

## 11. [81] Item

**现象**：应为 "Item"（例如 "Item count" 被识别成别的）。

**出问题的 Step**：若 [81] 是商品名或标签，则 Step 4 清理或 fuzzy 匹配；若是 "Iten count" 这种，则属 OCR 错误（t→i 缺失）。

**原因**：若为 "Iten"→"Item"，可在一编辑距离里用 RECEIPT_WORDS 或常用词表纠正；当前 RECEIPT_WORDS 可能没有 "ITEM"。

**修改建议**：
- **Patch 11**：在 `RECEIPT_WORDS`（或通用「收据/支付」词表）中加入 "ITEM"，这样 "Iten" 会在一编辑距离内被纠正为 "Item"；若 [81] 是 "Item count" 整段，可再加 "COUNT" 等，避免只改了一个词。

---

## 小结表（Step 与 Patch 对应）

| 问题 | Step | 文件 | Patch 要点 |
|------|------|------|------------|
| 1. 主体边界/背景草稿纸 | Receipt body | receipt_body_detector.py | 硬边界 0.3–0.7；Y 用店名截断 |
| 2. 分区/items 未正确 + T&T 会员卡 | Step 3 区域划分 | region_splitter.py | 实现 T&T items_start：日期时间下一行 + 可选会员行 |
| 3. veight→weight | Step 4 商品名 | item_extractor_v2.py | RECEIPT_WORDS 加 WEIGHT |
| 4. Tere→Tare, 16→lb | Step 4 / typo / 单位 | item_extractor_v2 + config | 确认 Tere 已 typo；加 16→lb 语境替换 |
| 5. TAIVANESE→Taiwanese | Step 4 | item_extractor_v2.py | 确认 RECEIPT_WORDS 有 TAIWANESE 且命中 |
| 6. NEAT→Meat | Step 4 | item_extractor_v2.py | 确认 MEAT 在词表且 section 行也走清理 |
| 7. @ 识别成 8 | Step 4 / 解析 | item_extractor_v2 或解析处 | 数量/单价解析前 8→@ 语境还原 |
| 8. 逗号小数 | 金额解析 | coordinate_extractor.py | 整段 comma-decimal 规范化 |
| 9–10. [64]/[65]、[68]/[69] 两行 | Step 1 行重建 | row_reconstructor.py | 增大 row_height_eps 或动态 eps |
| 11. Iten→Item | Step 4 | item_extractor_v2.py | RECEIPT_WORDS 加 ITEM（及 COUNT 等） |

如需我按上述建议在代码里逐条改（并标明具体函数/常量），可以说你希望先做哪几条（例如先 1+2+3+9+11），我按优先级写 patch。
