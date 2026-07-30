import { Star, Bell } from 'lucide-react'
import {
  combinedScoreForListingType,
  hasDualScores,
  statScoreForListingType,
} from '../../utils/scores.js'
import {
  bestListingForType,
  decisioningPrice,
  groupListings,
} from '../../utils/primaryListing.js'
import { formatPlatform } from '../../labels.js'
import { formatNumber, formatCurrency } from '../../i18n/format.js'
import { linkIdForProperty } from '../../routes/propertyPaths.js'

// Moved verbatim from the pre-split Properties.jsx (BIN-141) — no behavior,
// DOM, or data-testid change.

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

function getPlatformCount(listings) {
  if (!listings || listings.length === 0) return 0
  return new Set(listings.map(l => l.platform)).size
}

function formatListingType(type, t) {
  if (type === 'rent') return t('common.rentUpper')
  return t('common.saleUpper')
}

function listingTypeColor(type) {
  if (type === 'rent') return { bg: 'rgba(99,102,241,0.2)', color: '#818cf8' }
  return { bg: 'rgba(16,185,129,0.2)', color: '#34d399' }
}

function formatLocationLabel(neighborhoodName, city) {
  const nb = (neighborhoodName || '').trim()
  const c = (city || '').trim()
  if (nb && c && nb.toLowerCase() !== c.toLowerCase()) return `${nb}, ${c}`
  return nb || c || ''
}

export default function PropertyCard({
  property: p,
  listingType = 'both',
  onClick,
  isWatched,
  onToggleWatchlist,
  isFavourited,
  onToggleFavourite,
  compareMode = false,
  isCompareSelected,
  onToggleCompare,
  t,
  locale,
}) {
  const img = (p.image_urls || [])[0]
  const listings = p.listings || []
  const groups = groupListings(listings)
  const groupKeys = Object.keys(groups)
  const platformCount = getPlatformCount(listings)
  const hasListings = listings.length > 0
  const locationLabel = formatLocationLabel(p.neighborhood_name, p.city)
  const compareKey = linkIdForProperty(p) || String(p.id)
  const fallbackPrice = decisioningPrice(p)

  return (
    <div
      className={`property-card${compareMode && isCompareSelected ? ' property-card--selected' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      data-property-id={p.id}
      data-public-id={p.public_id ?? undefined}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onClick();
        }
      }}
    >
      {compareMode && (
        <label
          className="property-compare-select"
          title={t('properties.selectForComparison')}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={!!isCompareSelected}
            onChange={(e) => onToggleCompare(e, p)}
            aria-label={isCompareSelected ? t('properties.removeFromComparison') : t('properties.selectForComparison')}
            data-testid={`compare-select-${compareKey}`}
          />
        </label>
      )}
      {img
        ? <img className="property-image" src={img} alt={p.title || t('common.propertyAlt')} loading="lazy" onError={e => { e.target.style.display='none'; e.target.nextSibling.style.display='flex' }} />
        : null
      }
      <div className="property-image-placeholder" style={{ display: img ? 'none' : 'flex' }}>🏠</div>

      <div className="property-body">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            {hasListings ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }} data-testid="card-price-rows">
                {groupKeys.map(type => {
                  const best = bestListingForType(p, type, groups)
                  const colors = listingTypeColor(type)
                  return (
                    <div key={type} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                      <span className="property-price" style={{ fontSize: groupKeys.length > 1 ? 16 : 20 }}>
                        {best?.price ? formatCurrency(best.price, locale) : t('common.emDash')}
                      </span>
                      <span style={{ padding: '1px 5px', fontSize: 9, background: colors.bg, color: colors.color, borderRadius: 3, fontWeight: 700 }}>
                        {formatListingType(type, t)}
                      </span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        {formatPlatform(best?.platform)}
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
              <div className="property-price" data-testid="card-decisioning-price">
                {fallbackPrice ? formatCurrency(fallbackPrice, locale) : t('common.emDash')}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            {platformCount > 1 && (
              <span style={{ padding: '2px 6px', fontSize: 9, background: 'rgba(251,191,36,0.15)', color: '#fbbf24', borderRadius: 4, fontWeight: 700 }}>
                {t('properties.platformsBadge', { n: platformCount })}
              </span>
            )}
            <div
              className={`icon-btn ${isFavourited ? 'active' : ''}`}
              data-testid={`favourite-toggle-${p.id}`}
              title={t('properties.addToFavourites')}
              aria-label={isFavourited ? t('properties.removeFromFavourites') : t('properties.addToFavourites')}
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
              <Star size={18} strokeWidth={2} fill={isFavourited ? 'currentColor' : 'none'} aria-hidden />
            </div>
            <div
              className={`icon-btn icon-btn--watch ${isWatched ? 'active' : ''}`}
              data-testid={`watchlist-toggle-${p.id}`}
              title={t('properties.watchForPriceDrops')}
              aria-label={isWatched ? t('properties.removeFromWatchlist') : t('properties.watchForPriceDrops')}
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
              <Bell size={18} strokeWidth={2} fill={isWatched ? 'currentColor' : 'none'} aria-hidden />
            </div>
          </div>
        </div>
        <div className="property-title">{p.title || p.address || t('common.untitled')}</div>
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
          {p.price_per_m2      && <span className="property-attr" style={{ color: 'var(--text-muted)' }}>R${formatNumber(Math.round(p.price_per_m2), locale)}/m²</span>}
          {locationLabel && <span className="property-attr" style={{ color: 'var(--text-muted)' }} data-testid="property-location">📍 {locationLabel}</span>}
        </div>

        {p.description && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
            {p.description}
          </div>
        )}

        <div className="property-scores" style={{ marginTop: 12 }}>
          {listingType === 'both' && hasDualScores(p) ? (
            <>
              {p.combined_score_rent != null && (
                <div className="score-badge combined" style={{ borderColor: listingTypeColor('rent').color }}>
                  <span className="score-badge-label">{t('properties.score')} {t('properties.scoreRent')}</span>
                  <span className="score-badge-val" style={{ color: scoreColor(p.combined_score_rent) }}>
                    {displayScore(p.combined_score_rent)}
                  </span>
                </div>
              )}
              {p.combined_score_sale != null && (
                <div className="score-badge combined" style={{ borderColor: listingTypeColor('sale').color }}>
                  <span className="score-badge-label">{t('properties.score')} {t('properties.scoreSale')}</span>
                  <span className="score-badge-val" style={{ color: scoreColor(p.combined_score_sale) }}>
                    {displayScore(p.combined_score_sale)}
                  </span>
                </div>
              )}
              {p.stat_score_rent != null && (
                <div className="score-badge stat" style={{ borderColor: listingTypeColor('rent').color }}>
                  <span className="score-badge-label">{t('properties.statRent')}</span>
                  <span className="score-badge-val">{displayScore(p.stat_score_rent)}</span>
                </div>
              )}
              {p.stat_score_sale != null && (
                <div className="score-badge stat" style={{ borderColor: listingTypeColor('sale').color }}>
                  <span className="score-badge-label">{t('properties.statSale')}</span>
                  <span className="score-badge-val">{displayScore(p.stat_score_sale)}</span>
                </div>
              )}
            </>
          ) : (
            <>
              {combinedScoreForListingType(p, listingType) != null && (
                <div className="score-badge combined">
                  <span className="score-badge-label">{t('properties.score')}</span>
                  <span className="score-badge-val" style={{ color: scoreColor(combinedScoreForListingType(p, listingType)) }}>
                    {displayScore(combinedScoreForListingType(p, listingType))}
                  </span>
                </div>
              )}
              <div className="score-badge stat">
                <span className="score-badge-label">{t('properties.stat')}</span>
                <span className="score-badge-val">
                  {statScoreForListingType(p, listingType) != null
                    ? displayScore(statScoreForListingType(p, listingType))
                    : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 'normal' }}>⌛ {t('common.calcPending')}</span>}
                </span>
              </div>
            </>
          )}
          <div className="score-badge ai">
            <span className="score-badge-label">{t('properties.ai')}</span>
            <span className="score-badge-val">{p.ai_score != null ? displayScore(p.ai_score) : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 'normal' }}>⌛ {t('common.calcPending')}</span>}</span>
          </div>
          {p.neighbourhood_quality?.neighbourhood_score != null && (
            <div className="score-badge" data-testid="card-nhood-score" title={t('properties.nhoodTitle')}>
              <span className="score-badge-label">{t('properties.nhood')}</span>
              <span className="score-badge-val">{displayScore(p.neighbourhood_quality.neighbourhood_score)}</span>
            </div>
          )}
        </div>

        {((p.ai_green_flags || []).length > 0 || (p.ai_red_flags || []).length > 0) && (
          <div className="flags" style={{ marginTop: 10 }} data-testid="card-ad-claims">
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginRight: 6 }}>{t('properties.adClaims')}</span>
            {(p.ai_green_flags || []).slice(0, 2).map(f => <span key={f} className="flag green">✔ {f}</span>)}
            {(p.ai_red_flags || []).slice(0, 1).map(f => <span key={f} className="flag red">✖ {f}</span>)}
          </div>
        )}
      </div>
    </div>
  )
}
