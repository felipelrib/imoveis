# Extract Shared AI Client Retry/JSON-Parse Helper — deduplicate Ollama/LM Studio retry loops

> Feature branch: `feat/extract-ai-client-retry-helper` · Linear: `BIN-137` · Status: implemented

## Problem

`src/adapters/ai/client.py` duplicated a retry-on-`JSONDecodeError` loop across four methods: `OllamaClient._llm_verdict`/`analyze_visuals`/`analyze_text` and the equivalent `LMStudioClient` methods. Each copy re-implemented the same 3-attempt loop shape (call the backend, `json.loads` the response, append an "invalid JSON" retry hint on failure, re-raise after the last attempt, and let the caller's `try/except` build a fixed fallback result). The copies had already drifted slightly — e.g. minor differences in how the retry hint was appended to the prompt vs. message content — meaning any future fix to the retry/backoff structure or the error-fallback shape (`condition_score=0.5, analysis="Error"`) would need to be applied in four-plus places to stay consistent.

## Approach

- Extract the retry-on-invalid-JSON loop into `LocalAIClient._run_json_retry_loop`, a method on the shared abstract base class used by both `OllamaClient` and `LMStudioClient`.
- The loop takes three closures supplied by each call site: `fetch()` (performs one HTTP call and returns `(raw_text, context)`), `apply_retry_hint()` (mutates the enclosing prompt/messages before the next attempt), and `build_result(data, context)` (shapes the final Pydantic result from the parsed JSON). This keeps the HTTP-call-shape differences (Ollama's `generate()` vs. LM Studio's `chat_completions()`) and the differing fallback/log messages local to each backend, while the loop mechanics (attempt counting, `JSONDecodeError` handling, re-raise on exhaustion) live in exactly one place.
- The `context` value threaded through `fetch` → `build_result` preserves a subtle pre-existing quirk: Ollama's `analysis` field falls back to `res.get("response", "")` (empty-string default) independently of the `"{}"` default used for JSON parsing, while LM Studio's `analysis` field falls back to `data.get("analysis", text)` (the raw response text). Both defaults are preserved exactly via `context` rather than being unified, since this is a pure characterization refactor with **no intended behavior change**.
- Outer `try/except` blocks (which build the per-backend fallback result and log a per-backend message) stay in each subclass method — only the inner retry-loop body was extracted.
- Dropped one dead `text = "<unread>"` placeholder variable in `LMStudioClient.analyze_visuals` that was assigned before the loop and never read outside it (write-only, no observable effect on behavior).

## Changes

Files touched:

```
src/adapters/ai/client.py | REFACTOR — extract LocalAIClient._run_json_retry_loop, used by OllamaClient/LMStudioClient's _llm_verdict/analyze_visuals/analyze_text
```

## New Dependencies

None.

## How to Test

```bash
bash scripts/agent/validate.sh all
bash scripts/agent/validate-ai.sh
```

This is a characterization-only refactor: the existing `src/tests/unit/test_ai_client.py` suite (42 tests, unchanged) and `src/tests/unit/test_ai_quality.py` golden-file tests (run via `validate-ai.sh` against a reachable Ollama instance) both pass unmodified — they lock retry-attempt counts, the retry-hint mutation, and the JSON-decode-failure fallback shapes per backend.

## Notes / Follow-ups

- Tracked as part of the BIN-128 tech-debt remediation epic (v0.10 milestone), from the 2026-07-29 audit.
- Epic parent: BIN-128.
- Any future third AI backend should implement `fetch`/`apply_retry_hint`/`build_result` closures against `LocalAIClient._run_json_retry_loop` rather than re-copying the retry loop a third time.
