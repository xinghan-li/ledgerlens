# backend/agent-tbd 与 docs 摘要（2026-03-05）

本文档汇总 `backend/agent-tbd/` 下所有文件的内容与状态，并标出**已过时**的文档及原因；同时简要覆盖 `docs/` 内容。

**归档已执行（2026-03-05）**：上述「已过时 / 已实现」的 11 份文档已移入 `backend/agent-tbd/archived/`，每份在**文件顶部**增加了 1～2 行「结论（归档原因）」；**架构上需要长期保留的决策**（Sum Check 容差、validation_status、item count、规则清洗、认证、分类匹配分工）已写入 **`docs/architecture/RECEIPT_VALIDATION_AND_AUTH_DECISIONS.md`**，供后续 LLM/开发直接查阅。当前 **agent-tbd 根目录只保留真正 TBD 与仍适用的说明/清单**（见文末「当前根目录保留文件」）。

---

## 一、agent-tbd 文件总览（按主题）

### 1. 需求 / 设计（未实现或进行中）

| 文件 | 内容摘要 | 状态 |
|------|----------|------|
| **CURRENCY_USD_CAD_CONVERSION_20260305.md** | 用户级显示货币(USD/CAD)、小票货币区分、总和统计换算、每日汇率 API | 需求草稿，待评审 |
| **CARD_NICKNAME_AND_PAYMENT_AGGREGATION_20260305.md** | 用户级卡 nickname、按 nickname 聚合统计 | 未来需求，待排期 |
| **VISION_PIPELINE_PROMPTS_DRAFT_20260303.md** | Vision-First 主轮 + Escalation 的 prompt 与 JSON schema 设计 | 设计草稿，已用于/可对照现有 Vision 流程 |
| **TBD-AB_TEST_VISION_FIRST_PIPELINE_20260303.md** | A/B 实验设计：A=现有流程，B=Vision First；shadow/ab 分流、双模型 escalation | 若 Vision 已为主流程，则从「实验设计」变为参考；实验开关/分流可能仍有用 |
| **ESCALATE_STRONGEST_MODELS_DESIGN.md** | OCR+LLM 双 needs_review 时用原图 + 双强模型共识 | 设计已落地到 `workflow_processor_vision` escalation |
| **TBD-OCR_CORRECTION_AND_MATCHING_TODO.md** | OCR 纠错（词库+字符映射）、categorizer 前增加纠错层；截断匹配已实现 | 截断完成；OCR 纠错 TBD，实施时按此 doc |
| **TBD-ANALYTICS_SUMMARY_DB_AGGREGATION.md** | 将 by_store/by_payment/by_category 聚合下推到 DB RPC | 未来再做，当前不改 |
| **TBD-BACKLOG_RECORD_ITEMS_BACKFILL_20260217.md** | record_items 空 category_id/product_id 按同小票同商品名回填 | 待实现，优先级中 |
| **ANALYSIS-RECEIPT_VS_FACT_SEPARATION_ANALYSIS_20260217.md** | 小票层 vs Fact 层分离、删除小票不删 products/stores | 分析/设计参考 |
| **ANALYSIS-CATEGORIZATION_API_GAP_20260212.md** | Categorization API 实际行为 vs 设想（未用 _metadata、未用规则表等） | 若已改 API 用 _metadata+规则则过时；否则仍为 gap 参考 |

### 2. 实现说明 / 检查清单（仍有用）

| 文件 | 内容摘要 | 状态 |
|------|----------|------|
| **STORE_ADDRESS_SUITE_UNIT_MATCHING_20260305.md** | Suite/Unit 地址归一化：方案一已实现，方案二/三为可选增强 | 当前实现说明，未过时 |
| **TNT_STORE_CHAIN_MERGE_BACKEND_CHECK_20260305.md** | T&T 合并为一条 chain 后的后端逻辑检查与数据扫描 SQL | 操作/检查清单，未过时 |
| **REVIEW_FEEDBACK_AND_ESCALATION_20260304.md** | Review Feedback 展示、42.90 vs 47.90 根因、Escalation 需配置 GEMINI_ESCALATION_MODEL/OPENAI_ESCALATION_MODEL | 实现与排障说明，未过时 |
| **STORE_MATCH_TOTEM_LAKE_VS_LYNNWOOD_20260220.md** | 无匹配不落店、进 store_candidates；仅地址匹配、不按店名 fallback | 正确逻辑说明，未过时 |
| **FIREBASE_AUTH_MIGRATION.md** | Supabase Auth → Firebase Auth 迁移步骤与配置 | 若已完成迁移，为已完成操作说明；仍可作运维参考 |
| **alignment-left-right-heights.md** | 左侧/右侧「顶→分割线」高度清单（Tailwind），Category 行对齐 | UI 实现细节，若布局已定可归档 |

### 3. 历史诊断 / 已修复问题（可标为过时）

| 文件 | 内容摘要 | 为何过时 |
|------|----------|----------|
| **RECEIPT_TNT_20260304_OCR_AND_SUCCESS_DIAGNOSIS.md** | 某张 T&T 小票误判 success 的根因：容差 3 分或 1%、LLM validation_status 纳入决策、item count check | **已实现**：sum check 容差、validation_status、item count 均已按文档修复 |
| **ANALYSIS-DEBUG_LOGIC_DIAGNOSIS.md** | DELI/$4.99 归属、GYG/$20.53 误匹配、section header+金额、仅金额行处理 | **已实施修复**：逻辑修正已落地，为历史诊断 |
| **ANALYSIS-DEBUG_121422_DIAGNOSIS.md** | 121422 小票：重量 26800、GYG line_total、AFC 重复、/lb strip | **部分已修复**：文档内标明已修复项，属单次 debug 记录 |
| **ANALYSIS-CLASSIFICATION_REVIEW_IMPLEMENTATION_SUMMARY_20260217.md** | Classification Review 表、API、前端、CRUD+Confirm 完整实施总结 | **已实现**：功能已上线，保留作实施参考即可，可视为「已完成」 |
| **ANALYSIS-CLASSIFICATION_REVIEW_UPDATES_20260217.md** | Category 三列、LLM 预填、status 下拉、size/unit、confirmed_at/by | **已实现**：与上一条一致 |
| **ANALYSIS-CONFIRM_FLOW_AND_SIZE_DESIGN_20260217.md** | Confirm 数据流、size_quantity/size_unit/package_type 设计；Migration 027 | **已实现**：Confirm 与 size 设计已落地 |

### 4. 已完成的 PR/分析（可标为过时）

| 文件 | 内容摘要 | 为何过时 |
|------|----------|----------|
| **TBD-PR_PROMPT_LIBRARY_REFACTOR_20260212.md** | 用 prompt_library + prompt_binding 替代 tag-based RAG；023 migration、prompt_loader、删 RAG | **已实现**：023 已存在，prompt_library/prompt_binding 在用，RAG 已移除 |
| **ANALYSIS-FILE_CLEANUP_REPORT_20260212.md** | 根目录/backend 文件清理建议：删、移至 docs/、移至 agent-tbd | **已执行**：DEBUG_* 等已进 agent-tbd，建议的目录与移动已做，清单可视为完成 |
| **ANALYSIS-BACKEND_SCRIPTS_ANALYSIS_20260212.md** | 脚本分类：tools/diagnostic/test/maintenance，移动与 README | **已实现**：`backend/scripts/` 下已有 tools/、diagnostic/、test/、maintenance/ 及 README |
| **ANALYSIS-RULE_BASED_PIPELINE_IN_FLOW_20260219.md** | Rule-based 清洗在流程中的位置、LLM input 是否带 initial_parse | 若已在 LLM input_payload 中带 initial_parse_summary，则建议已落实；否则仍为待办参考 |

### 5. 认证与登录（部分过时）

| 文件 | 内容摘要 | 为何过时 / 注意 |
|------|----------|------------------|
| **MAGIC_LINK_REFRESH_LOGIN_AND_SECURITY.md** | Supabase Magic Link、Redirect URLs、OTP 一次性、过期时间 | **已过时**：当前认证已迁至 **Firebase**（见 FIREBASE_AUTH_MIGRATION），登录流程与 Supabase OTP/Magic Link 不同，本文档针对旧方案 |

---

## 二、已过时文件汇总与原因

| 文件 | 原因 |
|------|------|
| **MAGIC_LINK_REFRESH_LOGIN_AND_SECURITY.md** | 新流程不需要：已改用 **Firebase Auth**，不再使用 Supabase Magic Link/OTP。 |
| **TBD-PR_PROMPT_LIBRARY_REFACTOR_20260212.md** | 已实现：023、prompt_loader、prompt_library/prompt_binding 已上线，RAG 已删。 |
| **ANALYSIS-FILE_CLEANUP_REPORT_20260212.md** | 已实现：清理与移动建议已执行。 |
| **ANALYSIS-BACKEND_SCRIPTS_ANALYSIS_20260212.md** | 已实现：脚本已按建议重组到 scripts/tools、diagnostic、test、maintenance。 |
| **RECEIPT_TNT_20260304_OCR_AND_SUCCESS_DIAGNOSIS.md** | 已实现：容差、validation_status、item count check 等修复已落地。 |
| **ANALYSIS-DEBUG_LOGIC_DIAGNOSIS.md** | 已实现：section header+金额、仅金额行等逻辑修复已实施。 |
| **ANALYSIS-DEBUG_121422_DIAGNOSIS.md** | 已实现：单次小票 debug，文中标注的修复已完成。 |
| **ANALYSIS-CLASSIFICATION_REVIEW_IMPLEMENTATION_SUMMARY_20260217.md** | 已实现：Classification Review 功能已完整上线。 |
| **ANALYSIS-CLASSIFICATION_REVIEW_UPDATES_20260217.md** | 已实现：表格与字段更新已落地。 |
| **ANALYSIS-CONFIRM_FLOW_AND_SIZE_DESIGN_20260217.md** | 已实现：Confirm 流与 size 设计已实现。 |
| **MATCHING_DB_VS_BACKEND.md** | 部分过时：当前 `docs/categorization-matching.md` 写明 **find_categorization_rule RPC 已废弃，匹配逻辑已迁移到后端**；本文档描述的是「DB RPC + 后端 prefix」的旧分工，与现状不完全一致。 |

其余 agent-tbd 文件要么是**未实现/待排期需求**，要么是**仍适用的设计或检查清单**，不视为过时。

---

## 三、docs/ 简要

| 文件 | 内容 |
|------|------|
| **docs/architecture/RECEIPT_WORKFLOW_CASCADE.md** | 小票处理全流程（含 Vision、Escalation、store_candidates）、各阶段输入输出、TODO（弹窗确认、一振三振、OCR 后地址校正等）。与当前 Vision 流程一致，未过时。 |
| **docs/architecture/RATE_LIMITER.md** | 限流实现（滑动窗口、admin 豁免、429 格式）。未过时。 |
| **docs/architecture/CATEGORIZATION.md** | Categorization 与 OCR/LLM 解耦、只处理 success、可重试。未过时。 |
| **docs/categorization-matching.md** | 分类匹配全部在后端：exact 查表、universal fuzzy（CSV 源）、DB find_categorization_rule RPC 已废弃。未过时。 |
| **docs/PRODUCTION_CHECKLIST.md** | 上生产前 CORS、HTTPS、敏感配置、限流等检查项。未过时。 |
| **docs/frontend/IMPLEMENTATION_SUMMARY.md** | 前端技术栈、Magic Link、Dashboard、上传等；若已全面改用 Firebase，文中 Supabase Auth 部分为旧实现，其余仍有效。 |

**docs 结论**：无整份文档需要标为「已过时」；仅 `docs/frontend/IMPLEMENTATION_SUMMARY.md` 中 Supabase Auth 相关描述与当前 Firebase 迁移后不一致，可后续在文档中注明「认证见 Firebase 迁移说明」。

---

## 四、已执行操作（2026-03-05）

1. **过时/已实现文档**：已移入 `backend/agent-tbd/archived/`，每份顶部已加「结论（归档原因）」一行。  
2. **架构文档**：`docs/architecture/RECEIPT_VALIDATION_AND_AUTH_DECISIONS.md` 已创建，汇总小票校验、认证、分类匹配等关键决策，供未来 LLM/开发直接读。  
3. **agent-tbd 根目录**：仅保留真正 TBD 与仍适用的说明/清单（见下）。

---

## 五、当前根目录保留文件（仅 TBD 与适用说明）

| 文件 | 性质 |
|------|------|
| **AGENT_TBD_SUMMARY_20260305.md** | 本摘要 |
| **CURRENCY_USD_CAD_CONVERSION_20260305.md** | 需求草稿，待评审 |
| **CARD_NICKNAME_AND_PAYMENT_AGGREGATION_20260305.md** | 未来需求，待排期 |
| **VISION_PIPELINE_PROMPTS_DRAFT_20260303.md** | 设计草稿，可对照 Vision 流程 |
| **TBD-AB_TEST_VISION_FIRST_PIPELINE_20260303.md** | A/B 实验设计 / 参考 |
| **TBD-OCR_CORRECTION_AND_MATCHING_TODO.md** | OCR 纠错 TODO，实施时按此执行 |
| **TBD-ANALYTICS_SUMMARY_DB_AGGREGATION.md** | 未来再做 |
| **TBD-BACKLOG_RECORD_ITEMS_BACKFILL_20260217.md** | 待实现 backfill |
| **ESCALATE_STRONGEST_MODELS_DESIGN.md** | 设计已落地，保留作参考 |
| **STORE_ADDRESS_SUITE_UNIT_MATCHING_20260305.md** | 方案一已实现，方案二/三可选 |
| **TNT_STORE_CHAIN_MERGE_BACKEND_CHECK_20260305.md** | 操作/检查清单 |
| **REVIEW_FEEDBACK_AND_ESCALATION_20260304.md** | 实现与排障说明 |
| **STORE_MATCH_TOTEM_LAKE_VS_LYNNWOOD_20260220.md** | 正确逻辑说明 |
| **FIREBASE_AUTH_MIGRATION.md** | 迁移步骤与配置，运维参考 |
| **alignment-left-right-heights.md** | UI 对齐实现细节 |
| **ANALYSIS-RECEIPT_VS_FACT_SEPARATION_ANALYSIS_20260217.md** | 分析/设计参考 |
| **ANALYSIS-RULE_BASED_PIPELINE_IN_FLOW_20260219.md** | 流程位置参考 |
| **ANALYSIS-CATEGORIZATION_API_GAP_20260212.md** | Gap 参考（若未改 API 仍适用） |
