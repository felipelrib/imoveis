const BASE = '/api'

// Admin API key — exposed at build time via Vite (SPA constraint).
// Set VITE_API_KEY in frontend/.env.development (git-ignored) for local dev.
// In production, admin endpoints should be protected by a reverse proxy.
const ADMIN_KEY = import.meta.env.VITE_API_KEY || ''

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
  page = 1, pageSize = 24, platform, minScore, maxPrice, minBedrooms, minParking, neighborhoodName, listingType, propertyType, isFurnished, acceptsPets, sortBy = 'combined_score', sortDir = 'desc', bbox,
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

  const r = await fetch(`${BASE}/properties?${params}`)
  if (!r.ok) throw new Error('Properties fetch failed')
  return r.json()
}

export async function fetchProperty(id) {
  const r = await fetch(`${BASE}/properties/${id}`)
  if (!r.ok) throw new Error('Property fetch failed')
  return r.json()
}

export async function pauseWorkers() {
  const r = await fetch(`${BASE}/admin/workers/pause`, { 
    method: 'POST',
    headers: { 'X-API-Key': ADMIN_KEY }
  })
  return r.json()
}

export async function resumeWorkers() {
  const r = await fetch(`${BASE}/admin/workers/resume`, {
    method: 'POST',
    headers: { 'X-API-Key': ADMIN_KEY }
  })
  return r.json()
}

export async function recalculateScores(weights) {
  const r = await fetch(`${BASE}/admin/scoring/recalculate`, {
    method: 'POST',
    headers: { 
      'Content-Type': 'application/json',
      'X-API-Key': ADMIN_KEY
    },
    body: JSON.stringify(weights || null),
  })
  return r.json()
}

export async function ensureOllama() {
  const r = await fetch(`${BASE}/system/ollama/ensure`, { 
    method: 'POST',
    headers: { 'X-API-Key': ADMIN_KEY }
  })
  return r.json()
}

export async function fetchSchedule() {
  const r = await fetch(`${BASE}/admin/schedule`, {
    headers: { 'X-API-Key': ADMIN_KEY }
  })
  if (!r.ok) throw new Error('Schedule fetch failed')
  return r.json()
}

export async function updateSchedule(platform, interval_minutes) {
  const r = await fetch(`${BASE}/admin/schedule`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': ADMIN_KEY
    },
    body: JSON.stringify({ platform, interval_minutes }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Schedule update failed')
  }
  return r.json()
}

// ---------------------------------------------------------------------------
// Watchlist API
// ---------------------------------------------------------------------------

export async function fetchWatchlist() {
  const r = await fetch(`${BASE}/watchlist`)
  if (!r.ok) throw new Error('Watchlist fetch failed')
  return r.json()
}

export async function addToWatchlist(propertyId, minDropPct = 5.0) {
  const r = await fetch(`${BASE}/watchlist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ property_id: propertyId, min_drop_pct: minDropPct }),
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Add to watchlist failed')
  }
  return r.json()
}

export async function removeFromWatchlist(propertyId) {
  const r = await fetch(`${BASE}/watchlist/${propertyId}`, { method: 'DELETE' })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail || 'Remove from watchlist failed')
  }
  return r.json()
}

export async function checkWatchlist(propertyId) {
  const r = await fetch(`${BASE}/watchlist/check/${propertyId}`)
  if (!r.ok) throw new Error('Watchlist check failed')
  return r.json()
}

// ---------------------------------------------------------------------------
// Saved Searches API
// ---------------------------------------------------------------------------

export async function fetchSavedSearches() {
  const r = await fetch(`${BASE}/saved-searches`)
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

export async function fetchFavourites() {
  const r = await fetch(`${BASE}/favourites`)
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
