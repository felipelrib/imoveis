# Local Agent Architecture (Goose + Ollama, parallel features)

How this repo lets multiple **Goose** agents design and implement features in
parallel on one machine — isolated by git worktrees and per-worktree Docker
stacks, planned with `deepseek-r1:14b`, implemented with `devstral:24b`, all
served by a single local Ollama.

---

## 1. Why it's built this way (the hardware truth)

Hardware: **RX 7900-class GPU, 20 GB VRAM, 64 GB DDR5.**

- Your Goose agents are just HTTP clients to **one** Ollama server on
  `localhost:11434`. Spawning N agents does **not** load N copies of the model and
  does **not** multiply VRAM by N. Model **weights load once** and are shared; only
  the **KV cache** grows with concurrency (`OLLAMA_NUM_PARALLEL`). Requests beyond
  the parallel limit **queue**.
- `devstral:24b` (~14 GB) + `deepseek-r1:14b` (~9 GB) ≈ **23 GB > 20 GB**. They
  **cannot** both stay resident on the GPU — Ollama would spill to system RAM
  (slow) or evict/reload on every switch (thrash).
- Therefore: **one model resident at a time.** Plan a whole batch of features with
  deepseek first, then swap **once** to devstral and implement. The GPU is the real
  serialization point — parallelism buys you **pipelining** (one agent builds/tests
  on CPU while another generates), not concurrent inference.

---

## 2. What's in the repo

| Path | Role |
|---|---|
| `.goose/guardrails.md` | **Persistent instructions (MOIM)** — hard rules injected *every turn*, can't be forgotten. Point `GOOSE_MOIM_MESSAGE_FILE` at it. |
| `.goosehints` | Project map + the feature lifecycle. Loaded at session start. |
| `.agents/agents/*.md` | **Custom agents**: `planner` (deepseek), `coder` (devstral), `orchestrator`, `reviewer`. |
| `recipes/*.yaml` | **Recipes**: `plan-feature`, `implement-feature` (with a validation `retry.checks` gate), `feature-pipeline` (plan→implement). |
| `scripts/agent/*.sh` | Deterministic tooling the agents call: worktree setup, isolated services, validate, merge-revalidate, docs, teardown. |
| `docker-compose.yml` | Now **port-parametrized** and **container_name-free** so `-p <project>` truly isolates. |
| `frontend/vite.config.js` | Port + API target are env-driven. |
| `FEATURES.md` | The feature queue. |
| `docs/features/` | One doc per shipped feature (auto-scaffolded + linked). |

Design principle: **all fiddly determinism (port math, project naming, race-free
registry) lives in bash**, so the small local models only need to call scripts.

---

## 3. One-time setup

### 3.1 Pull the models
```bash
ollama pull deepseek-r1:14b
ollama pull devstral:24b
```

### 3.2 Configure the Ollama **server** (VRAM discipline)
Set these where `ollama serve` runs (Windows: System env vars / `setx`, then restart
Ollama). Pick ONE mode:

**Mode A — serialized (no spill, fastest per token).** One model resident; deepseek
and devstral swap. Best if you plan the whole batch first, then implement.
```
OLLAMA_MAX_LOADED_MODELS = 1
OLLAMA_NUM_PARALLEL      = 1
OLLAMA_KEEP_ALIVE        = 30m
OLLAMA_CONTEXT_LENGTH    = 16384
```

**Mode B — both models resident, accept spill (overlap planning + implementing).**
`devstral` (~14 GB) + `deepseek-r1` (~9 GB) ≈ 23 GB; ~3 GB spills into your 64 GB
RAM. This lets a planner (deepseek) run *while* a coder (devstral) implements. Slower
per token on the spilled layers, but no reload thrash.
```
OLLAMA_MAX_LOADED_MODELS = 2        # keep BOTH models loaded
OLLAMA_NUM_PARALLEL      = 1        # one request per model -> minimises spill
OLLAMA_KEEP_ALIVE        = 30m
OLLAMA_CONTEXT_LENGTH    = 8192     # smaller ctx keeps the spill small
```
In Mode B, cap concurrency at **2 Goose sessions** — one on deepseek (planning), one
on devstral (implementing). A third concurrent request just queues and grows spill.

AMD/ROCm note: ensure your Ollama build uses ROCm for the 7900-series (see
`docs/rocm_directml_setup.md`).

### 3.3 Configure Goose

**Config file (Windows):** `%APPDATA%\Block\goose\config\config.yaml`

```yaml
GOOSE_PROVIDER: ollama
GOOSE_MODEL: devstral:24b          # default = implementation model
OLLAMA_HOST: http://localhost:11434

# CLI plan mode uses the reasoning model:
GOOSE_PLANNER_PROVIDER: ollama
GOOSE_PLANNER_MODEL: deepseek-r1:14b
```

**Environment variables** (your `~/.zshrc`, since you use zsh — use absolute,
forward-slash paths on Windows):
```bash
export CONTEXT_FILE_NAMES='["AGENTS.md", ".goosehints"]'
export GOOSE_RECIPE_PATH="C:/Workfolder/imoveis/recipes"
export GOOSE_MOIM_MESSAGE_FILE="C:/Workfolder/imoveis/.goose/guardrails.md"
```
> `GOOSE_MOIM_MESSAGE_FILE` re-injects the guardrails on **every** turn — this is
> what stops a long-running agent from "forgetting" it must not touch `main`.
> Goose Desktop must see these in its launch environment; for the CLI, `~/.zshrc`
> is enough. Verify with `goose info -v`.

**Custom-agent model field:** the `.agents/agents/*.md` files use
`model: ollama:deepseek-r1:14b` / `model: ollama:devstral:24b`. If your Goose build
rejects the `provider:model` form, change them to the bare name (`deepseek-r1:14b`)
— the provider then comes from `GOOSE_PROVIDER: ollama`.

### 3.4 Enable extensions
- **Developer** (shell + file editing) — required; on by default.
- **Memory** (optional, recommended): Desktop → Extensions → toggle `Memory`, or
  CLI `goose configure → Toggle Extensions → memory`. Stores to `.goose/memory/`
  (git-ignored). Use it to teach agents durable project conventions ("remember: new
  migrations must set a unique alembic revision id").

### 3.5 (Optional) Bake the workflow into every subagent
Override the subagent system prompt so *every* delegated agent inherits the
isolation lifecycle: copy Goose's `subagent_system.md` into
`%APPDATA%\Block\goose\config\prompts\subagent_system.md` and append a short pointer
to `.goosehints` + `.goose/guardrails.md`. (Do this only if you find subagents
skipping the worktree step.)

---

## 4. The feature lifecycle

Every feature follows this; the scripts enforce isolation so nothing collides.

1. **Plan** → `implementation_plan.md` written in the worktree (deepseek).
2. **Isolate** → `setup-worktree.sh <slug>` makes `.worktrees/<slug>` on branch
   `feat/<slug>` with a unique port block in `.env.local`.
3. **Run isolated services** → `run-services.sh` (private ports + compose project).
4. **Implement + commit often** (devstral).
5. **Validate** → `validate.sh` must pass.
6. **Sync with main (only when finished)** → `merge-revalidate.sh` merges latest
   `main` and re-validates (exit 2 = resolve conflicts; 1 = fix; 0 = ready).
7. **Document** → `gen-docs.sh <slug> "<Title>"` scaffolds the doc + wires README/
   index links; fill in prose; commit.
8. **Teardown** → `teardown.sh [--remove]` frees ports/containers.

### How isolation actually works
- Each worktree gets a deterministic-but-collision-checked block of 4 ports
  (Postgres/Redis/API/Frontend), recorded under `.worktrees/registry.tsv` behind a
  lock so parallel setups never clash.
- `docker compose --env-file .env.local -p <branch>` gives each worktree its own
  containers, network, **and named volumes** (`<branch>_postgres_data`), so their
  databases and Redis are fully separate.
- The main checkout still works on default ports with no `.env.local`.

---

## 5. Running it

**A single feature, end to end (recommended):**
```bash
goose run --recipe recipes/feature-pipeline.yaml \
  --params feature_slug=price-drop-alerts \
           feature_title="Price-drop alerts" \
           feature_description="Notify when a tracked listing drops in price."
```

**A batch (best for the 20 GB / one-model-at-a-time rule):**
```bash
# Phase 1 — plan everything (deepseek loads once)
for f in price-drop-alerts saved-searches map-clustering; do
  goose run --recipe recipes/plan-feature.yaml \
    --params feature_slug=$f feature_description="..." ; done

# Phase 2 — implement (devstral loads once); keep concurrency <= 2
goose run --recipe recipes/implement-feature.yaml \
  --params feature_slug=price-drop-alerts feature_title="Price-drop alerts"
```

**Conversationally in Goose Desktop** (no `/plan` keyword there — ask explicitly):
```
@orchestrator work the FEATURES.md queue: plan everything first, then implement
the top two in parallel. Create a plan before coding each one.
```
- `@planner` / `@coder` / `@reviewer` mention a single role.
- "Delegate to planner: ..." runs it in an isolated session and returns the result.

**Concurrency ceiling:** launch at most **2** coders at once. More agents just
queue on the one GPU and add KV-cache pressure without adding throughput.

---

## 6. Verification checklist

```bash
# scripts parse
bash -n scripts/agent/*.sh

# isolation works (dry run of one worktree)
bash scripts/agent/setup-worktree.sh smoke-test
cd .worktrees/smoke-test && cat .env.local        # unique ports?
bash scripts/agent/run-services.sh postgres redis # come up on private ports?
docker compose --env-file .env.local -p feat-smoke-test ps
bash scripts/agent/teardown.sh --remove           # cleans up

# goose sees the config
goose info -v                                      # provider/model/planner/recipe path
```

---

## 7. Gotchas

- **Don't** run `start.sh` / default-port compose while agents are working — it
  binds 5432/6379/8000 and can shadow a worktree that fell back to defaults.
- Migrations: if two features add Alembic revisions, they can collide on
  `down_revision`. The `reviewer` agent checks for this; sequence DB-heavy features.
- `deepseek-r1` is a reasoning model (token-heavy). Front-loading planning keeps it
  from stealing GPU time from implementation.
- Everything under `.worktrees/`, `.env.local`, and `.goose/memory/` is git-ignored.
