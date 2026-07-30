import { getActiveLocale } from './i18n/activeLocale.js'
import { t } from './i18n/index.js'

const BASE = '/api'

/** sessionStorage key for the paste-once API credential (never committed). */
export const API_KEY_STORAGE = 'api_key'

// ---------------------------------------------------------------------------
// Shared wire types (mirrors src/api/schemas.py + the admin/watchlist/
// favourites/saved-searches routers). Kept intentionally close to the
// Pydantic response models — this is the seam between backend and frontend,
// so drift here should surface as a compile error, not a runtime bug.
// ---------------------------------------------------------------------------

export type ListingType = 'rent' | 'sale' | 'both'
export type PriceType = 'rent' | 'sale'
export type SortDir = 'asc' | 'desc'
export type ExportFormat = 'csv' | 'json'

export interface PropertyListing {
  platform: string
  platform_listing_id: string
  listing_type: string
  price: number
  currency: string
  url: string
  is_furnished?: boolean | null
  accepts_pets?: boolean | null
  condo_fee?: number | null
  iptu?: number | null
  base_price?: number | null
  fees_bundled?: boolean | null
}

export interface NeighbourhoodQuality {
  amenity_score?: number | null
  transit_score?: number | null
  access_score?: number | null
  safety_score?: number | null
  neighbourhood_score: number
  risk_flags: string[]
  quality_meta?: Record<string, unknown> | null
  quality_notes?: string | null
}

/** `GET /properties` list item — see api.schemas.PropertyModel. */
export interface Property {
  id: string
  public_id?: number | null
  platform: string
  platform_id: string
  title: string
  price: number
  area_m2?: number | null
  bedrooms?: number | null
  bathrooms?: number | null
  address?: string | null
  image_urls: string[]
  created_at?: string | null
  lat?: number | null
  lon?: number | null
  stat_score?: number | null
  ai_score?: number | null
  combined_score?: number | null
  percentile_rank?: number | null
  z_score?: number | null
  price_per_m2?: number | null
  neighborhood_mean?: number | null
  neighborhood_id?: string | null
  neighborhood_name?: string | null
  city?: string | null
  parking?: number | null
  description?: string | null
  available_for_rent: boolean
  available_for_sale: boolean
  ai_features: string[]
  ai_issues: string[]
  ai_green_flags: string[]
  ai_red_flags: string[]
  // AI domain scores are floats in [0.0, 1.0] (see VisualResult / SentimentResult).
  condition_score?: number | null
  sentiment_score?: number | null
  stat_category?: string | null
  stat_reasoning?: string | null
  deal_summary?: string | null
  visual_category?: string | null
  visual_reasoning?: string | null
  sentiment_category?: string | null
  sentiment_reasoning?: string | null
  listings: PropertyListing[]
  primary_listing?: PropertyListing | null
  neighbourhood_quality?: NeighbourhoodQuality | null
}

/** `GET /properties/{id}` — see api.schemas.PropertyDetailModel (superset of Property). */
export interface PropertyDetail extends Omit<Property, 'listings' | 'primary_listing'> {
  props_json: Record<string, unknown>
  location: Record<string, unknown>
  stat_analysis: Record<string, unknown>
  ai_analysis: Record<string, unknown>
  listings: PropertyListing[]
  primary_listing?: PropertyListing | null
}

export interface PaginatedProperties {
  total: number
  page: number
  page_size: number
  pages: number
  properties: Property[]
}

export interface PropertyBatch {
  properties: Property[]
}

export interface Neighborhood {
  name: string
  count: number
  city?: string | null
  id?: string | null
  amenity_score?: number | null
  transit_score?: number | null
  access_score?: number | null
  safety_score?: number | null
  risk_flags: string[]
  quality_meta?: Record<string, unknown> | null
  quality_notes?: string | null
  neighbourhood_score?: number | null
}

export interface City {
  name: string
  count: number
}

export interface PriceHistoryPoint {
  id: string
  price: number
  start_ts?: string | null
  end_ts?: string | null
  listing_type: string
  platform: string
  property_listing_id?: string | null
}

export interface WatchlistItem {
  id: string
  property_id: string
  min_drop_pct: number
  last_notified_price?: number | null
  created_at?: string | null
}

export interface WatchlistCheck {
  watched: boolean
  id?: string
  min_drop_pct?: number
  last_notified_price?: number | null
}

export interface FavouriteItem {
  id: string
  property_id: string
  created_at?: string | null
}

export interface FavouriteWithProperty {
  id: string
  property_id: string
  public_id?: number | null
  created_at?: string | null
  title?: string | null
  address?: string | null
  price?: number | null
  image_urls?: string[] | null
  combined_score?: number | null
  neighborhood_name?: string | null
  platform?: string | null
}

export interface PaginatedFavourites {
  items: FavouriteWithProperty[]
  total: number
  page: number
  page_size: number
}

export interface FavouriteCheck {
  favourited: boolean
  id?: string
  created_at?: string | null
}

export interface SavedSearchItem {
  id: string
  name: string
  filters: Record<string, unknown>
  created_at?: string | null
}

export interface PaginatedSavedSearches {
  items: SavedSearchItem[]
  total: number
  page: number
  page_size: number
}

export interface SystemStatus {
  database: Record<string, unknown>
  redis: Record<string, unknown>
  ollama: Record<string, unknown>
  workers: Record<string, unknown>
  ai_workers_paused: boolean
  stats: Record<string, unknown>
}

export interface PipelineStatus {
  queues: Record<string, number>
  scrapers_status: Record<string, unknown>
  ai_metrics: Record<string, unknown>
  recent_scrape_runs: Record<string, unknown>[]
  proxy: Record<string, unknown>
}

export interface PipelineHistoryPoint {
  ts: string
  total_properties?: number | null
  enriched_properties?: number | null
  scraper_queue: number
  ai_queue: number
  throughput_per_min: number
}

export interface PipelineHistory {
  points: PipelineHistoryPoint[]
}

export type PlatformInfo = Record<string, unknown>
export type ScrapeCheckpoint = Record<string, unknown>
export type ScrapeTriggerResult = Record<string, unknown>
export type ScoringWeights = Record<string, unknown>
export type ScheduleEntry = Record<string, unknown>
export type AlertItem = Record<string, unknown>
export type LocaleResponse = Record<string, unknown>

/** Generic admin-endpoint envelope for actions that just report status/counts. */
export type AdminActionResult = Record<string, unknown>

export type EnrichmentMode = 'missing' | 'force' | 'stale_before'
export type EnrichmentStages = 'all' | 'visual+sentiment' | 'verdict_only'

export interface EnrichmentRerunOptions {
  mode?: EnrichmentMode
  stages?: EnrichmentStages
  dry_run?: boolean
  city?: string
  platform?: string
  limit?: number | string
  active_only?: boolean
  stale_before?: string
  neighbourhood_ids?: string[]
}

// ---------------------------------------------------------------------------
// Shared property filter params (list + export)
// ---------------------------------------------------------------------------

export interface PropertyFilterOptions {
  page?: number
  pageSize?: number
  platform?: string
  minScore?: number
  maxPrice?: number
  priceType?: PriceType
  minBedrooms?: number
  minParking?: number
  neighborhoodName?: string
  cityName?: string
  listingType?: ListingType
  propertyType?: string
  isFurnished?: boolean
  acceptsPets?: boolean
  sortBy?: string
  sortDir?: SortDir
  bbox?: string
  q?: string
}

interface BuildPropertyFilterParamsOptions extends PropertyFilterOptions {
  includePagination?: boolean
}

// ---------------------------------------------------------------------------
// Fetch plumbing
// ---------------------------------------------------------------------------

function authErrorMessage(): string {
  return t(getActiveLocale(), 'errors.invalidCredential')
}

function apiError(key: string, fallbackDetail?: unknown): string {
  if (fallbackDetail) return String(fallbackDetail)
  return t(getActiveLocale(), key)
}

export function getApiKey(): string {
  return sessionStorage.getItem(API_KEY_STORAGE) || ''
}

export function setApiKey(key: string): void {
  const trimmed = String(key ?? '').trim()
  if (trimmed) {
    sessionStorage.setItem(API_KEY_STORAGE, trimmed)
  } else {
    sessionStorage.removeItem(API_KEY_STORAGE)
  }
}

export function clearApiKey(): void {
  sessionStorage.removeItem(API_KEY_STORAGE)
}

export function hasApiKey(): boolean {
  return Boolean(getApiKey())
}

/** Validate the stored (or just-set) credential against /admin/health. */
export async function validateApiCredential(): Promise<{ status: string }> {
  return apiFetch('/admin/health')
}

interface ApiFetchOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | Record<string, unknown> | null
}

async function apiFetch<T = unknown>(endpoint: string, options: ApiFetchOptions = {}): Promise<T> {
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) }

  const apiKey = getApiKey()
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }

  let body = options.body
  if (body && typeof body === 'object' && !(body instanceof URLSearchParams)) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(body)
  } else if (body instanceof URLSearchParams) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded'
  }

  const r = await fetch(`${BASE}${endpoint}`, {
    ...options,
    headers,
    body: body as BodyInit | null | undefined,
  })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) {
      throw new Error(authErrorMessage())
    }
    const err = await r.json().catch(() => ({}))
    throw new Error(apiError('errors.apiRequestFailed', err.detail))
  }
  return r.json()
}

/** Attaches X-API-Key when present (Epic 2 edge auth) — these routes accept
 * anonymous access only when no admin API key is configured server-side
 * (BIN-150: consistent with the rest of the admin surface). */
function authHeaders(): Record<string, string> {
  const apiKey = getApiKey()
  return apiKey ? { 'X-API-Key': apiKey } : {}
}

export async function fetchStatus(): Promise<SystemStatus> {
  const r = await fetch(`${BASE}/system/status`, { headers: authHeaders() })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) throw new Error(authErrorMessage())
    throw new Error(t(getActiveLocale(), 'errors.statusFetchFailed'))
  }
  return r.json()
}

export async function fetchPipeline(): Promise<PipelineStatus> {
  const r = await fetch(`${BASE}/system/pipeline`, { headers: authHeaders() })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) throw new Error(authErrorMessage())
    throw new Error(t(getActiveLocale(), 'errors.pipelineFetchFailed'))
  }
  return r.json()
}

export async function fetchPipelineHistory(minutes = 60): Promise<PipelineHistory> {
  const r = await fetch(`${BASE}/system/pipeline/history?minutes=${minutes}`, { headers: authHeaders() })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) throw new Error(authErrorMessage())
    throw new Error(t(getActiveLocale(), 'errors.pipelineHistoryFetchFailed'))
  }
  return r.json()
}

export async function fetchPlatforms(): Promise<PlatformInfo> {
  const r = await fetch(`${BASE}/platforms`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.platformsFetchFailed'))
  return r.json()
}

export async function triggerScrape(
  platform: string,
  checkpoint: ScrapeCheckpoint = {},
  scrapeType = 'both',
): Promise<ScrapeTriggerResult> {
  // /scrape requires an admin credential (BIN-149) — routed through apiFetch
  // so the stored X-API-Key is attached like other gated admin actions
  // (enrichMissing, triggerAvailabilityRecheck, ...).
  return apiFetch<ScrapeTriggerResult>('/scrape', {
    method: 'POST',
    body: { platform, checkpoint, scrape_type: scrapeType },
  })
}

/** Shared filter query params for list + export (same surface as GET /properties). */
function buildPropertyFilterParams({
  page = 1,
  pageSize = 24,
  platform,
  minScore,
  maxPrice,
  priceType,
  minBedrooms,
  minParking,
  neighborhoodName,
  cityName,
  listingType,
  propertyType,
  isFurnished,
  acceptsPets,
  sortBy = 'combined_score',
  sortDir = 'desc',
  bbox,
  q,
  includePagination = true,
}: BuildPropertyFilterParamsOptions = {}): URLSearchParams {
  const params = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir })
  if (includePagination) {
    params.set('page', String(page))
    params.set('page_size', String(pageSize))
  }
  if (platform) params.set('platform', platform)
  if (minScore != null) params.set('min_score', String(minScore))
  if (maxPrice != null) params.set('max_price', String(maxPrice))
  if (maxPrice != null && priceType) params.set('price_type', priceType)
  if (minBedrooms != null) params.set('min_bedrooms', String(minBedrooms))
  if (minParking != null) params.set('min_parking', String(minParking))
  if (neighborhoodName) params.set('neighborhood_name', neighborhoodName)
  if (cityName) params.set('city_name', cityName)
  if (listingType && listingType !== 'both') params.set('listing_type', listingType)
  if (propertyType) params.set('property_type', propertyType)
  if (isFurnished) params.set('is_furnished', 'true')
  if (acceptsPets) params.set('accepts_pets', 'true')
  if (bbox) params.set('bbox', bbox)
  if (q && String(q).trim()) params.set('q', String(q).trim())
  return params
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function fetchProperties(opts: PropertyFilterOptions = {}): Promise<PaginatedProperties> {
  const params = buildPropertyFilterParams({ ...opts, includePagination: true })

  const r = await fetch(`${BASE}/properties?${params}`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.propertiesFetchFailed'))
  return r.json()
}

export interface ExportResult {
  format: ExportFormat
  total: number | null
  truncated: boolean | null
}

/**
 * Download filtered properties as CSV or JSON via GET /properties/export (BIN-51).
 * Attaches X-API-Key when present (Epic 2 edge auth). Triggers a browser download.
 */
export async function exportProperties(
  opts: PropertyFilterOptions & { format?: ExportFormat } = {},
): Promise<ExportResult> {
  const { format = 'json', ...filterOpts } = opts
  if (format !== 'csv' && format !== 'json') {
    throw new Error(t(getActiveLocale(), 'errors.exportFormatInvalid'))
  }

  const params = buildPropertyFilterParams({ ...filterOpts, includePagination: false })
  params.set('format', format)

  const headers: Record<string, string> = {}
  const apiKey = getApiKey()
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }

  const r = await fetch(`${BASE}/properties/export?${params}`, { headers })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) {
      throw new Error(authErrorMessage())
    }
    const err = await r.json().catch(() => ({}))
    const detail = err.detail
    const message = typeof detail === 'string'
      ? detail
      : (Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg || d).join('; ') : null)
    throw new Error(message || t(getActiveLocale(), 'errors.exportFailed'))
  }

  if (format === 'csv') {
    const blob = await r.blob()
    triggerBrowserDownload(blob, 'properties-export.csv')
    const totalHeader = r.headers.get('X-Export-Total')
    const truncatedHeader = r.headers.get('X-Export-Truncated')
    return {
      format,
      total: totalHeader != null ? Number(totalHeader) : null,
      truncated: truncatedHeader === 'true',
    }
  }

  const data = await r.json()
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  triggerBrowserDownload(blob, 'properties-export.json')
  return {
    format,
    total: data.total ?? null,
    truncated: Boolean(data.truncated),
  }
}

export async function fetchProperty(id: string): Promise<PropertyDetail> {
  const r = await fetch(`${BASE}/properties/${id}`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.propertyFetchFailed'))
  return r.json()
}

export async function fetchPropertiesByIds(
  ids: Array<string | null | undefined>,
): Promise<PropertyBatch> {
  const list = Array.isArray(ids) ? ids.filter(Boolean) : []
  if (list.length < 1 || list.length > 4) {
    throw new Error(t(getActiveLocale(), 'errors.batchIdsInvalid'))
  }
  const params = new URLSearchParams({ ids: (list as string[]).join(',') })
  const r = await fetch(`${BASE}/properties/by-ids?${params}`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.batchFetchFailed'))
  return r.json()
}

export async function pauseWorkers(): Promise<AdminActionResult> {
  return apiFetch('/admin/workers/pause', { method: 'POST' })
}

export async function resumeWorkers(): Promise<AdminActionResult> {
  return apiFetch('/admin/workers/resume', { method: 'POST' })
}

export async function recalculateScores(weights: ScoringWeights | null = null): Promise<AdminActionResult> {
  return apiFetch('/admin/scoring/recalculate', {
    method: 'POST',
    body: weights,
  })
}

export async function enrichMissing(): Promise<AdminActionResult> {
  return apiFetch('/admin/enrichment/missing', { method: 'POST' })
}

/**
 * Enqueue one batch of listing URL availability rechecks (BIN-80 / BIN-123).
 * @param batchSize optional override; server uses config default when omitted
 */
export async function triggerAvailabilityRecheck(
  batchSize?: number | string,
): Promise<AdminActionResult> {
  const qs =
    batchSize != null && batchSize !== ''
      ? `?batch_size=${encodeURIComponent(Number(batchSize))}`
      : ''
  return apiFetch(`/admin/availability/recheck${qs}`, { method: 'POST' })
}

/** Selective AI enrichment re-run (BIN-95). */
export async function enrichmentRerun(opts: EnrichmentRerunOptions = {}): Promise<AdminActionResult> {
  const body: Record<string, unknown> = { ...opts }
  if (body.limit === '' || body.limit == null) delete body.limit
  else body.limit = Number(body.limit)
  if (!body.city) delete body.city
  if (!body.platform) delete body.platform
  if (!body.stale_before) delete body.stale_before
  if (!(body.neighbourhood_ids as string[] | undefined)?.length) delete body.neighbourhood_ids
  return apiFetch('/admin/enrichment/rerun', {
    method: 'POST',
    body,
  })
}

export async function scaleGPU(limit: number): Promise<AdminActionResult> {
  return apiFetch('/admin/gpu/scale', {
    method: 'POST',
    body: { limit },
  })
}

export async function updateWeights(weights: ScoringWeights): Promise<AdminActionResult> {
  return apiFetch('/admin/scoring/weights', {
    method: 'POST',
    body: weights,
  })
}

export async function ensureOllama(): Promise<AdminActionResult> {
  return apiFetch('/system/ollama/ensure', { method: 'POST' })
}

export async function fetchSchedule(): Promise<ScheduleEntry> {
  return apiFetch('/admin/schedule')
}

export async function updateSchedule(
  platform: string,
  intervalMinutes: number,
): Promise<AdminActionResult> {
  return apiFetch('/admin/schedule', {
    method: 'POST',
    body: { platform, interval_minutes: intervalMinutes },
  })
}

export async function fetchLocale(): Promise<LocaleResponse> {
  return apiFetch('/admin/locale')
}

export async function updateLocale(locale: string): Promise<LocaleResponse> {
  return apiFetch('/admin/locale', {
    method: 'POST',
    body: { locale },
  })
}

// ---------------------------------------------------------------------------
// Alerts API
// ---------------------------------------------------------------------------

export async function fetchAlerts(): Promise<AlertItem[]> {
  const r = await fetch(`${BASE}/system/alerts`, { headers: authHeaders() })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) throw new Error(authErrorMessage())
    throw new Error(t(getActiveLocale(), 'errors.alertsFetchFailed'))
  }
  return r.json()
}

// ---------------------------------------------------------------------------
// Watchlist API
// ---------------------------------------------------------------------------

export async function fetchWatchlist(): Promise<WatchlistItem[]> {
  return apiFetch('/watchlist')
}

export async function addToWatchlist(propertyId: string, minDropPct = 5.0): Promise<WatchlistItem> {
  return apiFetch('/watchlist', {
    method: 'POST',
    body: { property_id: propertyId, min_drop_pct: minDropPct },
  })
}

export async function removeFromWatchlist(propertyId: string): Promise<AdminActionResult> {
  return apiFetch(`/watchlist/${propertyId}`, { method: 'DELETE' })
}

export async function checkWatchlist(propertyId: string): Promise<WatchlistCheck> {
  return apiFetch(`/watchlist/check/${propertyId}`)
}

// ---------------------------------------------------------------------------
// Saved Searches API
// ---------------------------------------------------------------------------

export async function fetchSavedSearches(page = 1, pageSize = 50): Promise<PaginatedSavedSearches> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  return apiFetch(`/saved-searches?${params}`)
}

export async function saveSearch(
  name: string,
  filters: Record<string, unknown>,
): Promise<SavedSearchItem> {
  return apiFetch('/saved-searches', {
    method: 'POST',
    body: { name, filters },
  })
}

export async function deleteSavedSearch(id: string): Promise<AdminActionResult> {
  return apiFetch(`/saved-searches/${id}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Favourites API
// ---------------------------------------------------------------------------

export async function fetchFavourites({
  page = 1,
  pageSize = 50,
  sortBy = 'combined_score',
  sortDir = 'desc',
}: { page?: number; pageSize?: number; sortBy?: string; sortDir?: SortDir } = {}): Promise<PaginatedFavourites> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort_by: sortBy,
    sort_dir: sortDir,
  })
  return apiFetch(`/favourites?${params}`)
}

export async function addFavourite(propertyId: string): Promise<FavouriteItem> {
  return apiFetch('/favourites', {
    method: 'POST',
    body: { property_id: propertyId },
  })
}

export async function removeFavourite(propertyId: string): Promise<AdminActionResult> {
  return apiFetch(`/favourites/${propertyId}`, { method: 'DELETE' })
}

export async function checkFavourite(propertyId: string): Promise<FavouriteCheck> {
  return apiFetch(`/favourites/check/${propertyId}`)
}

// ---------------------------------------------------------------------------
// Neighborhoods API
// ---------------------------------------------------------------------------

export async function fetchNeighborhoods(): Promise<Neighborhood[]> {
  const r = await fetch(`${BASE}/properties/neighborhoods`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.neighborhoodsFetchFailed'))
  return r.json()
}

export async function fetchCities(): Promise<City[]> {
  const r = await fetch(`${BASE}/properties/cities`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.citiesFetchFailed'))
  return r.json()
}

// ---------------------------------------------------------------------------
// Price History API
// ---------------------------------------------------------------------------

export async function fetchPriceHistory(propertyId: string): Promise<PriceHistoryPoint[]> {
  const r = await fetch(`${BASE}/properties/${propertyId}/price-history`)
  if (!r.ok) throw new Error(t(getActiveLocale(), 'errors.priceHistoryFetchFailed'))
  return r.json()
}
