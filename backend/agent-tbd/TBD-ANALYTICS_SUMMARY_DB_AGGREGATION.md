# TODO: Analytics summary 聚合下推到数据库

**来源**：Code review（gemini-code-assist）对 `supabase_client.get_user_analytics_summary` 的建议。  
**优先级**：未来再做，当前不改。

## 现状

- `get_user_analytics_summary` 在 Python 中：
  1. 查出用户所有 receipt 的 record_summaries（再按 period 过滤 receipt_date）
  2. 查出这些 receipt 的 record_items（line_total, category_id）
  3. 在内存里按 store、payment、category L1/L2/L3 做 SUM 和排序

- 用户小票数量增大后，拉全量再聚合会低效、占内存，且无法利用数据库的聚合优化。

## 建议

- 将 **by_store、by_payment、by_category_l1/l2/l3** 的聚合放到数据库侧完成，例如：
  - Supabase **RPC**：写一个 PostgreSQL 函数，入参 `user_id`、可选 `start_date`/`end_date`，返回 JSON（total_receipts, total_amount_cents, by_store, by_payment, by_category_l1/l2/l3）
  - 或使用带 **GROUP BY** 与 **SUM** 的 SQL 查询（多表 JOIN receipt_status、record_summaries、record_items、categories、store_chains），在 Supabase 里执行后只取聚合结果

- 后端只调用 RPC 或执行聚合查询，拿到结果后直接返回给前端，减少数据传输与 Python 侧计算。

## 涉及代码

- `backend/app/services/database/supabase_client.py`：`get_user_analytics_summary`（约 1748–1891 行）
- 新增：数据库 migration（RPC 或 view/query 定义）

## 何时做

- 当单用户小票数量明显增多、或 Analytics 接口变慢时再实现；当前先保持现状。
