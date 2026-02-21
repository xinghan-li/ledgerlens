# Backlog: record_items 空值回填（Backfill）

**创建日期**: 2026-02-17  
**状态**: 待实现  
**优先级**: 中（数据一致性/报表准确性）

---

## 问题描述

- 一张小票上同品项可能有多行（例如 3 瓶 milk），上传后会在 `record_items` 里生成多条，并在 `classification_review` 里出现多条待审核。
- 用户往往只对其中一条点「Confirm」，其余在分类审核里点「删除」，避免重复插入 product/规则。
- **结果**：被删掉的那几条对应的 `record_items` 仍然存在，但 `category_id`、`product_id` 等多为空，历史数据里会留下很多空值，影响按分类/商品统计。

## 目标

- **Backfill**：对 `record_items` 中 `category_id` 或 `product_id` 为空的记录，用「同小票 + 同商品名」的已填充行来回填，使同一小票上的相同商品（如 3 瓶 milk）共享同一套 category/product。
- **执行频率**：不需要实时，可接受**每日或每周**跑一次（定时任务/脚本即可）。

## 实现思路（供后续开发参考）

1. **识别待回填行**  
   - `record_items` 中 `category_id IS NULL` 或 `product_id IS NULL`（或两者都空）的行。

2. **同小票 + 同商品名匹配**  
   - 在同一 `receipt_id` 下，按 `product_name`（或标准化后的 product_name）分组；  
   - 若该组内存在已填好 `category_id` / `product_id` 的行，则用该行的值回填同组内空值行。

3. **可选：与 product_categorization_rules / products 对齐**  
   - 若希望与当前规则一致，可对回填后的 `normalized_name` + `store_chain_id` 再查一次 rules/products，做二次回填或校验。

4. **执行方式**  
   - 脚本或后台任务（如 Celery/ cron），每日或每周执行；  
   - 可选：提供 Admin API 手动触发一次 backfill。

## 相关表

- `record_items`: `receipt_id`, `product_name`, `category_id`, `product_id`, …
- `record_summaries`: `receipt_id`, `store_chain_id`（同小票的 store 信息，可用于规则匹配）
- `product_categorization_rules` / `products`: 已存在的分类与商品，用于校验或二次匹配

## 验收

- 跑完 backfill 后，同一小票、同一 `product_name` 的 `record_items` 行，其 `category_id` / `product_id` 与同组内已填充行一致（或从 rules 解析得到一致结果）。
- 不影响已有非空值数据；仅更新当前为空的字段。

---

**记入项目 TODO**：实现 record_items 空值 backfill（每日/每周），并视需要加 Admin 手动触发接口。
