# Development Log

## 2025-03-21 — AI-Native Workflow Upgrade (Batch 1)

### #8 清理 OpenAI 残留代码
- Removed `_run_shadow_legacy()` function and all 5 fire-and-forget call sites in `workflow_processor_vision.py`
- Removed `/api/receipt/openai-llm` endpoint from `main.py`
- Removed `process_receipt_with_llm_from_docai()` wrapper (hardcoded OpenAI)
- Changed `receipt_llm_processor.py` default `llm_provider` from `"openai"` to `"gemini"`; removed OpenAI branch in LLM call
- Marked OpenAI config fields as DEPRECATED in `config.py` (kept for .env backward compat)
- Added deprecation notice to `llm_client.py` (file kept for reference, no active imports)
- Cleaned up all OpenAI/shadow references in comments and docstrings
- **Files changed**: `workflow_processor_vision.py`, `main.py`, `receipt_llm_processor.py`, `config.py`, `gemini_client.py`, `llm_client.py`

### #1 Gemini Structured Output
- Defined `RECEIPT_OUTPUT_SCHEMA` dict in `gemini_client.py` matching the full receipt JSON structure (receipt, items, tbd, metadata)
- Added `response_schema=RECEIPT_OUTPUT_SCHEMA` to all three Gemini call functions:
  - `parse_receipt_with_gemini()` (text mode)
  - `parse_receipt_with_gemini_vision()` (vision retry)
  - `parse_receipt_with_gemini_vision_escalation()` (primary + escalation)
- API now enforces JSON schema at the model level — eliminates JSON parse failures
- **Files changed**: `gemini_client.py`

### #7 大图片自动压缩 (后端)
- Added `_compress_image_if_needed()` helper in `workflow_processor_vision.py`
- Threshold: 5 MB; target: 2000px long edge, JPEG quality 85
- Called at the very start of `process_receipt_workflow_vision()`, transparent to downstream
- Added `Pillow>=10.0.0` to `requirements.txt`
- **Files changed**: `workflow_processor_vision.py`, `requirements.txt`

## 2025-03-21 — AI-Native Workflow Upgrade (Batch 2)

### #3 Gemini Context Caching
- Added `_get_or_create_vision_cache()` in `gemini_client.py`
- Caches the vision system instruction via `client.caches.create()` with 1-hour TTL
- `parse_receipt_with_gemini_vision_escalation()` now attempts cached path first; falls back to inline prompt if caching fails
- Cached path sends only the image per-call (instruction is in the cache), reducing token cost for batch/repeat uploads
- **Files changed**: `gemini_client.py`

### #5 Prompt 混合迁移
- Extracted 3 core prompts from hardcoded Python strings to local files:
  - `prompts/templates/system_message.txt` — system message
  - `prompts/templates/prompt_template.txt` — user prompt template
  - `prompts/templates/output_schema.json` — JSON output schema
- Updated `prompt_manager.py` to load from files via `_load_template()`, raises RuntimeError if file missing
- Store-specific second-round prompts remain in Supabase `prompt_library` (operational — no code deploy needed for new stores)
- Fixed stale `settings.openai_model` → `settings.gemini_model` in `get_default_prompt()`
- **Files changed**: `prompt_manager.py`, new files in `prompts/templates/`

## 2025-03-21 — AI-Native Workflow Upgrade (Batch 3)

### #4 Google Search Grounding for Address Verification
- Created `processors/enrichment/address_grounding.py` — new module using Gemini + Google Search tool
- Prompt asks Gemini to search for the real store address and return structured fields (address_line1, address_line2, city, state, zip_code, country)
- Integrated as fallback in `workflow_processor_vision.py`: runs after `correct_address()` when canonical DB has no match
- Applied to both primary vision and escalation paths
- Only fills missing fields by default; overwrites address_line1 only on high confidence
- Records grounding metadata (`_metadata.address_grounding`) for auditability
- **Files changed**: new `address_grounding.py`, `workflow_processor_vision.py`

### #6 Evaluation Pipeline
- Created `evaluation/` module with:
  - `evaluators.py` — 9 evaluators: total_match, subtotal_match, tax_match, item_count, item_totals, date_match, merchant_match, address_completeness, sum_check
  - `run.py` — CLI runner: loads ground truth + predictions, runs all evaluators, prints summary table + per-receipt failures, optional JSON report output
  - `ground_truth/_EXAMPLE.json` — sample ground truth format
- Usage: `python -m app.evaluation.run -g evaluation/ground_truth/ -p output/20260219/`
- **Files changed**: new `evaluation/` directory

## 2025-03-21 — AI-Native Workflow Upgrade (Batch 4)

### #10 前端性能优化
- **Parallel data fetches**: Combined 3 serial useEffect chains (auth/me → receipt list → categories) into a single parallel effect. All 3 API calls now fire simultaneously when token is available.
- **Lazy-load DataAnalysisSection**: Changed from static import to `next/dynamic` with `ssr: false` and placeholder skeleton. Analytics section no longer blocks initial render.
- **Desktop receipt pagination**: Added `desktopReceiptVisibleCount` state (default 10). Desktop receipt list now renders only first 10 receipts with a "Show more" button, matching mobile behavior. Previously rendered ALL receipts on mount.
- Build compiles successfully; pre-existing TS strict error (`_key` on `ReceiptItem` union type) is unrelated.
- **Files changed**: `frontend/app/dashboard/page.tsx`
