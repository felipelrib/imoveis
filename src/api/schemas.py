from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PropertyListingModel(BaseModel):
    platform: str
    platform_listing_id: str
    listing_type: str
    price: float
    currency: str
    url: str
    is_furnished: Optional[bool] = None
    accepts_pets: Optional[bool] = None
    condo_fee: Optional[float] = None
    iptu: Optional[float] = None
    base_price: Optional[float] = None
    fees_bundled: Optional[bool] = None


class PropertyModel(BaseModel):
    id: str
    public_id: Optional[int] = None
    platform: str
    platform_id: str
    title: str
    price: float
    area_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    address: Optional[str] = None
    image_urls: List[str]
    created_at: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    stat_score: Optional[float] = None
    ai_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    combined_score: Optional[float] = None
    percentile_rank: Optional[float] = None
    z_score: Optional[float] = None
    price_per_m2: Optional[float] = None
    neighborhood_mean: Optional[float] = None
    price_per_m2_rent: Optional[float] = None
    price_per_m2_sale: Optional[float] = None
    neighborhood_mean_rent: Optional[float] = None
    neighborhood_mean_sale: Optional[float] = None
    stat_score_rent: Optional[float] = None
    stat_score_sale: Optional[float] = None
    z_score_rent: Optional[float] = None
    z_score_sale: Optional[float] = None
    percentile_rank_rent: Optional[float] = None
    percentile_rank_sale: Optional[float] = None
    combined_score_rent: Optional[float] = None
    combined_score_sale: Optional[float] = None
    neighborhood_id: Optional[str] = None
    neighborhood_name: Optional[str] = None
    city: Optional[str] = None
    parking: Optional[int] = None
    description: Optional[str] = None
    available_for_rent: bool = False
    available_for_sale: bool = False
    ai_features: List[str] = []
    ai_issues: List[str] = []
    ai_green_flags: List[str] = []
    ai_red_flags: List[str] = []
    # AI domain scores are floats in [0.0, 1.0] (see VisualResult / SentimentResult;
    # clamped at the Ollama-response parsing boundary in adapters/ai/client.py — BIN-148).
    condition_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    sentiment_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    stat_category: Optional[str] = None
    stat_reasoning: Optional[str] = None
    deal_summary: Optional[str] = None
    visual_category: Optional[str] = None
    visual_reasoning: Optional[str] = None
    sentiment_category: Optional[str] = None
    sentiment_reasoning: Optional[str] = None
    listings: List[PropertyListingModel] = []
    primary_listing: Optional[PropertyListingModel] = None
    neighbourhood_quality: Optional["NeighbourhoodQualityModel"] = None
    model_config = ConfigDict(extra="ignore")


class NeighbourhoodQualityModel(BaseModel):
    """Objective neighbourhood quality profile projected onto a property (BIN-94)."""

    amenity_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    transit_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    access_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    safety_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    neighbourhood_score: float = Field(0.5, ge=0.0, le=1.0)
    risk_flags: List[str] = Field(default_factory=list)
    quality_meta: Optional[Dict[str, Any]] = None
    quality_notes: Optional[str] = None


class PaginatedPropertiesResponse(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    properties: List[PropertyModel]


class PropertyBatchResponse(BaseModel):
    properties: List[PropertyModel]


class PropertyExportResponse(BaseModel):
    """JSON export envelope for ``GET /properties/export?format=json`` (BIN-50)."""

    properties: List[PropertyModel]
    total: int
    truncated: bool


class NeighborhoodModel(BaseModel):
    """Neighbourhood filter option + optional quality profile (BIN-86).

    Score fields are floats in ``[0.0, 1.0]``; ``None`` means unknown / not filled.
    Legacy list rows (props-only neighbourhoods) omit ``id`` and leave profile null.
    """

    name: str
    count: int
    city: Optional[str] = None
    id: Optional[str] = None
    amenity_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    transit_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    access_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    safety_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    risk_flags: List[str] = Field(default_factory=list)
    quality_meta: Optional[Dict[str, Any]] = None
    quality_notes: Optional[str] = None
    neighbourhood_score: Optional[float] = Field(None, ge=0.0, le=1.0)


class CityModel(BaseModel):
    name: str
    count: int


class PropertyDetailModel(BaseModel):
    id: str
    public_id: Optional[int] = None
    platform: str
    platform_id: str
    title: str
    description: Optional[str] = None
    price: float
    area_m2: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking: Optional[int] = None
    address: Optional[str] = None
    image_urls: List[str]
    created_at: Optional[str] = None
    props_json: Dict[str, Any]
    stat_score: Optional[float] = None
    # AI domain score is a float in [0.0, 1.0] (see VisualResult / SentimentResult;
    # clamped at the Ollama-response parsing boundary in adapters/ai/client.py — BIN-148).
    ai_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    combined_score: Optional[float] = None
    percentile_rank: Optional[float] = None
    z_score: Optional[float] = None
    price_per_m2: Optional[float] = None
    neighborhood_mean: Optional[float] = None
    neighborhood_median: Optional[float] = None
    price_per_m2_rent: Optional[float] = None
    price_per_m2_sale: Optional[float] = None
    neighborhood_mean_rent: Optional[float] = None
    neighborhood_mean_sale: Optional[float] = None
    neighborhood_median_rent: Optional[float] = None
    neighborhood_median_sale: Optional[float] = None
    stat_score_rent: Optional[float] = None
    stat_score_sale: Optional[float] = None
    z_score_rent: Optional[float] = None
    z_score_sale: Optional[float] = None
    percentile_rank_rent: Optional[float] = None
    percentile_rank_sale: Optional[float] = None
    combined_score_rent: Optional[float] = None
    combined_score_sale: Optional[float] = None
    neighborhood_id: Optional[str] = None
    neighborhood_name: Optional[str] = None
    city: Optional[str] = None
    location: Dict[str, Any]
    listings: List[PropertyListingModel] = []
    primary_listing: Optional[PropertyListingModel] = None
    deal_summary: Optional[str] = None
    stat_analysis: Dict[str, Any]
    ai_analysis: Dict[str, Any]
    neighbourhood_quality: Optional[NeighbourhoodQualityModel] = None
    model_config = ConfigDict(extra="ignore")


class PriceHistoryModel(BaseModel):
    id: str
    price: float
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    listing_type: str
    platform: str
    property_listing_id: Optional[str] = None


# System models
class SystemStatusResponse(BaseModel):
    database: Dict[str, Any]
    redis: Dict[str, Any]
    ollama: Dict[str, Any]
    workers: Dict[str, Any]
    ai_workers_paused: bool
    stats: Dict[str, Any]


class PipelineResponse(BaseModel):
    queues: Dict[str, int]
    scrapers_status: Dict[str, Any]
    ai_metrics: Dict[str, Any]
    recent_scrape_runs: List[Dict[str, Any]] = []
    # Safe proxy mode / pool readiness (BIN-124); never includes credentials.
    proxy: Dict[str, Any] = Field(default_factory=dict)


class PipelineHistoryPoint(BaseModel):
    ts: str
    total_properties: Optional[int] = None
    enriched_properties: Optional[int] = None
    scraper_queue: int
    ai_queue: int
    throughput_per_min: float


class PipelineHistoryResponse(BaseModel):
    points: List[PipelineHistoryPoint]


# ---------------------------------------------------------------------------
# Backfill control plane (v0.13-s1.5)
#
# Wire contract for ``/admin/backfill/*``: the *control* state of the cloud
# enrichment backfill, read from the same Redis keys the CLI uses. Never any
# DB-derived progress figure (coverage/throughput/ETA belong to story 1.4), and
# the state vocabulary stays English on the wire — pt-BR rendering is story 1.6.
# ---------------------------------------------------------------------------


class BackfillLeaseModel(BaseModel):
    """Who holds the single-instance runner lease (provenance, never the token)."""

    owner: str
    acquired_at: Optional[str] = None
    last_seen: Optional[str] = None
    seconds_since_last_seen: Optional[float] = None


class BackfillBudgetModel(BaseModel):
    """Today's request budget over the runner's rolling 24h window.

    ``consumed`` and ``seconds_until_reset`` come from the live window in Redis;
    ``limit`` is the configured ceiling (AppConfig ``backfill``) and
    ``remaining`` is arithmetic on the two. The runner accepts a
    ``--daily-budget`` override, which this endpoint cannot see — so ``--serve``
    refuses that flag, keeping the configured ceiling the one an API-requested
    run actually paces to.
    """

    limit: int
    consumed: int
    remaining: int
    seconds_until_reset: float


class BackfillCheckpointModel(BaseModel):
    """Resume marker — where the multi-day pass left off."""

    last_property_id: Optional[str] = None
    last_run_date: Optional[str] = None
    processed_total: int = 0


class BackfillPacingModel(BaseModel):
    """Configured pacing governors (AppConfig ``backfill``), for context.

    Configured, not observed: a run started by hand with ``--concurrency`` /
    ``--tpm-limit`` / ``--min-interval`` can pace differently. ``--serve``
    refuses those overrides so a run the *API* asked for always matches what is
    reported here.
    """

    requests_per_property: int
    rpm_limit: int
    concurrency: int
    tpm_limit: int


class BackfillStatusResponse(BaseModel):
    """``GET /admin/backfill/status``.

    **Four liveness-ish fields, and they mean different things.** Read them in
    this precedence:

    - ``active`` — **the** liveness signal: someone holds the single-instance
      runner lease. Render "a run is in progress" from this and nothing else.
    - ``state`` — what the runner last *published* (``idle|running|paused|
      backing-off|blocked``). It decays on a 120s TTL, so one row slower than
      that makes a live run read back ``idle`` while ``active`` stays true
      (DW-20). Use it to say *what* the run is doing, never *whether* it lives.
    - ``heartbeat_active`` — "rows are being enriched **right now**", not
      "alive". A deliberately paused run is healthy and stops beating the
      ``:active`` key on purpose (that key blocks ``migrate-primary.sh``, and a
      paused run must not), so a paused run reads ``active=true``,
      ``state=paused``, ``heartbeat_active=false``. Never render this as dead.
    - ``runner_present`` — "is anything listening at all": a lease holder **or**
      a waiting ``--serve`` supervisor. False means a start request would queue
      into the void, which is the one thing the UI must say out loud (UX-DR3).
    """

    state: str
    active: bool
    runner_present: bool
    heartbeat_active: bool
    migration_active: bool
    pending_requests: List[str] = Field(default_factory=list)
    start_requested_at: Optional[str] = None
    lease: Optional[BackfillLeaseModel] = None
    budget: BackfillBudgetModel
    checkpoint: BackfillCheckpointModel
    # Deliberately **not** computed on this surface: counting quarantined rows
    # is an O(properties-ever-attempted) HGETALL + sort, and this endpoint is
    # polled every few seconds and carries no rate limit. Always null here; the
    # CLI's one-shot ``--status`` still reports it, and progress telemetry is
    # story 1.4's (DB-derived).
    quarantined: Optional[int] = None
    pacing: BackfillPacingModel


class BackfillControlResponse(BaseModel):
    """``POST /admin/backfill/pause|resume`` — the action plus refreshed status.

    ``status`` is **nullable and its absence is not a failure**: a null status
    means the request WAS applied and only the follow-up status read failed
    (Redis blip mid-response). Reporting an applied pause as a 500 would tell the
    operator it did not take, so the mutation's own outcome is the response code
    and the status is best-effort — poll ``GET /admin/backfill/status``.
    """

    action: str
    # "resume" clears a pending stop as well as the pause; saying so keeps the
    # caller from thinking a stop it issued earlier is still in force.
    cleared_stop: bool = False
    # "pause" withdraws a pending start request when no run holds the lease —
    # otherwise the launching run would discard the pause at start-up and the
    # operator's second command would be silently void.
    cleared_start: bool = False
    status: Optional[BackfillStatusResponse] = None


class BackfillStartResponse(BaseModel):
    """``POST /admin/backfill/start`` — a *request*, not an execution.

    The API never spawns a runner (no cloud key in the container, no subprocess
    from a request thread): it records the request and a host-side ``--serve``
    supervisor consumes it. ``runner_present`` says whether anything is
    listening at all.
    """

    requested: bool
    already_requested: bool
    requested_at: Optional[str] = None
    runner_present: bool
    discarded_requests: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Enrichment coverage (v0.13-s1.6, absorbing story 1.4 — FR-29)
#
# The counterpart to the control plane above: how much of the corpus actually
# carries each enrichment signal, measured from ``properties`` /
# ``metrics_scoring`` and never from the runner's Redis checkpoints. The only
# thing Redis contributes here is ``backfill.active`` (does anyone hold the
# lease). Signal identity is the ``EnrichmentTaskClass`` vocabulary, English on
# the wire; pt-BR exists only as a rendered label.
#
# Every optional field means "not measurable", never "zero" — the UI omits the
# line rather than printing 0% or an invented ETA (UX-DR3/DR5/DR6).
# ---------------------------------------------------------------------------


class SignalCoverageModel(BaseModel):
    """Coverage of one ``EnrichmentTaskClass`` over the active corpus.

    ``fraction`` is ``null`` — not ``0.0`` — when ``total`` is 0: an empty
    denominator makes coverage undefined, and 0% would read as a total
    enrichment failure on a database that simply has no active properties.
    """

    task_class: str
    enriched: int
    total: int
    fraction: Optional[float] = Field(None, ge=0.0, le=1.0)


class BackfillProgressModel(BaseModel):
    """Live-run progress: one Redis-sourced flag, everything else from the DB.

    ``active`` is the runner's single-instance lease (the same liveness signal
    ``GET /admin/backfill/status`` exposes) and is the *only* field Redis feeds.
    ``remaining`` counts the runner's own queue — active rows with no AI score,
    minus the rows its photo gate would refuse — so it stays reachable.

    The three projection fields are ``null`` together whenever they cannot be
    stated honestly: no run holds the lease, fewer than two usable snapshots sit
    in the throughput window (which starts at the current run's lease
    acquisition when that is inside the trailing 24h, so a young run is not
    averaged across idle hours), or the delta is non-positive. ``eta_days`` is
    never ``inf``/NaN on the wire (JSON cannot carry either); an unreachable
    completion is ``null``, and ``remaining == 0`` under a live run is ``0.0``
    with today's date.

    ``throughput_per_day``, ``eta_days`` and ``projected_completion_date`` are
    **approximations, not schedule commitments**, for two reasons a consumer of
    this schema has to know (both are argued at length in
    ``adapters.db.enrichment_coverage_queries``):

    * *The numerator and the denominator measure different populations.* The
      rate comes from ``pipeline_metric_snapshots.enriched_properties``, which
      is ``COUNT(*) FROM metrics_scoring WHERE ai_score > 0`` over the whole
      corpus — no ``active`` filter, no photo gate, and it also moves when the
      live pipeline enriches a row that the backfill never touched. Dividing
      the backfill's ``remaining`` by total enrichment velocity runs optimistic
      whenever the live pipeline is busy.
    * *``remaining`` does not subtract quarantined candidates.* Rows that have
      exhausted their retry budget stop being work for the runner but keep
      counting here, because excluding them means an O(rows-ever-attempted)
      Redis scan on a polled route (the same cost that keeps ``quarantined``
      null on ``GET /admin/backfill/status``). A pass whose tail is permanently
      failing rows therefore shows an ETA that does not converge to zero.

    Render them as an order of magnitude for an operator watching a multi-day
    pass — never as a delivery date.
    """

    active: bool
    remaining: int
    throughput_per_day: Optional[float] = Field(None, ge=0.0)
    eta_days: Optional[float] = Field(None, ge=0.0)
    # ISO ``YYYY-MM-DD``; a string, so a client renders it without re-deriving a
    # timezone the server never meant.
    projected_completion_date: Optional[str] = None


class EnrichmentCoverageResponse(BaseModel):
    """``GET /admin/enrichment/coverage``.

    ``signals`` always carries one entry per ``EnrichmentTaskClass``, in enum
    declaration order — an omitted signal would read as "not applicable" rather
    than "not enriched". ``minimum_fraction`` is the smallest measurable
    fraction (the figure the Painel health strip renders as ``Cobertura de IA
    N%``) and is ``null`` when nothing is measurable.
    """

    signals: List[SignalCoverageModel]
    minimum_fraction: Optional[float] = Field(None, ge=0.0, le=1.0)
    total_properties: int
    backfill: BackfillProgressModel
