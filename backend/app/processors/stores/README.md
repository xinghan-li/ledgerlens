# Store Processors

门店/连锁店专用处理器。**统一逻辑：OCR blocks → rule-based 提取（不依赖 LLM）**。

**输出结构**：所有 processor 须遵循 `backend/config/PIPELINE_OUTPUT_STANDARD.md` 定义的统一 JSON 结构（上：洗好的数据；下：`ocr_blocks` 原 OCR 坐标信息）。

## 结构

```
stores/
├── costco_ca/           # Costco Canada
│   └── digital/         # 电子小票
├── costco_us/           # Costco US
│   └── physical/        # 实体小票
├── tnt_supermarket/     # T&T 超市 (US + Canada)
└── README.md
```

## 流程

主流程：**OCR → 拿到 blocks → rule-based 提取 → 校验**

- **Costco CA digital**：专用 processor（layout: costco_ca_digital），blocks → items/totals
- **Costco US physical**：专用 processor（layout: costco_us_physical），blocks → items/totals
- **T&T**：专用 processor（chain_id: tnt_supermarket_us / tnt_supermarket_ca），走通用 validation pipeline + store_config，与 Costco 同级路由

全部在 LLM 之前完成，先尝试纯 rule-based 能否解析正确。

## T&T 补充说明

- **路由**：`process_receipt_pipeline` 根据 `store_config.chain_id in ("tnt_supermarket_us", "tnt_supermarket_ca")` 走 T&T 专用入口 `process_tnt_supermarket`，内部调用通用 validation pipeline（region_splitter、item_extractor、totals 等）并带上 T&T 的 store_config。
- **clean_tnt_receipt_items**：仅用于仍走 LLM 的 workflow 路径，做会员卡/积分行清洗。

## Config

- `costco_canada_digital.json` → layout: costco_ca_digital
- `costco_usa_physical.json` → layout: costco_us_physical
- `tnt_supermarket_us.json` / `tnt_supermarket_ca.json` → 路由按 chain_id（tnt_supermarket_us / tnt_supermarket_ca）走 T&T 专用 processor
