# price_snapshots 刷新说明

## 何时刷新

`price_snapshots` 表**不会自动更新**，需要手动或定时任务触发。

## 刷新方式

### 1. 每日聚合（推荐 cron）

```sql
SELECT aggregate_prices_for_date(CURRENT_DATE);
```

建议设置每日 cron，在凌晨执行。

### 2. 历史回填

```sql
SELECT * FROM backfill_all_price_snapshots();
```

按 `record_summaries.receipt_date` 的日期范围，逐日调用 `aggregate_prices_for_date` 填充历史数据。

### 3. Confirm 后自动刷新（程序内）

在 Admin Confirm classification 成功后，程序会自动调用 `aggregate_prices_for_date(receipt_date)` 刷新该小票对应日期的 price_snapshots，使新回填的 `record_items.product_id` 能立即进入聚合。

## 数据依赖

聚合函数 `aggregate_prices_for_date` 从 `record_items` 读取，需要：

- `record_items.product_id` 非空（Confirm 时会回填）
- `record_summaries.store_location_id` 非空
- `record_summaries.receipt_date` = target_date
- `record_items.unit_price` 非空且 > 0

因此需先完成 classification review 的 Confirm，`record_items` 才有 `product_id`，price_snapshots 才会产生数据。

## 后续优化（待做）

- **定时刷新**：未来可改为每 30–60 分钟跑一次 `aggregate_prices_for_date(CURRENT_DATE)`（或按需刷新最近几天），使价格表更及时；当前不着急实现。
