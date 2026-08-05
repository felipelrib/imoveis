---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: []
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'Imoveis stack verification — local vs cloud vs hybrid architecture with free-tier AI enrichment'
research_goals: 'Verify the current stack (FastAPI, Celery+Redis, PostGIS+pgvector, Ollama, React/Vite) still makes sense for local development with AI enrichment given the Gemma 31B ~14k RPD free-tier quota on the Gemini API; evaluate whether to migrate data/scraping/enrichment to a cloud instance on free tiers, or adopt a hybrid local-scraper + cloud-storage/enrichment approach.'
user_name: 'Felipe'
date: '2026-08-05'
web_research_enabled: true
source_verification: true
---

# Research Report: technical

**Date:** 2026-08-05
**Author:** Felipe
**Research Type:** technical

---

## Research Overview

This research verified the Imoveis stack (FastAPI, Celery + Redis, PostgreSQL/PostGIS/pgvector, Ollama, React/Vite) against its actual operating context — local-only development on a GPU workstation, a 396 MB and growing dataset, AI enrichment newly viable through the Gemini API's Gemma free quota (~14,400 RPD), and a free-tiers-only budget constraint — and evaluated three topologies: stay local, migrate fully to cloud, or split hybrid.

**Headline conclusion:** the stack survives verification intact, and full cloud migration fails the constraint test on three independent grounds (scraper IP reputation, loss of GPU fallback, storage caps). The recommended path is incremental: Cloudflare Tunnel for remote access now ($0, no migration), data pruning as a no-regrets prerequisite, and — only if 24/7 availability proves necessary — a CQRS-lite hybrid pushing a slim read-model projection to a scale-to-zero cloud Postgres. Full findings, decision matrix, and phased roadmap are in the Research Synthesis section at the end of this document.

---

<!-- Content will be appended sequentially through research workflow steps -->

## Technical Research Scope Confirmation

**Research Topic:** Imoveis stack verification — local vs cloud vs hybrid architecture with free-tier AI enrichment
**Research Goals:** Verify the current stack (FastAPI, Celery+Redis, PostGIS+pgvector, Ollama, React/Vite) still makes sense for local development with AI enrichment given the Gemma 31B ~14k RPD free-tier quota on the Gemini API; evaluate whether to migrate data/scraping/enrichment to a cloud instance on free tiers, or adopt a hybrid local-scraper + cloud-storage/enrichment approach.

**Technical Research Scope:**

- Architecture Analysis — current pipeline design (scrape → normalize → dedupe → enrich → dashboard) vs cloud/hybrid topologies; where each stage can legitimately live
- Implementation Approaches — migration paths (lift-and-shift vs hybrid split); impact on Celery/Redis/Alembic/config if storage moves off-box
- Technology Stack — free-tier viability per component: managed Postgres with PostGIS+pgvector, Redis hosting, container hosting for FastAPI/Celery, Gemma-31B-via-API vs local Ollama for enrichment
- Integration Patterns — local scraper → cloud DB connectivity, API auth, rate-limit budgeting against the ~14.4k RPD quota, residential-IP scraping constraints vs cloud egress
- Performance Considerations — free-tier limits (storage caps, connection limits, cold starts, sleep policies), geospatial query performance, enrichment throughput local vs cloud

**Research Methodology:**

- Current web data with rigorous source verification
- Multi-source validation for critical technical claims (free-tier limits and quotas especially, as they drift)
- Confidence level framework for uncertain information
- Comprehensive technical coverage with architecture-specific insights

**Scope Confirmed:** 2026-08-05

## Technology Stack Analysis

### Current Stack Verification (grounded in repo + live DB)

The existing stack — Python/FastAPI, Celery + Redis, PostgreSQL + PostGIS + pgvector, Ollama for local AI, React 19 + Vite 8 — is current-generation and healthy; nothing in it is legacy or being phased out. Recent repo history confirms active maintenance at the leading edge (PostGIS 17-3.5, MapLibre 6, Vite 8).

Grounding measurements taken 2026-08-05 from the running local stack:

_Database size: **396 MB** (`realestate`), **26,226 properties**, 24,161 with `vector(1024)` embeddings_
_AI config: multi-backend already implemented (`ai.backend: ollama | lmstudio | gemini | gemma`), Gemma runner (BIN-248) paced at 14,000 RPD budget, 3 requests/property, ~4,600 properties/day_
_GPU: RX 7900 XT 20GB, `qwen2.5vl:7b` VLM at `OLLAMA_NUM_PARALLEL=2`_
_Confidence: HIGH (direct measurement)_

### AI Enrichment: Local Ollama vs Gemma-via-API

**Gemma free-tier quota (Gemini API):** ~**30 RPM / 14,400 RPD / 16K TPM** for Gemma models on the free tier — corroborated by third-party trackers and matching the repo's observed BIN-248 limits exactly. Note one caveat: users report `ResourceExhausted` errors sometimes firing before the documented ceiling, so treat 14,400 as a best-case, not a guarantee.
_Source: https://gemma4-ai.com/blog/gemma4-free-api-limits (corroborated by repo `configs/app_config.yaml` backfill block, empirically validated in BIN-248/BIN-269)_
_Confidence: HIGH for the numbers; MEDIUM for sustained day-over-day reliability_

**Gemini Flash free tier (for comparison):** Gemini 3 Flash free tier is ~10 RPM / 1,500 RPD — an order of magnitude below Gemma's RPD; Gemini 2.5 Flash historically as low as 20 RPD on this account (per project memory). Gemma is the only Google free-tier model whose quota supports pipeline-scale enrichment.
_Source: https://tinkerllm.com/blog/gemini-api-free-tier-limits-rate-quotas/, https://www.aifreeapi.com/en/posts/gemini-api-free-tier-complete-guide_
_Confidence: MEDIUM (third-party; Google no longer publishes per-model tables — official limits now only visible in the AI Studio dashboard: https://ai.google.dev/gemini-api/docs/rate-limits)_

**Throughput comparison:** at 3 requests/property, Gemma free tier processes ~4,600 properties/day → full 26K-property re-enrichment ≈ 6 days. Local Ollama has no daily cap and no network dependency but is bounded by VRAM/concurrency (semaphore 2) and produced lower visual-assessment quality than full-res Gemma in the repo's own BIN-242 A/B. The two are complementary, not competing: Gemma for bulk/quality passes, Ollama for daily incremental + offline fallback.
_Confidence: HIGH (repo-internal evidence)_

### Database and Storage Free Tiers (the binding constraint)

_Supabase Free: **500 MB database**, shared 500 MB RAM instance, **projects pause after 1 week of inactivity**, max 2 active projects; pgvector included on all plans; PostGIS available as a standard extension._
_Source: https://uibakery.io/blog/supabase-pricing, https://infrafree.dev/en-us/provider/supabase_
_Confidence: HIGH_

_Neon Free: **0.5 GB storage/project**, 100 compute-hours/project/month, compute scales to zero after 5 min idle, suspends when monthly limit hit; supports PostGIS + pgvector (all standard extensions)._
_Source: https://neon.com/pricing, https://www.srvrlss.io/provider/neon/_
_Confidence: HIGH_

**Critical finding:** the live database is already **396 MB — ~80% of both free caps** — and grows with every scrape. A cloud migration of the full dataset onto a Postgres free tier is dead-on-arrival without either aggressive pruning (drop inactive listings, move embeddings out, trim price-history) or accepting a paid tier. The `vector(1024)` embeddings alone account for roughly 100+ MB across 24K rows before index overhead.
_Confidence: HIGH (direct measurement vs published caps)_

### Redis / Task Queue Free Tiers

_Upstash Redis Free: **500K commands/month**, 256 MB storage, 10 GB bandwidth. Compatibility caveat: Celery/Kombu workers poll the broker continuously (BRPOP + heartbeats); an always-on worker plausibly burns tens of thousands of commands/day, exhausting the 500K/month budget in under two weeks — before any real work. Upstash also doesn't support every Redis command/config Celery touches._
_Source: https://upstash.com/pricing/redis, https://agentdeals.dev/vendor/upstash_
_Confidence: HIGH for limits; MEDIUM for the exact Celery burn rate (estimate, not benchmarked)_

Implication: a cloud-hosted Celery + free-tier Redis combination is a poor fit. If anything moves to cloud, Redis should stay co-located with the worker (e.g., both on one free VM), or the cloud side should avoid Celery entirely (plain HTTP API + cron-style jobs).

### Container / Compute Hosting Free Tiers (2026 state)

The free-PaaS landscape contracted sharply:

_Fly.io: **no free tier** for new users (trial only: ~2 VM-hours or 7 days)._
_Railway: no free tier since 2023; one-time $5 trial credit._
_Render: still has a real free tier — 512 MB web services, **sleeps after inactivity with cold starts**, and free tier covers web services only, not persistent background workers._
_Source: https://expresstech.io/render-vs-railway-vs-fly-io-2026-pricing-showdown/, https://www.saaspricepulse.com/blog/flyio-free-tier-2026, https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026_
_Confidence: HIGH_

_Oracle Cloud Always Free: the one genuinely capable option — but **quietly halved June 15, 2026** from 4 OCPU/24 GB to **2 OCPU/12 GB ARM (Ampere A1)** for free-tier tenancies, with no announcement. Still enough to run the full compose stack (API + Celery + Postgres + Redis, no GPU). Known frictions: ARM capacity shortages ("Out of Capacity" in popular regions), and idle-resource reclamation requiring periodic activity._
_Source: https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/, https://terminalbytes.com/oracle-cloud-free-tier-changes-2026/_
_Confidence: HIGH_

### Scraping Egress: Datacenter vs Residential IP

2026 anti-bot reality: datacenter ASN ranges (AWS, GCP, Azure, DigitalOcean, and by extension Oracle/Render) are flagged wholesale by Cloudflare/DataDome-class protection; the datacenter-vs-residential success-rate gap widened further this year, and residential IPs are now described as "the minimum bar" for scraping protected targets. The current local setup scrapes from a residential ISP IP — an asset that any cloud migration of the *scraper* stage would destroy, forcing paid residential proxies to get back to parity.
_Source: https://www.scrapingbee.com/blog/web-scraping-without-getting-blocked/, https://www.twinstrata.com/residential-proxies-are-now-the-minimum-bar/, https://www.zenrows.com/blog/how-to-bypass-ip-ban_
_Confidence: HIGH (multi-source agreement + repo's own Cloudflare-403 incident history)_

### Technology Adoption Trends

_Local-first + API-hybrid AI is a mainstream 2026 pattern: local models for latency/privacy/unlimited-volume work, cloud free-quota models for quality-critical passes — exactly the multi-backend design the repo already implemented._
_Serverless Postgres (Neon-style scale-to-zero) has become the default for hobby/dev tiers, but storage caps (~0.5 GB) target prototypes, not accumulating datasets like scraped listings._
_The "free PaaS" era is ending (Heroku 2022, Railway 2023, Fly 2025-26, Oracle downgrade 2026) — free tiers are shrinking, so architectures that *depend* on them carry platform risk._
_Confidence: MEDIUM-HIGH_

## Integration Patterns Analysis

Focused on the three integration seams that decide the local/cloud/hybrid question: (a) how a local half and a cloud half would exchange data, (b) how remote access can be achieved *without* migrating, and (c) whether substituting technologies (per expanded scope) simplifies the cloud story.

### Source conflict resolved: Neon free-tier storage

A secondary source (Koyeb's 2026 free-tier roundup) claimed Neon free = "3 GiB per branch". Neon's official pricing page states **0.5 GB/project storage, 100 CU-hours/project/month, 100 projects, scale-to-zero after 5 min, and compute suspension when any monthly limit is hit**. The official page wins; the 396 MB database remains at ~80% of the cap.
_Source: https://neon.com/pricing (official, fetched 2026-08-05) vs https://www.koyeb.com/blog/top-postgresql-database-free-tiers-in-2026_
_Confidence: HIGH_

### Local → Cloud Data Sync Patterns (hybrid topology)

_**Logical replication (Postgres-native):** Neon officially documents replicating *from* a local/external Postgres *into* Neon (local = publisher, Neon = subscriber). This would let scraping + enrichment stay local while a cloud replica serves a dashboard. Caveats: replication of a 1024-d pgvector column + PostGIS types requires the same extensions on both ends (both supported on Neon); an always-streaming subscriber keeps Neon compute awake, eroding the 100 CU-hour budget; and the 0.5 GB cap applies to the replica too — so only a *pruned projection* (active listings, scores, no embeddings) realistically fits._
_Source: https://neon.com/docs/guides/logical-replication-postgres-to-neon_
_Confidence: HIGH that it works; MEDIUM on CU-hour economics under continuous streaming_

_**Periodic push (pg_dump / upsert batch):** cron-style nightly sync of a slim "serving schema" (properties + scores + price history, no embeddings, no raw payloads) over HTTPS or direct Postgres/TLS. Fits scale-to-zero free tiers far better than streaming: the cloud DB wakes briefly once a day. This is the documented budget pattern in the wild._
_Source: https://medium.com/@rkemon94/how-i-automated-postgresql-data-sync-from-neondb-to-local-db-a-step-by-step-journey-cd12f19af97d (inverse direction, same mechanics)_
_Confidence: HIGH_

_**Outbox-over-HTTP:** the local pipeline already has FastAPI + API-key auth; a cloud "read API" could ingest via authenticated batch POSTs. More code than logical replication but fully decoupled from Postgres versions/extensions and free-tier-friendly (short bursts)._
_Confidence: HIGH (standard pattern)_

### Remote Access Without Migration (the inverted integration)

_**Cloudflare Tunnel (free):** outbound-only `cloudflared` daemon from the local machine exposes the dashboard/API at a public hostname — no port forwarding, no inbound firewall rules, home IP never exposed; free plan includes Zero Trust Access for up to 50 users (SSO/email-gated access in front of the tunnel). This directly satisfies "reach my data from outside" without moving a single byte of the stack — the strongest counter-argument to any migration whose only driver is remote access._
_Source: https://recca0120.github.io/en/2026/04/14/cloudflare-tunnel-2026/, https://selfhostedguides.com/cloudflare-tunnels-zero-trust-access/_
_Confidence: HIGH_

_Constraint to respect: WSL2 + Windows host sleep/reboot means local uptime ≠ cloud uptime. A tunnel makes the dashboard reachable only while the workstation is on — acceptable for a single-user tool, not for always-on serving._
_Confidence: HIGH (inherent)_

### Frontend Split Pattern

_The React/Vite dashboard is a static build artifact — it can live on **Cloudflare Pages** (free: unlimited bandwidth, ~500 builds/month) or Vercel Hobby (~100 GB bandwidth) and call the API wherever it lives (tunnel hostname or cloud API) with the existing `API_KEY` auth + CORS configuration. This decouples "pretty URL for the dashboard" from "where the data lives" at zero cost._
_Source: https://speedvitals.com/blog/cloudflare-pages-vs-vercel/, https://thesoftwarescout.com/vercel-vs-cloudflare-pages-2026-which-deployment-platform-should-you-choose/_
_Confidence: HIGH_

### Technology Substitution: Queue Layer (expanded scope)

_**Postgres-native queues (Procrastinate, PgQueuer, pgmq):** use LISTEN/NOTIFY + `FOR UPDATE SKIP LOCKED` to eliminate Redis entirely — one fewer service everywhere, and the strongest simplification candidate for a cloud deployment. Two catches for Imoveis: (1) on serverless Postgres free tiers, a listening/polling worker holds a connection open and defeats scale-to-zero — an always-on 0.25 CU connection ≈ 180 CU-hours/month, **busting Neon's 100 CU-hour budget on its own** (MEDIUM confidence, arithmetic estimate); (2) Redis in this repo is not only Celery's broker — it also backs slowapi rate limiting, the `ui:locale` runtime override, and the `backfill:gemma` pacing state, so removing Redis is a multi-surface refactor, not a broker swap._
_Source: https://docs.bswen.com/blog/2026-06-18-celery-alternatives-2026/, https://lab.abilian.com/Tech/Python/Useful%20Libraries/Job%20queues/_
_Confidence: HIGH on the pattern; MEDIUM on effort sizing_

_**Modern Celery replacements (Dramatiq, Taskiq, Repid):** meaningfully leaner and async-native (Taskiq pairs well with FastAPI), but all still require a broker (Redis/RabbitMQ/NATS) — they do not change the cloud free-tier calculus at all. Migration would be lateral churn for this project's I/O profile (scraping is already throttled by politeness delays, enrichment by GPU/RPD budgets — queue throughput is not a bottleneck)._
_Source: https://pyrastra.com/posts/python-task-queues-celery-dramatiq-taskiq-2026/, https://aleksul.space/posts/choosing-python-task-queue-library/_
_Confidence: HIGH_

### AI Enrichment Integration (already cloud-ready)

_The repo's Gemma integration uses the Gemini API's **OpenAI-compatible endpoint** with env-only `GEMINI_API_KEY` and client-side RPD/RPM/TPM pacing persisted in Redis (`backfill:gemma`) — a location-independent pattern: the enrichment worker can run anywhere with outbound HTTPS. Quota budgeting stays correct as long as exactly one pacer owns the daily budget (single-writer constraint worth preserving in any hybrid split)._
_Confidence: HIGH (repo-internal)_

### Integration Security Patterns

_Applicable stack: existing API-key auth on FastAPI; Cloudflare Access (free, zero-trust SSO) in front of any tunnel hostname; TLS-required Postgres connections (`sslmode=require`) for any local→cloud DB link — Neon/Supabase enforce TLS by default; secrets remain env-only per repo convention (never in YAML). No new auth technology is required for any of the three topologies._
_Source: https://selfhostedguides.com/cloudflare-tunnels-zero-trust-access/, https://neon.com/docs (TLS default)_
_Confidence: HIGH_

## Architectural Patterns and Design

### System Architecture Patterns: the three candidate topologies

**Topology A — All-local + tunnel (current stack, remote access added).** Everything stays as-is; Cloudflare Tunnel + Access exposes the dashboard. Zero migration, zero new platform risk, keeps residential-IP scraping and free unlimited GPU enrichment. Weakness: availability is tied to the workstation being awake (WSL2 host).
_Change effort: ~0 (one daemon + DNS). Free-tier dependencies: Cloudflare only._

**Topology B — Full cloud lift-and-shift.** The whole compose stack on a free VM (realistically only Oracle Always Free, 2 OCPU/12 GB ARM). Verified blockers: scraping from a datacenter ASN degrades against Cloudflare-protected targets (would need paid residential proxies, breaking the free constraint); no GPU means Ollama fallback disappears entirely, leaving enrichment 100% hostage to one free API quota; Oracle capacity/reclaim frictions; and the June 2026 halving shows free compute can be repriced under you silently. 2026 self-hosting cost analyses also converge on "home hardware for bandwidth-heavy private workloads, cloud for public serving" rather than wholesale moves.
_Change effort: HIGH (ARM images, proxy procurement, ops). Verdict signal: the scraper and the GPU are the two components that objectively lose capability in cloud._
_Source: https://dev.to/pikapods/the-true-cost-of-self-hosting-vps-vs-managed-hosting-vs-diy-homelab-2ca4, https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/, https://www.twinstrata.com/residential-proxies-are-now-the-minimum-bar/_

**Topology C — Hybrid: local pipeline, cloud serving (CQRS-lite).** Scrape + dedupe + enrich + full DB (system of record, embeddings included) stay local; a nightly batch push publishes a pruned **read-model projection** (active listings, scores, price history — no embeddings, no raw payloads) to a free cloud Postgres (Neon fits best: scale-to-zero matches burst-sync), fronted by a thin read-only FastAPI on Render free (or by the static dashboard querying Supabase's auto-generated API). This is the textbook "lightweight CQRS: same write model, purpose-built read store" shape — the most common production CQRS form — and its known cost, eventual consistency, is irrelevant at a once-daily scrape cadence.
_Change effort: MEDIUM (sync job + slim schema + read API auth). Free-tier dependencies: 2–3 providers, each individually replaceable._
_Source: https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs, https://thecodinginterface.com/blog/cqrs-read-model-patterns/_
_Confidence: HIGH_

### Design Principles and Best Practices

_**Keep the pipeline a modular monolith.** The scrape→normalize→dedupe→enrich flow shares one schema and one transaction boundary; splitting it into cloud microservices adds distributed-systems failure modes with zero scalability payoff for a single-user system. The only architecturally natural seam is **write side vs read side** — which is exactly where Topology C cuts._
_**System of record stays where capability is highest.** Local Postgres keeps PostGIS dedupe, pgvector embeddings, and full history; anything in the cloud is a disposable, regenerable projection. This also mirrors 2026 local-first thinking (primary copy on owned hardware, sync outward), applied server-side._
_Source: https://wal.sh/research/local-first, https://verity.salient.community/research/local-first-software-in-2026.html_
_Confidence: HIGH_

### Scalability and Performance Patterns

_Single-user workload: horizontal scaling is a non-goal. The real performance budgets are (a) Gemma RPD (14,400/day → ~4,600 properties/day), (b) local VRAM concurrency (semaphore 2), (c) free-tier compute hours (Neon 100 CU-h — burst access only), and (d) scraper politeness limits. All four favor batch/burst patterns over always-on services; the architecture should treat "stay asleep by default" as the cloud-side design goal._
_Confidence: HIGH_

### Security Architecture Patterns

_Topology A/C both reduce exposed surface: A exposes one tunnel hostname behind Cloudflare Access (SSO, free ≤50 users); C exposes only a read-only projection with no scraper credentials, no API keys for enrichment, and no write path — a breach of the cloud read store loses nothing irreplaceable. Topology B would put scraper session state, `GEMINI_API_KEY`, and the full dataset on shared free infrastructure. Single-user auth needs: existing `API_KEY` + TLS everywhere; no new auth stack required._
_Source: https://selfhostedguides.com/cloudflare-tunnels-zero-trust-access/_
_Confidence: HIGH_

### Data Architecture Patterns

_**Slim serving schema** (Topology C): properties (~26K rows minus embeddings/raw JSON), scores, price-history deltas — plausibly 30–80 MB vs today's 396 MB, comfortably inside a 500 MB cap with years of headroom. Embeddings (`vector(1024)`, the dominant storage cost) never leave the local box — dedupe/similarity runs at write time locally, so the read side doesn't need pgvector at all (MEDIUM confidence: exact projection size unmeasured; estimate from column arithmetic)._
_**Storage-growth policy is needed regardless of topology:** at 396 MB and growing, even local hygiene (archiving inactive listings' raw payloads, pruning superseded price rows) extends every option's runway — and is a prerequisite for any free-tier cloud projection._
_Confidence: MEDIUM-HIGH_

### Deployment and Operations Architecture

_Docker Compose remains the right unit of deployment in all three topologies (compose-on-VM for B/C's cloud half; the repo's compose + validate.sh gates already encode ops knowledge). ARM note for Oracle: `postgis/postgis` and `pgvector` images publish arm64 variants, and Python/Node stacks are architecture-agnostic — but the repo's custom-built `imoveis-postgres` image with LLVM-dependent pgvector build steps (see BIN-272) would need an arm64 build pass (MEDIUM confidence — untested). Operational asymmetry: cloud free tiers add *external* failure modes (pause after 7 days idle on Supabase, CU-hour exhaustion on Neon, capacity reclaim on Oracle) that don't exist locally; each must be monitored or designed around (keep-alive pings, sync-job alerting)._
_Source: https://www.saaspricepulse.com/tools/neon, https://infrafree.dev/en-us/provider/supabase_
_Confidence: HIGH for the pattern; MEDIUM for ARM build specifics_

## Implementation Approaches and Technology Adoption

### Technology Adoption Strategies

_Incremental (strangler-fig-shaped) adoption is the verified best practice for this class of change: small, reversible steps, each delivering standalone value, rather than a big-bang move. Two documented failure lessons map directly onto Imoveis: (1) **data-synchronization complexity** between parallel systems is the top technical risk — argues for the simplest possible sync (nightly one-way batch, cloud side disposable/regenerable); (2) **stalling with two systems running indefinitely** doubles maintenance — argues for keeping the cloud side so thin (a projection, not a second pipeline) that there is no meaningful duplicate to maintain._
_Source: https://learn.microsoft.com/en-us/azure/architecture/patterns/strangler-fig, https://oneuptime.com/blog/post/2026-01-30-strangler-fig-pattern/view_
_Confidence: HIGH_

_Concretely, each phase is independently valuable and independently abandonable: tunnel (remote access, day one) → data hygiene (headroom everywhere) → static frontend split (pretty URL, free CDN) → read-model projection sync (always-on serving) — and full lift-and-shift never happens._
_Confidence: HIGH_

### Development Workflows and Tooling

_Nothing in any recommended topology disturbs the existing gates: validate.sh tiers, finish-feature.sh, contract tests, Alembic, and the docker-rebuild rules all stay authoritative for the local system of record. New surfaces added by the hybrid phase are small and testable within existing discipline: the projection sync job is a brownfield-SQL surface (characterization test locking the projection query before evolving it), and the cloud read API is thin glue (one happy/error path). CI already runs on GitHub Actions free for public/private repos at this scale; no workflow migration is implied by any topology._
_Confidence: HIGH (repo-internal)_

### Testing and Quality Assurance

_Per the repo's risk-tiered discipline: the slim-schema projection deserves oracle-first treatment (run it against the real 396 MB DB, lock row counts/sizes as fixtures) since its correctness claim — "the dashboard shows the same deals" — is empirical; enrichment behavior needs no new tests (backends already abstracted and A/B-validated in BIN-242); scraper tests are untouched because scraping never moves. Add one contract test asserting the cloud read API schema matches the local one so drift between the two FastAPI surfaces is caught mechanically._
_Confidence: HIGH_

### Deployment and Operations Practices

_The decisive operational addition in any topology is **dead-man's-switch monitoring** for the scheduled jobs that now matter (nightly scrape, Gemma backfill pacing, projection sync): healthchecks.io free tier (20 checks, 1-year retention, cron-aware with grace periods) pings-on-success and alerts when a job silently never runs — the failure mode cron actually has. Uptime Kuma (self-hosted, free) covers the complementary active-probe question ("is the tunnel/dashboard up?"). If Supabase is chosen over Neon, its 7-day-inactivity pause needs a scheduled keep-alive query — one more moving part in Neon's favor (scale-to-zero pauses compute, not the project)._
_Source: https://hyperping.com/blog/healthchecks-io-alternatives, https://futurion.blog/self-hosting-uptime-kuma-vs-healthchecks-io-honest-trade-offs-for-solo-builders/_
_Confidence: HIGH_

### Team Organization and Skills

_Solo-operator context: every recommended step uses skills already demonstrated in the repo (Docker/compose, Postgres/SQL, FastAPI, GitHub Actions). Net-new learning is limited to `cloudflared` configuration (hours, well-documented) and one cloud provider's dashboard. The rejected paths are also the skill-heaviest ones (ARM image debugging, proxy management, queue-framework migration) — effort better spent on product features._
_Confidence: HIGH_

### Cost Optimization and Resource Management

_The honest $0-vs-paid framing: 2026 cost analyses of self-hosting consistently find the dominant cost is operator time, not infrastructure. If any free-tier ceiling becomes a recurring time sink, the escape hatches are cheap and lateral: **Hetzner CAX11** (~$4–5/mo, 2 ARM vCPU / 4 GB / 40 GB NVMe — repeatedly called the best compute value on the market, with far better disk/network than Oracle's free ARM) replaces the entire cloud free-tier juggling act for the serving half; **Gemini paid Tier 1** replaces quota anxiety on the enrichment half. Neither requires architectural change — the topology-C seam accepts free or paid providers interchangeably, which is itself the cost-optimization: the architecture never depends on any single free tier surviving._
_Source: https://comparedge.com/tools/hetzner/pricing, https://www.bitdoze.com/hetzner-oracle-arm-performance/, https://dev.to/pikapods/the-true-cost-of-self-hosting-vps-vs-managed-hosting-vs-diy-homelab-2ca4_
_Confidence: HIGH_

### Risk Assessment and Mitigation

_**Free-tier repricing/revocation** (Oracle halved silently June 2026; Fly/Railway precedents): keep cloud side a disposable projection; never make a free tier the system of record. **Gemma quota instability** (`ResourceExhausted` before documented limits; Google can change RPD anytime): retain Ollama as permanent fallback backend — this is the strongest argument against deleting the local AI path. **Workstation downtime** (Topology A/C write side): acceptable by definition for a personal tool; mitigate visibility with healthchecks alerts, not with infrastructure. **DB growth** (396 MB → caps everywhere): pruning/archival policy is a no-regrets action. **Supabase pause / Neon CU exhaustion**: prefer Neon; sync bursts fit 100 CU-hours with large margin (nightly minutes-long wake). **ARM image build** (only if Oracle path is ever attempted): untested `imoveis-postgres` arm64 build — treat as a spike, not a plan._
_Confidence: HIGH for risk identification; MEDIUM for likelihood estimates_

## Technical Research Recommendations

### Implementation Roadmap

**Phase 0 — Cloudflare Tunnel + Access over the existing stack** (effort: ~half a day). Delivers the actual headline need — remote access to the dashboard — at $0 with zero migration. No-regrets regardless of later phases.

**Phase 1 — Data hygiene** (effort: 1–2 tickets). Archival/pruning policy for inactive-listing raw payloads and superseded price rows; measure the resulting "slim projection" size empirically. Buys headroom locally and is the gating prerequisite for any cloud projection.

**Phase 2 — Static frontend on Cloudflare Pages** (effort: ~1 ticket; optional). Vite build to Pages, pointed at the tunnel API with existing API-key auth + CORS. Pretty URL, global CDN, still $0.

**Phase 3 — Read-model projection to Neon + thin read API** (effort: a small epic; only if workstation-independent availability proves genuinely needed). Nightly batch push of the slim schema; read-only FastAPI (Render free) or direct-from-frontend queries; healthchecks.io on the sync job. Topology C realized.

**Explicitly not recommended:** full lift-and-shift (Topology B — scraping and GPU capabilities objectively degrade); queue-framework migration (lateral churn); Postgres-native queue adoption *for the cloud's sake* (busts Neon compute budget; multi-surface Redis refactor for no capability gain).

### Technology Stack Recommendations

**Keep (verified fit):** FastAPI, Celery + Redis (locally free-running, deeply integrated beyond brokering), PostgreSQL + PostGIS + pgvector as local system of record, Ollama as permanent enrichment fallback, React/Vite. The stack survives verification intact — the multi-backend AI layer (BIN-248) already implements the hybrid enrichment pattern this research would otherwise have recommended building.

**Add (when the phase calls for it):** cloudflared (P0), Cloudflare Pages (P2), Neon free + healthchecks.io (P3).

**Switch only on trigger conditions:** Hetzner CAX11 (~$5/mo) if free-tier juggling costs real time; Gemini paid Tier 1 if Gemma free RPD becomes unreliable; Supabase-instead-of-Neon only if its auto-generated REST API (skipping the thin read API entirely) outweighs the pause-management burden.

### Skill Development Requirements

Minimal: cloudflared/Zero Trust basics (P0), Neon dashboard + logical `pg_dump`/upsert mechanics (P3). No new languages, frameworks, or paradigms.

### Success Metrics and KPIs

- **Remote availability:** dashboard reachable from outside the LAN (P0: while workstation on; P3: 24/7 for reads).
- **Cost:** infrastructure spend stays $0/mo until a trigger condition is consciously accepted.
- **Enrichment throughput:** sustained ~4,000+ properties/day during Gemma backfills without `ResourceExhausted` stalls; Ollama fallback exercised at least monthly to stay warm.
- **Data headroom:** local DB growth rate measured; slim projection ≤ 200 MB (≤40% of a 500 MB cap) at P3 launch.
- **Ops signal:** zero silent failures — every scheduled job (scrape, backfill, sync) reports to a dead-man's switch.

---

# Research Synthesis: Keep the Stack, Invert the Migration — Local Pipeline, Cloud Projection

## Executive Summary

The Imoveis stack was put on trial against its real 2026 context: a solo-operated, gate-heavy pipeline on a GPU workstation, a 396 MB dataset growing with every scrape, enrichment newly turbocharged by the Gemini API's Gemma free quota (~30 RPM / 14,400 RPD / 16K TPM — verified against both third-party trackers and the repo's own empirically validated BIN-248 pacing), and a hard budget constraint of free tiers only. The verdict is unambiguous: **every component of the current stack is the right tool where it currently runs**, and the repo already implements the pattern this research would otherwise have prescribed — a multi-backend AI layer that uses cloud Gemma for bulk quality passes and local Ollama as an uncapped, offline-capable fallback.

Full cloud migration fails on three independent, verified grounds. First, scraping from any datacenter ASN is wholesale-flagged by 2026 anti-bot systems — residential IPs are now "the minimum bar," making the workstation's residential IP an asset a migration would destroy and paid proxies would have to buy back. Second, no free tier replaces a 20 GB GPU: cloud-only enrichment would be hostage to a single revocable quota. Third, the measured database (396 MB) already sits at ~80% of every free Postgres cap (Supabase 500 MB; Neon 0.5 GB — confirmed against Neon's official pricing over a conflicting secondary source), and the free-compute landscape itself is contracting (Fly and Railway free tiers dead; Oracle's Always Free silently halved to 2 OCPU/12 GB in June 2026). Meanwhile, the strongest driver for cloud — remote access — is fully solved without migration by a free Cloudflare Tunnel with Zero Trust Access.

The strategic recommendation is therefore an **inverted migration**: the local stack remains the system of record, and only a disposable, regenerable read-model projection ever goes to the cloud (CQRS-lite: slim schema without embeddings or raw payloads, nightly batch push to scale-to-zero Neon, thin read-only API). Each phase is independently valuable and abandonable, no phase requires new frameworks, and the architecture never depends on any single free tier surviving — the known escape hatches (Hetzner CAX11 at ~$5/mo, Gemini paid Tier 1) slot into the same seam without redesign.

**Key Technical Findings:**

- Gemma free tier (~14,400 RPD) is the only Google free-tier quota that supports pipeline-scale enrichment (~4,600 properties/day at 3 requests each); Gemini Flash free tiers are an order of magnitude smaller. Treat the ceiling as best-case — `ResourceExhausted` can fire early.
- The live DB (396 MB, 26,226 properties, 24,161 embeddings) exceeds practical free-Postgres headroom today; only a pruned projection (~30–80 MB estimated) fits sustainably.
- Free-tier Redis + Celery is structurally incompatible (broker polling alone would exhaust Upstash's 500K commands/month in under two weeks); Redis in this repo also backs rate limiting, locale, and quota pacing — so Redis stays, locally, where it is free-running.
- Queue-framework substitution (Dramatiq/Taskiq/Procrastinate) buys no cloud advantage: broker-based options don't change the calculus, and Postgres-native queues would bust Neon's 100 CU-hour budget with an always-listening worker.
- Cloudflare Tunnel + Access (free, ≤50 users) satisfies remote access with zero migration; Cloudflare Pages can host the static Vite dashboard for free whenever a stable URL is wanted.

**Technical Recommendations (top 5):**

1. **Phase 0 now:** Cloudflare Tunnel + Access over the existing stack (~half a day, $0, no-regrets).
2. **Phase 1 next:** data pruning/archival policy — prerequisite for any cloud projection and pure headroom locally.
3. **Keep Ollama permanently** as the enrichment fallback; never make the pipeline cloud-quota-hostage.
4. **Only if 24/7 reads prove necessary:** nightly slim-projection sync to Neon free + thin read-only API (Topology C), with healthchecks.io dead-man's-switch monitoring on every scheduled job.
5. **Never lift-and-shift** the scraper or the full DB to cloud free tiers; on sustained friction, pay laterally (Hetzner ~$5/mo or Gemini Tier 1) instead of re-architecting.

## Table of Contents

1. Research Scope Confirmation — topic, goals, methodology
2. Technology Stack Analysis — stack verification, Gemma vs Ollama quotas, DB/Redis/hosting free tiers, scraping egress, adoption trends
3. Integration Patterns Analysis — local→cloud sync options, tunnel-based remote access, frontend split, queue substitution verdicts, AI integration, security
4. Architectural Patterns and Design — the three topologies (A: local+tunnel, B: lift-and-shift, C: hybrid CQRS-lite), design principles, data architecture, deployment/ops
5. Implementation Approaches and Technology Adoption — incremental adoption strategy, workflows, testing, ops, cost, risk register
6. Technical Research Recommendations — phased roadmap, stack recommendations, skills, KPIs
7. Research Synthesis (this section) — executive summary, decision matrix, strategic outlook, source documentation

## Introduction and Methodology

**Why this research now:** three pressures converged in mid-2026 — the BIN-248/BIN-269 work proved cloud-quota enrichment viable at pipeline scale for the first time; the dataset crossed the size where free-tier caps became a real boundary rather than a distant abstraction; and the free-infrastructure market shifted under everyone's feet (Fly/Railway exits, Oracle's silent halving), making "just move it to a free cloud" a claim requiring verification rather than an assumption.

**Methodology:** every load-bearing claim was verified against current (August 2026) web sources, with official vendor pages overriding secondary roundups on conflict (exercised concretely: Neon's official 0.5 GB/project vs a secondary source's "3 GiB" claim). Claims were grounded against direct measurement of the running system (database size, row/embedding counts, live config) rather than estimates wherever possible. Confidence levels (HIGH/MEDIUM/LOW) are attached inline throughout; arithmetic estimates (Celery command burn, projection size, CU-hour consumption) are explicitly labeled as such.

**Goals achieved:** (1) stack verified component-by-component against the local + free-quota context — outcome: keep, with evidence; (2) full cloud migration evaluated — outcome: rejected on three verified grounds; (3) hybrid approach evaluated — outcome: viable and specified as a phased, reversible roadmap with explicit trigger conditions for each escalation.

## Topology Decision Matrix

| Criterion | A: Local + Tunnel | B: Full cloud (free tiers) | C: Hybrid (local SoR + cloud projection) |
|---|---|---|---|
| Scraping capability | ✅ residential IP kept | ❌ datacenter ASN flagged; paid proxies required | ✅ residential IP kept (scraper never moves) |
| AI enrichment | ✅ Gemma quota + GPU fallback | ⚠️ quota-only, no fallback | ✅ Gemma quota + GPU fallback |
| Data fits free tier | n/a (local disk) | ❌ 396 MB vs 500 MB caps, growing | ✅ slim projection ~30–80 MB (est.) |
| Dashboard availability | ⚠️ workstation-on only | ✅ 24/7 | ✅ 24/7 reads (writes lag ≤1 day) |
| Change effort | ~0 (half a day) | HIGH (ARM builds, proxies, ops) | MEDIUM (sync job + slim schema + read API) |
| Platform risk | minimal (1 free dep) | HIGH (Oracle precedent; single point) | LOW (2–3 deps, each disposable/replaceable) |
| Security surface | 1 tunnel behind SSO | full dataset + all secrets in cloud | read-only projection, nothing irreplaceable |
| Monthly cost | $0 | $0 nominal (+proxies in practice) | $0 |
| **Verdict** | **Do now (Phase 0)** | **Rejected** | **Do when 24/7 reads are needed (Phase 3)** |

## Strategic Outlook

**Near term (6–12 months):** the free-tier contraction trend is expected to continue — architectures should treat free quotas as weather, not climate. The Gemma quota specifically is generous today precisely because Google is competing for developer attention on open-weight models; budget-paced consumption (already implemented) plus a warm local fallback is the correct hedging posture, not deeper dependence.

**Medium term (1–3 years):** two developments could legitimately reopen this analysis: (a) local model quality closing the gap that currently makes Gemma the quality pass (the repo's A/B infrastructure from BIN-242 makes re-testing cheap), and (b) sync-engine maturation ("2026: the year of the sync engine") potentially making the local↔cloud projection a solved commodity rather than a custom job. Neither changes the core invariant worth carrying forward: **the system of record lives where the capabilities (GPU, residential IP, unmetered storage) live; the cloud gets projections.**

## Source Documentation and Quality Assurance

**Primary sources (official/vendor):** neon.com/pricing (fetched directly to resolve a source conflict); ai.google.dev/gemini-api/docs/rate-limits (confirmed per-model tables are no longer published — limits now live in the AI Studio dashboard); neon.com/docs logical-replication guides; upstash.com/pricing/redis; learn.microsoft.com CQRS and Strangler Fig pattern references.

**Secondary sources (cross-checked, ≥2 where load-bearing):** 2026 free-tier trackers and comparisons (infrafree.dev, agentdeals.dev, saaspricepulse.com, uibakery.io, komparisons via expresstech.io/snapdeploy.dev), InfoQ + TerminalBytes on the Oracle June 2026 halving, scraping-industry analyses (scrapingbee.com, zenrows.com, twinstrata.com), Python task-queue comparisons (bswen.com, pyrastra.com, aleksul.space, lab.abilian.com), self-hosting cost analyses (dev.to/pikapods), monitoring comparisons (hyperping.com, futurion.blog), Hetzner pricing roundups (comparedge.com, bitdoze.com).

**Repo-internal evidence (highest confidence):** live DB measurement (396 MB / 26,226 / 24,161), `configs/app_config.yaml` (multi-backend AI, backfill pacing, GPU semaphore), BIN-242 A/B results, BIN-248/BIN-269 empirical quota validation, BIN-272 image build history.

**Search queries executed (16):** Gemma/Gemini free-tier limits (×3 including official fetch), Supabase free tier, Neon free tier (×2 including official fetch), Upstash/Celery, PaaS free-tier comparison, scraping datacenter-vs-residential, Oracle Always Free 2026, Celery alternatives, Cloudflare Tunnel, local-Postgres→Neon replication, Pages-vs-Vercel, homelab-vs-VPS economics, CQRS read models, local-first sync engines, strangler-fig migration, Hetzner pricing, monitoring tools.

**Known limitations:** exact Gemma RPD reliability day-over-day is not guaranteed by Google (documented tables withdrawn); projection size (30–80 MB) and Celery command-burn figures are arithmetic estimates, not measurements; ARM build compatibility of the custom `imoveis-postgres` image is untested; free-tier terms cited here have a shelf life measured in months — re-verify caps before executing Phase 3.

## Conclusion

The stack is not the question — the topology is. Every technology in the current stack earned its place when verified against 2026 realities, and the components that a cloud migration would forfeit (residential scraping IP, 20 GB of free GPU compute, unmetered storage) are precisely the ones free tiers cannot replace. The pragmatic path inverts the usual migration: keep the pipeline sovereign and local, publish only a slim, disposable projection outward, gate each phase on demonstrated need, and let cheap paid options ($5/mo compute, Tier 1 API) — not re-architecture — absorb any future free-tier failures.

**Next steps:** Phase 0 (tunnel) can be a single ticket this week; Phase 1 (pruning policy) is one small epic and unlocks everything else; Phases 2–3 wait for their trigger conditions. Suggested tracking: one Linear epic per phase under the next versioned milestone, refined via the standard planning bridge when picked up.

---

**Technical Research Completion Date:** 2026-08-05
**Research Period:** current comprehensive technical analysis (August 2026 sources)
**Source Verification:** all load-bearing claims cited; official sources override secondary on conflict
**Technical Confidence Level:** HIGH overall — grounded in direct system measurement plus multi-source web verification; MEDIUM items individually flagged inline

_This comprehensive technical research document serves as an authoritative reference on the Imoveis local/cloud/hybrid decision and provides strategic technical insights for informed decision-making and implementation._
