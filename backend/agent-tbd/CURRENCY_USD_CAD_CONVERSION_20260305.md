# 小票货币 USD/CAD 换算与展示需求

**日期**: 2026-03-05  
**状态**: 需求草稿，待评审  
**范围**: 用户级显示货币、小票货币区分、总和统计换算、每日汇率 API

---

## 1. 目标

- 小票按 **USD** 和 **CAD** 能正确区分并做换算。
- 用户可在 **用户级** 设置「显示货币」为 USD 或 CAD。
- 当用户选择 USD 时，CAD 小票内的金额展示需带 **CA$** 前缀，避免与美元混淆。
- **总和统计**（Dashboard 等）需统一换算到用户偏好货币（除以/乘以 conversion rate）。
- 需接入 **每日汇率 API** 提供 USD↔CAD 的 conversion rate。

---

## 2. 现状简要

- **小票/汇总层**：`record_summaries.currency` 已存在（TEXT，默认 `'USD'`），解析与部分 processor 已支持 USD/CAD（如 Costco US/CA、prompt_library schema）。
- **用户层**：当前 **没有** 用户级「显示货币」或「偏好货币」字段。
- **汇率**：当前 **没有** 汇率数据源或表结构，总和统计未做跨币种换算。

---

## 3. 需求明细

### 3.1 用户级显示货币 (User-level display currency)

- **存储**：在用户维度增加「显示货币」设置，可选值：`USD` | `CAD`。
- **实现方式**（待定）：
  - 方案 A：`users` 表新增列，如 `display_currency TEXT DEFAULT 'USD' CHECK (display_currency IN ('USD', 'CAD'))`。
  - 方案 B：独立 `user_preferences` 表，键值或 JSONB 存 `display_currency`，便于后续扩展其他偏好。
- **前端**：设置页/账户页提供「显示货币」选项，并写回后端；后端读取该设置用于所有金额展示与汇总换算。

### 3.2 小票按 USD/CAD 区分，CAD 金额带 CA$ 前缀

- **数据**：小票货币已由 `record_summaries.currency`（及上游解析）得到，需保证 Vision/LLM 与各 processor 正确写入 `USD` 或 `CAD`。
- **展示规则**：
  - 用户显示货币 = **USD** 时：
    - 小票为 **CAD** 的行项/小计/总价：展示时加 **CA$** 前缀（如 `CA$ 12.99`）。
    - 小票为 USD 的：可继续用 `$` 或统一为 `US$`（产品决策可再定）。
  - 用户显示货币 = **CAD** 时：
    - 小票为 **USD** 的金额：建议加 **US$** 前缀；CAD 用 `$` 或 `CA$` 视产品统一。
- **实现层级**：可在后端 API 返回金额时附带「是否 CAD」或「展示前缀」，或由前端根据 `record_summaries.currency` + 用户 `display_currency` 决定前缀。

### 3.3 总和统计按用户偏好货币换算

- **场景**：Dashboard、报表、分类汇总等「总和」类统计可能混合多张 USD 与 CAD 小票。
- **规则**：所有参与总和的钱，先按小票日期（或交易日期）换算到用户偏好货币，再相加。
- **换算**：  
  - 用户偏好 **USD**：CAD 金额 ÷ (CAD/USD rate) 或 × (USD/CAD rate)，得到 USD 后加总。  
  - 用户偏好 **CAD**：USD 金额 × (CAD/USD rate)，得到 CAD 后加总。  
- **汇率取值**：建议按 **小票日期** 的日汇率（见 3.4）查表或 API，避免用「当前汇率」导致历史数据失真。

### 3.4 每日汇率 API 与 conversion rate 存储

- **需求**：需要 **每日** USD↔CAD 的汇率，用于历史小票的换算与总和统计。
- **可选方案**：
  - 接入第三方 **Daily Exchange Rate API**（如央行、Open Exchange Rates、Exchangerate-api 等），按日拉取并落库。
  - 本地建表存储「日期 + 基准货币 + 目标货币 + rate」，例如：  
    `(date, from_currency, to_currency, rate)`，如 `(2026-03-05, 'CAD', 'USD', 0.74)`。
  - 后台定时任务（日跑一次或按需）拉取当日汇率并写入；查询时按 `receipt_date` 取对应日期的 rate。
- **降级**：若某日无汇率（API 缺失或未跑），可约定用最近一日已有汇率或固定 fallback rate，并在文档/日志中说明。

---

## 4. Todo 清单（与实现对应）

| # | 项 | 说明 |
|---|----|------|
| 1 | 用户级货币偏好 (USD/CAD) | 存储与设置：DB 迁移 + API + 前端设置页 |
| 2 | 小票按 USD/CAD 区分，CAD 显示 CA$ | 展示逻辑：当用户为 USD 时，CAD 小票金额加 CA$ 前缀 |
| 3 | 每日汇率 API | 接入并落库；定时任务 + 表结构 |
| 4 | 总和统计换算 | Dashboard/报表等总和按用户偏好货币换算（使用 3 的 rate） |

---

## 5. 后续可补充

- 具体选用哪家汇率 API、限流与成本。
- `users` 与 `user_preferences` 的选型结论。
- 前端展示规范：US$ / CA$ / $ 的统一用法。
- 历史数据 backfill：若此前部分小票未写 `currency`，是否按门店/国家推断并 backfill。
