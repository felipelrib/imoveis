# image-store-and-vlm-pipeline — Local image caching and VLM visual-condition analysis

> Feature branch: `feat/image-store-vlm` · Linear: `BIN-XX` · Status: implemented

## Problem

The AI enrichment pipeline needed property photos to run visual-condition analysis
(scratch detection, renovation quality, dated fixtures, etc.), but:

1. Remote URLs are ephemeral — scraper images expire or rotate, making re-analysis
   impossible.
2. Passing raw URLs to the VLM is not supported by Ollama or LM Studio APIs —
   images must be base64-encoded in the request body.
3. Repeated scrapes of the same property should not re-download unchanged images.

## Approach

- **`ImageStore`** (`adapters/ai/image_store.py`) manages a local filesystem cache at
  `{config.image_storage_path}/{property_id}/{content_hash}.ext`.
  - Images are de-duplicated by **MD5 content hash** encoded in the filename.
    Identical images (same bytes) from different scrape runs are stored exactly once.
  - `download_images()` is async (uses `httpx.AsyncClient`) and skips already-cached files.
    Redirect following is disabled (`follow_redirects=False`) to prevent SSRF vulnerabilities.
    File extensions are inferred from the `Content-Type` header (e.g. `.jpg`, `.png`).
    `max_images` (default: 5) caps disk usage per property.
  - `encode_base64(file_path)` reads a cached file and returns its base64 string for VLM
    submission.
  - An ORM hook is registered in `adapters/db/models.py` (`delete_property_images`) to automatically
    delete image directories when a property is deleted, preventing disk leaks.

- **VLM prompt** (`adapters/ai/prompts.py` → `build_visual_condition_prompt()`) is a
  few-shot JSON-output prompt that asks the model to classify property condition into
  five categories (`Pristine`, `Good`, `Average`, `Needs Renovation`, `Poor`) and
  return `condition_score`, `features_detected`, and `issues_detected` as strict JSON.

- **Pipeline integration** (`adapters/queue/tasks.py` → `ai_enrich` task):
  1. `ImageStore.download_images()` downloads up to 5 images.
  2. `OllamaClient.analyze_visuals()` / `LMStudioClient.analyze_visuals()` encodes images
     as base64 and sends them alongside the prompt.
  3. The `VisualResult` is blended 60% into the final `ai_score`
     (40% from text/sentiment analysis).
  4. Visual result is persisted in `metrics_scoring.meta["visual"]`.

## Changes

Files touched:

```
 src/adapters/ai/image_store.py      | NEW — local image cache with MD5 de-duplication
 src/adapters/ai/prompts.py          | NEW — build_visual_condition_prompt() few-shot template
 src/adapters/ai/client.py           | analyze_visuals() on OllamaClient and LMStudioClient
 src/adapters/queue/tasks.py         | ImageStore download + VLM call wired into ai_enrich
 configs/app_config.yaml             | image_storage_path config key
```

## New Dependencies

- `httpx` — used in `ImageStore.download_images()` for async HTTP fetching. Already a
  transitive dependency; no new `requirements.txt` entry needed.

## How to Test

1. Run a scrape + AI enrichment cycle:
   ```bash
   curl -X POST http://localhost:8000/scrape -d '{"platform":"olx"}'
   ```
2. After the `ai_enrich` task completes, inspect the image cache:
   ```bash
   ls -lh /path/to/image_storage/<property_id>/
   # Each file is named {md5_hash}.jpg
   ```
3. Re-trigger enrichment for the same property — log should show `image_download_skip_max`
   (cached images reused, no HTTP requests made).
4. Check `metrics_scoring.meta` in Postgres:
   ```sql
   SELECT meta->'visual' FROM metrics_scoring LIMIT 5;
   ```

## Notes / Follow-ups

- **MD5 as identity hash**: MD5 is used purely for de-duplication (not security). A
  collision would cause two distinct images to overwrite each other. SHA-256 would be
  marginally safer with negligible performance cost.
- **`asyncio.run()` in a Celery sync task**: The `ai_enrich` task is synchronous but
  uses `asyncio.run(image_store.download_images(...))` and `asyncio.run(run_ai())`.
  Creating a new event loop per task is safe but wasteful. A better approach is to make
  `ai_enrich` an `async def` task with `celery[gevent]` or use a thread pool for
  async-in-sync bridging.
