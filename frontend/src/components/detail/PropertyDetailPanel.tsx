import { useEffect, useRef, useState, type ComponentType } from 'react'
import { Star, Bell, X } from 'lucide-react'
import {
  fetchProperty, checkWatchlist, addToWatchlist, removeFromWatchlist,
  checkFavourite, addFavourite, removeFavourite, fetchPriceHistory,
  type PropertyDetail, type PriceHistoryPoint,
} from '../../api.js'
import { formatPlatform } from '../../labels.js'
import { useLocale, type TFunction } from '../../i18n/LocaleContext.jsx'
import { formatCurrency } from '../../i18n/format.js'
import { decisioningPrice } from '../../utils/primaryListing.js'
import { percentileSentences } from '../../utils/percentile.js'
import type { DetailSectionProps } from './PanelSection.jsx'
import VerdictSection from './VerdictSection.jsx'
import MonthlyCostSection from './MonthlyCostSection.jsx'
import PlatformPricesSection from './PlatformPricesSection.jsx'
import PriceHistorySection from './PriceHistorySection.jsx'
import FactsSection from './FactsSection.jsx'
import NeighbourhoodSection from './NeighbourhoodSection.jsx'
import DescriptionSection from './DescriptionSection.jsx'

/**
 * The panel body, top to bottom. Each entry is an independent component that
 * returns `null` when it has nothing to say; adding a section is one file and
 * one line here.
 */
const SECTIONS: { id: string; Section: ComponentType<DetailSectionProps> }[] = [
  { id: 'verdict', Section: VerdictSection },
  { id: 'cost', Section: MonthlyCostSection },
  { id: 'price-history', Section: PriceHistorySection },
  { id: 'platforms', Section: PlatformPricesSection },
  { id: 'facts', Section: FactsSection },
  { id: 'neighbourhood', Section: NeighbourhoodSection },
  { id: 'description', Section: DescriptionSection },
]

export interface PropertyDetailPanelProps {
  /** Route id (`public_id`) of the Property to show. */
  id: string
  onClose: () => void
  /**
   * What the page behind the panel is showing. `grid` gets the partial scrim
   * over the grid; `map` gets none, so the visible part of the map stays usable.
   */
  viewType: string
  /**
   * A favourite was added or removed from inside the panel. `propertyId` is the
   * Property UUID (what the page's favourite set is keyed by).
   */
  onFavouriteChange?: (propertyId: string, favourited: boolean) => void
  /** The same for the price-drop watch (the page's bell set). */
  onWatchChange?: (propertyId: string, watched: boolean) => void
}

/**
 * Right-side detail panel (UX-DR4): one level deep, `Esc` closes, the page
 * behind it keeps its scroll, filters and map. Not a dialog: nothing outside
 * it is made inert.
 */
export default function PropertyDetailPanel({
  id, onClose, viewType, onFavouriteChange, onWatchChange,
}: PropertyDetailPanelProps) {
  const { t } = useLocale()
  const panelRef = useRef<HTMLElement>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Esc belongs to whatever handled it first (a dropdown closing itself)
      // and to the save dialog while that is open; only a free Esc closes.
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (document.querySelector('.dialog-overlay')) return
      onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Focus moves into the panel on open and back to where it was on close,
  // unless the user has meanwhile put it on a control of the page behind.
  // `preventScroll` on both: opening and closing never move the window.
  useEffect(() => {
    const previous = document.activeElement
    const panel = panelRef.current
    panel?.focus({ preventScroll: true })
    return () => {
      // Focus that was inside the panel falls to `body` when the panel leaves.
      const active = document.activeElement
      const wasInPanel = active == null || active === document.body || !!panel?.contains(active)
      if (wasInPanel && previous instanceof HTMLElement && previous.isConnected) {
        previous.focus({ preventScroll: true })
      }
    }
  }, [])

  return (
    <>
      {viewType !== 'map' && (
        <div className="detail-scrim" data-testid="detail-scrim" onClick={onClose} aria-hidden="true" />
      )}
      <aside
        ref={panelRef}
        className="detail-panel meia"
        data-testid="detail-panel"
        aria-label={t('detail.panelLabel')}
        tabIndex={-1}
      >
        {/* Keyed by id: selecting another point on the map swaps the content
            (fresh state) while the panel itself stays mounted. */}
        <PanelContent
          key={id}
          id={id}
          onClose={onClose}
          onFavouriteChange={onFavouriteChange}
          onWatchChange={onWatchChange}
        />
      </aside>
    </>
  )
}

type LoadStatus = 'loading' | 'ready' | 'error'

interface PanelContentProps {
  id: string
  onClose: () => void
  onFavouriteChange?: (propertyId: string, favourited: boolean) => void
  onWatchChange?: (propertyId: string, watched: boolean) => void
}

function PanelContent({ id, onClose, onFavouriteChange, onWatchChange }: PanelContentProps) {
  const { t, locale } = useLocale()
  const [property, setProperty] = useState<PropertyDetail | null>(null)
  const [status, setStatus] = useState<LoadStatus>('loading')
  const [isWatched, setIsWatched] = useState(false)
  const [isFavourited, setIsFavourited] = useState(false)
  const [priceHistory, setPriceHistory] = useState<PriceHistoryPoint[]>([])
  const [dropPct, setDropPct] = useState('5')

  useEffect(() => {
    let cancelled = false
    fetchProperty(id)
      .then((data) => {
        if (cancelled) return
        setProperty(data)
        setStatus('ready')
      })
      .catch((err) => {
        console.error(err)
        if (!cancelled) setStatus('error')
      })
    checkWatchlist(id)
      .then((data) => { if (!cancelled) setIsWatched(data.watched) })
      .catch(() => {})
    checkFavourite(id)
      .then((data) => { if (!cancelled) setIsFavourited(data.favourited) })
      .catch(() => {})
    fetchPriceHistory(id)
      .then((data) => { if (!cancelled) setPriceHistory(Array.isArray(data) ? data : []) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [id])

  // Prefer the resolved UUID from the detail payload: the route `id` may be
  // the public_id (BIN-82).
  const mutationId = property?.id || id

  const toggleWatchlist = async () => {
    try {
      if (isWatched) {
        await removeFromWatchlist(mutationId)
        setIsWatched(false)
        onWatchChange?.(mutationId, false)
      } else {
        await addToWatchlist(mutationId, Number(dropPct) || 5)
        setIsWatched(true)
        onWatchChange?.(mutationId, true)
      }
    } catch (err) {
      console.error('Watchlist toggle failed:', err)
    }
  }

  const toggleFavourite = async () => {
    try {
      if (isFavourited) {
        await removeFavourite(mutationId)
        setIsFavourited(false)
        onFavouriteChange?.(mutationId, false)
      } else {
        await addFavourite(mutationId)
        setIsFavourited(true)
        onFavouriteChange?.(mutationId, true)
      }
    } catch (err) {
      console.error('Favourite toggle failed:', err)
    }
  }

  const favouriteLabel = isFavourited ? t('properties.removeFromFavourites') : t('properties.addToFavourites')
  const watchLabel = isWatched ? t('properties.removeFromWatchlist') : t('properties.watchForPriceDrops')

  return (
    <>
      <div className="detail-actions">
        {status === 'ready' && (
          <>
            <div className="detail-watch">
              {!isWatched && (
                <>
                  <span>{t('detail.alertAt')}</span>
                  <input
                    type="text"
                    inputMode="numeric"
                    pattern="[0-9]*"
                    className="detail-watch-input"
                    data-testid="detail-drop-pct-input"
                    aria-label={`${t('detail.alertAt')} ${t('detail.pctDrop')}`}
                    value={dropPct}
                    onChange={(e) => setDropPct(e.target.value.replace(/[^\d]/g, ''))}
                  />
                  <span>{t('detail.pctDrop')}</span>
                </>
              )}
              <button
                type="button"
                className={`detail-icon-btn detail-icon-btn--watch${isWatched ? ' active' : ''}`}
                data-testid="detail-watchlist-toggle"
                onClick={toggleWatchlist}
                title={watchLabel}
                aria-label={watchLabel}
              >
                <Bell size={16} strokeWidth={2} fill={isWatched ? 'currentColor' : 'none'} aria-hidden />
              </button>
            </div>
            <button
              type="button"
              className={`detail-icon-btn detail-icon-btn--fav${isFavourited ? ' active' : ''}`}
              data-testid="detail-favourite-toggle"
              onClick={toggleFavourite}
              title={favouriteLabel}
              aria-label={favouriteLabel}
            >
              <Star size={16} strokeWidth={2} fill={isFavourited ? 'currentColor' : 'none'} aria-hidden />
            </button>
          </>
        )}
        <button
          type="button"
          className="detail-icon-btn"
          data-testid="detail-close"
          onClick={onClose}
          aria-label={t('detail.close')}
          title={t('detail.close')}
        >
          <X size={16} strokeWidth={2} aria-hidden />
        </button>
      </div>

      {status === 'loading' && (
        <p className="detail-note" data-testid="property-detail-loading">{t('common.loading')}</p>
      )}

      {status === 'error' && (
        <div className="detail-error" data-testid="property-detail-error" role="alert">
          <p className="detail-lead">{t('detail.loadErrorTitle')}</p>
          <p className="detail-text">{t('detail.loadErrorBody')}</p>
        </div>
      )}

      {status === 'ready' && property && (
        <>
          <PanelHeader property={property} t={t} locale={locale} />
          <PanelGallery key={property.id} images={property.image_urls || []} t={t} />
          {SECTIONS.map(({ id: sectionId, Section }) => (
            <Section
              key={sectionId}
              property={property}
              priceHistory={priceHistory}
              t={t}
              locale={locale}
            />
          ))}
        </>
      )}
    </>
  )
}

function PanelHeader({ property: p, t, locale }: { property: PropertyDetail; t: TFunction; locale: string }) {
  const listings = p.listings || []
  const listingTypes = listings.map((l) => l.listing_type || 'sale')
  const uniqueTypes = [...new Set(listingTypes)]

  // The badge speaks for the price beside it: the listing type of the
  // decisioning price, or the only type the Property has.
  const headerType = p.primary_listing
    ? (p.primary_listing.listing_type || 'sale')
    : (uniqueTypes.length === 1 ? uniqueTypes[0] : null)
  const badge = percentileSentences(p, listingTypes).find((s) => s.type === headerType)

  const platforms = [...new Set(listings.map((l) => formatPlatform(l.platform)))]
  const meta: string[] = []
  if (p.bedrooms != null) {
    meta.push(t(p.bedrooms === 1 ? 'common.bedsShortOne' : 'common.bedsShortMany', { n: p.bedrooms }))
  }
  if (p.area_m2) meta.push(t('common.areaM2', { n: p.area_m2 }))
  if (platforms.length > 0) meta.push(platforms.join(' + '))

  return (
    <header className="detail-header" data-testid="detail-header">
      <div className="detail-price-line">
        <span className="detail-price">{formatCurrency(decisioningPrice(p), locale)}</span>
        {badge && (
          <span className="percentile-badge" data-testid="detail-percentile-badge">
            {t('properties.amongCheapest', { n: badge.n })}
          </span>
        )}
      </div>
      {p.neighborhood_name && <div className="detail-hood">{p.neighborhood_name}</div>}
      <div className="detail-title">{p.title || p.address || t('common.untitled')}</div>
      {meta.length > 0 && (
        <div className="detail-meta">
          {meta.map((item, index) => (
            <span key={item}>
              {index > 0 && <span className="detail-meta-sep" aria-hidden="true">·</span>}
              {item}
            </span>
          ))}
        </div>
      )}
    </header>
  )
}

function PanelGallery({ images, t }: { images: string[]; t: TFunction }) {
  const [index, setIndex] = useState(0)
  if (images.length === 0) return null
  return (
    <div className="detail-gallery">
      <img
        key={index}
        className="detail-gallery-main"
        src={images[index]}
        alt=""
        onError={(e) => { e.currentTarget.style.display = 'none' }}
      />
      {images.length > 1 && (
        <div className="detail-gallery-thumbs">
          {images.map((url, i) => (
            <button
              key={`${url}-${i}`}
              type="button"
              className={`detail-gallery-thumb${i === index ? ' active' : ''}`}
              onClick={() => setIndex(i)}
              aria-label={t('common.thumbnailAlt', { n: i + 1 })}
              aria-pressed={i === index}
            >
              <img src={url} alt="" onError={(e) => { e.currentTarget.style.display = 'none' }} />
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
