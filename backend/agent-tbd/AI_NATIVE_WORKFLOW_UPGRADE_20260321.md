# AI-Native Workflow Upgrade Plan

> Created: 2025-03-21
> Status: All batches completed (2025-03-21). #9 and #2 deferred to future.

## Context

LedgerLens currently uses a traditional software architecture with LLM API calls bolted on.
This plan upgrades to Google AI-native patterns (Structured Output, Context Caching,
Grounding, Evaluation) to improve accuracy, speed, and cost.

---

## Task Checklist

### Batch 1 — Cleanup & Quick Wins

- [x] **#8 清理 OpenAI 残留代码**
  - Remove `_run_shadow_legacy()` in `workflow_processor_vision.py` (line ~340-371)
  - Remove `/api/receipt/openai-llm` endpoint in `main.py` (line ~924)
  - Remove or archive `services/llm/llm_client.py`
  - Remove OpenAI from confirm endpoint (`main.py:1303` "Textract+OpenAI")
  - Clean up all OpenAI references in comments/docstrings
  - Update docs to clarify: pipeline is Gemini-only, OpenAI is fully deprecated
  - **Why**: OpenAI escalation was deprecated because it hallucinated and two-AI voting
    degraded confidence. Dead code confuses future AI agents and developers.

- [x] **#1 Gemini Structured Output**
  - Replace prompt-based JSON schema enforcement with `response_mime_type="application/json"`
    and `response_schema=...` in Gemini API calls
  - Affects: `gemini_client.py` (primary vision call + escalation call)
  - Keep the text instructions for *behavior* (cents, validation rules, date parsing)
    but remove the output schema block from prompts
  - **Why**: Eliminates JSON parse failures, reduces prompt token usage, guarantees valid JSON.

- [x] **#7 大图片自动压缩 (后端)**
  - In the upload handler, detect if image > 5MB
  - Auto-compress with Pillow (resize + JPEG quality reduction) to target ~2MB
  - Small receipts don't need high resolution; 1500-2000px long edge is sufficient
  - No frontend changes needed
  - **Why**: iPhone photos regularly exceed 5MB; Gemini Vision has input limits and
    larger images cost more tokens.

### Batch 2 — Cost & Prompt Management

- [x] **#3 Gemini Context Caching**
  - Cache system prompt + schema + common extraction rules
  - Especially beneficial for bulk uploads of same-store receipts
  - Use `genai.caching.CachedContent.create()` with 1-hour TTL
  - **Why**: Repeated system prompts are the bulk of input tokens. Caching can cut
    token cost 50%+ for batch processing.

- [x] **#5 Prompt 混合迁移**
  - Move core prompts to local files (git-tracked, code-reviewable):
    - System message → `backend/app/prompts/templates/system_message.txt`
    - Output schema → `backend/app/prompts/templates/output_schema.json`
    - Extraction rules → `backend/app/prompts/templates/extraction_rules.txt`
    - Escalation template → `backend/app/prompts/templates/escalation.txt`
  - Keep store-specific second-round prompts in Supabase `prompt_library` + `prompt_binding`
    (operational — new store doesn't require code deploy)
  - Update `prompt_manager.py` to load from files first, DB second
  - **Why**: Core prompts change with code and should be version-controlled. Store prompts
    change operationally and belong in the database.

### Batch 3 — New Capabilities

- [x] **#4 Google Search Grounding for Address Verification**
  - Use Gemini's `google_search` tool to verify/complete merchant addresses
  - Ensure output strictly follows existing field separation:
    `address_line1`, `address_line2`, `city`, `state`, `zip_code`, `country`
  - Can be a post-processing step after primary extraction
  - **Why**: Current address parsing relies entirely on OCR text. Grounding against
    real-world data catches errors and fills missing fields.

- [x] **#6 Evaluation Pipeline**
  - Build `backend/app/evaluation/` module with:
    - Ground truth dataset (curated from `input/` samples with known-correct JSON)
    - Evaluators: JSON field accuracy, total match, item count match, category accuracy
    - CLI command: `python -m app.evaluation.run --dataset test_receipts/`
    - Output: per-receipt scores + aggregate metrics
  - Run eval before and after any prompt/model change
  - **Why**: Without automated eval, prompt changes are blind — you can't tell if
    accuracy improved or regressed.

### Batch 4 — Frontend

- [x] **#10 前端性能优化**
  - Split `page.tsx` (2700+ lines) into smaller components
  - Parallelize data fetches (currently serial: auth → me → data)
  - Add SWR or React Query for client-side caching
  - Lazy-load below-fold sections (receipt history, analytics)
  - **Root cause**: Everything is `'use client'`, zero SSR, serial fetches, no cache.
    Paid Vercel backend is not the bottleneck.

- [ ] **#9 用户预选商店跳过第一轮 (后做)**
  - Frontend: Add optional store quick-select on upload (show recent stores first)
  - Backend: If `chain_id` provided, skip merchant resolution + go directly to
    store-specific prompt in a single Gemini call
  - **Why**: For repeat shoppers (e.g., weekly Costco), this cuts processing time ~50%
    by eliminating the generic first-round parse.

---

## Future TODO (not yet started)

- [ ] **#9 用户预选商店跳过第一轮**
  - Frontend: Add optional store quick-select on upload (show recent stores first)
  - Backend: If `chain_id` provided, skip merchant resolution + go directly to
    store-specific prompt in a single Gemini call
  - **Why**: For repeat shoppers (e.g., weekly Costco), this cuts processing time ~50%
    by eliminating the generic first-round parse.
  - **Blocked**: Needs frontend button layout changes; user doesn't have time this week.
    Risk of breaking existing UI — do this when there's time to QA the upload flow.

- [ ] **#2 Genkit Flow 重构 workflow_processor_vision.py (1400+ lines)**
  - Replace hand-written orchestration with declarative Flow (Google Genkit or similar)
  - Would simplify: retry logic, tracing, streaming, error handlingre
  - **Skipped (2025-03-21)**: Pipeline is stable and working. Large refactor with high
    risk of breakage and no user-visible improvement. Revisit when adding major new
    pipeline features (e.g., multi-page receipt support) where the current code becomes
    unmaintainable.

---

## Architecture Notes

- **LLM Provider**: Gemini only (OpenAI fully deprecated as of 2025-03-21)
- **Escalation**: Gemini escalation model only (e.g., gemini-1.5-pro when flash fails)
- **Database**: Supabase (PostgreSQL)
- **Frontend**: Next.js 15 / React 19 on Vercel
- **Backend**: FastAPI on Vercel (paid tier)
