# Pipeline 输出结构标准

所有 store processor（Costco、T&T、未来新增）必须遵循统一的 JSON 输出结构，便于标准化和后续开发。

## 整体结构

```json
{
  "【上：洗好的数据】": "success / method / chain_id / store / items / totals / validation 等",
  "【下：原 OCR】": "ocr_blocks — 原始 OCR blocks，保留每个字段的 x/y 坐标"
}
```

- **上半部分**：洗好的提取结果，无论 `success` 为 true 还是 false，结构一致
- **下半部分**：原 OCR 的所有有用信息，保留完整坐标（x, y, center_x, center_y, width, height 等），参照 T&T 的 blocks 结构

---

## 一、洗好的数据（Washed / Extracted）

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 校验是否通过 |
| `method` | string | 处理器标识：`costco_ca_digital` / `costco_us` / `tnt_supermarket_us` / `tnt_supermarket_ca` / `pipeline` |
| `chain_id` | string | 商店 chain_id |
| `store` | string | 门店名称 |
| `address` | string \| null | 地址（如有） |
| `currency` | string | 币种（如有） |
| `membership` | string \| null | 会员号（如有） |
| `error_log` | string[] | 处理过程中的错误/警告 |
| `items` | array | 提取的商品列表 |
| `totals` | object | subtotal, tax, fees, total |
| `validation` | object | 校验详情（items_sum_check, totals_sum_check, passed） |
| `regions_y_bounds` | object | 各 section 的 Y 范围（header/items/totals/payment） |
| `amount_column` | object | 金额列 X 坐标（main_x, tolerance） |
| `ocr_and_regions` | object | 分区后的 rows 详情（section_rows_detail） |

---

## 二、原 OCR 信息（ocr_blocks）

**必须包含**：`ocr_blocks` 数组，每个元素为原始 OCR 的一个 block，保留完整坐标信息。

### Block 结构（参照 T&T / example_tnt.json）

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | 识别文本 |
| `x` | number | 左上角 x（归一化 0–1 或原始值） |
| `y` | number | 左上角 y |
| `center_x` | number | 中心点 x |
| `center_y` | number | 中心点 y |
| `width` | number | 宽度（可选） |
| `height` | number | 高度（可选） |
| `is_amount` | boolean | 是否为金额块（可能由 pipeline 标记） |
| `amount` | number \| null | 解析出的金额（如有） |
| `confidence` | number | OCR 置信度（可选） |
| `page_number` | number | 多页时页码（可选） |

**原则**：不做裁剪或聚合，直接透传 OCR 输出，保证未来做 special processor 时能拿到完整原始信息。

### 数值精度（ocr_blocks 内）

坐标、宽高、置信度等浮点数字段**统一保留 5 位小数**，避免冗长精度（如 0.35078126192092896）影响可读性和体积：

- `x`, `y`, `center_x`, `center_y`, `width`, `height` → `round(v, 5)`
- `confidence` → `round(v, 5)`
- `amount` → 金额保持 2 位小数（如 13.99），不截断

透传 OCR blocks 时应对上述字段做精度规整，再写入 `ocr_blocks`。

---

## 三、完整示例（精简）

```json
{
  "success": true,
  "method": "tnt_supermarket_us",
  "chain_id": "tnt_supermarket_us",
  "store": "T&T Supermarket US",
  "address": null,
  "membership": null,
  "error_log": [],
  "items": [
    {
      "product_name": "HOT FOOD BY WEIGHT",
      "line_total": 1399,
      "quantity": 127,
      "unit": "1/100 lb",
      "unit_price": 1099,
      "on_sale": false
    }
  ],
  "totals": { "subtotal": 20.49, "tax": [], "fees": [], "total": 20.49 },
  "validation": { "items_sum_check": {...}, "totals_sum_check": {...}, "passed": true },
  "regions_y_bounds": { "header": [...], "items": [...], "totals": [...], "payment": [...] },
  "amount_column": { "main_x": 6300, "tolerance": 500 },
  "ocr_and_regions": {
    "section_rows_detail": [
      { "section": "header", "label": "Store info", "rows": [...] },
      { "section": "items", "label": "Items", "rows": [...] },
      { "section": "totals", "label": "Totals", "rows": [...] },
      { "section": "payment", "label": "Payment & below", "rows": [...] }
    ]
  },
  "ocr_blocks": [
    {
      "text": "T&T Supermarket US",
      "x": 0.523,
      "y": 0.1497,
      "center_x": 0.523,
      "center_y": 0.1497,
      "width": 0.15,
      "height": 0.012,
      "is_amount": false,
      "amount": null
    },
    {
      "text": "P $13.99 T",
      "x": 0.6336,
      "y": 0.2273,
      "center_x": 0.6336,
      "center_y": 0.2273,
      "width": 0.08,
      "height": 0.01,
      "is_amount": true,
      "amount": 13.99
    }
  ]
}
```

---

## 四、新增 Processor 检查清单

新增 dedicated processor 时，确保：

1. 上半部分：返回 `success`、`method`、`chain_id`、`items`、`totals`、`validation`、`error_log` 等
2. 下半部分：**必须**在结果中包含 `"ocr_blocks": blocks`（传入的原始 blocks 透传）
3. `ocr_blocks` 不做修改，保留 OCR 输出的原始结构
