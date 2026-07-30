import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate, useParams, useLocation, Outlet } from 'react-router-dom'
import { fetchProperties, exportProperties, fetchWatchlist, addToWatchlist, removeFromWatchlist, fetchSavedSearches, saveSearch, deleteSavedSearch, fetchFavourites, addFavourite, removeFavourite, fetchNeighborhoods, fetchCities } from '../api.js'
import PropertyModal from '../components/PropertyModal.jsx'
import CompareView from '../components/CompareView.jsx'
import { useToast } from '../components/ToastProvider.jsx'
import MapView from '../components/MapView.jsx'
import PropertiesFilterBar from '../components/properties/PropertiesFilterBar.jsx'
import PropertiesResultsGrid from '../components/properties/PropertiesResultsGrid.jsx'
import PropertiesPagination from '../components/properties/PropertiesPagination.jsx'
import { useCompareSelection } from '../hooks/useCompareSelection.js'
import { usePropertiesFiltersState } from '../hooks/usePropertiesFiltersState.js'
import { usePropertiesPagination } from '../hooks/usePropertiesPagination.js'
import { useLocale } from '../i18n/LocaleContext.jsx'
import { formatNumber } from '../i18n/format.js'
import { toSavedSearchWire } from '../savedSearchFilters.js'
import {
  PROPERTIES_PATH,
  FAVOURITES_PATH,
  propertyPath,
  comparePath,
  parseCompareIds,
  parsePropertyId,
  linkIdForProperty,
} from '../routes/propertyPaths.js'

export default function Properties() {
  const navigate = useNavigate()
  const location = useLocation()
  const { propertyId: propertyIdParam, compareIds: compareIdsParam } = useParams()
  const routePropertyId = parsePropertyId(propertyIdParam)
  const routeCompareIds = parseCompareIds(compareIdsParam)
  const isFavouritesRoute = location.pathname === FAVOURITES_PATH
    || location.pathname.startsWith(`${FAVOURITES_PATH}/`)
  const isCompareRoute = location.pathname.startsWith('/compare/')

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const { page, setPage } = usePropertiesPagination()
  const {
    sortBy, setSortBy,
    sortDir,
    showAdvanced, setShowAdvanced,
    listingType, setListingType,
    propertyType, setPropertyType,
    platform, setPlatform,
    maxPrice, setMaxPrice,
    priceType, setPriceType,
    minBedrooms, setMinBedrooms,
    minParking, setMinParking,
    minScore, setMinScore,
    neighborhood, setNeighborhood,
    city, setCity,
    isFurnished, setIsFurnished,
    acceptsPets, setAcceptsPets,
    q, setQ,
    qDraft, setQDraft,
    currentFilters,
    hasActiveFilters,
    buildListQueryFilters,
    applyFilters,
    clearAllFilters,
    clearFiltersKeepSearch,
  } = usePropertiesFiltersState()
  const [loadError, setLoadError] = useState(null)
  const [watchedIds, setWatchedIds] = useState(new Set())
  const [favouriteIds, setFavouriteIds] = useState(new Set())
  const showToast = useToast()
  const { t, locale } = useLocale()

  const onCompareLimitReached = useCallback(() => {
    showToast(t('properties.toastCompareLimit'), { type: 'warning' })
  }, [showToast, t])

  const {
    selectedIds: compareIds,
    toggle: toggleCompare,
    clear: clearCompare,
    replace: replaceCompare,
    isSelected: isCompareSelected,
    canCompare,
  } = useCompareSelection({
    onLimitReached: onCompareLimitReached,
    initialIds: isCompareRoute ? routeCompareIds : (location.state?.compareIds || []),
  })

  const listReturnPath = isFavouritesRoute ? FAVOURITES_PATH : PROPERTIES_PATH
  const returnToRef = useRef(listReturnPath)

  const openProperty = useCallback((propertyOrId) => {
    const linkId = typeof propertyOrId === 'object'
      ? linkIdForProperty(propertyOrId)
      : (parsePropertyId(String(propertyOrId)) || String(propertyOrId))
    if (!linkId) return
    returnToRef.current = isFavouritesRoute ? FAVOURITES_PATH : PROPERTIES_PATH
    navigate(propertyPath(linkId), { state: { returnTo: returnToRef.current, compareIds } })
  }, [navigate, isFavouritesRoute, compareIds])

  const handleToggleCompare = useCallback((e, property) => {
    e.stopPropagation()
    const linkId = linkIdForProperty(property)
    if (!linkId) return
    toggleCompare(linkId)
  }, [toggleCompare])

  const [compareMode, setCompareMode] = useState(false)

  const closeProperty = useCallback(() => {
    const returnTo = location.state?.returnTo || returnToRef.current || PROPERTIES_PATH
    navigate(returnTo, { state: { compareIds } })
  }, [navigate, location.state, compareIds])

  const toggleCompareMode = useCallback(() => {
    setCompareMode((prev) => {
      if (prev) {
        clearCompare()
        return false
      }
      return true
    })
  }, [clearCompare])

  const openCompare = useCallback(() => {
    if (!canCompare) return
    navigate(comparePath(compareIds), { state: { returnTo: listReturnPath } })
  }, [canCompare, navigate, compareIds, listReturnPath])

  const closeCompare = useCallback(() => {
    const returnTo = location.state?.returnTo || PROPERTIES_PATH
    navigate(returnTo, { state: { compareIds } })
  }, [navigate, location.state, compareIds])

  const clearCompareAndExitMode = useCallback(() => {
    clearCompare()
    setCompareMode(false)
    const returnTo = location.state?.returnTo || PROPERTIES_PATH
    navigate(returnTo)
  }, [clearCompare, navigate, location.state])

  // Saved searches state
  const [savedSearches, setSavedSearches] = useState([])
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [saveName, setSaveName] = useState('')

  // View mode derived from URL: 'all' | 'favourites'
  const viewMode = isFavouritesRoute ? 'favourites' : 'all'
  const [favouritesData, setFavouritesData] = useState({ items: [], total: 0 })

  // Dynamic neighborhoods / cities from backend
  const [neighborhoods, setNeighborhoods] = useState([])
  const [neighborhoodsLoading, setNeighborhoodsLoading] = useState(false)
  const [cities, setCities] = useState([])
  const [citiesLoading, setCitiesLoading] = useState(false)

  // View mode: 'grid' | 'map'
  const [viewType, setViewType] = useState('grid')
  const [mapProperties, setMapProperties] = useState([])
  const [mapLoading, setMapLoading] = useState(false)
  const [exporting, setExporting] = useState(false)

  const selectedId = routePropertyId
  const compareOpen = isCompareRoute && routeCompareIds.length >= 2

  // Hydrate compare selection from URL / navigation state
  useEffect(() => {
    if (isCompareRoute) {
      if (routeCompareIds.length >= 2) {
        replaceCompare(routeCompareIds)
        // Route-driven mode sync; a full effect->render refactor is tracked under BIN-141
        // (Properties.jsx split), not this lint-tooling ticket.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setCompareMode(true)
      } else {
        navigate(PROPERTIES_PATH, { replace: true })
      }
      return
    }
    if (location.state?.compareIds?.length) {
      replaceCompare(location.state.compareIds)
    }
  }, [isCompareRoute, compareIdsParam]) // eslint-disable-line react-hooks/exhaustive-deps

  // Invalid /properties/:id → list
  useEffect(() => {
    if (propertyIdParam && !routePropertyId) {
      navigate(PROPERTIES_PATH, { replace: true })
    }
  }, [propertyIdParam, routePropertyId, navigate])

  const handleExport = useCallback(async (format) => {
    if (exporting) return
    setExporting(true)
    try {
      await exportProperties({ format, ...buildListQueryFilters() })
    } catch (err) {
      console.error('Export failed:', err)
      showToast(t('properties.toastExportFailed', { message: err.message || t('common.unknownError') }), { type: 'error' })
    } finally {
      setExporting(false)
    }
  }, [exporting, buildListQueryFilters, showToast, t])

  const handleBboxChange = useCallback(async (bboxStr) => {
    setMapLoading(true)
    try {
      const res = await fetchProperties({
        page: 1,
        pageSize: 200,
        sortBy: sortBy === 'price_desc' ? 'price' : sortBy,
        sortDir: sortBy === 'price_desc' ? 'desc' : sortDir,
        maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
        priceType: maxPrice ? priceType : undefined,
        minBedrooms: minBedrooms ? parseInt(minBedrooms) : undefined,
        minScore: minScore ? parseFloat(minScore) : undefined,
        minParking: minParking ? parseInt(minParking) : undefined,
        neighborhoodName: neighborhood || undefined,
        cityName: city || undefined,
        listingType: listingType,
        propertyType: propertyType || undefined,
        platform: platform || undefined,
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
  }, [sortBy, sortDir, maxPrice, priceType, minBedrooms, minScore, minParking, neighborhood, city, listingType, propertyType, platform, isFurnished, acceptsPets, q])

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
        setLoadError(e.message || t('properties.failedToLoadFavourites'))
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
        priceType: maxPrice ? priceType : undefined,
        minBedrooms: minBedrooms ? parseInt(minBedrooms) : undefined,
        minScore: minScore ? parseFloat(minScore) : undefined,
        minParking: minParking ? parseInt(minParking) : undefined,
        neighborhoodName: neighborhood || undefined,
        cityName: city || undefined,
        listingType: listingType,
        propertyType: propertyType || undefined,
        platform: platform || undefined,
        isFurnished: isFurnished ? true : undefined,
        acceptsPets: acceptsPets ? true : undefined,
        q: q || undefined,
      })
      setData(res)
    } catch (e) {
      console.error(e)
      setLoadError(e.message || t('properties.failedToLoad'))
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
    // Fetch dynamic neighborhoods / cities
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount-only fetch-loading flag
    setNeighborhoodsLoading(true)
    fetchNeighborhoods()
      .then(setNeighborhoods)
      .catch(() => {})
      .finally(() => setNeighborhoodsLoading(false))
    setCitiesLoading(true)
    fetchCities()
      .then(setCities)
      .catch(() => {})
      .finally(() => setCitiesLoading(false))
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
      showToast(t('properties.toastWatchlistFailed'), { type: 'error' })
    }
  }, [watchedIds, showToast, t])

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
      showToast(t('properties.toastFavouritesFailed'), { type: 'error' })
    }
  }, [favouriteIds, showToast, t])

  // Reload on filter changes; also enter favourites view via URL/sidebar
  //
  // `load` is a plain (unmemoized) closure over ~15 filter fields, not a stable callback —
  // adding it to the deps array below would fire this effect on every render (its identity
  // changes each render) instead of only on real filter changes. Memoizing `load` (and
  // untangling it from the page-change effect just below) is exactly the kind of effect
  // restructuring tracked separately under BIN-141 (Properties.jsx split), not this
  // lint-tooling ticket — narrowly suppressed here instead of a risky untested refactor.
  useEffect(() => {
    // `setPage` here comes from usePropertiesPagination(), not a literal
    // useState() in this file, so the lint rule below can no longer trace it
    // back to a recognized state setter — no disable comment needed for
    // this line post-BIN-141 (it doesn't flag it). `load(1)` still does,
    // since it synchronously calls setLoading/setData underneath.
    setPage(1)
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see BIN-141 note above
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see BIN-141 note above
  }, [sortBy, listingType, propertyType, platform, maxPrice, priceType, minBedrooms, minParking, minScore, isFurnished, acceptsPets, neighborhood, city, viewMode, q])

  // Always load on page change — including returning to page 1 via pagination (BIN-57).
  // Filter effect above owns the initial/filter-driven page-1 fetch; this also re-fetches
  // page 1 when setPage(1) runs after visiting page 2+, which is intentional and correct.
  // Same `load`-is-unmemoized rationale as above (BIN-141) for the suppressions below.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see BIN-141 note above
    load(page)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see BIN-141 note above
  }, [page])

  const handleViewModeChange = (mode) => {
    setPage(1)
    if (mode === 'favourites') {
      navigate(FAVOURITES_PATH, { state: { compareIds } })
    } else {
      navigate(PROPERTIES_PATH, { state: { compareIds } })
    }
  }

  const handleSaveSearch = async () => {
    if (!saveName.trim()) return
    try {
      await saveSearch(saveName.trim(), toSavedSearchWire(currentFilters))
      const updated = await fetchSavedSearches()
      setSavedSearches(updated.items || [])
      setSaveName('')
      setShowSaveDialog(false)
      showToast(t('properties.toastSearchSaved'), { type: 'success' })
    } catch (err) {
      console.error('Save search failed:', err)
      showToast(t('properties.toastSaveSearchFailed'), { type: 'error' })
    }
  }

  const handleDeleteSavedSearch = async (e, id) => {
    e.stopPropagation()
    try {
      await deleteSavedSearch(id)
      setSavedSearches(prev => prev.filter(s => s.id !== id))
      showToast(t('properties.toastSavedSearchDeleted'), { type: 'info' })
    } catch (err) {
      console.error('Delete saved search failed:', err)
      showToast(t('properties.toastDeleteSearchFailed'), { type: 'error' })
    }
  }

  const handleApplySavedSearch = (filters) => {
    navigate(PROPERTIES_PATH, { state: { compareIds } })
    applyFilters(filters)
  }

  const totalResults = viewMode === 'favourites' ? favouritesData.total : (data?.total || 0)
  // Favourites API uses property_id (+ public_id); cards need UUID on `id` for watchlist/favourites.
  const properties = viewMode === 'favourites'
    ? (favouritesData.items || []).map((f) => ({
        ...f,
        id: f.property_id || f.id,
        public_id: f.public_id,
      }))
    : (data?.properties || [])
  const pages = viewMode === 'favourites' ? Math.ceil(totalResults / 24) : (data?.pages || 1)

  return (
    <div style={{ display: 'flex', gap: 20, minHeight: 'calc(100vh - 60px)' }}>
      <Outlet />
      {/* Sidebar */}
      <aside className="saved-searches-sidebar">
        <div className="sidebar-section">
          <div className="sidebar-header">{t('properties.savedSearches')}</div>
          {savedSearches.length === 0 ? (
            <div className="sidebar-empty">{t('properties.noSavedSearches')}</div>
          ) : (
            <div className="sidebar-list">
              {savedSearches.map(ss => (
                <div
                  key={ss.id}
                  className="sidebar-item"
                  onClick={() => handleApplySavedSearch(ss.filters)}
                >
                  <span className="sidebar-item-name">{ss.name}</span>
                  <button className="sidebar-item-delete" onClick={(e) => handleDeleteSavedSearch(e, ss.id)} title={t('common.delete')}>✕</button>
                </div>
              ))}
            </div>
          )}
          <button className="btn btn-ghost btn-sm" style={{ width: '100%', marginTop: 8 }} onClick={() => setShowSaveDialog(true)}>
            {t('properties.saveCurrentFilters')}
          </button>
        </div>

        <div className="sidebar-section">
          <button
            className={`sidebar-link ${viewMode === 'favourites' ? 'active' : ''}`}
            onClick={() => handleViewModeChange('favourites')}
            data-testid="favourites-nav"
          >
            {t('properties.favouritesTitle')} {favouriteIds.size > 0 && <span className="badge">{favouriteIds.size}</span>}
          </button>
          {viewMode === 'favourites' && (
            <button
              className="btn btn-ghost btn-sm"
              style={{ width: '100%', marginTop: 4 }}
              onClick={() => handleViewModeChange('all')}
              data-testid="favourites-back"
            >
              ← {t('properties.backToAll')}
            </button>
          )}
        </div>
      </aside>

      {/* Main content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="page-header">
          <h1 className="page-title">{viewMode === 'favourites' ? t('properties.favouritesTitle') : t('properties.title')}</h1>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
              {viewMode === 'favourites'
                ? t('properties.countFavourited', { n: formatNumber(favouritesData.total, locale) })
                : t('properties.countProperties', { n: formatNumber(totalResults, locale) })}
            </div>
        </div>

        {/* Toolbar */}
        <PropertiesFilterBar
          t={t}
          qDraft={qDraft}
          setQDraft={setQDraft}
          q={q}
          setQ={setQ}
          sortBy={sortBy}
          setSortBy={setSortBy}
          listingType={listingType}
          setListingType={setListingType}
          setPriceType={setPriceType}
          platform={platform}
          setPlatform={setPlatform}
          propertyType={propertyType}
          setPropertyType={setPropertyType}
          exporting={exporting}
          onExport={handleExport}
          viewType={viewType}
          setViewType={setViewType}
          compareMode={compareMode}
          onToggleCompareMode={toggleCompareMode}
          showAdvanced={showAdvanced}
          setShowAdvanced={setShowAdvanced}
          maxPrice={maxPrice}
          setMaxPrice={setMaxPrice}
          priceType={priceType}
          minBedrooms={minBedrooms}
          setMinBedrooms={setMinBedrooms}
          minParking={minParking}
          setMinParking={setMinParking}
          minScore={minScore}
          setMinScore={setMinScore}
          isFurnished={isFurnished}
          setIsFurnished={setIsFurnished}
          acceptsPets={acceptsPets}
          setAcceptsPets={setAcceptsPets}
          citiesLoading={citiesLoading}
          cities={cities}
          city={city}
          setCity={setCity}
          neighborhoodsLoading={neighborhoodsLoading}
          neighborhoods={neighborhoods}
          neighborhood={neighborhood}
          setNeighborhood={setNeighborhood}
          onClearAdvanced={clearAllFilters}
        />

        {/* Error state */}
        {loadError && !loading && (
          <div className="empty-state" style={{ borderColor: 'var(--accent-rose)', background: 'rgba(244,63,94,0.08)' }}>
            <div className="empty-state-icon">⚠️</div>
            <h3 style={{ color: 'var(--accent-rose)' }}>{t('properties.failedToLoad')}</h3>
            <p style={{ maxWidth: 600, margin: '0 auto' }}>{loadError}</p>
            <button className="btn btn-primary" onClick={() => load(page)} style={{ marginTop: 16 }}>{t('properties.retry')}</button>
          </div>
        )}

        {/* Map View — keep MapView mounted while bbox refetch runs (mapLoading);
            unmounting caused compare hit targets to vanish mid-interaction. */}
        {!loadError && viewType === 'map' && (
          <div style={{ position: 'relative' }}>
            {mapLoading && (
              <div
                className="map-loading-overlay"
                data-testid="map-loading"
                aria-busy="true"
                style={{
                  position: 'absolute',
                  inset: 0,
                  zIndex: 2,
                  pointerEvents: 'none',
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'center',
                  paddingTop: 12,
                }}
              >
                <span className="skeleton" style={{ width: 120, height: 12, borderRadius: 6 }} />
              </div>
            )}
            <MapView
              properties={mapProperties.length > 0 ? mapProperties : (data?.properties || [])}
              listingType={listingType}
              compareMode={compareMode}
              selectedIds={compareIds}
              onToggleCompare={(propertyOrId) => {
                if (propertyOrId && typeof propertyOrId === 'object') {
                  const linkId = linkIdForProperty(propertyOrId)
                  if (linkId) toggleCompare(linkId)
                  return
                }
                const list = mapProperties.length > 0 ? mapProperties : (data?.properties || [])
                const key = String(propertyOrId)
                const match = list.find(
                  (p) => String(linkIdForProperty(p) || '') === key || String(p.id) === key,
                )
                const linkId = match ? linkIdForProperty(match) : key
                if (linkId) toggleCompare(linkId)
              }}
              onSelectProperty={(id) => {
                const list = mapProperties.length > 0 ? mapProperties : (data?.properties || [])
                const match = list.find((p) => String(p.id) === String(id))
                openProperty(match || id)
              }}
              onBboxChange={handleBboxChange}
            />
          </div>
        )}

        {/* Grid */}
        {!loadError && viewType === 'grid' && (
          <>
            <PropertiesResultsGrid
              loading={loading}
              properties={properties}
              viewMode={viewMode}
              hasActiveFilters={hasActiveFilters}
              onClearFilters={clearFiltersKeepSearch}
              listingType={listingType}
              watchedIds={watchedIds}
              onToggleWatchlist={toggleWatchlist}
              favouriteIds={favouriteIds}
              onToggleFavourite={toggleFavourite}
              compareMode={compareMode}
              isCompareSelected={isCompareSelected}
              onToggleCompare={handleToggleCompare}
              onOpenProperty={openProperty}
              t={t}
              locale={locale}
            />

            {!loading && properties.length > 0 && viewMode === 'all' && pages > 1 && (
              <PropertiesPagination page={page} pages={pages} onPageChange={setPage} />
            )}
          </>
        )}
      </div>

      {/* Save search dialog */}
      {showSaveDialog && (
        <div className="modal-overlay" onClick={() => setShowSaveDialog(false)}>
          <div className="modal" style={{ maxWidth: 400, padding: 24 }} onClick={e => e.stopPropagation()}>
            <h3 style={{ marginBottom: 16, fontSize: 18 }}>{t('properties.saveDialogTitle')}</h3>
            <input
              className="form-input"
              placeholder={t('properties.saveDialogPlaceholder')}
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSaveSearch()}
              autoFocus
              style={{ width: '100%', marginBottom: 16 }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowSaveDialog(false)}>{t('common.cancel')}</button>
              <button className="btn btn-primary btn-sm" onClick={handleSaveSearch} disabled={!saveName.trim()}>{t('common.save')}</button>
            </div>
          </div>
        </div>
      )}

      {selectedId && <PropertyModal id={selectedId} onClose={closeProperty} />}

      {compareOpen && (
        <CompareView
          ids={routeCompareIds.length >= 2 ? routeCompareIds : compareIds}
          onClose={closeCompare}
          onClearSelection={clearCompareAndExitMode}
        />
      )}

      {compareMode && compareIds.length > 0 && !compareOpen && (
        <div className="compare-bar" data-testid="compare-bar" role="region" aria-label={t('properties.compareBarLabel')}>
          <span className="compare-bar-count" data-testid="compare-count">
            {t('properties.compareSelected', { n: compareIds.length })}
          </span>
          <div className="compare-bar-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="compare-clear"
              onClick={clearCompare}
            >
              {t('properties.compareClear')}
            </button>
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid="compare-open"
              disabled={!canCompare}
              onClick={openCompare}
            >
              {t('properties.compareOpen')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
