---
title: 'Story 1.18 — Periodic tasks are not blocked by scrapes'
type: 'bugfix'
created: '2026-10-08'
status: done
baseline_revision: '5fda254a4a8afc0c79823056fba678ef44f35e1a'
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/AGENTS.md'
  - '{project-root}/docs/features/_template.md'
warnings: ['oversized']
operator_actions:
  - >-
    AGENT-RUNNABLE. After the branch is merged, rebuild and restart the primary stack from the
    primary checkout so that worker_periodic exists and the API, the workers and beat run the
    new routing (no database migration): ./scripts/restart.sh --build . Verify read-only:
    docker ps --filter name=imoveis-worker_periodic --format "{{.Names}} {{.Status}}" shows
    imoveis-worker_periodic-1 Up; docker exec imoveis-worker_periodic-1 celery -A
    adapters.queue.tasks inspect active_queues lists periodic on the periodic node, scrapers
    and celery on the scraper node, ai on the ai node. Record under "Operator results" in
    docs/features/v0.14-s1.18-periodic-tasks-not-blocked-by-scrapes.md.
  - >-
    AGENT-RUNNABLE. Measure the old backlog, read-only: docker exec imoveis-redis-1 redis-cli
    llen scrapers and docker exec imoveis-redis-1 redis-cli llen periodic, then the dry run
    from the primary checkout: .venv/Scripts/python.exe scripts/ops/purge_stale_periodic.py
    --dry-run (first line names the Redis it is aimed at, before it reads anything: it must be
    redis localhost:6379/0; then one count per task type, marked removable or kept; it writes
    nothing). Expected: periodic is a single digit, scrapers is in
    the thousands, mostly tasks.snapshot_pipeline_metrics and tasks.monitor_queues. Record the
    counts in the same section.
  - >-
    AGENT-RUNNABLE (optional, recommended). Remove the stale housekeeping messages from the
    old backlog: .venv/Scripts/python.exe scripts/ops/purge_stale_periodic.py --apply . Its
    first line names the target Redis before anything is removed. It removes only
    tasks.snapshot_pipeline_metrics, tasks.monitor_queues,
    tasks.evaluate_watchlist_alerts and tasks.match_saved_search_new_matches from scrapers and
    refuses anything else. Recommended because draining them through worker_scraper writes
    thousands of snapshot rows stamped with the time they run and delays the scrapes behind
    them; skipping this step is safe, the backlog then drains by itself. Verify: the report's
    "removed" total matches the dry run minus "gone", and llen scrapers dropped by that much.
    Record removed and gone in the same section.
  - >-
    AGENT-RUNNABLE. Confirm a periodic task runs inside its interval while a scrape is in
    flight. While docker logs --since 20m imoveis-worker_scraper-1 2>&1 | grep -E "Task
    tasks.scrape_listings|scrape_completed|scrape_skipped_already_running" shows a scrape
    received and not yet completed, docker logs --since 20m imoveis-worker_periodic-1 2>&1 |
    grep -E "queue_monitor|pipeline_metric_snapshot_written|saved_search_new_match_run" must
    show queue_monitor lines about 60 s apart, snapshot lines about 30 s apart and at least one
    saved_search_new_match_run within 15 minutes of the rebuild. Record the timestamps in the
    same section.
  - >-
    AGENT-RUNNABLE. Confirm scrapes are single-flight: docker logs --since 6h imoveis-beat-1
    2>&1 | grep scrape_enqueue_skipped shows skipped ticks with reason queued or running for a
    platform whose scrape outlasts its interval; docker exec imoveis-redis-1 redis-cli --scan
    --pattern "scrape:single_flight:*" lists at most one running and one queued lease per
    platform and scope, and docker exec imoveis-redis-1 redis-cli ttl <key> is positive for
    each; the worker_scraper log does not show QuintoAndar window fetches from both
    ForkPoolWorker processes at the same time. Record in the same section.
  - >-
    HUMAN-ONLY (decision). The development of this story left two things on the primary Redis
    by mistake (a raw test run on 2026-10-08): one tasks.scrape_listings message on scrapers
    (id fd1f4df9-1898-4d68-91c1-88daa7ad62bd, a manual OLX scrape, scrape_type both) and the
    lease key scrape:single_flight:olx:2fe9313c54db7883:queued:lease with its :meta hash.
    Options: leave them (recommended: the lease expires by itself within three hours of 20:00
    UTC and the old code ignores it; the message runs one ordinary OLX scrape of about a
    minute), or remove them by hand (LREM scrapers 1 <exact payload>, DEL of the two keys). If
    nothing is done, the first option happens. Verify either way: docker exec imoveis-redis-1
    redis-cli exists scrape:single_flight:olx:2fe9313c54db7883:queued:lease returns 0 after
    23:10 UTC.
  - >-
    HUMAN-ONLY (decision). About 193 tasks.scrape_listings messages published before this
    story are still on scrapers and the purge tool never removes a scrape. Options: let them
    drain (recommended: one that starts while a scrape of its platform is running is skipped
    and consumed, one that starts while none is running scrapes, so they run one at a time per
    platform, which is no worse than today and nothing new piles up behind them), or delete
    the old scrape messages by hand to return to the hourly schedule at once. If nothing is
    done they drain; how long that takes was not measured (while one slot holds a long scrape
    the other slot consumes the queue behind it). Verify the trend with the dry run of the
    purge tool: the tasks.scrape_listings count falls and does not grow.
deferred:
  - summary: >-
      One scheduled QuintoAndar scrape cannot finish inside its 60-minute interval: it walks
      about 1,500 price windows per city over three cities, so a scraper slot is held for
      more than three hours per run.
    evidence: |-
      Read on the primary worker log, read-only, 2026-10-08 16:34 to 19:41 UTC: 4,777
      price-window fetches in three hours across two concurrent runs of the same scrape
      (3,341 URLs fetched by both processes, none twice by one); alugar windows per city:
      Sao Paulo 1,589, Belo Horizonte 1,556, Campinas 1,510; windows split down to R$ 13
      wide; neither run had finished after 3 h 07 min, while the OLX and ZapImoveis scrapes
      finished in 38 s and 93 s. Cause, read in src/adapters/scrapers/quintoandar.py
      fetch_pages: a breadth-first price-window funnel (12 results per SSR page, split while
      saturated, then neighbourhood and house-type fan-out) under rate_limit 30/min with 2-7 s
      jitter, over the three cities of configs/app_config.yaml scraping.platforms.quintoandar
      .extra.cities. Expected from the design, not a parsing defect; the duplicate concurrent
      run was the defect and Story 1.18 removes it. Whether Sao Paulo and Campinas belong in
      the schedule of a Belo Horizonte decision engine, and whether the interval should match
      the run length, is a product decision. Not measured: the length of one complete run.
    location: >-
      configs/app_config.yaml:110
    severity: medium
  - summary: >-
      After the deploy the scrape_listings messages already on scrapers (193 counted) run one
      after the other, one per platform at a time, until they are gone; nothing coalesces them.
    evidence: |-
      Counted read-only on 2026-10-08: 193 tasks.scrape_listings among 11,716 messages on the
      primary scrapers list. The purge tool never removes a scrape (story rule). Each legacy
      message that starts while no scrape of its platform runs is a full scrape; for
      QuintoAndar that is more than three hours each, and the beat publishes nothing for a
      platform while one runs, so scraping is continuous until the backlog is consumed. This is
      no worse than before the story (the same messages ran, two at once). Options for the
      operator: let it drain, or remove old scrape messages by hand; a code option is to skip
      a scheduled scrape that starts soon after one of the same platform completed.
    location: >-
      src/adapters/queue/tasks.py:336
    severity: low
  - summary: >-
      The SPA does not show the new queue or why the workers are not ok: the Celery card
      says offline for an unconsumed queue without the reason, and Scraper Control shows two
      queue lengths.
    evidence: |-
      frontend/src/pages/Dashboard.tsx:93,100 maps any workers.status other than ok to
      offline and never renders workers.detail or unconsumed_queues;
      frontend/src/pages/ScraperControl.tsx types and renders queues.scrapers and queues.ai
      only. The third part of this item (the manual trigger said "enqueued" for
      already_queued and already_running) was fixed in the follow-up review.
    location: >-
      frontend/src/pages/Dashboard.tsx:93
    severity: low
  - summary: >-
      The Dashboard history has no series for the periodic queue: the snapshot row stores the
      scrapers and ai lengths only.
    evidence: |-
      PipelineMetricSnapshot (src/adapters/db/models.py:501) has scraper_queue and ai_queue.
      Story 1.18 reports periodic_queue in the snapshot task result, its log line, the monitor
      log and GET /system/pipeline, and stores nothing: a third column needs a migration, a
      change to src/api/schemas.py (serial surface) and to the Dashboard chart, and the
      migration cannot be applied while a backfill holds the guard.
    location: >-
      src/adapters/metrics/pipeline_snapshots.py:34
    severity: low
  - summary: >-
      worker_periodic has two slots and no task on it has a time limit, so two long jobs at
      once (the availability recheck and a refresh job) delay the short periodic tasks until
      one ends.
    evidence: |-
      docker-compose.yml worker_periodic runs --concurrency=2. recheck_listing_availability
      probes up to 50 URLs with a 20 s timeout each (about 17 minutes worst case, every six
      hours); refresh_neighbourhood_amenities in overpass mode sleeps for its rate limit; none
      has time_limit or soft_time_limit (only ai_enrich has). The weekly refresh jobs are off
      in the committed config, so today one slot at most is held. Stale housekeeping ticks
      expire meanwhile; the hourly sender waits.
    location: >-
      docker-compose.yml:159
    severity: low
  - summary: >-
      A scrape killed without SIGTERM keeps its running lease for up to two hours, because the
      lease is renewed from the item loop and has no time-based heartbeat that would allow a
      short TTL.
    evidence: |-
      src/adapters/queue/scrape_single_flight.py RUNNING_TTL_SECONDS is 2 h and renew() is
      called per yielded item. A graceful worker stop releases the lease (shutdown hook added
      in review); an OOM kill or power loss does not, and the redelivered message of that id
      returns skipped while the lease lives. POST /scrape (own scope) starts a scrape at once.
      A renewer thread in the task (the backfill runner has the pattern) would allow a TTL of
      minutes and remove the dependence on items being yielded; on 2026-10-08 the longest gap
      between item-level log lines of a run was 112 s in a 12-minute sample.
    location: >-
      src/adapters/queue/scrape_single_flight.py:33
    severity: low
  - summary: >-
      A second consumer of the scrapers queue would let a scrape start beside one that
      outlives a graceful stop, because the shutdown hook frees the lease when the stop is
      requested, not when the task ends.
    evidence: |-
      Celery sends worker_shutting_down from the signal handler and then waits for running
      tasks. Checked on a real Celery 5.6.3 prefork worker in a scratch container
      (2026-10-08): the running lease was gone within a second of SIGTERM and the scrape ran
      21 more seconds to completion. With the committed layout nothing can start in that
      time: worker_scraper is the only consumer of scrapers and under docker stop it is
      killed after ten seconds. docs/setup.md "Scaling" still says scraper workers scale
      horizontally; with two consumers and a stop that is allowed to wait, the beat would
      queue a scrape that the other worker starts while the first is finishing. A time-based
      heartbeat with a short TTL (the hard-kill item above) replaces the hook and closes
      this; until then the scaling sentence in docs/setup.md should say one scraper worker.
    location: >-
      src/adapters/queue/tasks.py:364
    severity: low
  - summary: >-
      The architecture spine still lists the Celery services as scrapers, ai and beat (AD-7);
      the periodic worker is not in it.
    evidence: |-
      _bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/
      ARCHITECTURE-SPINE.md AD-7: "Docker Compose (Postgres/PostGIS, Redis, API, Celery
      scrapers + ai + beat, ...)". Story 1.18 adds worker_periodic and states it in AGENTS.md
      and docs/; the spine is a planning artifact amended by the architecture workflow, not by
      a dev session.
    location: >-
      _bmad-output/planning-artifacts/architecture/architecture-imoveis-2026-07-23/ARCHITECTURE-SPINE.md:115
    severity: low
---

<intent-contract>

## Intent

**Problem:** Every non-AI Celery task, including all beat-scheduled ones, is routed to `scrapers`, whose worker has two slots. On the primary (2026-10-08) both slots were held for more than three hours by two concurrent runs of the same QuintoAndar scrape, about 11,600 messages waited on `scrapers` (mostly `snapshot_pipeline_metrics`, `monitor_queues`, `evaluate_watchlist_alerts`), and the 15-minute saved-search matcher had not run once two hours after a rebuild (DW-63).

**Approach:** Give short periodic work its own queue `periodic` with its own worker service, so it never waits for a scrape slot; make idempotent beat entries expire after one interval so missed ticks coalesce; and make `scrape_listings` single-flight per platform and scope with an expiring lease, so the beat cannot queue a duplicate behind a queued or running scrape and a duplicate that is delivered anyway does not run.

## Boundaries & Constraints

**Always:**
- Three routed queues, named once as constants: `scrapers` (only `tasks.scrape_listings` and the operator-triggered `tasks.backfill_listing_costs`), `ai` (`tasks.ai_enrich`, `tasks.embed_property`, unchanged, GPU semaphore unchanged) and `periodic` (every other task). Every task `build_beat_schedule()` can emit has a `task_routes` entry.
- A worker service `worker_periodic` in `docker-compose.yml` consumes `periodic` and nothing else; `worker_scraper` keeps consuming `scrapers,celery` and never `periodic`. Same image (`Dockerfile.worker`), same environment and volumes as `worker_scraper`, concurrency 2, `restart: unless-stopped`.
- Messages published under the old routing stay on `scrapers` and must still run there: every worker loads the same task module, so no task is removed or renamed and `worker_scraper` keeps its queue list.
- `expires` (seconds, equal to the entry's own interval) on these beat entries only: `monitor-queues`, `snapshot-pipeline-metrics`, `evaluate-watchlist-alerts`, `match-saved-search-new-matches`, `recheck-listing-availability`, `refresh-neighbourhood-amenities`, `refresh-transit-proximity`, `refresh-neighbourhood-access`, `refresh-listing-claim-stats`. Never on `send-saved-search-new-match-alerts`, `send-daily-digest`, `send-top-deals-digest` or `scrape-*`.
- The scrape single-flight reuses `core.backfill_runner.BackfillLease` (atomic `SET NX EX`, owner-token renew and release). Both leases have a TTL; nothing in it blocks scraping without a time limit.
- A duplicate scrape that is skipped never releases or renews a lease it does not own.
- The purge script only reads unless `--apply` is given, only ever removes the four allowlisted task types, and is never invoked by any other script, hook, test against a real broker, or task.

**Never:**
- No database migration, no change to `src/api/schemas.py`, `src/infra/config.py`, `configs/app_config.yaml`, `frontend/`, `docker-compose.test.yml`, `.claude/`, `.bmad-loop/` or `sprint-status.yaml`.
- No change to how a scrape fetches, paginates, rate-limits or persists; no change to scrape intervals.
- No GPU work, AI client call or `ai`-queue task on `periodic`.
- No `expires` on the hourly sender or the digests; no purge of `scrape_listings`, sender, digest, `backfill_listing_costs`, recheck, refresh, alert or AI messages.
- No docker command against project `imoveis`, no write to the primary Redis, no read of `.env.local`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Route table | `make_celery().conf.task_routes` | `scrape_listings` and `backfill_listing_costs` → `scrapers`; `ai_enrich`, `embed_property` → `ai`; all others → `periodic` | — |
| No shared queue | every optional beat branch enabled | no scheduled task except `tasks.scrape_listings` routes to the queue of `tasks.scrape_listings` | — |
| Every queue consumed | `docker-compose.yml` worker commands | each queue in `task_routes` appears in a worker `--queues=`; `periodic` and `scrapers` are never on the same worker; `ai` only on `worker_ai` | — |
| Housekeeping expiry | maximal beat config | the nine idempotent entries carry `options.expires` == their interval in seconds | — |
| Must-not-lose entries | maximal beat config | sender, both digests and every `scrape-*` entry carry no `expires` | — |
| Beat tick, platform free | no lease for (platform, scope) | queued lease taken with the new task id, message published with that id | publish raises → queued lease released, error propagates |
| Beat tick, already queued | queued lease held | nothing published, `scrape_enqueue_skipped` logged with reason `queued`, entry still advances | — |
| Beat tick, in flight | running lease held | nothing published, reason `running`, entry still advances | — |
| Task starts, owns reservation | queued lease token == task id | queued lease released, running lease taken, scrape runs, running lease released at the end (success or failure) | failure → lease released before the retry is scheduled |
| Task starts, other run in flight | running lease held by another execution (legacy backlog message, or a redelivery of the same id) | returns `{"status": "skipped", "reason": "already_running", "platform": ...}` without creating a scraper, opening a DB session or touching the other run's leases | — |
| Task starts, no reservation | legacy message, no lease | takes the running lease itself and runs | — |
| Scrapers paused | `workers:scrapers:paused` set | own queued lease released, then the existing retry | — |
| Long run | scrape lasts longer than the running TTL | running lease renewed at most once a minute from the item loop | renew reports lost → warning `scrape_single_flight_lost`, run continues |
| Crashed run | process killed, lease never released | lease expires by TTL; the next tick after that queues a scrape | — |
| Scope | no checkpoint override → `default`; override → stable digest of the override | different scopes of one platform do not block each other | — |
| Manual trigger duplicate | `POST /scrape` while same platform+scope queued or running | 200, `status` `already_queued` or `already_running`, `task_id` of the holder, nothing published | — |
| Queue lengths | `GET /system/pipeline` | `queues` has `scrapers`, `ai`, `periodic` | — |
| Snapshot | `snapshot_pipeline_metrics` | result and log line include `periodic_queue`; the stored row is unchanged | — |
| Monitor | `monitor_queues` | logs `ai_queue`, `scrapers_queue`, `periodic_queue`; warns `queue_monitor_periodic_backlog` above 100; pause logic on `ai` unchanged | — |
| Unconsumed queue at runtime | a routed queue has no worker | `GET /system/status` `workers.status` is `error`, `detail` names the queue(s), `unconsumed_queues` lists them | no worker replies → existing `No workers responding` |
| Purge dry run | list with mixed task types | prints counts per task type, marks which are removable, removes nothing, exit 0 | — |
| Purge apply | `--apply` | removes only `tasks.snapshot_pipeline_metrics`, `tasks.monitor_queues`, `tasks.evaluate_watchlist_alerts`, `tasks.match_saved_search_new_matches`; prints removed counts; unparseable payloads are counted as `unparseable` and kept | a payload already consumed by a worker counts as `gone`, not an error |
| Purge wrong queue or task | `--queue ai`, or `--task tasks.scrape_listings` | refused with exit 2 before reading anything | — |

</intent-contract>

## Code Map

- `src/adapters/queue/celery_app.py` -- `make_celery()` holds `task_routes` (about line 244, all non-AI → `scrapers`) and `build_beat_schedule()` builds entries as plain dicts (`task`, `schedule`, sometimes `args`/`kwargs`). Add the queue constants (`QUEUE_SCRAPERS`, `QUEUE_AI`, `QUEUE_PERIODIC`, `ROUTED_QUEUES`) here; they are the one definition every other module imports.
- `src/adapters/queue/redis_scheduler.py` -- `RedisAwareScheduler(PersistentScheduler).apply_entry` already skips a disabled `scrape-*` entry by returning without calling super; Celery's `tick` advances the entry regardless. Celery 5.6.3 `Scheduler.apply_entry` swallows publish errors, and `Scheduler.apply_async(entry, producer=None, advance=True, **kwargs)` publishes with `**entry.options` (kwargs are ignored), so the single-flight belongs in an `apply_async` override that sets `task_id` through a temporary copy of `entry.options` and restores it.
- `src/adapters/queue/tasks.py` -- `scrape_listings` (line 329; `bind=True`, `autoretry_for=(Exception,)`, `max_retries=3`; opens `SessionLocal()` before the paused check at line 350; per-item loop calls `_write_scraper_status`; `finally` closes the session and deletes the status key). `monitor_queues` (1152) reads only `llen("ai")`. `snapshot_pipeline_metrics` (1176). `_enqueue_post_scrape_jobs` publishes with `queue="ai"` (keep). Comment at 1295 says "the scrapers worker has more than one process" (now the periodic worker).
- `src/core/backfill_runner.py:664` -- `BackfillLease(redis, *, prefix, ttl_seconds, token, owner)`: `acquire()`, `renew()`, `release()`, `holder()`; key is `<prefix>:lease`. Reuse as is; do not edit this file.
- `src/api/main.py:110` -- `trigger_scrape` calls `scrape_listings.delay(req.platform, checkpoint)` with `checkpoint["scrape_type"]` always set; returns a plain dict (no response model).
- `src/api/admin.py:469,484,503` -- three `apply_async(queue="scrapers")` for recheck, access refresh and claim stats: an explicit queue overrides `task_routes`, so these must name the periodic queue constant.
- `src/api/system.py:72` `_check_workers` (uses `inspect().ping()`), `:258` `_pipeline_queue_lengths` (two queues). `src/adapters/metrics/pipeline_snapshots.py` `collect_snapshot_fields` / `snapshot_and_prune` (two queue columns; `write_snapshot` ignores unknown keys; `PipelineMetricSnapshot` has no third column and gets none).
- `docker-compose.yml` -- `worker_scraper` (`--queues=scrapers,celery --concurrency=2`), `worker_ai` (`--queues=ai`), `beat`. No script enumerates services (`scripts/start.sh`, `restart.sh`, `stop.sh`, `lib.sh` pass through to compose), so a new service starts with the stack. `docker-compose.test.yml` has only postgres and redis.
- Tests that pin the old routing and must be updated, not deleted: `src/tests/unit/test_schedule.py` (`test_make_celery_applies_broker_routes_and_schedule`, `test_beat_maintenance_tasks_routed_to_scrapers_queue`, `test_every_scheduled_task_has_a_route` with `consumed_queues = {"scrapers", "ai"}`), `src/tests/unit/test_celery_app.py` (`test_both_tasks_are_routed_to_the_scrapers_queue`), `src/tests/unit/test_redis_scheduler.py`, `src/tests/unit/test_scrape_listings_pipeline.py`, `test_scrape_run_telemetry.py`, `test_scrape_proxy_observability.py`, `test_bin159_reliability.py` (call `scrape_listings` with a `MagicMock` redis whose `set()` is truthy), `test_pipeline_metric_snapshots.py`, `test_system_status_counts.py`, `src/tests/contract/test_api_contract.py`, admin tests asserting `queue="scrapers"`.
- Docs naming the two-queue layout: `AGENTS.md` (Celery bullet), `docs/architecture.md:64-68`, `docs/setup.md:212-218`, `docs/harness-troubleshooting.md:128`, `docs/deployment-guide.md:16`, `docs/development-guide.md:20`, `docs/integration-architecture.md`, `docs/project-overview.md:21`, `docs/source-tree-analysis.md:63`, `README.md:28`.
- `_bmad-output/implementation-artifacts/deferred-work.md:638` -- DW-63, `status: open`; resolved entries carry `status: resolved` plus a `resolution:` line (see DW-53).
- Evidence read on the primary, read-only, 2026-10-08 19:40 (for the feature doc): `llen scrapers` 11,640, `llen periodic` 0; two `scrape_listings` received 16:34 and 16:36 still running at 19:41, both fetching QuintoAndar price windows (`ForkPoolWorker-1` and `-2`); in three hours 4,777 window fetches, 3,341 URLs fetched by both processes, none fetched twice by one process; windows per city: `alugar` São Paulo 1,589, Belo Horizonte 1,556, Campinas 1,510; price windows split down to R$ 13 wide; the other platforms' scrapes finished in 38 s and 93 s; no task id was received twice in 48 h.

## Working Rules

- The repository root for this work is the git worktree that contains this spec (`C:\Workfolder\imoveis\.run\wt-18`, branch `feat/v0.14-s1.18-periodic-tasks-not-blocked-by-scrapes`). A shell may start elsewhere: `cd` there or use absolute paths for every read, edit and command. Never edit anything under `C:\Workfolder\imoveis` outside that worktree.
- Python interpreter: `C:\Workfolder\imoveis\.venv\Scripts\python.exe` (the worktree has no venv). Single test files may be run with it while developing; the gate (`scripts/agent/validate.py`) is run by the parent session, not by the implementer.
- Do not commit, push, merge or run `ship.py`. Do not run any `docker` command, any `scripts/*.sh`, or the purge script against a real Redis. Do not read `.env.local`.
- Heredocs break on apostrophes in this shell: create files with the file-writing tool, not with `cat <<EOF`.
- Lint that the gate enforces: isort, flake8 (see `.flake8`), no `print(` where `scripts/agent/lint_forbidden.py` forbids it, no f-string SQL, logger kwargs never named `name`, `msg`, `args`, `level`.

## Tasks & Acceptance

**Execution:**
- `src/adapters/queue/celery_app.py` -- add the queue constants; rewrite `task_routes` per the matrix (also route `tasks.send_price_drop_alert` to `periodic`); add `options: {"expires": <interval seconds>}` to the nine idempotent entries through one small helper; fix the comment above the routes -- the layout has one owner.
- `src/adapters/queue/scrape_single_flight.py` (new) -- `scrape_scope(checkpoint)`, constants `QUEUED_TTL_SECONDS = 3 * 3600`, `RUNNING_TTL_SECONDS = 2 * 3600`, `RENEW_EVERY_SECONDS = 60`, and a small class over two `BackfillLease`s keyed `scrape:single_flight:<platform>:<scope>:queued` / `:running` with the task id as token: reserve (publisher), cancel reservation, begin (worker), renew (throttled, monotonic clock injectable), finish, holder; plus `enqueue_scrape(task, platform, checkpoint, redis)` returning the task id and one of `queued` / `already_queued` / `already_running` -- one mechanism for beat, API and worker.
- `src/adapters/queue/redis_scheduler.py` -- override `apply_async` for entries whose task is `tasks.scrape_listings` per the matrix (honour `advance` on the skip path; restore `entry.options`; release the reservation when the publish raises).
- `src/adapters/queue/tasks.py` -- wire the single-flight into `scrape_listings` before the DB session is opened (fall back to a generated id when `self.request.id` is empty); renew in the item loop; release in `finally`; `monitor_queues` and `snapshot_pipeline_metrics` per the matrix; correct the comment at 1295.
- `src/api/main.py` -- `trigger_scrape` goes through `enqueue_scrape` and reports the duplicate statuses; log `scrape_enqueue_skipped`.
- `src/api/admin.py` -- the three explicit queues use `QUEUE_PERIODIC`.
- `src/api/system.py`, `src/adapters/metrics/pipeline_snapshots.py` -- three queue lengths from `ROUTED_QUEUES`; `_check_workers` uses one `inspect().active_queues()` round trip instead of `ping()` and reports unconsumed routed queues; snapshot result and log carry `periodic_queue`.
- `docker-compose.yml` -- add `worker_periodic` after `worker_scraper` with a comment stating what runs there and that old `scrapers` messages still drain through `worker_scraper`.
- `scripts/ops/purge_stale_periodic.py` (new) -- argparse CLI: `--redis-url` (default `redis://localhost:6379/0`), `--queue` (only `scrapers` accepted), repeatable `--task` (subset of the allowlist), `--apply`; reads the list in pages with `LRANGE`, takes the task name from the Kombu JSON `headers.task`, removes with `LREM key 1 <exact payload>`; pure functions importable by tests; output through `sys.stdout.write` if the forbidden-print lint covers `scripts/`.
- `src/tests/unit/test_queue_layout.py` (new) -- route table, no-shared-queue, every-queue-consumed (parse `docker-compose.yml` with `yaml`), expiry and must-not-lose rows. `src/tests/unit/test_scrape_single_flight.py` (new) -- every single-flight row against an in-memory fake Redis that implements `set(nx, ex)`, `get`, `delete`, `expire`, `eval` is absent (the lease falls back to its guarded path), including TTL expiry through an injectable clock in the fake. `src/tests/unit/test_purge_stale_periodic.py` (new) -- the three purge rows against the same kind of fake. Update the pinned tests listed in the Code Map to the new layout; add scheduler tests for the three beat rows, task tests for the task rows, API tests for the manual-trigger, queue-length, snapshot, monitor and unconsumed-queue rows.
- `docs/features/v0.14-s1.18-periodic-tasks-not-blocked-by-scrapes.md` (new, every template section) -- problem with the measured evidence; the layout table (queue → worker → tasks → expires); the single-flight; **Operator steps** (rebuild so `worker_periodic` exists, what the old backlog does, drain versus purge with the recommendation, exact verify commands) and an empty **Operator results** section; the scrape-duration finding; limits.
- `AGENTS.md`, `docs/architecture.md`, `docs/setup.md`, `docs/harness-troubleshooting.md`, `docs/deployment-guide.md`, `docs/development-guide.md`, `docs/integration-architecture.md`, `docs/project-overview.md`, `docs/source-tree-analysis.md`, `README.md` -- state the three-queue layout and the rule for new beat tasks (route to `periodic` unless it is a scrape or GPU work; add `expires` when idempotent).
- `_bmad-output/implementation-artifacts/deferred-work.md` -- DW-63 `status: resolved` with a `resolution:` line that says what the code resolves and that the primary deploy is an operator step.

**Acceptance Criteria:**
- Given scrapes holding both `worker_scraper` slots, when any beat task other than a scrape comes due, then it is published to `periodic`, which `worker_scraper` does not consume and `worker_periodic` does, and `test_queue_layout.py` fails if a periodic task is ever routed to the queue of `scrape_listings` or a routed queue loses its consumer in `docker-compose.yml`.
- Given the periodic worker is slower than a housekeeping interval or was down, when it catches up, then expired housekeeping messages are discarded by Celery and at most one interval of each is pending, while every queued sender and digest message still runs.
- Given a scrape of a platform is queued or running, when the beat ticks or the operator triggers the same platform and scope, then no second message is published; and given a second message exists anyway, when a worker receives it while the first runs, then it returns `skipped` without scraping.
- Given the three-queue layout, when the docs and AGENTS.md are read, then they name `periodic`, its worker and the routing rule, and GPU work is still only on `ai`.
- Given the feature doc, when the operator follows it, then the steps cover the rebuild, the fate of messages already on `scrapers`, the optional purge with its dry run, and how to confirm a periodic task ran on time during a scrape; DW-63 is resolved in the ledger.

## Spec Change Log

## Review Triage Log

### 2026-10-08 — Review pass
- verdicts: 33 findings — high 0, medium 7, low 23, false 3, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: `begin()` releases the queued lease before taking the running lease, leaving a moment with neither — real, a window of one Redis round trip in which a publisher sees the platform free; fixed by taking the running lease first and releasing the own reservation afterwards in both outcomes.
  - `[medium]` `[patch]` Blind: a killed scrape's redelivered message is skipped and the platform waits out the 2 h lease — real and frequent here: the primary was restarted at 19:59 UTC on 2026-10-08 and both in-flight scrape ids were received again within a second. Fixed for the graceful stop (the rebuild case): the running lease records the worker node as owner and a `worker_shutting_down` hook releases that node's running leases by owner-token CAS. The hard-kill case keeps the TTL (matrix row "Crashed run") and is deferred as the time-based heartbeat.
  - `[low]` `[reject]` Blind: a skipped redelivery stores `skipped` under the running task's id in the result backend — real, but nothing reads a scrape's result (the API returns the id and no route polls it); avoiding it needs result-ignoring plumbing for one branch. Stated in the feature doc.
  - `[low]` `[patch]` Blind: the 3 h queued reservation is not renewed and can expire while its message still waits behind the legacy backlog — real, bounded to one extra message per platform per 3 h, never concurrent; feature doc corrected to say so.
  - `[low]` `[patch]` Blind: during a pause the reservation is handed back, so a tick can publish one more message, and the doc sentence "run one after the other" was imprecise — real; doc corrected (a second message that starts while the first runs is skipped). No test added for a tick during a pause-retry: the two halves (reservation released on pause, tick publishes when free) are each tested.
  - `[low]` `[reject]` Blind: a manual trigger has its own scope, so it still runs beside the scheduled scrape and shares the checkpoint row and status key — real and unchanged from before the story; the manual trigger is the operator's explicit action and the documented way to start a scrape while a stale lease lives. Sharing a scope would also make Scraper Control report "enqueued" for a refused trigger (frontend untouched).
  - `[low]` `[patch]` Blind: the periodic-backlog warning runs on the queue it watches — real: it cannot fire while `worker_periodic` is down; `GET /system/status` is the signal for that. Stated in the feature doc.
  - `[low]` `[defer]` Blind: `worker_periodic` can be held by two long jobs, no time limits — real and bounded today (one long job at most with the committed config); recorded in `deferred`.
  - `[low]` `[defer]` Blind: the frontend shows "offline" for an unconsumed queue without the reason and no periodic queue length — real; frontend follow-up recorded in `deferred`.
  - `[low]` `[patch]` Blind: `docs/api.md` not updated for the `/scrape` statuses, `queues.periodic` and `unconsumed_queues` — real; documented. The `task_id: ""` corner of a double race is not tested (needs two expiries between three reads).
  - `[low]` `[patch]` Blind: "named once" is not true while `queue="ai"` literals remain in `tasks.py` and `admin.py` — real; literals replaced by `QUEUE_AI` and the source scan widened to any string-literal `queue=`.
  - `[medium]` `[patch]` Blind: the lease tests run against a fake without `eval`, so the Lua compare-and-swap path production uses is not exercised by this story — real; an integration test against the gate's Redis added (`src/tests/integration/test_scrape_single_flight_redis.py`), and the fake now records `hset`.
  - `[low]` `[patch]` Blind: the purge tool does not say which Redis it read — real; the report's first line names host:port/db.
  - `[medium]` `[defer]` Blind: the primary-Redis incident was fixed for one test only; a raw pytest run can still reach the configured broker — real and pre-existing (config default plus the primary on localhost:6379); recorded in `deferred` with the incident as evidence.
  - `[false]` `[reject]` Blind: tracking gaps (no `1-18` key in sprint-status, DW-63 resolved before the deploy, limits not minted) — sprint-status.yaml is written by the orchestrator only; the story's instruction is to resolve DW-63 for what the code resolves, and the resolution line says the deploy is an operator step; the limits are in `deferred`, which is what the orchestrator mints from.
  - `[medium]` `[patch]` Edge: a Redis error from `flight.renew()` in the item loop aborts a multi-hour scrape — real; caught and logged as `scrape_single_flight_renew_failed`, the run continues.
  - `[low]` `[patch]` Edge: the task raises for an unknown platform before the flight exists, leaking a reservation for 3 h — real (a platform removed from config while its message waits); the flight is built first and the reservation cancelled before raising.
  - `[medium]` `[patch]` Edge: recovery redelivery after a worker kill is acked as skipped — same root cause as the Blind row above; same fix.
  - `[low]` `[patch]` Edge: publisher `reserve()` between `begin()`'s release and acquire — same root cause as the first row; same fix.
  - `[low]` `[patch]` Edge: a Redis error from `cancel_reservation()` on the paused path replaces the pause retry — real though it needs Redis to fail between two calls; wrapped, the retry is still raised.
  - `[low]` `[reject]` Edge: a run that lost its lease deletes the status key a successor writes — real only after a lease loss (two hours without an item); the unconditional delete predates the story and guarding it adds a branch for a case not observed.
  - `[medium]` `[patch]` Edge: `active_queues()` with a one-second window turns one late reply into `status: error` where `ping()` accepted any reply — real; the check asks once more before reporting an unconsumed queue.
  - `[low]` `[patch]` Edge (claim): "no second message while one is queued" does not hold after the 3 h reservation expires — same as the Blind row on the queued TTL; doc corrected.
  - `[low]` `[patch]` Edge (claim): "no second message while one is queued" does not hold during a pause — same as the Blind row on the pause; doc corrected.
  - `[medium]` `[patch]` Verification gap: the two admin triggers moved to `periodic` have no executed test of the queue they publish to — filed with evidence; two route tests added that assert `apply_async(..., queue="periodic")`.
  - `[low]` `[defer]` Verification gap (other): Scraper Control toasts "enqueued" for the duplicate statuses — real; same frontend follow-up in `deferred`.
  - `[false]` `[reject]` Intent: AC1 is tested at static config, not on a running stack — the story's own guidance makes the proof on the primary an operator step with exact commands; the gate has no worker containers. The capacity remark is the Blind row on two slots.
  - `[low]` `[patch]` Intent: AC2 is tested at the schedule dict; discard itself is Celery's; "a persisted beat schedule may not pick up the options" — the last part is false (`celery/beat.py` `ScheduleEntry.update` copies `options`, `merge_inplace` calls it for existing entries); the remark that a worker persistently later than an interval discards every tick of that entry is real and is the intended coalescing, now stated in the feature doc.
  - `[low]` `[reject]` Intent: AC3 covers the beat and the API and one definition of scope; remaining cases are listed in the doc — the cases are the Blind rows above (scope, pause, queued TTL, lost lease) and carry their routes.
  - `[low]` `[defer]` Intent: "report the new queue" is met in the task result, logs and the live endpoint, not in the stored row or the UI — recorded decision (Design Notes) and `deferred` (history series, frontend).
  - `[low]` `[patch]` Intent: AC5 purge has no literal `--dry-run`; the operator steps did not connect a restart with the leases — real; `--dry-run` accepted (refused together with `--apply`), restart behaviour stated in the doc. The narrower purge allowlist is deliberate (recheck and refresh can be operator-triggered with arguments).
  - `[low]` `[patch]` Intent: the scrape-duration guidance asked for a verdict and a deferred finding; the diff had a doc section only — real; explicit verdict added to the doc and the finding recorded in `deferred`.
  - `[false]` `[reject]` Intent: items not asked for (two `/scrape` statuses without a schema change, the incident disclosure, no sprint-status key) — `/scrape` has no response model to change; the disclosure is required; sprint-status belongs to the orchestrator.

### 2026-10-08 — Follow-up review pass
- verdicts: 43 findings — high 0, medium 6, low 31, false 6, maybe-false 0
- findings:
  - `[low]` `[patch]` Blind: `docs/api.md` appends the new sections inside the unclosed `## System` code fence — real (the fence opened before `GET /system/pipeline` had no closer, so the headings rendered as code); closing fence added.
  - `[low]` `[patch]` Blind: `reserve()` reads the running lease before it takes the reservation, so a task that begins in between gets a duplicate queued behind it — real, a window of two Redis calls; `reserve()` now looks at the running lease again once it holds the reservation and hands the reservation back (`_confirm_reservation`), with a test that starts the task inside the window.
  - `[low]` `[patch]` Blind: a Redis error in `begin()` after the running lease is taken strands it, and the retry of the same id is skipped for two hours — real; `begin()` records ownership before the next Redis call and the task gives the lease back when `begin()` raises (`_finish_scrape_flight`); two tests.
  - `[low]` `[patch]` Blind: the shutdown hook releases the lease when the stop is requested, while the scrape still runs — real and by design: under `docker stop` the task never ends by itself, so there is no later moment to release at. Kept; ruling recorded in the hook's docstring and the feature doc. Bounded by the layout (the stopping worker is the only consumer of `scrapers`). Checked on a real Celery 5.6.3 prefork worker in a scratch container: lease gone within a second of SIGTERM, the scrape ran 21 more seconds and completed, the redelivered id ran after a kill.
  - `[medium]` `[patch]` Blind: the hook matches leases by node name, and the documented host commands give all three workers the same name — real: stopping the periodic or AI worker on a host would free the lease of a scrape the scraper worker is running, and the beat would queue a second one beside it. The hook now releases only leases whose token is the id of one of that worker's active `scrape_listings` requests (`celery.worker.state.active_requests`) and does not read Redis when there is none; `docs/setup.md` gives the host workers `-n`. Five tests.
  - `[low]` `[reject]` Blind: a manual `scrape_type: both` is a different scope and still runs beside the scheduled scrape — carried: same claim as the first pass's row on the manual scope; the code reads as that row describes.
  - `[medium]` `[patch]` Blind: with `--apply` the purge tool prints its target Redis after the messages are removed — real, and the operator's only check that it is aimed at the primary; the target line is now written and flushed before a connection is opened, in every mode and on the error path; two tests.
  - `[false]` `[reject]` Blind: no `1-18` key in `sprint-status.yaml` — carried: the first pass's row on tracking gaps; the file is the orchestrator's.
  - `[false]` `[reject]` Blind: six leftovers are recorded in the feature doc only, no ledger entry — carried: same row; the leftovers are in `deferred`, which is what the orchestrator mints from.
  - `[low]` `[patch]` Blind: any unconsumed queue sets `workers.status` to `error` and the degraded path waits about two seconds — the Dashboard half is carried (first pass's frontend row, deferred); the wait is real and bounded: one second as with `ping()`, two only while a queue has no consumer or one reply is late. Stated in the feature doc with the 8 s poll interval; no code change.
  - `[low]` `[defer]` Blind: two long jobs can hold both `periodic` slots; a discarded monitor tick then moves the scraper pause late — carried: the first pass's capacity row; the pause detail is the same root cause.
  - `[medium]` `[patch]` Blind: the contract fixture fakes the broker but the rate limiter still stores its counters in the configured Redis — real in a raw run (the configured Redis is the primary); closed at the root by the suite-wide connection guard below: the limiter connects through redis-py and is refused. In the gate the counters go to the ephemeral Redis.
  - `[low]` `[patch]` Blind: the last fallback of `reserve()` can answer `already_queued` with an empty `task_id` — carried: named in the first pass's row on `docs/api.md` as an untested corner of a double race; the code reads the same after the loop rewrite.
  - `[low]` `[reject]` Blind: the monitor logs `scrapers_queue` and the snapshot logs `scraper_queue` — real and cosmetic; the monitor key is fixed by the intent matrix and the snapshot key is the stored column's name, so the correction would edit the spec.
  - `[low]` `[patch]` Blind: `test_no_gpu_task_is_routed_to_periodic` only searches the task body for `GPUSemaphore` — real as a claim about the docstring; the docstring now says what the check sees.
  - `[false]` `[reject]` Blind: `_expiring` raises `TypeError` on a crontab entry at import — no caller passes one (the nine call sites are numeric); a misuse fails at once in every process and in `test_queue_layout.py`, which is the wanted behaviour.
  - `[low]` `[patch]` Blind: the integration test's skip message names `validate.sh` — real; corrected to `validate.py --tier backend`.
  - `[low]` `[patch]` Blind: the backlog figure and the clock are inconsistent across the feature doc — real; the doc now says every time is UTC, that the backlog was read several times while it grew, and which window the "received twice" row covers.
  - `[low]` `[patch]` Edge: `begin()` raises after the running lease is taken — same root cause as the Blind row; same fix.
  - `[low]` `[reject]` Edge: `finish()` fails in `finally` and the retry of the same id finds its own lease and is skipped — real only when Redis fails exactly at the release; the fix is a second ownership rule (adopt a lease by token and owner) that cannot tell a retry from a visibility-timeout redelivery of a run still in flight.
  - `[low]` `[defer]` Edge: a pool child killed mid-scrape is requeued at once and acked as skipped; the node hook never fires — carried: the first pass's hard-kill row (deferred as the time-based heartbeat).
  - `[low]` `[patch]` Edge: a warm shutdown that is not followed by a kill leaves the scrape without a lease — same root cause as the Blind row on the hook's timing; same ruling and documentation.
  - `[low]` `[reject]` Edge: the hook does Redis I/O in the signal handler on a client without a socket timeout — real; when Redis is unreachable the handler blocks until Docker kills the worker after the grace period, which is the outcome without a hook. A dedicated client with timeouts adds a second Redis configuration path for no change in outcome.
  - `[low]` `[patch]` Edge: `reserve()` reads running as free, the task begins, the reservation is then taken — same root cause as the Blind row; same fix.
  - `[low]` `[patch]` Edge: `already_queued` with an empty `task_id` — carried with the Blind row.
  - `[low]` `[reject]` Edge: the beat's publish raises and `cancel_reservation()` raises too — real only when Redis fails between the reservation and the publish (broker and lease are one Redis); either error is logged by `apply_entry`, and no code can release a lease on a Redis that is down.
  - `[low]` `[reject]` Edge: the same in `enqueue_scrape` — same reasoning; the route answers 500 either way.
  - `[low]` `[reject]` Edge: `r.exists(paused)` raises before the reservation is handed back — the retry carries the same id and hands it back at its next start; only after three failed retries does the reservation wait out its TTL, and that needs Redis down for the whole retry window.
  - `[medium]` `[patch]` Edge: the purge target is named after the removal and never on an error — same root cause as the Blind row; same fix.
  - `[low]` `[patch]` Edge (claim): "one `active_queues` round trip" is two when a queue looks unconsumed — real as a doc claim; the feature doc row and a note now say one call, plus a second before a queue is reported.
  - `[low]` `[patch]` Edge (claim): a pause-retry or failure-retry message has no lease, so a second message can be published — carried: the first pass's rows on the pause and the retry; the doc states it.
  - `[low]` `[patch]` Edge (claim): "at most one interval of each is pending" holds only once the worker has caught up; while it is down the list grows by every tick — real as wording; the comment above `PERIODIC_BACKLOG_THRESHOLD` now says ticks are discarded when received, not before.
  - `[low]` `[reject]` Edge (claim): after a lost lease the first run continues and a second delivery scrapes beside it — carried: the first pass's row on a run that lost its lease; said loudly by `scrape_single_flight_lost`. The shutdown-induced case is the Blind row on the hook's timing.
  - `[medium]` `[patch]` Verification gap: the beat-side single-flight depends on the compose `--scheduler` flag and no test reads it — filed with evidence; `test_beat_runs_the_scheduler_that_makes_scheduled_scrapes_single_flight` parses the real compose file and compares the flag with the class.
  - `[low]` `[patch]` Verification gap: a scrape that fails before its database session exists has no test — filed with evidence; test added (`SessionLocal` raises: the error propagates and both leases are free).
  - `[false]` `[reject]` Intent: the runtime expectations are exercised at the config and unit surface — carried: the first pass's row on AC1; the gate has no worker containers. This pass adds one real-worker check of the shutdown path (feature doc).
  - `[low]` `[reject]` Intent: the scope rule leaves the incident reachable through a manual `both` trigger — carried with the Blind row on the manual scope.
  - `[low]` `[patch]` Intent: the shutdown release is a lease path the contract does not list and it fires before the task ends — same root cause as the Blind row on the hook's timing; same ruling.
  - `[low]` `[defer]` Intent: "short periodic work" versus "every other task" on two slots — carried: the capacity row.
  - `[low]` `[patch]` Intent: residual duplicate-publish paths (retries without a reservation, the 3 h reservation) — carried: the first pass's rows; the doc states them.
  - `[false]` `[reject]` Intent: `SessionLocal()` moved inside the `try` is a control-flow change in a function the Never list protects — the Never list protects how a scrape fetches, paginates, rate-limits and persists, none of which changed; a session that cannot be opened now reaches the failure telemetry and the lease release, which the new test pins.
  - `[false]` `[reject]` Intent: additions beyond the matrix (`--dry-run`, `--redis-url`, the second `active_queues`, the `docs/api.md` body) — carried: the first pass's row on items not asked for.
  - `[medium]` `[patch]` Intent: the development process wrote to the primary Redis, against the Never list — the first pass deferred the cause (a raw pytest run can reach the configured broker); the follow-up dispatch put the fix in scope. `tests/conftest.py` installs `install_redis_connection_guard` (`tests/redis_isolation.py`): redis-py, and through it Kombu, the result backend and the limiter, can connect only to the host, port and logical DB of a wipe-safe `REDIS_URL`; without one nothing is reachable. 15 tests; the unit suite (2,868) passes with every Redis connection refused. The item is removed from `deferred`.

## Design Notes

- **Why a queue and not only `expires`.** Expiry bounds the backlog but a task still waits for a slot a scrape holds for hours; the matcher would be discarded every time instead of running. Separate capacity is what makes "within its own interval" true; expiry only keeps a slow or restarted periodic worker from replaying history.
- **Sender and digests stay without `expires`.** Their duplicates are harmless (the sender claims the day per search under a row lock, the digest drains a list) and their discard is not: Celery checks `expires` when a worker receives the message, so a worker that is behind by more than the interval would discard every run. With its own worker the backlog is at most a handful of hourly messages, each a no-op after the first.
- **`backfill_listing_costs` stays on `scrapers`.** It is operator-triggered, walks the whole corpus and would hold a periodic slot for its whole run. `send_price_drop_alert` moves to `periodic`: it is short and an alert should not wait for a scrape.
- **Two leases, not one.** A queued reservation and a running lease are different facts: the reservation is taken by the publisher and handed over when the task starts; the running lease is what makes a second delivery (old backlog, or a broker redelivery of the same id after the one-hour visibility timeout under `acks_late`) skip instead of scraping the same windows again, which is what the primary was doing. TTLs: a run renews its two-hour lease every minute, so a killed run blocks its platform for at most two hours; a reservation lasts three hours, longer than a queue wait behind two multi-hour scrapes.
- **Scope.** Beat scrapes pass no checkpoint (`default`). A manual trigger always carries `scrape_type`, so it is its own scope and can still run beside a scheduled scrape, as today.
- **No stored snapshot column.** A third queue column needs a migration, `schemas.py` and the Dashboard chart; the migration also cannot be applied while a backfill holds the guard, and code that writes a column the primary does not have would fail every snapshot. The live value is in `GET /system/pipeline`, the snapshot result and the monitor log.
- **Capacity limit.** `worker_periodic` has two slots. The availability recheck can hold one for up to about 17 minutes (50 URLs × 20 s timeout) every six hours; the weekly refresh jobs are off by default. Two long jobs at once delay the short ones until one ends (their stale ticks expire).

## Verification

**Commands:**
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/agent/validate.py` -- expected: exit 0 (auto tier; harness-marked tests run because `scripts/` changed).
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe -m pytest src/tests/unit/test_queue_layout.py src/tests/unit/test_scrape_single_flight.py src/tests/unit/test_purge_stale_periodic.py src/tests/unit/test_schedule.py src/tests/unit/test_celery_app.py src/tests/unit/test_redis_scheduler.py -q -o addopts= -p no:cacheprovider` -- expected: all pass (development check, not the gate). Safe as a raw run since the follow-up review: the suite refuses every Redis and broker connection unless `REDIS_URL` names the gate's isolated Redis.
- `C:\Workfolder\imoveis\.venv\Scripts\python.exe scripts/ops/purge_stale_periodic.py --help` -- expected: usage text, exit 0, no connection attempted.

## Auto Run Result

Status: awaiting-operator (code complete; the primary needs a rebuild before `worker_periodic` exists there. No migration.)

**Summary.** Three routed queues, one worker service each: `scrapers` (`worker_scraper`: `scrape_listings` and the operator-triggered `backfill_listing_costs`), `ai` (`worker_ai`, unchanged) and the new `periodic` (`worker_periodic`, two slots: every other task). The nine idempotent beat entries carry `expires` equal to their interval; the hourly sender, the digests and the scrapes carry none. A scrape is single-flight per platform and scope through two expiring `BackfillLease`s (queued 3 h, taken by the publisher; running 2 h, renewed from the item loop, released at the end and on a graceful worker stop): the beat and `POST /scrape` publish nothing while one is queued or running, and a duplicate delivery returns `skipped`. The three queues are reported by `GET /system/pipeline`, the monitor log and the snapshot result; `GET /system/status` reports a routed queue nobody consumes. Messages already on `scrapers` keep draining through `worker_scraper`; `scripts/ops/purge_stale_periodic.py` optionally removes the four stale housekeeping types (dry run by default, never run automatically).

**Files changed.**
- `src/adapters/queue/celery_app.py` — queue constants, three-queue `task_routes`, `expires` on nine beat entries.
- `src/adapters/queue/scrape_single_flight.py` (new) — scope, the two leases, `enqueue_scrape`, release by worker node.
- `src/adapters/queue/redis_scheduler.py` — scheduled scrapes are single-flight (`apply_async` override).
- `src/adapters/queue/tasks.py` — `scrape_listings` takes, renews and releases the running lease; shutdown hook; `monitor_queues` reports three queues.
- `src/api/main.py`, `src/api/admin.py`, `src/api/system.py`, `src/adapters/metrics/pipeline_snapshots.py` — `/scrape` duplicate statuses, admin triggers on `periodic`, three queue lengths, unconsumed-queue check, `periodic_queue` in the snapshot result.
- `docker-compose.yml` — service `worker_periodic`.
- `scripts/ops/purge_stale_periodic.py` (new) — operator purge tool.
- `src/tests/redis_isolation.py`, `src/tests/conftest.py` — connection guard for the whole suite (follow-up pass).
- `frontend/src/pages/ScraperControl.tsx`, `frontend/src/i18n/locales/en.json`, `pt-BR.json` — the manual trigger reports the duplicate statuses (follow-up pass).
- Tests: `test_queue_layout.py`, `test_scrape_single_flight.py`, `test_purge_stale_periodic.py`, `test_queue_observability.py`, `fake_queue_redis.py`, `test_redis_connection_guard.py`, `frontend/tests/e2e/scrape-duplicate-status.spec.js` (new); `integration/test_scrape_single_flight_redis.py` (new); `test_schedule.py`, `test_celery_app.py`, `test_admin_listing_claim_stats.py`, `contract/test_api_contract.py` (moved to the new layout).
- Docs: the feature doc, `AGENTS.md`, `README.md`, `docs/api.md`, `docs/architecture.md`, `docs/setup.md`, `docs/harness-troubleshooting.md`, `docs/deployment-guide.md`, `docs/development-guide.md`, `docs/integration-architecture.md`, `docs/project-overview.md`, `docs/source-tree-analysis.md`; DW-63 resolved in `deferred-work.md`; Story 1.18 in `epics.md` (first commit); `epic-1-context.md` regenerated.

**Decisions.**
- One new queue for all non-scrape, non-GPU work, concurrency 2, same image as the scraper worker (the image has no browser dependencies to split off).
- `expires` equals the interval on the nine idempotent entries; none on the sender and the digests even now that they have their own capacity: a duplicate run is a no-op (the sender claims the day per search under a row lock), a discarded run is a missed email, and Celery discards at receive time, so a worker behind by more than an hour would discard every run.
- `backfill_listing_costs` stays on `scrapers` (a corpus walk would hold a periodic slot); `send_price_drop_alert` moves to `periodic`.
- A manual `POST /scrape` is its own scope: it can still run beside a scheduled scrape and is the way to start a scrape while a stale lease lives.
- No stored snapshot column (no migration, `schemas.py` untouched). One frontend change, made in the follow-up pass: the manual trigger's toast and log line.
- `GET /system/status` now reports `workers.status: error` when a routed queue has no consumer; the Dashboard Celery card shows that as offline.
- The purge allowlist is four task types; recheck and refresh messages are kept because an operator may have triggered them with arguments.
- Deviation from the workflow: the fix for the worker-stop case (shutdown hook) was applied as a review patch, not through a spec loopback, because the restart of the primary at 19:59 UTC supplied the evidence during review and the matrix rows stay true.

**Scrape duration.** Expected from the design, not a parsing defect: one QuintoAndar run is a rate-limited walk of about 1,500 price windows per city over three cities and does not finish inside its 60-minute interval. The defect was two concurrent runs of the same scrape (3,341 URLs fetched by both processes in three hours); the single-flight removes it. Recorded in `deferred`.

**Review (first pass).** 33 findings from four layers: high 0, medium 7, low 23, false 3. Patched 21 rows in 17 entries (5 medium entries: worker-stop lease release, renew error handling, late `active_queues` reply, admin trigger tests, real-Redis lease test; 12 low entries). Deferred 5 rows (raw pytest can reach the primary broker, periodic worker capacity, frontend twice, history series). Rejected 7: three false (tracking and scope claims that belong to the orchestrator or to the story's instructions), four low (result-backend entry of a skipped duplicate, manual scope overlap, status key after a lost lease, AC3 restatement).

**Follow-up review: not recommended (false).** This was the follow-up pass (2026-10-08, a fresh session that did not write the code). It patched no `high` entry; by the workflow's rule the work has converged. Patched this pass, at entry verdict: high 0, medium 4, low 11 (see "Follow-up review pass" below).

**Follow-up review pass (2026-10-08).** Four layers, 43 findings: high 0, medium 6 (4 entries), low 31, false 6.
- Patched (15 entries):
  - `medium` the suite could reach the primary broker (two rows: the limiter in the contract fixture, the incident). `src/tests/conftest.py` installs a connection guard from `src/tests/redis_isolation.py`; `src/tests/unit/test_redis_connection_guard.py` is new.
  - `medium` the shutdown hook released by node name. It now releases only the leases of the worker's own active scrapes (`src/adapters/queue/tasks.py`, `scrape_single_flight.py`); host workers get `-n` in `docs/setup.md`.
  - `medium` the purge tool named its target after removing (two rows). `scripts/ops/purge_stale_periodic.py` writes the target line first.
  - `medium` the beat `--scheduler` flag was unpinned. Test added in `test_queue_layout.py`.
  - `low` `reserve()` handover window (two rows); `begin()` stranding the running lease on a Redis error (two rows); the hook's timing, kept by ruling and documented (three rows); test for a scrape that cannot open its session; `docs/api.md` fence; skip message; GPU test docstring; threshold comment; two feature-doc corrections (clock and backlog figures, the `active_queues` count); the status wait stated in the doc.
  - In scope by the follow-up dispatch, not from a finding of this pass: Scraper Control reports `already_queued` / `already_running` instead of "enqueued" (`frontend/src/pages/ScraperControl.tsx`, both locale catalogs, `frontend/tests/e2e/scrape-duplicate-status.spec.js`). It was the first pass's deferred frontend row.
- Deferred: nothing new from the findings. One item added by the ruling on the hook (a second `scrapers` consumer), one removed (raw pytest reaching the broker, fixed), one narrowed (frontend: the toast is fixed).
- Rejected (8 new rows): the two log keys (`scrapers_queue` / `scraper_queue`; the correction would edit the spec); `finish()` failing exactly at the release; Redis I/O in the signal handler without a timeout; the publish and its cancel both failing (beat, API); the paused check raising; `_expiring` on a crontab (false: fails loudly, no caller); `SessionLocal` inside the `try` (false: persistence unchanged); and the carried rows keep their first-pass routes.
- Carried from the first pass without re-verification of the fix, same claim and same code: 14 rows (manual scope, tracking, capacity, hard kill, retries without a reservation, empty `task_id`, lost lease, test surface, additions beyond the matrix).

**Ruling on the shutdown hook.** Releasing when the stop is requested is right for the deployment this project runs, and it stays. Celery sends `worker_shutting_down` from the main process's signal handler and then waits for running tasks; under `docker stop` the process is killed ten seconds later, so the task never reaches its `finally` and "release when the task ends" would mean the two-hour TTL every time. Between the signal and the kill the scrape holds no lease, and nothing can start beside it because the stopping worker is the only consumer of `scrapers`. The residual case (a warm shutdown that is allowed to wait, with a second `scrapers` consumer alive) is recorded in `deferred`. What changed is which leases the hook may release: only those of the scrapes that worker is executing. Verified on a real worker (feature doc, "What a worker restart does"): Celery 5.6.3 prefork in a scratch container against a scratch Redis, real task module, hook and leases, scraper and database stubbed.

**Deviation recorded.** The intent contract's Never list excludes `frontend/`. The follow-up dispatch put the toast fix in scope as a contained change (one handler, four catalog strings in two locales, one e2e spec). Nothing else under `frontend/` changed.

**Verification.** First pass, during development: 2811 unit tests passed with Redis unreachable (before the review patches), 189 tests of the story's files after them; the purge tool prints its usage without connecting and refuses `--dry-run --apply` with exit 2. A first gate run on the pre-patch tree failed in the gate's own "test db: create + extensions" step (the test Postgres closed the connection one second after reporting healthy, while another gate was using the host), which skipped the integration suite; lint, unit (2811), contract (60 passed, 23 skipped) and harness (212) passed in that run. Follow-up pass: the gate's fast tier (`validate.py --tier fast --no-extras`) passed twice on the patched working tree, 2,868 unit tests with every Redis connection refused by the guard; the new Playwright spec passed (3 tests, mocked API) and eslint was clean; single test files were run only with `REDIS_URL` unset or pointed at a closed port and `DATABASE_URL` pointed at a closed port. The full gate was run on the final commit after this file was written: its tier and exit code are in the session's final report, not here, because recording them would change the validated tree.

**Residual risks.**
- Nothing ran on the primary: that a periodic task runs on time during a scrape there is an operator verification.
- A hard-killed scrape (no SIGTERM) blocks its platform's scheduled scrape for up to two hours; a lost queued message for up to three.
- The shutdown release assumes one consumer of `scrapers`; with a second one a scrape could start beside one that outlives a graceful stop (in `deferred`).
- The connection guard lives in the pytest process: a script that a test starts as a subprocess, and anything run outside pytest, is not covered.
- The legacy `scrape_listings` messages on `scrapers` run one after the other after the deploy.
- One stray message and one lease were written to the primary Redis by a raw test run of the implementation session and were not removed (operator action).

## Operator Confirmation

Confirmed 2026-10-08: the external actions this story owed were carried out.

- AGENT-RUNNABLE. After the branch is merged, rebuild and restart the primary stack from the primary checkout so that worker_periodic exists and the API, the workers and beat run the new routing (no database migration): ./scripts/restart.sh --build . Verify read-only: docker ps --filter name=imoveis-worker_periodic --format "{{.Names}} {{.Status}}" shows imoveis-worker_periodic-1 Up; docker exec imoveis-worker_periodic-1 celery -A adapters.queue.tasks inspect active_queues lists periodic on the periodic node, scrapers and celery on the scraper node, ai on the ai node. Record under "Operator results" in docs/features/v0.14-s1.18-periodic-tasks-not-blocked-by-scrapes.md.
- AGENT-RUNNABLE. Measure the old backlog, read-only: docker exec imoveis-redis-1 redis-cli llen scrapers and docker exec imoveis-redis-1 redis-cli llen periodic, then the dry run from the primary checkout: .venv/Scripts/python.exe scripts/ops/purge_stale_periodic.py --dry-run (first line names the Redis it is aimed at, before it reads anything: it must be redis localhost:6379/0; then one count per task type, marked removable or kept; it writes nothing). Expected: periodic is a single digit, scrapers is in the thousands, mostly tasks.snapshot_pipeline_metrics and tasks.monitor_queues. Record the counts in the same section.
- AGENT-RUNNABLE (optional, recommended). Remove the stale housekeeping messages from the old backlog: .venv/Scripts/python.exe scripts/ops/purge_stale_periodic.py --apply . Its first line names the target Redis before anything is removed. It removes only tasks.snapshot_pipeline_metrics, tasks.monitor_queues, tasks.evaluate_watchlist_alerts and tasks.match_saved_search_new_matches from scrapers and refuses anything else. Recommended because draining them through worker_scraper writes thousands of snapshot rows stamped with the time they run and delays the scrapes behind them; skipping this step is safe, the backlog then drains by itself. Verify: the report's "removed" total matches the dry run minus "gone", and llen scrapers dropped by that much. Record removed and gone in the same section.
- AGENT-RUNNABLE. Confirm a periodic task runs inside its interval while a scrape is in flight. While docker logs --since 20m imoveis-worker_scraper-1 2>&1 | grep -E "Task tasks.scrape_listings|scrape_completed|scrape_skipped_already_running" shows a scrape received and not yet completed, docker logs --since 20m imoveis-worker_periodic-1 2>&1 | grep -E "queue_monitor|pipeline_metric_snapshot_written|saved_search_new_match_run" must show queue_monitor lines about 60 s apart, snapshot lines about 30 s apart and at least one saved_search_new_match_run within 15 minutes of the rebuild. Record the timestamps in the same section.
- AGENT-RUNNABLE. Confirm scrapes are single-flight: docker logs --since 6h imoveis-beat-1 2>&1 | grep scrape_enqueue_skipped shows skipped ticks with reason queued or running for a platform whose scrape outlasts its interval; docker exec imoveis-redis-1 redis-cli --scan --pattern "scrape:single_flight:*" lists at most one running and one queued lease per platform and scope, and docker exec imoveis-redis-1 redis-cli ttl <key> is positive for each; the worker_scraper log does not show QuintoAndar window fetches from both ForkPoolWorker processes at the same time. Record in the same section.
- HUMAN-ONLY (decision). The development of this story left two things on the primary Redis by mistake (a raw test run on 2026-10-08): one tasks.scrape_listings message on scrapers (id fd1f4df9-1898-4d68-91c1-88daa7ad62bd, a manual OLX scrape, scrape_type both) and the lease key scrape:single_flight:olx:2fe9313c54db7883:queued:lease with its :meta hash. Options: leave them (recommended: the lease expires by itself within three hours of 20:00 UTC and the old code ignores it; the message runs one ordinary OLX scrape of about a minute), or remove them by hand (LREM scrapers 1 <exact payload>, DEL of the two keys). If nothing is done, the first option happens. Verify either way: docker exec imoveis-redis-1 redis-cli exists scrape:single_flight:olx:2fe9313c54db7883:queued:lease returns 0 after 23:10 UTC.
- HUMAN-ONLY (decision). About 193 tasks.scrape_listings messages published before this story are still on scrapers and the purge tool never removes a scrape. Options: let them drain (recommended: one that starts while a scrape of its platform is running is skipped and consumed, one that starts while none is running scrapes, so they run one at a time per platform, which is no worse than today and nothing new piles up behind them), or delete the old scrape messages by hand to return to the hourly schedule at once. If nothing is done they drain; how long that takes was not measured (while one slot holds a long scrape the other slot consumes the queue behind it). Verify the trend with the dry run of the purge tool: the tasks.scrape_listings count falls and does not grow.

_Appended by hand in place of `bmad-loop confirm` (the loop was not in use that day): the agent operator carried these actions out and recorded the evidence in the feature doc, and the story was advanced from `awaiting-operator` to `done`._
