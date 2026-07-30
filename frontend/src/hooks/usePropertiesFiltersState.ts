import { useCallback, useState } from 'react'
import { fromSavedSearchWire } from '../savedSearchFilters.js'
import type { PropertyFilterOptions, ListingType, PriceType, SortDir } from '../api.js'

export const DEFAULT_FILTERS = {
  sortBy: 'combined_score',
  sortDir: 'desc',
  listingType: 'both',
  propertyType: '',
  platform: '',
  maxPrice: '',
  priceType: 'rent',
  minBedrooms: '',
  minParking: '',
  minScore: '',
  neighborhood: '',
  city: '',
  isFurnished: false,
  acceptsPets: false,
  q: '',
}

/**
 * Owns every filter/sort/search input on the Properties page (the "toolbar +
 * advanced filters" state slice), plus the derived query-filter shape and
 * saved-search apply/clear helpers. Pure state + derivations — fetching
 * (`load()`, the refetch effects) stays owned by Properties.tsx since it
 * also depends on `page`/`viewMode`, which live outside this hook.
 *
 * Extracted verbatim from the pre-split Properties.jsx (BIN-141) — no
 * behavior change, including the two distinct "clear filters" variants
 * (one resets the free-text search, one doesn't — see clearAllFilters vs
 * clearFiltersKeepSearch below).
 */
export function usePropertiesFiltersState() {
  const [sortBy, setSortBy] = useState(DEFAULT_FILTERS.sortBy)
  const [sortDir, setSortDir] = useState(DEFAULT_FILTERS.sortDir)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [listingType, setListingType] = useState(DEFAULT_FILTERS.listingType)
  const [propertyType, setPropertyType] = useState(DEFAULT_FILTERS.propertyType)
  const [platform, setPlatform] = useState(DEFAULT_FILTERS.platform)
  const [maxPrice, setMaxPrice] = useState(DEFAULT_FILTERS.maxPrice)
  const [priceType, setPriceType] = useState(DEFAULT_FILTERS.priceType)
  const [minBedrooms, setMinBedrooms] = useState(DEFAULT_FILTERS.minBedrooms)
  const [minParking, setMinParking] = useState(DEFAULT_FILTERS.minParking)
  const [minScore, setMinScore] = useState(DEFAULT_FILTERS.minScore)
  const [neighborhood, setNeighborhood] = useState(DEFAULT_FILTERS.neighborhood)
  const [city, setCity] = useState(DEFAULT_FILTERS.city)
  const [isFurnished, setIsFurnished] = useState(DEFAULT_FILTERS.isFurnished)
  const [acceptsPets, setAcceptsPets] = useState(DEFAULT_FILTERS.acceptsPets)
  const [q, setQ] = useState(DEFAULT_FILTERS.q)
  const [qDraft, setQDraft] = useState(DEFAULT_FILTERS.q)

  const currentFilters = {
    sortBy, sortDir, listingType, propertyType, platform, maxPrice, priceType,
    minBedrooms, minParking, minScore, neighborhood, city, isFurnished, acceptsPets, q,
  }

  const buildListQueryFilters = useCallback((): PropertyFilterOptions => {
    const isPriceDesc = sortBy === 'price_desc'
    const actualSortBy = isPriceDesc ? 'price' : sortBy
    const actualSortDir = sortBy === 'price' ? 'asc' : isPriceDesc ? 'desc' : sortDir
    return {
      sortBy: actualSortBy,
      sortDir: actualSortDir as SortDir,
      maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
      priceType: maxPrice ? (priceType as PriceType) : undefined,
      minBedrooms: minBedrooms ? parseInt(minBedrooms) : undefined,
      minScore: minScore ? parseFloat(minScore) : undefined,
      minParking: minParking ? parseInt(minParking) : undefined,
      neighborhoodName: neighborhood || undefined,
      cityName: city || undefined,
      listingType: listingType as ListingType,
      propertyType: propertyType || undefined,
      platform: platform || undefined,
      isFurnished: isFurnished ? true : undefined,
      acceptsPets: acceptsPets ? true : undefined,
      q: q || undefined,
    }
  }, [sortBy, sortDir, maxPrice, priceType, minBedrooms, minScore, minParking, neighborhood, city, listingType, propertyType, platform, isFurnished, acceptsPets, q])

  const applyFilters = useCallback((rawFilters: Record<string, unknown>) => {
    const filters = fromSavedSearchWire(rawFilters)
    if (filters.sortBy !== undefined) setSortBy(filters.sortBy as string)
    if (filters.sortDir !== undefined) setSortDir(filters.sortDir as string)
    if (filters.listingType !== undefined) setListingType(filters.listingType as string)
    if (filters.propertyType !== undefined) setPropertyType(filters.propertyType as string)
    if (filters.platform !== undefined) setPlatform(filters.platform as string)
    if (filters.maxPrice !== undefined) setMaxPrice(String(filters.maxPrice))
    if (filters.priceType !== undefined) setPriceType(filters.priceType as string)
    if (filters.minBedrooms !== undefined) setMinBedrooms(String(filters.minBedrooms))
    if (filters.minParking !== undefined) setMinParking(String(filters.minParking))
    if (filters.minScore !== undefined) setMinScore(String(filters.minScore))
    if (filters.neighborhood !== undefined) setNeighborhood(filters.neighborhood as string)
    if (filters.city !== undefined) setCity(filters.city as string)
    if (filters.isFurnished !== undefined) setIsFurnished(Boolean(filters.isFurnished))
    if (filters.acceptsPets !== undefined) setAcceptsPets(Boolean(filters.acceptsPets))
    if (filters.q !== undefined) {
      setQ(filters.q as string)
      setQDraft(filters.q as string)
    }
  }, [])

  // "Clear All" button inside the advanced-filters panel — also resets the
  // free-text search (q/qDraft).
  const clearAllFilters = useCallback(() => {
    setMaxPrice(''); setPriceType(DEFAULT_FILTERS.priceType); setMinBedrooms(''); setMinScore(''); setMinParking('')
    setNeighborhood(''); setCity(''); setPropertyType(''); setListingType('both')
    setPlatform('')
    setIsFurnished(false); setAcceptsPets(false)
    setQ(''); setQDraft('')
  }, [])

  // "Clear filters" button in the empty-state — intentionally leaves the
  // free-text search (q/qDraft) untouched, matching pre-split behavior.
  const clearFiltersKeepSearch = useCallback(() => {
    setMaxPrice(''); setPriceType(DEFAULT_FILTERS.priceType); setMinBedrooms(''); setMinScore(''); setMinParking('')
    setNeighborhood(''); setCity(''); setPropertyType(''); setListingType('both')
    setPlatform('')
    setIsFurnished(false); setAcceptsPets(false)
  }, [])

  const hasActiveFilters = Object.entries(currentFilters).some(([key, value]) => {
    if (key === 'priceType') return Boolean(maxPrice)
    const defaults = (DEFAULT_FILTERS as Record<string, string | boolean>)[key]
    if (defaults !== undefined) return value !== defaults && Boolean(value)
    return Boolean(value)
  })

  return {
    sortBy, setSortBy,
    sortDir, setSortDir,
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
  }
}
