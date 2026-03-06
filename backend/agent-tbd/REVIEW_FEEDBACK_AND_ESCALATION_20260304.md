# Review Feedback 展示与 Escalation 说明（2026-03-04）

## 1. 前端已做修改

- **标题**：统一为 "Review Feedback"（F 大写）。
- **内容**：不再重复显示与 reasoning 重复的那两行总结；只展示：
  - **Reasoning**（模型自报的推理）
  - **Sum check**（仅当与 reasoning 不同时显示）
  - **Item count**（receipt says / extracted）
- **已隐藏**：Validation、Confidence 两行不再展示。

若无 `review_metadata`，则回退显示原来的 `review_feedback` 一段文案。

---

## 2. 为什么 LLM 说 42.90 而界面上加起来是 47.90？

- **42.90** 来自**模型自报**：Vision 模型在 `_metadata.reasoning` / `_metadata.sum_check_notes` 里写的是 “Sum of extracted items ($42.90)”。
- **47.90** 是**当前展示的 9 条 line item 的金额之和**，数据来自已落库的 `record_items`（即当时解析结果里各商品的 `line_total`）。

因此有两种可能：

1. **模型自算错了**：模型在写 reasoning 时自己加总错了（例如漏加、单位搞错、或按错误字段算），所以报 42.90；而实际输出的 `items[].line_total` 加起来是 47.90，后端 sum_check 可能用的是后者。
2. **后端 sum check 用的和展示的不一致**：若当时落库的 `record_items` 与模型当轮输出的 `items` 不一致（例如有清洗、合并、舍入），也可能出现“模型说 42.90、后端用一套数、前端展示另一套数”的情况。

**根因已确认（2026-03-04）**：用户提供了该小票的 output payload，items 的 `line_total` 均为**分**，之和 = 4790 分 = $47.90，tax=180 分，total=4970 分，即 47.90+1.80=49.70，数学完全正确。42.90 是**模型在 reasoning 里自报错了**（没按实际 items 加总）。

**后端 bug 已修**：`sum_checker` 在 **subtotal 为 null** 时原先用 `line_total_sum` 直接和 `total` 比，而小票的 total 含税，导致 4790 ≠ 4970 被误判失败。已改为在 subtotal 为 null 时用 **line_total_sum + tax ≈ total** 判定，该 payload 现在会通过 sum check。

---

## 3. Sum check 失败后为什么没有 Escalation？

流程理解没问题：**Vision 管线**在 sum check 失败时确实会走 escalation（见 `workflow_processor_vision.py` 约 885–948 行）。

但 escalation **只有在配置了对应环境变量时才会执行**：

- `GEMINI_ESCALATION_MODEL`（例如 gemini-2.5-pro / 你说的 gemini 3.0 pro）
- 和/或 `OPENAI_ESCALATION_MODEL`（例如 gpt-4o、gpt-5 等）

若**两个都没配置**，代码会打日志：

```text
[vision] No escalation models configured (GEMINI_ESCALATION_MODEL / OPENAI_ESCALATION_MODEL). Marking as needs_review without escalation.
```

然后直接标记为 `needs_review`，**不会**调用 Gemini 3.0 Pro 或 OpenAI。

请检查 `backend/.env`（或当前运行环境）中是否设置了：

- `GEMINI_ESCALATION_MODEL=...`
- `OPENAI_ESCALATION_MODEL=...`

只要其中至少一个配置了，sum check 失败时就会先写 primary 结果、再并行调这两个 escalation 模型做共识；若两个都未配置，就只会 needs_review，不会 escalate。
