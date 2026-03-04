# LedgerLens A/B Test TODO（A=现有流程，B=Vision First）

**日期**: 2026-03-03  
**状态**: Draft（今天不改代码，明早开始实现）  
**目标**: 验证「简化流程 B（Vision First + 双强模型兜底）」是否在**准确率、成本、处理时长、可维护性**上优于现有流程 A。

---

## 1) 业务目标（人和 AI 都要懂）

当前痛点：
- OCR 额外引入噪声（漏行、错配金额、错店名），后续 LLM 再纠错成本高。
- 多阶段链路复杂，debug 成本高。
- 传大段 OCR JSON 可能比直接传图更贵。

A/B 核心假设：
- **H1 准确率**：B 流程在复杂小票上 needs_review 误判率更低。
- **H2 成本**：B 流程平均 token/请求成本不高于 A（或在同等准确率下更低）。
- **H3 时延**：B 流程 P50/P95 耗时不劣于 A 太多（可接受阈值见验收标准）。
- **H4 可维护性**：B 流程更少分支、更易定位问题（通过 debug 面板验证）。

---

## 2) A/B 流程定义

### A 流程（现有）
- 上传图片 -> rate limiter/security/validation -> OCR + 规则清洗 + LLM 结构化 + sum check + fallback/escalation（按现有实现）。

### B 流程（Vision First，目标流程）
- 上传图片 -> rate limiter/security/validation  
- 直接调用 Vision 模型（Gemini，主模型）输出结构化 JSON  
- 结构校验 + 数学校验：
  - 若有 `Item count: N`，做 item count check（解析 item 数需 >= N）
  - 若无 item count，做 sum check（3 分或 1%）
- 通过 -> success（后续入库/categorization 与现有一致）
- 不通过 -> escalation：
  - 把「原图 + 首轮 LLM comments/失败原因」分别发给 **Gemini 3.0 Pro** 与 **OpenAI 5.1**
  - 两模型各生成 JSON
  - 若关键字段/行项可对齐一致 -> success
  - 若不一致 -> needs_review；一致部分预填，不一致字段/行高亮给用户修正

---

## 3) A/B 实验设计

### 3.1 分流策略
- 新增实验开关：`RECEIPT_PIPELINE_EXPERIMENT=off|shadow|ab`
- 新增分流比例：`RECEIPT_PIPELINE_B_RATIO=0~100`
- 分流键：`hash(user_id + receipt_id)` 保证稳定分流
- 模式：
  - `off`: 全走 A
  - `shadow`: 前端/用户结果仍用 A；后台异步再跑一遍 B（仅用于比较）
  - `ab`: 按比例真实分流 A/B，用户看到对应结果

### 3.2 先做 Shadow（推荐）
- 阶段 1（建议 3-7 天）：`shadow`，不影响用户结果，专注对比数据。
- 阶段 2：小流量 `ab`（如 10%-20% B）。
- 阶段 3：B 扩容（50%+）或全量切换；A 进入 deprecate 计划。

---

## 4) 后端 TODO（按优先级）

## P0（必须）
- [ ] 增加实验配置读取（off/shadow/ab、B 比例、模型名）
- [ ] workflow 增加 B 主流程入口（Vision First）
- [ ] 保留 A 原流程不动（可并行执行）
- [ ] `shadow` 模式下：A 出用户结果，B 后台跑并落库
- [ ] B 流程首轮失败时接入双模型 escalation（Gemini 3.0 Pro + OpenAI 5.1）
- [ ] 一致性判定规则落地（关键字段、行项、sum/item_count）
- [ ] 结果融合策略（一致部分采纳，不一致部分标记）
- [ ] needs_review 输出包含高亮字段列表（供前端渲染）

## P1（强烈建议）
- [ ] 统一记录 A/B 全链路 run 数据（含输入摘要、输出、错误、阶段耗时）
- [ ] 记录每次模型调用 token（input/output）和估算成本
- [ ] 记录处理总时长与阶段时长（P50/P95）
- [ ] 增加 A/B diff 计算（summary/items/payment/date/store 等）

## P2（可后补）
- [ ] 管理端支持按日期/用户/商家筛选 A/B 差异
- [ ] 差异聚类（常见失败模式：漏行、金额串行、店名错）
- [ ] 自动生成日报（准确率、cost、latency、needs_review 率）

---

## 5) 前端 TODO

## P0（必须）
- [ ] needs_review 页面支持「预填 + 高亮冲突字段」
- [ ] 冲突展示最小集：`merchant_name/subtotal/tax/total/payment/date/time/items[*]`
- [ ] items 冲突支持逐行高亮（缺失行、金额不一致、数量不一致）

## P1（管理端）
- [ ] 新增 Admin Debug 页面（或区块）：
  - 左侧 A 结果，右侧 B 结果（side-by-side）
  - 中间显示 diff（字段级 + 行项级）
  - 显示 A/B 各自总耗时、每阶段耗时、token in/out、估算成本
  - 可查看原图与 processing runs 原始 payload（脱敏）

---

## 6) 数据与埋点规范（关键）

每条 receipt 至少记录：
- `experiment_mode`: off/shadow/ab
- `experiment_bucket`: A/B
- `pipeline_version`: legacy_a / vision_first_b
- `final_status`: success/needs_review/failed
- `duration_ms_total`
- `duration_ms_by_stage`（json）
- `token_input_total` / `token_output_total`
- `estimated_cost_total_usd`
- `escalated`: true/false
- `escalation_reason`
- `diff_summary`（A vs B 差异摘要，shadow/ab 对比时）

每次模型调用记录：
- provider/model/stage
- token_in/token_out（如厂商无原生 token，记录估算方法）
- latency_ms
- request/response payload（必要脱敏）
- 校验结果（schema/sum/item_count/pass_fail）

---

## 7) 一致性与高亮规则（B escalation 后）

关键字段一致（必须一致或在容差内）：
- total/subtotal/tax/currency/date/time/payment/card_last4/store

items 对齐策略（建议）：
- 先按 `line_total` + 归一化 `product_name` 粗匹配
- 再按 `quantity/unit_price` 二次确认
- 无法匹配的行标记为：
  - `missing_in_model_x`
  - `value_conflict`
  - `name_conflict`

最终给前端的数据：
- `resolved_json`（一致部分）
- `conflicts[]`（每个冲突包含字段路径、A值、B值、推荐值、原因）

---

## 8) 验收标准（明确定义 Done）

功能验收：
- [ ] off/shadow/ab 三模式可切换，行为符合预期
- [ ] shadow 模式下用户结果不受影响，但后台有 A/B 可比结果
- [ ] B 首轮失败可稳定触发双模型 escalation
- [ ] needs_review 可展示并高亮冲突字段/行项

质量验收（建议门槛，先作为目标）：
- [ ] B 的 success 后人工回查错误率 <= A
- [ ] B 的 needs_review 漏判率 < A（重点看漏行/金额串行）
- [ ] B 平均成本不高于 A * 1.15（或准确率显著提升可放宽）
- [ ] B P95 总时长不高于 A * 1.3（可按业务接受度调整）

---

## 9) 风险与回滚

主要风险：
- Vision 直读在某些票据类型上不稳定
- 双模型对齐逻辑复杂，可能产生误高亮
- token/成本统计口径不一致

回滚策略：
- 任何时候可切回 `off`（全 A）
- `shadow` 先行，确保无用户面风险
- 保留 A 全链路一段时间，待指标稳定再 deprecate

---

## 10) 明早开工执行清单（按顺序）

Day 1（建议）：
- [ ] 加配置开关 + 分流器（off/shadow/ab）
- [ ] 抽象统一 pipeline 接口（A/B 都实现）
- [ ] 接入 B 首轮 Vision（Gemini）
- [ ] 接入 B 校验（schema + item_count/sum）
- [ ] 打通 B 基础落库与 run 记录

Day 2：
- [ ] 接入 B escalation（Gemini 3.0 Pro + OpenAI 5.1）
- [ ] 实现一致性融合 + conflicts 输出
- [ ] needs_review 预填/高亮协议定稿

Day 3：
- [ ] Admin side-by-side debug 页面
- [ ] A/B 时延、token、成本统计看板
- [ ] 小流量 shadow 运行与首轮复盘

---

## 11) 给 AI 的“开动指令”模板（明天直接复制）

> 开动：按 `backend/agent-tbd/TBD-AB_TEST_VISION_FIRST_PIPELINE_20260303.md` 实现 P0。  
> 要求：  
> 1) 先做 `shadow` 模式，不影响现网用户结果；  
> 2) A 流程保持兼容，B 流程走 Vision First；  
> 3) 完整记录 A/B 每阶段耗时、token in/out、成本估算；  
> 4) 输出 admin side-by-side diff 所需数据结构；  
> 5) 每完成一个子任务就跑一次相关测试并更新文档进度。  

---

## 12) 非目标（本轮不做）

- 不在今天直接改线上逻辑
- 不在本轮完成所有 UI 美化
- 不在本轮做复杂自动纠错（先做可解释的高亮 + 人工修正）

