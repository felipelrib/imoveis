# Cloud AI enrichment A/B — Gemini/Gemma client + comparison harness

> Feature branch: `feat/ai-provider-ab` · Linear: `BIN-242` · Status: implemented

## Problem

AI enrichment (visual condition, listing sentiment, deal verdict) runs on local
**Ollama** (`qwen2.5vl:7b`). We needed to know whether a cloud model gives better
quality and/or throughput, and whether quotas / broken pipes would bite — without
mutating production scores while we found out.

## Approach

- Add a **cloud provider path** that reuses the existing OpenAI-compatible client
  code (`LMStudioClient`) so a new backend is transport-only:
  - `GeminiClient` — Gemini via its OpenAI-compatible endpoint: bearer-key auth,
    JSON `response_format`, exponential-backoff retry on 429/5xx, and `last_error`
    surfacing so a fully-fallen-back run is self-explanatory.
  - `GemmaClient(GeminiClient)` — Gemma emits a `<thought>…</thought>` preamble
    before the JSON even in JSON mode, and its reasoning ate the inherited
    256-token verdict budget (truncating the JSON away → 100% fallback). It strips
    the thought wrapper and raises the token floor to 2048.
- Keep embeddings on local **bge-m3** (`properties.embedding` is `vector(1024)`;
  mixing model vector spaces corrupts cosine search) — `embed()` raises.
- A **read-only offline harness** (`scripts/dev/ab_gemini_vs_ollama.py`) runs each
  arm over identical cached images + prompts and reports latency, fallback rate,
  score deltas, category agreement, 429/retry counts, and a whole-DB feasibility
  verdict. `--downscale` A/Bs image size. No production wiring or scores touched.
- Provider selection stays config-driven: `create_ai_client()` routes `backend:
  gemini` (and `gemma-*` model ids → `GemmaClient`) via `_gemini_client_for`.

## Changes

Files touched:

```
 src/adapters/ai/client.py            | GeminiClient + GemmaClient + _gemini_client_for; backend=gemini branch
 src/infra/config.py                  | AIConfig.gemini_url/gemini_model/gemini_api_key; GEMINI_API_KEY/GEMINI_MODEL env overrides
 configs/app_config.yaml              | ai.gemini_* keys (api key blank — env only)
 scripts/dev/ab_gemini_vs_ollama.py   | NEW — offline A/B/C/D harness (arms × image size), feasibility report
 src/tests/unit/test_ai_client.py     | GeminiClient transport/retry + GemmaClient sanitize/token-floor tests
 .gitignore                           | ignore data/images/ (ImageStore cache must never be committed)
```

## New Dependencies

None in `requirements.txt`. The harness's `--downscale` flag lazily imports
**Pillow** (dev-only); productionizing downscaling (BIN-248) will add it properly.

## How to Test

```bash
bash scripts/agent/validate.sh backend
```

Live A/B (free-tier Gemini/Gemma key in `GEMINI_API_KEY`; spends nothing on free
tier, calls the real API):

```bash
GEMINI_API_KEY=... OLLAMA_HOST=http://<host>:11434 \
  python scripts/dev/ab_gemini_vs_ollama.py --property-ids <a,b,c> \
  --gemini-models gemma-4-31b-it --concurrency 1 --downscale 768
```

## Notes / Follow-ups

- **Spike outcome:** Gemma 4 31B chosen over Ollama — 0 failures vs Ollama's 25%
  visual-error rate at full-size images, and far more discriminating output.
  **768px downscaling** is lossless for Gemma and *fixes* Ollama's failures.
- **Backfill viability:** free-tier Gemma is RPD-bound (14,400/day ≈ 4,800
  properties/day) → a full ~26k pass takes ~5.5–6 days; 0 rate-limit errors at
  concurrency 1. Productionization tracked in **BIN-248** (resumable RPD-aware
  runner + `backend: gemma` wiring + downscaling in the enrich path).
- Provider quotas verified free-tier from the AI Studio dashboard; DeepSeek was
  ruled out (no vision) and Mistral was not cheaper for our image-heavy workload.
- Embeddings intentionally out of scope (stay on local bge-m3).
