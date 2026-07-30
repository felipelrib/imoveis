import type { SyntheticEvent } from 'react'
import PropertyCard from './PropertyCard.jsx'
import { linkIdForProperty } from '../../routes/propertyPaths.js'
import type { Property } from '../../api.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'

export interface PropertiesResultsGridProps {
  loading: boolean
  properties: Property[]
  viewMode: string
  hasActiveFilters: boolean
  onClearFilters: () => void
  listingType: string
  watchedIds: Set<string>
  onToggleWatchlist: (e: SyntheticEvent, id: string) => void
  favouriteIds: Set<string>
  onToggleFavourite: (e: SyntheticEvent, id: string) => void
  compareMode: boolean
  isCompareSelected: (id: string | number | null | undefined) => boolean
  onToggleCompare: (e: SyntheticEvent, property: Property) => void
  onOpenProperty: (property: Property) => void
  t: TFunction
  locale: string
}

/**
 * Loading skeleton / empty state / property grid for the Properties page.
 * Pure rendering, moved verbatim from the pre-split Properties.jsx
 * (BIN-141) — the surrounding `viewType === 'grid'` gate and the pagination
 * sibling below the grid stay owned by Properties.tsx.
 */
export default function PropertiesResultsGrid({
  loading,
  properties,
  viewMode,
  hasActiveFilters,
  onClearFilters,
  listingType,
  watchedIds,
  onToggleWatchlist,
  favouriteIds,
  onToggleFavourite,
  compareMode,
  isCompareSelected,
  onToggleCompare,
  onOpenProperty,
  t,
  locale,
}: PropertiesResultsGridProps) {
  if (loading) {
    return (
      <div className="loading-grid">
        {Array.from({ length: 12 }).map((_, i) => <div key={i} className="skeleton" />)}
      </div>
    )
  }

  if (properties.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">{viewMode === 'favourites' ? '☆' : '🏚️'}</div>
        <h3>{viewMode === 'favourites' ? t('properties.emptyFavouritesTitle') : t('properties.emptyPropertiesTitle')}</h3>
        <p>{viewMode === 'favourites' ? t('properties.emptyFavouritesBody') : (
          hasActiveFilters
            ? t('properties.emptyAdjustFilters')
            : t('properties.emptyFirstIngest')
        )}</p>
        {viewMode !== 'favourites' && (
          hasActiveFilters
            ? <button className="btn btn-ghost" onClick={onClearFilters}>{t('properties.clearFilters')}</button>
            : <a href="/scraper" className="btn btn-primary">{t('properties.goToScraper')} →</a>
        )}
      </div>
    )
  }

  return (
    <div className="property-grid">
      {properties.map(p => (
        <PropertyCard
          key={p.id}
          property={p}
          listingType={listingType}
          onClick={() => onOpenProperty(p)}
          isWatched={watchedIds.has(p.id)}
          onToggleWatchlist={onToggleWatchlist}
          isFavourited={favouriteIds.has(p.id)}
          onToggleFavourite={onToggleFavourite}
          compareMode={compareMode}
          isCompareSelected={isCompareSelected(linkIdForProperty(p))}
          onToggleCompare={onToggleCompare}
          t={t}
          locale={locale}
        />
      ))}
    </div>
  )
}
