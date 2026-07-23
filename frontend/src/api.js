const BASE = '/api'

/** sessionStorage key for the paste-once API credential (never committed). */
export const API_KEY_STORAGE = 'api_key'

const AUTH_ERROR_MESSAGE = 'Invalid or missing API credential'

export function getApiKey() {
  return sessionStorage.getItem(API_KEY_STORAGE) || ''
}

export function setApiKey(key) {
  const trimmed = String(key ?? '').trim()
  if (trimmed) {
    sessionStorage.setItem(API_KEY_STORAGE, trimmed)
  } else {
    sessionStorage.removeItem(API_KEY_STORAGE)
  }
}

export function clearApiKey() {
  sessionStorage.removeItem(API_KEY_STORAGE)
}

export function hasApiKey() {
  return Boolean(getApiKey())
}

/**
 * Validate the stored (or just-set) credential against /admin/health.
 * @returns {Promise<{status: string}>}
 */
export async function validateApiCredential() {
  return apiFetch('/admin/health')
}

async function apiFetch(endpoint, options = {}) {
  const headers = { ...options.headers }

  const apiKey = getApiKey()
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }

  if (options.body && typeof options.body === 'object') {
    if (options.body instanceof URLSearchParams) {
      headers['Content-Type'] = 'application/x-www-form-urlencoded'
    } else {
      headers['Content-Type'] = 'application/json'
      options.body = JSON.stringify(options.body)
    }
  }

  const r = await fetch(`${BASE}${endpoint}`, { ...options, headers })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) {
      throw new Error(AUTH_ERROR_MESSAGE)
    }
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'API request failed')
  }
  return r.json()
}

export async function fetchStatus() {
  const r = await fetch(`${BASE}/system/status`)
  if (!r.ok) throw new Error('Status fetch failed')
  return r.json()
}

export async function fetchPipeline() {
  const r = await fetch(`${BASE}/system/pipeline`)
  if (!r.ok) throw new Error('Pipeline fetch failed')
  return r.json()
}

export async function fetchPlatforms() {
  const r = await fetch(`${BASE}/platforms`)
  if (!r.ok) throw new Error('Platforms fetch failed')
  return r.json()
}

export async function triggerScrape(platform, checkpoint = {}, scrapeType = 'both') {
  const r = await fetch(`${BASE}/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ platform, checkpoint, scrape_type: scrapeType }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Scrape trigger failed')
  }
  return r.json()
}

/**
 * Shared filter query params for list + export (same surface as GET /properties).
 * @param {object} opts
 * @param {boolean} [opts.includePagination]
 */
function buildPropertyFilterParams({
  page = 1,
  pageSize = 24,
  platform,
  minScore,
  maxPrice,
  minBedrooms,
  minParking,
  neighborhoodName,
  listingType,
  propertyType,
  isFurnished,
  acceptsPets,
  sortBy = 'combined_score',
  sortDir = 'desc',
  bbox,
  q,
  includePagination = true,
} = {}) {
  const params = new URLSearchParams({ sort_by: sortBy, sort_dir: sortDir })
  if (includePagination) {
    params.set('page', String(page))
    params.set('page_size', String(pageSize))
  }
  if (platform) params.set('platform', platform)
  if (minScore != null) params.set('min_score', minScore)
  if (maxPrice != null) params.set('max_price', maxPrice)
  if (minBedrooms != null) params.set('min_bedrooms', minBedrooms)
  if (minParking != null) params.set('min_parking', minParking)
  if (neighborhoodName) params.set('neighborhood_name', neighborhoodName)
  if (listingType && listingType !== 'both') params.set('listing_type', listingType)
  if (propertyType) params.set('property_type', propertyType)
  if (isFurnished) params.set('is_furnished', 'true')
  if (acceptsPets) params.set('accepts_pets', 'true')
  if (bbox) params.set('bbox', bbox)
  if (q && String(q).trim()) params.set('q', String(q).trim())
  return params
}

function triggerBrowserDownload(blob, filename) {
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

export async function fetchProperties({
  page = 1, pageSize = 24, platform, minScore, maxPrice, minBedrooms, minParking, neighborhoodName, listingType, propertyType, isFurnished, acceptsPets, sortBy = 'combined_score', sortDir = 'desc', bbox, q,
} = {}) {
  const params = buildPropertyFilterParams({
    page, pageSize, platform, minScore, maxPrice, minBedrooms, minParking,
    neighborhoodName, listingType, propertyType, isFurnished, acceptsPets,
    sortBy, sortDir, bbox, q, includePagination: true,
  })

  const r = await fetch(`${BASE}/properties?${params}`)
  if (!r.ok) throw new Error('Properties fetch failed')
  return r.json()
}

/**
 * Download filtered properties as CSV or JSON via GET /properties/export (BIN-51).
 * Attaches X-API-Key when present (Epic 2 edge auth). Triggers a browser download.
 *
 * @param {object} opts
 * @param {'csv'|'json'} opts.format
 * @returns {Promise<{ total: number|null, truncated: boolean|null, format: string }>}
 */
export async function exportProperties({
  format = 'json',
  platform,
  minScore,
  maxPrice,
  minBedrooms,
  minParking,
  neighborhoodName,
  listingType,
  propertyType,
  isFurnished,
  acceptsPets,
  sortBy = 'combined_score',
  sortDir = 'desc',
  bbox,
  q,
} = {}) {
  if (format !== 'csv' && format !== 'json') {
    throw new Error('Export format must be csv or json')
  }

  const params = buildPropertyFilterParams({
    platform, minScore, maxPrice, minBedrooms, minParking,
    neighborhoodName, listingType, propertyType, isFurnished, acceptsPets,
    sortBy, sortDir, bbox, q, includePagination: false,
  })
  params.set('format', format)

  const headers = {}
  const apiKey = getApiKey()
  if (apiKey) {
    headers['X-API-Key'] = apiKey
  }

  const r = await fetch(`${BASE}/properties/export?${params}`, { headers })
  if (!r.ok) {
    if (r.status === 401 || r.status === 403) {
      throw new Error(AUTH_ERROR_MESSAGE)
    }
    const err = await r.json().catch(() => ({}))
    const detail = err.detail
    const message = typeof detail === 'string'
      ? detail
      : (Array.isArray(detail) ? detail.map(d => d.msg || d).join('; ') : null)
    throw new Error(message || 'Export failed')
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

export async function fetchProperty(id) {
  const r = await fetch(`${BASE}/properties/${id}`)
  if (!r.ok) throw new Error('Property fetch failed')
  return r.json()
}

export async function fetchPropertiesByIds(ids) {
  const list = Array.isArray(ids) ? ids.filter(Boolean) : []
  if (list.length < 1 || list.length > 4) {
    throw new Error('fetchPropertiesByIds requires 1–4 ids')
  }
  const params = new URLSearchParams({ ids: list.join(',') })
  const r = await fetch(`${BASE}/properties/by-ids?${params}`)
  if (!r.ok) throw new Error('Properties batch fetch failed')
  return r.json()
}

export async function pauseWorkers() {
  return apiFetch('/admin/workers/pause', { method: 'POST' })
}

export async function resumeWorkers() {
  return apiFetch('/admin/workers/resume', { method: 'POST' })
}

export async function recalculateScores(weights = null) {
  return apiFetch('/admin/scoring/recalculate', {
    method: 'POST',
    body: weights
  })
}

export async function scaleGPU(limit) {
  return apiFetch('/admin/gpu/scale', {
    method: 'POST',
    body: { limit }
  })
}

export async function updateWeights(weights) {
  return apiFetch('/admin/scoring/weights', {
    method: 'POST',
    body: weights
  })
}

export async function ensureOllama() {
  return apiFetch('/system/ollama/ensure', { method: 'POST' })
}

export async function fetchSchedule() {
  return apiFetch('/admin/schedule')
}

export async function updateSchedule(platform, intervalMinutes) {
  return apiFetch('/admin/schedule', {
    method: 'POST',
    body: { platform, interval_minutes: intervalMinutes }
  })
}

// ---------------------------------------------------------------------------
// Alerts API
// ---------------------------------------------------------------------------

export async function fetchAlerts() {
  const r = await fetch(`${BASE}/system/alerts`)
  if (!r.ok) throw new Error('Alerts fetch failed')
  return r.json()
}

// ---------------------------------------------------------------------------
// Watchlist API
// ---------------------------------------------------------------------------

export async function fetchWatchlist() {
  return apiFetch('/watchlist')
}

export async function addToWatchlist(propertyId, minDropPct = 5.0) {
  return apiFetch('/watchlist', {
    method: 'POST',
    body: { property_id: propertyId, min_drop_pct: minDropPct }
  })
}

export async function removeFromWatchlist(propertyId) {
  return apiFetch(`/watchlist/${propertyId}`, { method: 'DELETE' })
}

export async function checkWatchlist(propertyId) {
  return apiFetch(`/watchlist/check/${propertyId}`)
}

// ---------------------------------------------------------------------------
// Saved Searches API
// ---------------------------------------------------------------------------

export async function fetchSavedSearches(page = 1, pageSize = 50) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  return apiFetch(`/saved-searches?${params}`)
}

export async function saveSearch(name, filters) {
  return apiFetch('/saved-searches', {
    method: 'POST',
    body: { name, filters },
  })
}

export async function deleteSavedSearch(id) {
  return apiFetch(`/saved-searches/${id}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Favourites API
// ---------------------------------------------------------------------------

export async function fetchFavourites({ page = 1, pageSize = 50, sortBy = 'combined_score', sortDir = 'desc' } = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize, sort_by: sortBy, sort_dir: sortDir })
  return apiFetch(`/favourites?${params}`)
}

export async function addFavourite(propertyId) {
  return apiFetch('/favourites', {
    method: 'POST',
    body: { property_id: propertyId },
  })
}

export async function removeFavourite(propertyId) {
  return apiFetch(`/favourites/${propertyId}`, { method: 'DELETE' })
}

export async function checkFavourite(propertyId) {
  return apiFetch(`/favourites/check/${propertyId}`)
}

// ---------------------------------------------------------------------------
// Neighborhoods API
// ---------------------------------------------------------------------------

export async function fetchNeighborhoods() {
  const r = await fetch(`${BASE}/properties/neighborhoods`)
  if (!r.ok) throw new Error('Neighborhoods fetch failed')
  return r.json()
}

// ---------------------------------------------------------------------------
// Price History API
// ---------------------------------------------------------------------------

export async function fetchPriceHistory(propertyId) {
  const r = await fetch(`${BASE}/properties/${propertyId}/price-history`)
  if (!r.ok) throw new Error('Price history fetch failed')
  return r.json()
}
