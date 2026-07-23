const BASE = '/api'

async function apiFetch(endpoint, options = {}) {
  const headers = { ...options.headers }

  // Attach JWT if available
  const token = sessionStorage.getItem('auth_token')
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
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

export async function fetchProperties({
  page = 1, pageSize = 24, platform, minScore, maxPrice, minBedrooms, minParking, neighborhoodName, listingType, propertyType, isFurnished, acceptsPets, sortBy = 'combined_score', sortDir = 'desc', bbox, q,
} = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize, sort_by: sortBy, sort_dir: sortDir })
  if (platform)    params.set('platform', platform)
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

  const r = await fetch(`${BASE}/properties?${params}`)
  if (!r.ok) throw new Error('Properties fetch failed')
  return r.json()
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

export async function adminLogin(username, password) {
  const params = new URLSearchParams()
  params.append('username', username)
  params.append('password', password)

  const r = await apiFetch('/auth/admin/login', {
    method: 'POST',
    body: params
  })
  if (r.access_token) {
    sessionStorage.setItem('auth_token', r.access_token)
  }
  return r
}

export function adminLogout() {
  sessionStorage.removeItem('auth_token')
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
  const r = await fetch(`${BASE}/saved-searches?${params}`)
  if (!r.ok) throw new Error('Saved searches fetch failed')
  return r.json()
}

export async function saveSearch(name, filters) {
  const r = await fetch(`${BASE}/saved-searches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, filters }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Save search failed')
  }
  return r.json()
}

export async function deleteSavedSearch(id) {
  const r = await fetch(`${BASE}/saved-searches/${id}`, { method: 'DELETE' })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Delete saved search failed')
  }
  return r.json()
}

// ---------------------------------------------------------------------------
// Favourites API
// ---------------------------------------------------------------------------

export async function fetchFavourites({ page = 1, pageSize = 50, sortBy = 'combined_score', sortDir = 'desc' } = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize, sort_by: sortBy, sort_dir: sortDir })
  const r = await fetch(`${BASE}/favourites?${params}`)
  if (!r.ok) throw new Error('Favourites fetch failed')
  return r.json()
}

export async function addFavourite(propertyId) {
  const r = await fetch(`${BASE}/favourites`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ property_id: propertyId }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Add favourite failed')
  }
  return r.json()
}

export async function removeFavourite(propertyId) {
  const r = await fetch(`${BASE}/favourites/${propertyId}`, { method: 'DELETE' })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Remove favourite failed')
  }
  return r.json()
}

export async function checkFavourite(propertyId) {
  const r = await fetch(`${BASE}/favourites/check/${propertyId}`)
  if (!r.ok) throw new Error('Check favourite failed')
  return r.json()
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
