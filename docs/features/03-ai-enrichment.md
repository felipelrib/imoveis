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

- **BUG (Critical): `await` in sync Celery task** (tasks.py L317): Line `verdict_result = await client.summarize_deal(...)` uses `await` inside a synchronous function (`ai_enrich`). This will raise `SyntaxError` or, if the function were somehow made async, would conflict with Celery's sync task execution. The call should be wrapped in `asyncio.run()` like the other async calls in the same function.

- **BUG (Moderate): Double `asyncio.run()` calls** (tasks.py L248, L262): `asyncio.run()` is called twice in the same task — once for image downloading and once for AI inference. Each `asyncio.run()` creates and destroys an event loop. While technically functional, it's wasteful and could cause issues with `aiohttp` sessions created inside the first loop.

- **BUG (Moderate): `scoring.ai_weight` / `scoring.stat_weight` not in AppConfig** (tasks.py L285-294): The code accesses `cfg.scoring.ai_weight` and `cfg.scoring.stat_weight`, but `AppConfig` has no `scoring` section. The YAML has it, but the Pydantic model doesn't define a `ScoringConfig`. This will raise `AttributeError`.

- **BUG (Minor): Unclosed `aiohttp.ClientSession`** (client.py L130-131): The `LocalAIClient` creates an `aiohttp.ClientSession` in `_ensure_session()`, but `ai_enrich` only closes it via `asyncio.run(client.close())` in a `finally` block. If the task is killed mid-execution, the session leaks.

- **BUG (Minor): `LMStudioClient.analyze_visuals` references unbound `text` variable** (client.py L416): In the `json.JSONDecodeError` handler, `text` is referenced as a local variable that may not be assigned if the error occurs before the response is parsed.

### Tech Debt

- **No retry on AI inference failures** — If Ollama returns garbage JSON, the task fails and retries the entire enrichment (including re-downloading images).
- **60/40 visual/sentiment weight is hardcoded** (tasks.py L265) — Should be configurable.
- **Image store uses MD5** (image_store.py L71) — MD5 is fine for dedup but is technically insecure. Not a security concern here, but `hashlib.sha256` would be more appropriate.
- **`image_storage_path` not in AppConfig schema** — The YAML has `image_storage_path: data/images` but `AppConfig` doesn't define this field. `ImageStore.__init__` calls `get_config().image_storage_path` which will raise `AttributeError`.
