# 商店专属 Prompt 注入流程

## 目标

在识别出小票属于某商店（如 Costco）后，自动在发给 LLM 的 system prompt 中注入该商店的**专属解析规则**，例如 Costco 的「折扣行在商品下一行、格式为 `/ 数字 金额-` 表示上一行商品减该金额」。

## 当前流程（已支持）

```
OCR/规则 识别出 merchant_name（及可选 address）
    ↓
get_store_chain(merchant_name, address) → chain_id, location_id
    ↓
format_prompt(..., store_chain_id=chain_id, location_id=location_id)
    ↓
load_prompts_for_receipt_parse(prompt_key="receipt_parse", store_chain_id=chain_id, location_id=location_id)
    ↓
解析 prompt_binding：default（始终） + chain（当 chain_id 匹配） + location（当 location_id 匹配）
    ↓
按 priority 排序，把各条 prompt_library 的 content 拼成 system_parts → 组成最终 system_message
    ↓
LLM 收到：通用规则 + 商店专属规则
```

因此：**只要在 `prompt_library` 里加一条商店专属的 system 片段，并在 `prompt_binding` 里用 `scope='chain'` 绑定到对应 `chain_id`，就会在识别到该商店时自动注入。**

## 如何「教」LLM 某商店的规则

1. **在 `prompt_library` 新增一条**
   - `key`: 语义化命名，如 `costco_discount_line_format`
   - `content_role`: `system`
   - `content`: 用英文写清规则，例如：
     - 折扣行出现在商品下一行；
     - 格式为：`/` 后跟若干位数字，再跟 `金额-`（如 `2.40-`、`3.00-`）；
     - 表示**上一行商品**的折扣金额，该商品的 `line_total` 应为原价减该金额，并可在 `discount_amount` 或 `is_on_sale` 等字段体现。

2. **在 `prompt_binding` 绑定到该商店**
   - `prompt_key`: `receipt_parse`
   - `library_id`: 上一步插入的 `prompt_library.id`
   - `scope`: `chain`
   - `chain_id`: 该商店在 `store_chains` 表中的 `id`（如 Costco US、Costco Canada 可各绑一条，或共用一个 prompt 绑多条）
   - `priority`: 建议 50，高于 default(10)，这样商店规则会追加在默认规则之后

3. **部署后**
   - 当 OCR/地址匹配得到该商店的 `chain_id` 时，`load_prompts_for_receipt_parse(store_chain_id=chain_id)` 会带上这条 chain 绑定；
   - LLM 的 system 里就会多一段 Costco 折扣行说明，按说明解析即可。

## 为何 LLM 之前没识别出

通用 prompt 里没有描述「Costco 折扣行」这种格式，模型只能靠泛化猜；一旦在 system 里明确写出「下一行、`/`、数字、`2.40-` 表示上一商品减 2.40」，模型会立刻按规则执行。所以**流程上**只需要：保证识别到 Costco → 用 `chain_id` 加载 prompt → 其中包含 Costco 专属片段。

## 其他商店

- **Trader Joe's、T&T 等**：同样在 `prompt_library` 加一条 `content`，在 `prompt_binding` 用 `scope='chain'` 绑定对应 `store_chains.id` 即可。
- **门店级规则**：若某条规则只对某一家门店生效，用 `scope='location'` 和 `location_id` 绑定。

## 第二轮（second round）— store match 后的 refinement

当管线走「先 LLM 一次 → store match → 再带图 + 第一轮 JSON 做第二轮」时，使用 `prompt_key='receipt_parse_second'`：

- **通用前缀（所有有 store match 的第二轮都会带上）**：`receipt_parse_second_common`，scope=default，priority=10。内容包含：corrected/pre-filled input 说明、suspicious corrections 时不要改、在 reasoning 里 bullet 列出；不自信的字可以猜但必须在 reasoning 里写明「此处看不清，该值为 guess」。**Item count vs. receipt**（bottle deposit/fee 导致 count 不对时不要改、写 reasoning）**不在 DB**，仅当「第一 run item count 不对且 items 里出现 fee/deposit 字样」时在代码里追加（`prompt_loader.build_second_round_system_message(..., first_pass_result=...)`）。
- **商店专属**：例如 Costco 用 `costco_second_round`，scope=chain，priority=50。内容包含：折扣行合并到上一行、合并后做 sum check，不匹配则写进 reasoning。
- 加载方式：`load_second_round_prompts(store_chain_id=..., location_id=...)`，返回的 system_parts 顺序即为「通用前缀 + 商店专属」。见 migration 052。

## 相关代码与表

- 加载逻辑：`backend/app/prompts/prompt_loader.py` → `load_prompts_for_receipt_parse`、`load_second_round_prompts`
- 调用处：`backend/app/services/llm/receipt_llm_processor.py` → `format_prompt(..., store_chain_id=chain_id, ...)`；第二轮流程调用 `load_second_round_prompts(store_chain_id=...)` 得到 system_parts 后拼成 system message
- 表结构：`023_prompt_library_and_binding.sql`、`023_seed_prompt_library.sql`、`052_costco_discount_line_prompt.sql`（第二轮 prompt）
