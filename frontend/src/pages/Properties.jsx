import { useState, useEffect, useCallback } from 'react'
import { fetchProperties, fetchWatchlist, addToWatchlist, removeFromWatchlist, fetchSavedSearches, saveSearch, deleteSavedSearch, fetchFavourites, addFavourite, removeFavourite, fetchNeighborhoods } from '../api.js'
import PropertyModal from '../components/PropertyModal.jsx'
import CompareView from '../components/CompareView.jsx'
import { useToast } from '../components/ToastProvider.jsx'
import MapView from '../components/MapView.jsx'
import { useCompareSelection } from '../hooks/useCompareSelection.js'

const SORT_OPTIONS = [
  { value: 'combined_score', label: '⭐ Best Score' },
  { value: 'price', label: '💰 Price (asc)' },
  { value: 'price_desc', label: '💰 Price (desc)' },
  { value: 'created_at', label: '🕒 Newest' },
  { value: 'area_m2', label: '📐 Area' },
]

const DEFAULT_FILTERS = {
  sortBy: 'combined_score',
  sortDir: 'desc',
  listingType: 'both',
  propertyType: '',
  maxPrice: '',
  minBedrooms: '',
  minParking: '',
  minScore: '',
  neighborhood: '',
  isFurnished: false,
  acceptsPets: false,
  q: '',
}

export default function Properties() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState(DEFAULT_FILTERS.sortBy)
  const [sortDir, setSortDir] = useState(DEFAULT_FILTERS.sortDir)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [listingType, setListingType] = useState(DEFAULT_FILTERS.listingType)
  const [propertyType, setPropertyType] = useState(DEFAULT_FILTERS.propertyType)
  const [maxPrice, setMaxPrice] = useState(DEFAULT_FILTERS.maxPrice)
  const [minBedrooms, setMinBedrooms] = useState(DEFAULT_FILTERS.minBedrooms)
  const [minParking, setMinParking] = useState(DEFAULT_FILTERS.minParking)
  const [minScore, setMinScore] = useState(DEFAULT_FILTERS.minScore)
  const [neighborhood, setNeighborhood] = useState(DEFAULT_FILTERS.neighborhood)
  const [isFurnished, setIsFurnished] = useState(DEFAULT_FILTERS.isFurnished)
  const [acceptsPets, setAcceptsPets] = useState(DEFAULT_FILTERS.acceptsPets)
  const [q, setQ] = useState(DEFAULT_FILTERS.q)
  const [qDraft, setQDraft] = useState(DEFAULT_FILTERS.q)
  const [selectedId, setSelectedId] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [watchedIds, setWatchedIds] = useState(new Set())
  const [favouriteIds, setFavouriteIds] = useState(new Set())
  const showToast = useToast()

  const onCompareLimitReached = useCallback(() => {
    showToast('You can compare up to 4 properties', { type: 'warning' })
  }, [showToast])

  const {
    selectedIds: compareIds,
    toggle: toggleCompare,
    clear: clearCompare,
    isSelected: isCompareSelected,
    canCompare,
  } = useCompareSelection({ onLimitReached: onCompareLimitReached })

  const handleToggleCompare = useCallback((e, propertyId) => {
    e.stopPropagation()
    toggleCompare(propertyId)
  }, [toggleCompare])

  const [compareOpen, setCompareOpen] = useState(false)

  const openCompare = useCallback(() => {
    if (!canCompare) return
    setCompareOpen(true)
  }, [canCompare])

  const closeCompare = useCallback(() => {
    setCompareOpen(false)
  }, [])

  // Saved searches state
  const [savedSearches, setSavedSearches] = useState([])
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [saveName, setSaveName] = useState('')

  // View mode: 'all' | 'favourites'
  const [viewMode, setViewMode] = useState('all')
  const [favouritesData, setFavouritesData] = useState({ items: [], total: 0 })

  // Dynamic neighborhoods from backend
  const [neighborhoods, setNeighborhoods] = useState([])
  const [neighborhoodsLoading, setNeighborhoodsLoading] = useState(false)

  // View mode: 'grid' | 'map'
  const [viewType, setViewType] = useState('grid')
  const [mapProperties, setMapProperties] = useState([])
  const [mapLoading, setMapLoading] = useState(false)

  const currentFilters = {
    sortBy, sortDir, listingType, propertyType, maxPrice,
    minBedrooms, minParking, minScore, neighborhood, isFurnished, acceptsPets, q,
  }

  const handleBboxChange = useCallback(async (bboxStr) => {
    setMapLoading(true)
    try {
      const res = await fetchProperties({
        page: 1,
        pageSize: 200,
        sortBy: sortBy === 'price_desc' ? 'price' : sortBy,
        sortDir: sortBy === 'price_desc' ? 'desc' : sortDir,
        maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
        minBedrooms: minBedrooms ? parseInt(minBedrooms) : undefined,
        minScore: minScore ? parseFloat(minScore) : undefined,
        minParking: minParking ? parseInt(minParking) : undefined,
        neighborhoodName: neighborhood || undefined,
        listingType: listingType,
        propertyType: propertyType || undefined,
        isFurnished: isFurnished ? true : undefined,
        acceptsPets: acceptsPets ? true : undefined,
        bbox: bboxStr,
        q: q || undefined,
      })
      setMapProperties(res.properties || [])
    } catch (e) {
      console.error('Map fetch failed:', e)
    } finally {
      setMapLoading(false)
    }
  }, [sortBy, sortDir, maxPrice, minBedrooms, minScore, minParking, neighborhood, listingType, propertyType, isFurnished, acceptsPets, q])

  const applyFilters = useCallback((filters) => {
    if (filters.sortBy !== undefined) setSortBy(filters.sortBy)
    if (filters.sortDir !== undefined) setSortDir(filters.sortDir)
    if (filters.listingType !== undefined) setListingType(filters.listingType)
    if (filters.propertyType !== undefined) setPropertyType(filters.propertyType)
    if (filters.maxPrice !== undefined) setMaxPrice(filters.maxPrice)
    if (filters.minBedrooms !== undefined) setMinBedrooms(filters.minBedrooms)
    if (filters.minParking !== undefined) setMinParking(filters.minParking)
    if (filters.minScore !== undefined) setMinScore(filters.minScore)
    if (filters.neighborhood !== undefined) setNeighborhood(filters.neighborhood)
    if (filters.isFurnished !== undefined) setIsFurnished(filters.isFurnished)
    if (filters.acceptsPets !== undefined) setAcceptsPets(filters.acceptsPets)
    if (filters.q !== undefined) {
      setQ(filters.q)
      setQDraft(filters.q)
    }
  }, [])

  const load = async (p = page) => {
    const isPriceDesc = sortBy === 'price_desc'
    const actualSortBy = isPriceDesc ? 'price' : sortBy
    const actualSortDir = sortBy === 'price' ? 'asc' : isPriceDesc ? 'desc' : sortDir

    if (viewMode === 'favourites') {
      setLoading(true)
      setLoadError(null)
      try {
        const favs = await fetchFavourites({ page: p, pageSize: 24, sortBy: actualSortBy, sortDir: actualSortDir })
        setFavouritesData(favs)
      } catch (e) {
        console.error(e)
        setLoadError(e.message || 'Failed to load favourites')
      } finally {
        setLoading(false)
      }
      return
    }

    setLoading(true)
    setLoadError(null)
    try {
      const isPriceDesc = sortBy === 'price_desc'
      const actualSortBy = isPriceDesc ? 'price' : sortBy
      const actualSortDir = sortBy === 'price' ? 'asc' : isPriceDesc ? 'desc' : sortDir

      const res = await fetchProperties({
        page: p,
        sortBy: actualSortBy,
        sortDir: actualSortDir,
        maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
        minBedrooms: minBedrooms ? parseInt(minBedrooms) : undefined,
        minScore: minScore ? parseFloat(minScore) : undefined,
        minParking: minParking ? parseInt(minParking) : undefined,
        neighborhoodName: neighborhood || undefined,
        listingType: listingType,
        propertyType: propertyType || undefined,
        isFurnished: isFurnished ? true : undefined,
        acceptsPets: acceptsPets ? true : undefined,
        q: q || undefined,
      })
      setData(res)
    } catch (e) {
      console.error(e)
      setLoadError(e.message || 'Failed to load properties')
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  // Load watchlist, favourites, saved searches, and neighborhoods on mount
  useEffect(() => {
    fetchWatchlist()
      .then(items => setWatchedIds(new Set(items.map(i => i.property_id))))
      .catch(() => {})
    fetchSavedSearches()
      .then(res => setSavedSearches(res.items || []))
      .catch(() => {})
    fetchFavourites({ page: 1, pageSize: 1000 })
      .then(res => setFavouriteIds(new Set((res.items || []).map(f => f.property_id))))
      .catch(() => {})
    // Fetch dynamic neighborhoods
    setNeighborhoodsLoading(true)
    fetchNeighborhoods()
      .then(setNeighborhoods)
      .catch(() => {})
      .finally(() => setNeighborhoodsLoading(false))
  }, [])

  const toggleWatchlist = useCallback(async (e, propertyId) => {
    e.stopPropagation()
    try {
      if (watchedIds.has(propertyId)) {
        await removeFromWatchlist(propertyId)
        setWatchedIds(prev => { const s = new Set(prev); s.delete(propertyId); return s })
      } else {
        await addToWatchlist(propertyId)
        setWatchedIds(prev => new Set([...prev, propertyId]))
      }
    } catch (err) {
      console.error('Watchlist toggle failed:', err)
      showToast('Failed to update watchlist: ' + err.message, { type: 'error' })
    }
  }, [watchedIds, showToast])

  const toggleFavourite = useCallback(async (e, propertyId) => {
    e.stopPropagation()
    try {
      if (favouriteIds.has(propertyId)) {
        await removeFavourite(propertyId)
        setFavouriteIds(prev => { const s = new Set(prev); s.delete(propertyId); return s })
      } else {
        await addFavourite(propertyId)
        setFavouriteIds(prev => new Set([...prev, propertyId]))
      }
    } catch (err) {
      console.error('Favourite toggle failed:', err)
      showToast('Failed to update favourites: ' + err.message, { type: 'error' })
    }
  }, [favouriteIds, showToast])

  // Reload on filter changes (except in favourites mode)
  useEffect(() => {
    if (viewMode === 'all') {
      load(1)
      setPage(1)
    }
  }, [sortBy, listingType, propertyType, maxPrice, minBedrooms, minParking, minScore, isFurnished, acceptsPets, neighborhood, viewMode, q])

  useEffect(() => {
    if (page !== 1 && viewMode === 'all') load(page)
  }, [page])

  const handleViewModeChange = (mode) => {
    setViewMode(mode)
    setPage(1)
  }

  const handleSaveSearch = async () => {
    if (!saveName.trim()) return
    try {
      await saveSearch(saveName.trim(), currentFilters)
      const updated = await fetchSavedSearches()
      setSavedSearches(updated)
      setSaveName('')
      setShowSaveDialog(false)
      showToast('Search saved!', { type: 'success' })
    } catch (err) {
      console.error('Save search failed:', err)
      showToast('Failed to save search: ' + err.message, { type: 'error' })
    }
  }

  const handleDeleteSavedSearch = async (e, id) => {
    e.stopPropagation()
    try {
      await deleteSavedSearch(id)
      setSavedSearches(prev => prev.filter(s => s.id !== id))
      showToast('Saved search deleted', { type: 'info' })
    } catch (err) {
      console.error('Delete saved search failed:', err)
      showToast('Failed to delete search: ' + err.message, { type: 'error' })
    }
  }

  const handleApplySavedSearch = (filters) => {
    setViewMode('all')
    applyFilters(filters)
  }

  const totalResults = viewMode === 'favourites' ? favouritesData.total : (data?.total || 0)
  const properties = viewMode === 'favourites' ? (favouritesData.items || []) : (data?.properties || [])
  const pages = viewMode === 'favourites' ? Math.ceil(totalResults / 24) : (data?.pages || 1)

  return (
    <div style={{ display: 'flex', gap: 20, minHeight: 'calc(100vh - 60px)' }}>
      {/* Sidebar */}
      <aside className="saved-searches-sidebar">
        <div className="sidebar-section">
          <div className="sidebar-header">Saved Searches</div>
          {savedSearches.length === 0 ? (
            <div className="sidebar-empty">No saved searches yet</div>
          ) : (
            <div className="sidebar-list">
              {savedSearches.map(ss => (
                <div
                  key={ss.id}
                  className="sidebar-item"
                  onClick={() => handleApplySavedSearch(ss.filters)}
                >
                  <span className="sidebar-item-name">{ss.name}</span>
                  <button className="sidebar-item-delete" onClick={(e) => handleDeleteSavedSearch(e, ss.id)} title="Delete">✕</button>
                </div>
              ))}
            </div>
          )}
          <button className="btn btn-ghost btn-sm" style={{ width: '100%', marginTop: 8 }} onClick={() => setShowSaveDialog(true)}>
            💾 Save Current Filters
          </button>
        </div>

        <div className="sidebar-section">
          <button
            className={`sidebar-link ${viewMode === 'favourites' ? 'active' : ''}`}
            onClick={() => handleViewModeChange('favourites')}
          >
            ★ Favourites {favouriteIds.size > 0 && <span className="badge">{favouriteIds.size}</span>}
          </button>
          {viewMode === 'favourites' && (
            <button className="btn btn-ghost btn-sm" style={{ width: '100%', marginTop: 4 }} onClick={() => handleViewModeChange('all')}>
              ← Back to All Properties
            </button>
          )}
        </div>
      </aside>

      {/* Main content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="page-header">
          <h1 className="page-title">{viewMode === 'favourites' ? '★ Favourites' : 'Properties'}</h1>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              {viewMode === 'favourites'
                ? `${favouritesData.total} favourited`
                : `${totalResults.toLocaleString('pt-BR')} properties`}
            </div>
        </div>

        {/* Toolbar */}
          <div className="toolbar" style={{ flexWrap: 'wrap', gap: 12 }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', width: '100%', alignItems: 'center' }}>
              <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0, flex: '1 1 220px' }}>
                <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }} htmlFor="semantic-search">Search</label>
                <input
                  id="semantic-search"
                  className="form-input"
                  style={{ flex: 1, minWidth: 160 }}
                  type="search"
                  placeholder="e.g. apto perto do metro com varanda"
                  value={qDraft}
                  onChange={e => setQDraft(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      setQ(qDraft.trim())
                    }
                  }}
                />
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={() => setQ(qDraft.trim())}
                >
                  Search
                </button>
                {q && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => { setQ(''); setQDraft('') }}
                    title="Clear search"
                  >
                    ✕
                  </button>
                )}
              </div>

              <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Sort by</label>
                <select className="form-select" style={{ width: 140 }} value={sortBy} onChange={e => setSortBy(e.target.value)}>
                  {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>

              <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Transaction</label>
                <select className="form-select" style={{ width: 110 }} value={listingType} onChange={e => setListingType(e.target.value)}>
                  <option value="both">Rent & Sale</option>
                  <option value="rent">Rent Only</option>
                  <option value="sale">Sale Only</option>
                </select>
              </div>

              <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Type</label>
                <select className="form-select" style={{ width: 120 }} value={propertyType} onChange={e => setPropertyType(e.target.value)}>
                  <option value="">Any</option>
                  <option value="Apartamento">Apartamento</option>
                  <option value="Casa">Casa</option>
                  <option value="CasaCondominio">Casa em Condomínio</option>
                  <option value="Studio">Studio</option>
                </select>
              </div>

              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ display: 'flex', border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
                  <button
                    className={`btn btn-sm ${viewType === 'grid' ? '' : 'btn-ghost'}`}
                    style={{ borderRadius: 0, padding: '4px 10px', fontSize: 12, fontWeight: 600, background: viewType === 'grid' ? 'var(--accent, #6366f1)' : 'transparent', color: viewType === 'grid' ? 'white' : 'var(--text-secondary)' }}
                    onClick={() => setViewType('grid')}
                  >
                    ☷ List
                  </button>
                  <button
                    className={`btn btn-sm ${viewType === 'map' ? '' : 'btn-ghost'}`}
                    style={{ borderRadius: 0, padding: '4px 10px', fontSize: 12, fontWeight: 600, background: viewType === 'map' ? 'var(--accent, #6366f1)' : 'transparent', color: viewType === 'map' ? 'white' : 'var(--text-secondary)', borderLeft: '1px solid var(--border-subtle)' }}
                    onClick={() => setViewType('map')}
                  >
                    🗺 Map
                  </button>
                </div>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => setShowAdvanced(!showAdvanced)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  {showAdvanced ? '▲ Hide Advanced' : '▼ Advanced Filters'}
                </button>
              </div>
            </div>

            {showAdvanced && (
              <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', width: '100%', alignItems: 'flex-start', background: 'rgba(0,0,0,0.1)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
                <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                  <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Max price R$</label>
                  <input className="form-input" style={{ width: 100 }} type="number" placeholder="Any" value={maxPrice} onChange={e => setMaxPrice(e.target.value)} />
                </div>
                <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                  <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Beds</label>
                  <select className="form-select" style={{ width: 70 }} value={minBedrooms} onChange={e => setMinBedrooms(e.target.value)}>
                    <option value="">Any</option>
                    {[1,2,3,4,5].map(n => <option key={n} value={n}>{n}+</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                  <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Parking</label>
                  <select className="form-select" style={{ width: 70 }} value={minParking} onChange={e => setMinParking(e.target.value)}>
                    <option value="">Any</option>
                    {[1,2,3,4,5].map(n => <option key={n} value={n}>{n}+</option>)}
                  </select>
                </div>
                <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
                  <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Min AI score</label>
                  <select className="form-select" style={{ width: 80 }} value={minScore} onChange={e => setMinScore(e.target.value)}>
                    <option value="">Any</option>
                    <option value="0.7">0.7+</option>
                    <option value="0.8">0.8+</option>
                    <option value="0.9">0.9+</option>
                  </select>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginLeft: 8 }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={isFurnished} onChange={e => setIsFurnished(e.target.checked)} />
                    Furnished
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={acceptsPets} onChange={e => setAcceptsPets(e.target.checked)} />
                    Pet Friendly
                  </label>
                </div>
                <div style={{ marginLeft: 16, display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: '200px' }}>
                  <label className="form-label" style={{ marginBottom: 0 }}>
                    Neighborhoods
                    {neighborhoodsLoading && <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>Loading…</span>}
                  </label>
                  <select
                    multiple
                    className="form-select"
                    style={{ height: '100px' }}
                    value={neighborhood ? neighborhood.split(',') : []}
                    onChange={e => { const opts = Array.from(e.target.selectedOptions).map(o => o.value); setNeighborhood(opts.join(',')) }}
                  >
                    {neighborhoods.length > 0
                      ? neighborhoods.map(n => (
                          <option key={n.name} value={n.name}>{n.name} ({n.count})</option>
                        ))
                      : <option value="" disabled>No data available</option>
                    }
                  </select>
                </div>
                <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => {
                  setMaxPrice(''); setMinBedrooms(''); setMinScore(''); setMinParking('');
                  setNeighborhood(''); setPropertyType(''); setListingType('both');
                  setIsFurnished(false); setAcceptsPets(false);
                  setQ(''); setQDraft('');
                }}>✕ Clear All</button>
              </div>
            )}
          </div>

        {/* Error state */}
        {loadError && !loading && (
          <div className="empty-state" style={{ borderColor: 'var(--accent-rose)', background: 'rgba(244,63,94,0.08)' }}>
            <div className="empty-state-icon">⚠️</div>
            <h3 style={{ color: 'var(--accent-rose)' }}>Failed to load properties</h3>
            <p style={{ maxWidth: 600, margin: '0 auto' }}>{loadError}</p>
            <button className="btn btn-primary" onClick={() => load(page)} style={{ marginTop: 16 }}>🔄 Retry</button>
          </div>
        )}

        {/* Map View */}
        {!loadError && viewType === 'map' && (
          mapLoading ? (
            <div className="loading-grid">
              {Array.from({ length: 12 }).map((_, i) => <div key={i} className="skeleton" />)}
            </div>
          ) : (
            <MapView
              properties={mapProperties.length > 0 ? mapProperties : (data?.properties || [])}
              onSelectProperty={(id) => setSelectedId(id)}
              onBboxChange={handleBboxChange}
            />
          )
        )}

        {/* Grid */}
        {!loadError && viewType === 'grid' && (
          loading ? (
            <div className="loading-grid">
              {Array.from({ length: 12 }).map((_, i) => <div key={i} className="skeleton" />)}
            </div>
          ) : properties.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">{viewMode === 'favourites' ? '☆' : '🏚️'}</div>
              <h3>{viewMode === 'favourites' ? 'No favourites yet' : 'No properties found'}</h3>
              <p>{viewMode === 'favourites' ? 'Star a property to add it to your favourites.' : (
                Object.values(currentFilters).some(v => v && v !== 'combined_score' && v !== 'desc' && v !== 'both')
                  ? 'Try adjusting your filters to see more results.'
                  : 'Go to Scraper Control and trigger your first ingestion job to start building the database.'
              )}</p>
              {viewMode !== 'favourites' && (
                Object.values(currentFilters).some(v => v && v !== 'combined_score' && v !== 'desc' && v !== 'both')
                  ? <button className="btn btn-ghost" onClick={() => {
                      setMaxPrice(''); setMinBedrooms(''); setMinScore(''); setMinParking('');
                      setNeighborhood(''); setPropertyType(''); setListingType('both');
                      setIsFurnished(false); setAcceptsPets(false);
                    }}>✕ Clear Filters</button>
                  : <a href="/scraper" className="btn btn-primary">Go to Scraper Control →</a>
              )}
            </div>
          ) : (
            <>
              <div className="property-grid">
                {properties.map(p => (
                  <PropertyCard
                    key={p.id}
                    property={p}
                    onClick={() => setSelectedId(p.id)}
                    isWatched={watchedIds.has(p.id)}
                    onToggleWatchlist={toggleWatchlist}
                    isFavourited={favouriteIds.has(p.id)}
                    onToggleFavourite={toggleFavourite}
                    isCompareSelected={isCompareSelected(p.id)}
                    onToggleCompare={handleToggleCompare}
                  />
                ))}
              </div>

              {viewMode === 'all' && pages > 1 && (
                <div className="pagination">
                  <button className="page-btn" onClick={() => setPage(1)} disabled={page === 1}>«</button>
                  <button className="page-btn" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
                  {Array.from({ length: Math.min(7, pages) }, (_, i) => {
                    const n = Math.max(1, Math.min(pages - 6, page - 3)) + i
                    return <button key={n} className={`page-btn ${n === page ? 'active' : ''}`} onClick={() => setPage(n)}>{n}</button>
                  })}
                  <button className="page-btn" onClick={() => setPage(p => Math.min(pages, p + 1))} disabled={page === pages}>›</button>
                  <button className="page-btn" onClick={() => setPage(pages)} disabled={page === pages}>»</button>
                </div>
              )}
            </>
          )
        )}
      </div>

      {/* Save search dialog */}
      {showSaveDialog && (
        <div className="modal-overlay" onClick={() => setShowSaveDialog(false)}>
          <div className="modal" style={{ maxWidth: 400, padding: 24 }} onClick={e => e.stopPropagation()}>
            <h3 style={{ marginBottom: 16, fontSize: 18 }}>Save Current Filters</h3>
            <input
              className="form-input"
              placeholder="Search name..."
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSaveSearch()}
              autoFocus
              style={{ width: '100%', marginBottom: 16 }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowSaveDialog(false)}>Cancel</button>
              <button className="btn btn-primary btn-sm" onClick={handleSaveSearch} disabled={!saveName.trim()}>Save</button>
            </div>
          </div>
        </div>
      )}

      {selectedId && <PropertyModal id={selectedId} onClose={() => setSelectedId(null)} />}

      {compareOpen && (
        <CompareView
          ids={compareIds}
          onClose={closeCompare}
          onClearSelection={clearCompare}
        />
      )}

      {compareIds.length > 0 && !compareOpen && (
        <div className="compare-bar" data-testid="compare-bar" role="region" aria-label="Compare selection">
          <span className="compare-bar-count" data-testid="compare-count">
            {compareIds.length} selected
          </span>
          <div className="compare-bar-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="compare-clear"
              onClick={clearCompare}
            >
              Clear
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid="compare-open"
              disabled={!canCompare}
              onClick={openCompare}
            >
              Compare
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function scoreColor(v) {
  if (v == null) return 'var(--text-muted)'
  if (v >= 0.7) return 'var(--score-high)'
  if (v >= 0.4) return 'var(--score-mid)'
  return 'var(--score-low)'
}

function displayScore(v) {
  const n = parseFloat(v);
  return isNaN(n) ? '—' : (n * 100).toFixed(0);
}

function groupListings(listings) {
  if (!listings || listings.length === 0) return {}
  const groups = {}
  for (const l of listings) {
    const key = l.listing_type || 'sale'
    if (!groups[key]) groups[key] = []
    groups[key].push(l)
  }
  // Sort each group by price (lowest first)
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => (a.price || Infinity) - (b.price || Infinity))
  }
  return groups
}

function getPlatformCount(listings) {
  if (!listings || listings.length === 0) return 0
  return new Set(listings.map(l => l.platform)).size
}

function formatListingType(type) {
  if (type === 'rent') return 'ALUGUEL'
  return 'VENDA'
}

function listingTypeColor(type) {
  if (type === 'rent') return { bg: 'rgba(99,102,241,0.2)', color: '#818cf8' }
  return { bg: 'rgba(16,185,129,0.2)', color: '#34d399' }
}

function PropertyCard({
  property: p,
  onClick,
  isWatched,
  onToggleWatchlist,
  isFavourited,
  onToggleFavourite,
  isCompareSelected,
  onToggleCompare,
}) {
  const img = (p.image_urls || [])[0]
  const listings = p.listings || []
  const groups = groupListings(listings)
  const groupKeys = Object.keys(groups)
  const platformCount = getPlatformCount(listings)
  const hasListings = listings.length > 0

  return (
    <div
      className={`property-card${isCompareSelected ? ' property-card--selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      data-property-id={p.id}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
    >
      <label
        className="property-compare-select"
        title="Select for comparison"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
      >
        <input
          type="checkbox"
          checked={!!isCompareSelected}
          onChange={(e) => onToggleCompare(e, p.id)}
          aria-label={isCompareSelected ? 'Remove from comparison' : 'Select for comparison'}
          data-testid={`compare-select-${p.id}`}
        />
      </label>
      {img
        ? <img className="property-image" src={img} alt={p.title || 'property'} loading="lazy" onError={e => { e.target.style.display='none'; e.target.nextSibling.style.display='flex' }} />
        : null
      }
      <div className="property-image-placeholder" style={{ display: img ? 'none' : 'flex' }}>🏠</div>

      <div className="property-body">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            {hasListings ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {groupKeys.map(type => {
                  const best = groups[type][0]
                  const colors = listingTypeColor(type)
                  return (
                    <div key={type} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                      <span className="property-price" style={{ fontSize: groupKeys.length > 1 ? 16 : 20 }}>
                        R$ {best.price ? best.price.toLocaleString('pt-BR') : '—'}
                      </span>
                      <span style={{ padding: '1px 5px', fontSize: 9, background: colors.bg, color: colors.color, borderRadius: 3, fontWeight: 700 }}>
                        {formatListingType(type)}
                      </span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        {best.platform}
                      </span>
                      {groups[type].length > 1 && (
                        <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                          ({groups[type].length})
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="property-price">
                R$ {p.price ? p.price.toLocaleString('pt-BR') : '—'}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            {platformCount > 1 && (
              <span style={{ padding: '2px 6px', fontSize: 9, background: 'rgba(251,191,36,0.15)', color: '#fbbf24', borderRadius: 4, fontWeight: 700 }}>
                {platformCount} plataformas
              </span>
            )}
            <div
              className={`icon-btn ${isFavourited ? 'active' : ''}`}
              title="Add to Favourites"
              aria-label={isFavourited ? "Remove from Favourites" : "Add to Favourites"}
              role="button"
              tabIndex={0}
              onClick={(e) => onToggleFavourite(e, p.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onToggleFavourite(e, p.id);
                }
              }}
            >
              {isFavourited ? '★' : '☆'}
            </div>
            <div
              className={`icon-btn ${isWatched ? 'active' : ''}`}
              title="Watch for price drops"
              aria-label={isWatched ? "Remove from Watchlist" : "Add to Watchlist"}
              role="button"
              tabIndex={0}
              onClick={(e) => onToggleWatchlist(e, p.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onToggleWatchlist(e, p.id);
                }
              }}
            >
              {isWatched ? '🔔' : '☆'}
            </div>
          </div>
        </div>
        <div className="property-title">{p.title || p.address || 'Sem título'}</div>
        {p.deal_summary && (
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--accent, #6366f1)', marginTop: 6, lineHeight: 1.4 }}>
            💡 {p.deal_summary}
          </div>
        )}

        <div className="property-attrs">
          {p.bedrooms != null  && <span className="property-attr">🛏 {p.bedrooms}</span>}
          {p.bathrooms != null && <span className="property-attr">🚿 {p.bathrooms}</span>}
          {p.parking != null   && <span className="property-attr">🚗 {p.parking}</span>}
          {p.area_m2 != null   && <span className="property-attr">📐 {p.area_m2}m²</span>}
          {p.price_per_m2      && <span className="property-attr" style={{ color: 'var(--text-muted)' }}>R${Math.round(p.price_per_m2)}/m²</span>}
          {p.neighborhood_name && <span className="property-attr" style={{ color: 'var(--text-muted)' }}>📍 {p.neighborhood_name}</span>}
        </div>

        {p.description && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
            {p.description}
          </div>
        )}

        <div className="property-scores" style={{ marginTop: 12 }}>
          {p.combined_score != null && (
            <div className="score-badge combined">
              <span className="score-badge-label">Score</span>
              <span className="score-badge-val" style={{ color: scoreColor(p.combined_score) }}>
                {displayScore(p.combined_score)}
              </span>
            </div>
          )}
          <div className="score-badge stat">
            <span className="score-badge-label">Stat</span>
            <span className="score-badge-val">{p.stat_score != null ? displayScore(p.stat_score) : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 'normal' }}>⌛ Calc</span>}</span>
          </div>
          <div className="score-badge ai">
            <span className="score-badge-label">AI</span>
            <span className="score-badge-val">{p.ai_score != null ? displayScore(p.ai_score) : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 'normal' }}>⌛ Calc</span>}</span>
          </div>
        </div>

        {((p.ai_green_flags || []).length > 0 || (p.ai_red_flags || []).length > 0) && (
          <div className="flags" style={{ marginTop: 10 }}>
            {(p.ai_green_flags || []).slice(0, 2).map(f => <span key={f} className="flag green">✔ {f}</span>)}
            {(p.ai_red_flags || []).slice(0, 1).map(f => <span key={f} className="flag red">✖ {f}</span>)}
          </div>
        )}
      </div>
    </div>
  )
}
