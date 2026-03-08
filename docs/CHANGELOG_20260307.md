# Changelog — 2026-03-07

今日工作记录（三个 commit：`7295f8f`、`65faf7b`、`d4b0508`）。

---

## Commit 1: fix on a secondary logic (`7295f8f`)

### 后端

- **main.py**：与 secondary / store-specific 逻辑相关的路由或调用调整（9 行变更）。
- **001_schema_v2.sql**：schema 小幅修正（4 行）。

### 数据库迁移

- **056_receipt_status_stage_store_specific.sql**：为 `receipt_status` 的 `current_stage` 增加 `vision_store_specific` 等 store-specific 阶段合法值（26 行新增）。

### 文档

- **CHANGELOG_20260306.md**：补充/修订 3 月 6 日 changelog 内容（约 171 行改写）。

### 前端

- **PublicNav.tsx**：导航或 secondary 相关展示/逻辑调整（30 行）。
- **dashboard/developer/page.tsx**：开发者页与 secondary 逻辑的联动（6 行）。
- **dashboard/page.tsx**：主 dashboard 与 secondary 状态展示（6 行）。

---

## Commit 2: user authorization by level number (`65faf7b`)

### 前端

- **dashboard/developer/page.tsx**：用户权限改为按**等级数字**（`user_class` 整型）做展示与编辑，替代原先的类别标签，便于与后端 `USER_CLASS_*` 一致（5 行净增）。

---

## Commit 3: modify prompts for a better accuracy (`d4b0508`)

### 小票识别与第二轮逻辑

- **第二轮一律带「第一轮 notes + 原图」**  
  Costco、Trader Joe's 的 second round 不再只喂第一轮 JSON，改为**必须**传入原小票图片 + 第一轮结果，方便模型对照图片修正。
  - **receipt_llm_processor.py**  
    - `run_costco_second_round`、`run_trader_joes_second_round` 增加参数：`image_bytes`、`mime_type`。  
    - 当 `image_bytes` 存在且 provider 为 Gemini 时，改用 `parse_receipt_with_gemini_vision_escalation` 做 **vision call**（图片 + system prompt + 第一轮 JSON 拼进 instruction）。  
    - 无图时保留原文字-only 行为（兼容非 vision 调用方）。
  - **workflow_processor_vision.py**  
    - `_run_and_save_costco_second_round`、`_run_and_save_trader_joes_second_round` 增加 `image_bytes`、`mime_type` 并向下传递。  
    - 所有调用处（Costco 两处、Trader Joe's 一处）均传入 `image_bytes=image_bytes, mime_type=mime_type`。

- **沃尔玛第二轮 vision prompt（Migration 060）**  
  - 问题：沃尔玛小票行格式为「商品简称 + UPC 条码 + 价格 + 税标」，通用 primary 常误判为「无明细」并推断成单一 "Item"，sum check 仍过，但商品信息丢失。  
  - 方案：当第一轮 sum check 通过且 `validation_status == "needs_review"` 且识别为 Walmart 时，触发**第二轮 vision 调用**，使用专用 prompt `walmart_second_round`（按 key 从 prompt_library 加载，无 prompt_binding）。  
  - **060_walmart_second_round_prompt.sql**：向 `prompt_library` 插入 `walmart_second_round`（system），内容包含沃尔玛行格式说明（商品简称 / UPC 非数量非价格 / 税标非商品名）、示例（如 `ST -40C`）、排除行规则、加拿大双税、完整输出 schema）。  
  - Python 侧：待实现 `_is_walmart_receipt`、`run_walmart_second_round`（vision）及在 vision workflow 中在 STEP 3A 前根据「sum 过 + needs_review + Walmart」触发并写库（见 060 文件末尾 NOTE）。

### Prompt 入库与 OCR+LLM 下线

- **058_vision_prompts_to_library.sql**  
  - 将 `vision_primary`、`vision_escalation` 从代码常量迁入 `prompt_library`，支持不部署改 prompt。  
  - `vision_escalation` 为 user_template，占位符：`{reference_date}`、`{failure_reason}`、`{primary_notes}`。  
  - 底部保留 OCR+LLM 用 key 的 deactivation 注释块，便于后续一键软删。

- **059_deactivate_ocr_llm_prompts.sql**  
  - 对 OCR+LLM 专用 key（如 `receipt_parse_base`、`receipt_parse_schema`、debug 等）做 `is_active = FALSE` 软删，vision 管线仅使用 `vision_primary`、`vision_escalation` 及 store-specific second round prompts。

- **057_canadian_date_ambiguity_prompt.sql**  
  - 加拿大日期歧义规则写入 prompt 库或相关备注（133 行），与 vision_primary 中加拿大日期逻辑一致。

### 后端架构与废弃

- **workflow_processor.py**  
  - 大幅精简，仅保留 vision 入口转发；原 OCR+LLM 主流程迁至 `backend/deprecated/workflow_processor_legacy_ocr_llm.py`（2662 行）。

- **deprecated/**  
  - **README.md**：说明 deprecated 目录用途及哪些入口已迁移。  
  - **vision_openai_escalation_deprecated.py**：原 vision escalation 中 OpenAI 相关逻辑保留作参考（87 行）。  
  - **workflow_processor_legacy_ocr_llm.py**：原 OCR+LLM 完整 workflow，供 shadow 或回退使用。

- **prompt_loader.py**  
  - 新增或调整从 `prompt_library` 按 key 加载 vision_primary / vision_escalation 的逻辑（约 50 行），与 058 入库一致。

- **prompt_manager.py**  
  - 小改动（1 行），配合 prompt 来源切换。

### 其他后端

- **main.py**：vision 路由或 bulk 入口改为使用新的 workflow/prompt 加载方式（约 124 行变更）。  
- **bulk_processor.py**：与 accuracy 或 prompt 相关的 6 行调整。  
- **rate_limiter.py**：5 行。  
- **jwt_auth.py**：5 行。  
- **supabase_client.py**：与 processing run / receipt status 或 store 匹配相关的 9 行调整。

### 前端

- **admin/layout.tsx**：admin 鉴权或布局 20 行。  
- **dashboard/camera/CameraCaptureButton.tsx**：1 行小改动（如 accuracy 相关文案或传参）。

---

## 今日 Diff 统计摘要

| Commit     | 说明                         | 涉及文件数 | 行数变化（约） |
|-----------|------------------------------|------------|----------------|
| 7295f8f   | fix on a secondary logic     | 7          | +192 / -60     |
| 65faf7b   | user authorization by level  | 1          | +5 / -5        |
| d4b0508   | modify prompts for accuracy  | 19         | +4324 / -3508  |

**合计**：3 个 commit，多份迁移与核心 vision/second-round 逻辑调整；第二轮 Costco/TJ 已统一为「图片 + 第一轮 notes」，沃尔玛第二轮 prompt 已入库，待 Python 触发与调用。
