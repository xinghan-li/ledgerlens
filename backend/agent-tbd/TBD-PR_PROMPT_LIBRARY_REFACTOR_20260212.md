# PR: Replace Tag-based RAG with Prompt Library + Binding

**Date**: 2026-02-12  
**Scope**: Prompt system refactoring, removal of legacy tag-based RAG

---

## Summary

Replaces the old tag-based RAG system (`prompt_tags`, `prompt_snippets`, `tag_matching_rules`) with a simpler **prompt_library + prompt_binding** design. The new system uses scope-based routing (default/chain/location) instead of OCR-driven tag matching.

---

## Changes Overview

### 1. New Database Schema (Migration 023)

**New files:**
- `backend/database/023_prompt_library_and_binding.sql` - Creates new tables, drops old ones
- `backend/database/023_seed_prompt_library.sql` - Seeds receipt_parse content

**New tables:**
- `prompt_library` - Stores prompt content (key, category, content_role, content)
- `prompt_binding` - Routes which library entries to use per prompt_key and scope (default/chain/location)

**Dropped tables:**
- `prompt_tags`
- `prompt_snippets`
- `tag_matching_rules`

**Removed migration:**
- `backend/database/009_tag_based_rag_system.sql` - No longer needed

---

### 2. New Code: prompt_loader.py

**File:** `backend/app/prompts/prompt_loader.py` (new)

- `load_prompts_for_receipt_parse()` - Loads and combines prompts from DB
- Scope resolution: default + chain (if chain_id matches) + location (if location_id matches)
- Caches bindings at startup; supports `clear_cache()` for refresh

---

### 3. Refactored: prompt_manager.py

- **Removed**: Import of `tag_based_rag` (detect_tags_from_ocr, load_rag_snippets, combine_rag_into_prompt)
- **Added**: Import of `prompt_loader.load_prompts_for_receipt_parse`
- **format_prompt()**:
  - Uses `load_prompts_for_receipt_parse(store_chain_id, location_id)` instead of tag detection
  - Builds system_message from loader's `system_parts` (with placeholder fill)
  - Uses loader's `user_template` and `schema` when available; falls back to defaults
  - `rag_metadata` updated: `library_parts_loaded`, `user_template_from_library`, `schema_from_library`
- **clear_cache()**: Also clears prompt_loader cache

---

### 4. Simplified: extraction_rule_manager.py

- **Removed**: All `tag_based_rag` imports and tag-based logic
- `get_merchant_extraction_rules()` now always returns `get_default_extraction_rules()`
- Future: Can add `content_role='extraction_rule'` support in prompt_library

---

### 5. Removed: RAG Service and API Routes

**Deleted files:**
- `backend/app/prompts/tag_based_rag.py` - Tag detection and RAG snippet loading
- `backend/app/services/rag/rag_manager.py` - CRUD for tags, snippets, matching rules
- `backend/app/services/rag/__init__.py`
- `backend/app/services/rag/` - Entire directory removed
- `backend/tests/tag_matching_rules_explanation.md`
- `temp/export_rag_tables_to_csv.py`
- `temp/prompt_tags.csv`, `temp/prompt_snippets.csv`, `temp/tag_matching_rules.csv`

**Removed from main.py:**
- Import of `rag_manager` (create_tag, get_tag, list_tags, update_tag, create_snippet, list_snippets, create_matching_rule, list_matching_rules)
- 8 RAG API endpoints:
  - `GET /api/rag/tags`
  - `POST /api/rag/tags`
  - `GET /api/rag/tags/{tag_name}`
  - `PUT /api/rag/tags/{tag_name}`
  - `GET /api/rag/tags/{tag_name}/snippets`
  - `POST /api/rag/tags/{tag_name}/snippets`
  - `GET /api/rag/tags/{tag_name}/matching-rules`
  - `POST /api/rag/tags/{tag_name}/matching-rules`

---

### 6. Documentation Updates

| File | Change |
|------|--------|
| `backend/database/MIGRATIONS_README.md` | Removed 009 from migration order; updated 023 description; Schema table marks 009 as "Removed" |
| `backend/database/001_schema_v2.sql` | Comment updated: reference 023 instead of 009 |
| `backend/database/DB_DEFINITIONS.md` | Replaced prompt_tags, prompt_snippets, tag_matching_rules with prompt_library, prompt_binding |

---

## Data Flow (Before vs After)

**Before (tag-based):**
1. OCR text + merchant_name → `detect_tags_from_ocr()` (regex/keyword/fuzzy against tag_matching_rules)
2. Tag names → `load_rag_snippets()` (from prompt_snippets via prompt_tags)
3. Combine snippets with base prompt → `format_prompt()`

**After (prompt library):**
1. `load_prompts_for_receipt_parse(store_chain_id, location_id)` queries prompt_binding + prompt_library
2. Scope match: default (always) + chain (if chain_id) + location (if location_id)
3. Returns system_parts, user_template, schema → `format_prompt()` assembles

---

## Breaking Changes

1. **RAG API routes removed** - No admin CRUD for prompts via REST. Use SQL/migrations or Supabase directly.
2. **extraction_rule_manager** - No longer supports store-specific extraction rules from DB; uses defaults only.
3. **Migration 009** - Removed. Fresh DBs should run 023 directly; existing DBs with 009 already run will have 023 drop old tables.

---

## Migration Steps (for existing deployments)

1. (Optional) Export old data: run `temp/export_rag_tables_to_csv.py` before migration if you need a backup
2. Run `023_prompt_library_and_binding.sql`
3. Run `023_seed_prompt_library.sql`
4. Deploy new backend code

---

## Testing

- `tests/test_initial_parse_integration.py` - Passes (format_prompt with initial_parse_result)
- App starts successfully; prompt_loader loads from DB

---

## Future Considerations

- **Prompt management API**: If admins need to CRUD prompts via UI, add GET/POST routes for prompt_library and prompt_binding.
- **Extraction rules in prompt_library**: Add `content_role='extraction_rule'` and wire extraction_rule_manager to load from DB.
- **Fee policy injection**: Placeholder `{store_specific_region_rules}` etc. in receipt_parse_base; can inject state-based fee rules later.
