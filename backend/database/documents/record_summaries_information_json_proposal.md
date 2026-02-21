# record_summaries.information JSON 提案

`information` 存的是「标准化 payload」里**未**在 record_summaries 行中显式拆出的部分，便于前端/API 用同一份结构展示。

## 行中已存在的列（不重复放入 information）

- `receipt_id`, `user_id`, `store_chain_id`, `store_location_id`, `store_name`, `store_address`
- `subtotal`, `tax`, `fees`, `total`, `currency`（均为 int 分）
- `payment_method`, `payment_last4`, `receipt_date`
- `user_note`, `user_tags`, `created_at`, `updated_at`

## 提议的 information 结构

只包含：**Section 2（商品列表）全量** + **other_info**（cashier、会员卡、门店电话、购买时间等）。

```json
{
  "other_info": {
    "cashier": "James C",
    "membership_card": null,
    "merchant_phone": "425-670-0623",
    "purchase_time": "13:00"
  },
  "items": [
    {
      "original_product_name": "CHICKEN FRIED RICE",
      "product_name": "Chicken Fried Rice",
      "quantity": 100,
      "unit": "bag",
      "unit_price": 399,
      "line_total": 399,
      "on_sale": false,
      "original_price": null,
      "discount_amount": null
    }
  ]
}
```

### 字段说明

- **other_info**  
  - `cashier`: 收银员（Trader Joe's 等从 transaction_info 合并；手动修正可从 summary 传入）  
  - `membership_card`: 会员卡号/描述（非标，先存）  
  - `merchant_phone`: 门店电话（Trader Joe's 从 header 提取并合并；手动修正可从 summary 传入）  
  - `purchase_time`: 购买时间 HH:MM 或 HH:MM:SS（从 transaction_info.datetime 拆出或 summary 传入）  
  - 不含 `country`（地址中已有）

- **items**  
  - `original_product_name`: 小票原始品名（OCR/LLM 原文）  
  - `product_name`: 展示用品名：若 products 表有匹配则用 normalized_name 首字母大写，否则用 original_product_name 首字母大写  
  - `unit`: 先取 item 原有 unit，若无则取 products.package_type 或 size_unit  
  - 其余与 record_items 对齐，金额/数量用整型：  
    - `quantity`: 整数，x100（如 1.5 → 150）  
    - `unit_price`, `line_total`, `original_price`, `discount_amount`: 整数，分  
  - `on_sale` 与现有一致。

Section 3（subtotal/tax/fees/total/currency）已在行中，故不再放入 information。

如需要增删字段或改名，可在此文档改一版后再改代码/迁移。
