# Deprecated — Removed pipeline code

This folder holds code that is **no longer used** in the active application. The app now runs **vision-only** for receipt processing.

## 1. Vision pipeline: OpenAI debate (removed)

- **Parallel escalation**: Previously, when sum check failed we called both Gemini and OpenAI vision in parallel, then ran consensus.
- **Consensus / 判定**: `_check_vision_consensus` compared the two model outputs and merged or flagged conflicts.
- **Why removed**: OpenAI results were often wrong; Gemini was consistently correct. Dropping OpenAI reduces cost and errors.

**File**: `vision_openai_escalation_deprecated.py` — Old `_run_vision_escalation` and `_check_vision_consensus` for reference. Not imported anywhere.

## 2. OCR + LLM pipeline (legacy, removed)

- **Legacy flow**: Google Document AI OCR → Gemini or GPT-4o-mini LLM → sum check → on failure AWS Textract + secondary LLM → file storage.
- **Why removed**: We now use vision-only (image → Gemini → optional store-specific second round → Gemini escalation). The old OCR+LLM path is no longer called.

**File**: `workflow_processor_legacy_ocr_llm.py` — Full legacy OCR+LLM workflow for reference only. Not imported by the app. Shared helpers live in `app.core.workflow_common`; this file imports from there.

## Current flow (vision-only)

1. **Vision 1** (primary): Gemini vision → structured JSON  
2. **If familiar store** (e.g. Costco, Trader Joe's): **Vision 2** (store-specific second round)  
3. **If sum check failed**: Escalation = **Gemini only**  
4. **If still wrong**: Mark as `needs_review` and ask the user.

Both `/api/receipt/workflow` and `/api/receipt/workflow-vision` now run this vision pipeline. Bulk upload uses it as well.
