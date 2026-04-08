# LedgerLens Engineering TODO

> 背景：这份 TODO 是基于对当前 receipt 解析 pipeline 的系统性 review 整理出来的。
> 目标模型：Gemini 2.5 Flash（已迁移，代码默认 + .env 均为 gemini-2.5-flash）。
> 当前 pipeline 概述：图片 → LLM#1（fast, cheap）→ sum check / confidence check → DB lookup → LLM#2（store-specific prompt）→ frontier model escalation → 用户 escalation。

---

## Task 1：前端选店取代自动店名识别

**背景**
当前 pipeline 依赖 LLM 从图片里识别店名，然后再去 DB 查 store profile。这一步引入了不必要的识别错误率，且浪费了一次 LLM roundtrip。

**方案**
用户上传图片之前，前端展示该用户的常用店铺列表（从历史记录里取 top N），让用户点选。系统拿到 store_id 之后直接去 DB 取 store profile，跳过自动识别。

**实现细节**
- 前端：上传图片时增加一个 store picker 组件，显示用户历史最常用的 top 5 店铺（按出现次数排序）
- 提供"其他 / 新店铺"选项，走原有的自动识别流程作为 fallback
- 后端：在 users 表或单独的 user_store_history 表记录每个用户的店铺访问频次，用于排序
- 用户选了店铺之后，第一次 LLM 调用直接携带 store-specific prompt，跳过 Step 3（DB lookup）

**副产品：image hash 去重**
与本 task 一起实现。用 perceptual hash（pHash）在图片上传时计算 hash，存入 receipts 表。每次上传时比对，防止同一张小票重复录入。使用 Python 的 `imagehash` 库，几行代码，不需要 LLM。

**验收条件**
- [ ] 前端 store picker 上线，用户可以选择已知店铺或选"新店铺"
- [ ] 选择已知店铺后，第一次 LLM call 已携带 store profile，无需再做 DB lookup
- [ ] image hash 去重逻辑上线，重复上传时给用户友好提示

---

## Task 2：调整 Confidence Score 的使用逻辑

**背景**
Sum check 是 hard gate（数字加总对不对是客观事实，可以 rule out 所有 Type I error）。
Confidence score 是 soft negative indicator，不能作为放行 gate，但低 confidence 应该触发额外审查。

**新的判断逻辑**

```
sum check FAIL  → 直接 Fail，走下一步 escalation，不管 confidence
sum check PASS + confidence >= threshold  → 放行，记录 confidence 值
sum check PASS + confidence < threshold  → 视为 Fail，走下一步 escalation
```

**关键原则**
- Confidence score 是 LLM 自己估的，不是概率校准值，模型会 overconfident。
- 因此：confidence 低 = 一定有问题；confidence 高 ≠ 一定没问题。
- 永远不要让 confidence 单独放行一个 sum check FAIL 的结果。
- Sum check 是唯一的 hard gate。

**Threshold 设置**
- 初始值建议 0.80，跑一段时间后根据 regression test 结果调整
- Threshold 应该是可配置的（存在环境变量或配置表里），不要 hardcode

**Prompt 要求**
在 LLM 的 output schema 里明确要求输出 `_confidence` 字段，说明这是模型对"所有字段提取准确、无遗漏、sum check 自验通过"的综合信心，0-1 浮点数。

**验收条件**
- [x] LLM output schema 包含 `_confidence` 字段，所有 LLM 层都输出这个字段
- [x] sum check PASS + confidence < threshold 的情况被正确路由到下一步 escalation
- [x] confidence threshold 是可配置的，不 hardcode

---

## Task 3：接入 Gemini Context Caching

**背景**
每次调用 Gemini 时，system prompt + store profile 是重复内容，按全价计费。
Gemini 2.5 的 implicit caching 对 cache 命中的 tokens 打 10%（即 90% 折扣）。
不需要改数据库结构，store profile 继续存 Supabase，在构建 API 请求时序列化进 prompt。

**工作原理**
Gemini 的 implicit caching 会自动检测请求的重复 prefix。开发者需要做的只有一件事：
**把 system prompt 和 store profile 放在消息结构的最前面，图片和动态内容（用户输入）放在最后。**

**Prompt 结构要求（必须按此顺序）**

```
messages = [
  {
    "role": "system",
    "content": """
      [全局 extraction instructions - 所有请求共享，尽量稳定不变]
      你是一个 receipt 解析助手，输出 JSON 格式...
      ...（这部分越稳定越好，cache 命中率越高）
    """
  },
  {
    "role": "user", 
    "content": [
      # 1. Store profile（如果有）- 放在图片之前
      {"type": "text", "text": f"Store profile:\n{json.dumps(store_profile)}"},
      # 2. 图片 - 动态内容，放在最后
      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
      # 3. 指令
      {"type": "text", "text": "请解析以上小票，输出 JSON。"}
    ]
  }
]
```

**注意事项**
- Implicit caching 最小 token 数要求：Gemini 2.5 Flash 是 1024 tokens。system prompt 太短不会命中 cache。
- 如果 system prompt 不够长，可以把通用的 extraction rules、edge case 处理说明、output schema 定义都放进去，反正这些内容本来就应该在 system prompt 里。
- 在 API response 的 `usage_metadata` 里可以看到 `cached_content_token_count`，用来监控 cache 命中率。
- Store profile 因为每家店不同，不会 cache（每家店的 profile 都是不同的 prefix），但 system prompt 部分会 cache。如果要给单个高频店铺的 profile 也做 explicit cache，可以之后再做，优先级低。
- ~~**迁移提醒：Gemini 2.0 Flash 将于 2026-06-01 关闭**~~ 已迁移到 gemini-2.5-flash。

**验收条件**
- [x] prompt 结构已按 system → store profile → 图片顺序重构
- [x] 迁移到 Gemini 2.5 Flash 或 Flash-Lite
- [x] 在 response metadata 里记录 `cached_content_token_count`，写入日志或监控
- [ ] 跑 10 次同一家店的 receipt，确认 cache 命中率 > 0

---

## Task 4：建立 Regression Test Suite

**背景**
每月 receipt 数量少（5-8 张），无法做统计意义上的 benchmark。
改用 regression test 思路：把每一张已处理的 receipt 变成 test case，改 prompt 后重跑，检测 regression。

**数据结构**

```
tests/regression/
  cases/
    costco_20240115.json
    safeway_20240203.json
    ...
  run_eval.py
  results/
    YYYY-MM-DD_HH-MM.json   ← 每次跑完的结果快照
```

每个 case 文件结构：

```json
{
  "case_id": "costco_20240115",
  "image_path": "tests/fixtures/costco_20240115.jpg",
  "store_id": "costco_canada",
  "ground_truth": {
    "store_name": "Costco Wholesale",
    "date": "2024-01-15",
    "items": [
      {"name": "Kirkland Olive Oil", "price": 19.99, "qty": 1},
      ...
    ],
    "subtotal": 87.43,
    "tax": 4.37,
    "total": 91.80
  },
  "metadata": {
    "added_date": "2024-01-20",
    "notes": "注意这张票的 tax 写在最后两行，格式特殊",
    "llm_steps_needed": 2
  }
}
```

**run_eval.py 逻辑**

```python
# 伪代码，LLM 实现时补全
for case in load_all_cases():
    result = run_pipeline(case["image_path"], case["store_id"])
    
    report = {
        "case_id": case["case_id"],
        "sum_check_pass": check_sum(result, case["ground_truth"]),
        "field_accuracy": compare_fields(result, case["ground_truth"]),
        "confidence": result["_confidence"],
        "steps_needed": result["steps_taken"],   # 走了几步才过
        "errors": diff(result, case["ground_truth"])
    }
    
    print_report(report)

# 最终输出：pass rate、每个 case 的 diff、和上次跑相比的 delta
```

**使用方法**
- 每次修改 prompt 后跑一次，对比结果
- 有新的 confirmed receipt 时，手动添加到 cases/ 目录（这是唯一需要人工的步骤）
- 结果文件按日期存档，方便 diff

**LLM-generated augmentation（可选，后期做）**
用 LLM 基于真实 case 生成变体（比如同一家店但 tax 格式不同），扩充测试集。初期不需要，积累 20+ 真实 case 后再考虑。

**验收条件**
- [ ] `tests/regression/cases/` 目录建立，已有历史 receipt 转成 case 文件
- [ ] `run_eval.py` 可以跑通，输出每个 case 的 pass/fail
- [ ] 结果文件按日期存档
- [ ] 有 README 说明如何添加新 case

---

## Task 5a：Store Profile 自动生成 Agent

**背景**
当一张来自新店铺的 receipt 通过 pipeline（不管走了几步）且被用户确认正确后，
自动触发 store profile 生成 agent，异步运行，不影响主流程延迟。

**触发条件**
```
新店铺（store_id 不在 DB）AND 最终结果被用户确认（或 sum check pass + confidence >= threshold）
```

**Agent Prompt 设计**

```
System:
你是一个 store profile 生成专家。你的任务是根据已确认正确的 receipt 解析结果，
生成一个结构化的 store profile，用于指导未来对同一家店 receipt 的解析。

User:
以下是一张来自新店铺的 receipt 的解析结果，已经过人工或自动验证确认正确。

原始图片：[image]

已确认的解析 JSON：
{confirmed_json}

本次解析走了 {steps_needed} 步才通过，在第 {resolved_at_step} 步解决。
{if steps > 1: "以下是解析过程中遇到的问题：{reasoning_log}"}

请生成一个 store profile JSON，包含：
1. store_name：标准化的店铺名称
2. address_pattern：地址的格式特征（如果图片里有）
3. tax_format：税的标注方式（如 "HST on last line", "GST/PST separate rows" 等，用英文描述）
4. discount_format：折扣的标注方式（如 "instant savings on separate line" 等）
5. special_items：需要特别注意的行类型（如 bottle deposit、membership fee 等）
6. known_quirks：其他已知的格式特殊性，数组，每条一句话
7. prompt_hints：给下一次 LLM 解析这家店时的具体指导，数组，每条一句话
8. confidence：对这个 profile 的可靠性评估（0-1），样本只有 1 张时应该较低（建议 0.5-0.6）
9. sample_count：生成这个 profile 时使用的样本数量（当前为 1）

输出纯 JSON，不要其他内容。
```

**DB Schema（store_profiles 表）**

```sql
CREATE TABLE store_profiles (
  store_id        TEXT PRIMARY KEY,       -- 标准化店铺 ID，如 "costco_ca_surrey"
  store_name      TEXT NOT NULL,
  tax_format      TEXT,
  discount_format TEXT,
  special_items   JSONB,                  -- array of strings
  known_quirks    JSONB,                  -- array of strings
  prompt_hints    JSONB,                  -- array of strings，直接拼进 LLM prompt
  profile_confidence FLOAT,              -- 对 profile 本身的置信度
  sample_count    INT DEFAULT 1,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

**Profile 更新逻辑**
- 同一家店第 2 张 receipt 进来时，用新的 confirmed JSON + 原有 profile 重新跑 agent，合并更新
- `sample_count` 累加，`profile_confidence` 随样本数提升（建议：1张=0.55, 3张=0.75, 5张+=0.85）
- `prompt_hints` 数组去重合并，不是简单覆盖

**集成到主 pipeline**
在 LLM#2（store-specific prompt）里，把 `prompt_hints` 数组序列化后插入 system prompt：

```
Store-specific hints for {store_name}:
- {hint_1}
- {hint_2}
...
```

**验收条件**
- [ ] `store_profiles` 表建立
- [ ] 新店铺 receipt 确认后，agent 异步触发，写入 store_profiles
- [ ] 第 N 张同店 receipt 进来时，profile 被正确 merge 更新
- [ ] prompt_hints 已集成进 LLM#2 的 system prompt
- [ ] 有日志记录 agent 触发、生成、写入的过程

---

## Task 5b：LLM-as-Judge Eval Pipeline

**背景**
用 LLM 自动评估 prompt 版本的好坏，替代人工 review 每条结果。
这是 Karpathy Loop 的正式版本：改 prompt → 跑 eval → judge 打分 → 分析失败 → 改 prompt。

**Judge Prompt 设计**

```
System:
你是一个 receipt 解析质量评审专家。你的任务是评估一个 AI 系统对 receipt 的解析结果质量。
你需要客观、严格地评分，不要对模型友好。

User:
以下是一张 receipt 的解析任务。

原始图片：[image]

Ground truth（人工确认的正确答案）：
{ground_truth_json}

待评估的解析结果：
{result_json}

请从以下维度评分（每项 0-10 分）：

1. field_completeness（字段完整性）：所有应该提取的字段是否都有，有无遗漏的 item
2. numeric_accuracy（数字准确性）：price、qty、tax、total 等数字是否正确
3. schema_compliance（格式合规）：输出 JSON 是否符合 schema，字段名是否正确
4. sum_consistency（加总一致性）：items 的 price*qty 加总是否等于 subtotal，加税是否等于 total

另外请输出：
- overall_pass：布尔值，是否整体通过（所有维度 >= 7 且 sum_consistency = 10）
- failure_reasons：如果 overall_pass=false，列出具体哪里错了
- improvement_hints：给 prompt 工程师的改进建议，针对这个具体的失败

输出纯 JSON，不要其他内容。
```

**run_judge.py 逻辑**

```python
# 伪代码，LLM 实现时补全

def run_judge_eval(prompt_version_label: str):
    """
    对某个 prompt 版本，跑所有 regression test case，
    每个 case 用 judge 打分，汇总输出报告。
    """
    results = []
    
    for case in load_all_cases():
        # 1. 用当前 prompt 跑 pipeline
        pipeline_result = run_pipeline(
            image_path=case["image_path"],
            store_id=case["store_id"],
            prompt_version=prompt_version_label
        )
        
        # 2. 用 judge 评分
        judge_result = call_judge(
            image_path=case["image_path"],
            ground_truth=case["ground_truth"],
            result=pipeline_result
        )
        
        results.append({
            "case_id": case["case_id"],
            "pipeline_result": pipeline_result,
            "judge_scores": judge_result,
        })
    
    # 3. 汇总报告
    report = {
        "prompt_version": prompt_version_label,
        "timestamp": now(),
        "total_cases": len(results),
        "overall_pass_rate": sum(r["judge_scores"]["overall_pass"] for r in results) / len(results),
        "avg_scores": average_scores(results),
        "failures": [r for r in results if not r["judge_scores"]["overall_pass"]],
        "common_failure_patterns": summarize_failures(results),   # 可以再用 LLM 做
    }
    
    save_report(report, f"results/judge_{prompt_version_label}_{now()}.json")
    print_summary(report)
```

**使用场景**
- 改了 system prompt 后，运行 `python run_judge.py --version v2.3`
- 输出对比：v2.2 pass rate 78% → v2.3 pass rate 91%，失败 case 从 5 个减少到 2 个
- 查看 `failure_reasons` 和 `improvement_hints`，定向修 prompt

**Judge 选型**
- 用 Gemini 1.5 Pro 或 Gemini 2.5 Pro 做 judge（比 pipeline 用的 Flash 更强）
- Judge 的 output 是评分，token 量少，成本可控
- Judge 不需要实时，可以 batch 跑

**与 Task 4 的关系**
- Task 4（regression test）是基础设施，提供 ground truth cases
- Task 5b（judge eval）建在 Task 4 之上，用 judge 代替人工 review
- 先完成 Task 4，再做 Task 5b

**验收条件**
- [ ] judge prompt 设计完成，人工验证评分结果的合理性（至少跑 5 个 case 手动核对）
- [ ] `run_judge.py` 可以跑通，输出 pass rate 和失败分析
- [ ] 报告按版本和日期存档，方便 A/B 对比
- [ ] 跑一次完整 eval，记录当前 prompt 的 baseline 分数

---

## 执行顺序建议

| 顺序 | Task | 理由 |
|------|------|------|
| 1 | Task 3（Caching）| 改动最小，只需重构 prompt 顺序 + 升级模型版本，顺手解决 deprecation 问题 |
| 2 | Task 1（前端选店）| 减少 pipeline 错误率，让后续 eval 数据更干净 |
| 3 | Task 2（Confidence 逻辑）| 逻辑改动，不依赖其他 task |
| 4 | Task 4（Regression Test）| 先建测试基础设施 |
| 5 | Task 5a（Store Profile Agent）| 依赖 Task 1 的 DB 结构 |
| 6 | Task 5b（Judge Eval）| 依赖 Task 4 的 test cases |

---

## 备注

- Gemini 2.0 Flash deprecation 截止日：**2026-06-01**，Task 3 必须在此之前完成。
- store_profiles 表的 `prompt_hints` 是 JSONB array，直接序列化成 bullet list 插进 prompt，不要做二次解析。
- 所有 LLM 调用都应该记录 token 用量（input / output / cached），便于后续成本分析。
- Judge 的评分结果本身也应该进 regression test 的监控——如果 judge 的行为变了（比如模型升级），分数基线会漂移。
