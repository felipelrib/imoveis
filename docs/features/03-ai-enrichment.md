# AI Enrichment Pipeline — Local VLM visual analysis + LLM sentiment scoring via Ollama/LM Studio

> Feature branch: `feat/ai-enrichment` · Linear: `BIN-XX` · Status: implemented

## Problem

Raw property listings lack quality signals. Users need to understand property condition (from photos) and location desirability (from descriptions) to make informed decisions. Cloud AI APIs are expensive at scale; local models via Ollama/LM Studio provide zero-cost, private inference.

## Approach

- **Dual-backend abstraction** (`LocalAIClient` ABC): Supports Ollama (`/api/generate`) and LM Studio (`/v1/chat/completions`) with shared `analyze_visuals()` and `analyze_text()` interfaces.
- **VLM visual analysis**: Sends up to 5 property photos (base64-encoded) to a vision model (e.g., LLaVA) with a detailed prompt requesting `condition_score` (0-1), `category`, `features_detected`, and `issues_detected`.
- **LLM sentiment analysis**: Sends property description text to a text model (e.g., Llama 3) for location/lifestyle evaluation, extracting `green_flags`, `red_flags`, `sentiment_score`.
- **Deal verdict synthesis**: Combines statistical, visual, and sentiment analyses into a single PT-BR "punchline" sentence. Uses LLM when available, falls back to a deterministic template (`template_deal_verdict`).
- **Image store**: Downloads and caches images locally by MD5 hash to avoid re-downloading and re-encoding.
- **Few-shot prompts**: Both visual and sentiment prompts include 3 few-shot examples for consistent JSON output.

## Changes

Files touched:

```
 src/adapters/ai/client.py      | OllamaClient, LMStudioClient, LocalAIClient ABC, create_ai_client factory
 src/adapters/ai/prompts.py     | build_visual_condition_prompt, build_sentiment_prompt, build_deal_verdict_prompt
 src/adapters/ai/image_store.py | ImageStore — download, cache, deduplicate images by content hash
 src/adapters/ai/__init__.py    | Package exports
 src/adapters/queue/tasks.py    | ai_enrich Celery task orchestrating the full pipeline
```

## New Dependencies

- `aiohttp` — Async HTTP client for AI model APIs
- `httpx` — Async image downloading

## How to Test

1. Ensure Ollama is running with a vision model:
   ```bash
   ollama pull llava
   ollama pull llama3
   ```
2. Trigger a scrape — AI enrichment is automatically enqueued for new/updated properties with images.
3. Run unit tests:
   ```bash
   pytest src/tests/unit/test_ai_client.py src/tests/unit/test_ai_quality.py src/tests/unit/test_deal_verdict.py -v
   ```

## Notes / Follow-ups

### Bugs Found

- ~~**BUG (Critical): `await` in sync Celery task**~~ — **FIXED**: Refactored `ai_enrich` to run a single inner async function `_run_enrichment()` via `asyncio.run()`, fixing `SyntaxError` and `RuntimeError`.
- ~~**BUG (Moderate): Double `asyncio.run()` calls**~~ — **FIXED**: Consolidated all async operations into the single `_run_enrichment()` event loop.
- ~~**BUG (Moderate): `cfg.scoring.ai_weight` / `cfg.scoring.stat_weight` AttributeError**~~ — **FIXED**: Included in `AppConfig` and `ScoringConfig` schemas.
- ~~**BUG (Minor): Unclosed `aiohttp.ClientSession`**~~ — **FIXED**: Migrated `_ensure_session` to an `asynccontextmanager` called `session_context()`.
- ~~**BUG (Minor): Unbound `text` variable in `LMStudioClient`**~~ — **FIXED**: Pre-assigned `text = "<unread>"` before the `try` block.

### Tech Debt

- **No retry on AI inference failures** — If Ollama returns garbage JSON, the task fails and retries the entire enrichment (including re-downloading images).
- **60/40 visual/sentiment weight is hardcoded** (tasks.py L265) — Should be configurable.
- **Image store uses MD5** (image_store.py L71) — MD5 is fine for dedup but is technically insecure. Not a security concern here, but `hashlib.sha256` would be more appropriate.
- **`image_storage_path` not in AppConfig schema** — The YAML has `image_storage_path: data/images` but `AppConfig` doesn't define this field. `ImageStore.__init__` calls `get_config().image_storage_path` which will raise `AttributeError`.
