import { formatPlatform } from '../../labels.js'
import { formatCurrency } from '../../i18n/format.js'
import { groupListings } from '../../utils/primaryListing.js'
import type { PropertyListing } from '../../api.js'
import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'
import { platformFallbackUrl, sanitizeListingUrl } from './listingUrl.js'

function attributeChips(listing: PropertyListing): { slug: string; labelKey: string }[] {
  const chips: { slug: string; labelKey: string }[] = []
  if (listing.is_furnished === true) chips.push({ slug: 'furnished', labelKey: 'detail.furnished' })
  else if (listing.is_furnished === false) chips.push({ slug: 'unfurnished', labelKey: 'detail.unfurnished' })
  if (listing.accepts_pets === true) chips.push({ slug: 'pets-ok', labelKey: 'detail.petsOk' })
  else if (listing.accepts_pets === false) chips.push({ slug: 'no-pets', labelKey: 'detail.noPets' })
  return chips
}

/**
 * One row per Listing: platform, listing type, published price and the link
 * to the original ad. With no Listing rows, the id-based fallback link when
 * the platform has one (BIN-158); otherwise nothing.
 */
export default function PlatformPricesSection({ property: p, t, locale }: DetailSectionProps) {
  const listings = p.listings || []

  if (listings.length === 0) {
    const fallbackUrl = platformFallbackUrl(p.platform, p.platform_id)
    if (!fallbackUrl) return null
    return (
      <PanelSection title={t('detail.sectionPlatforms')} testId="listings-by-platform">
        <a
          href={fallbackUrl}
          className="detail-link"
          data-testid="detail-fallback-link"
          target="_blank"
          rel="noopener noreferrer"
        >
          {t('detail.viewOriginal')}
        </a>
      </PanelSection>
    )
  }

  const groups = groupListings(listings)
  const types = Object.keys(groups).sort((a, b) => Number(b === 'rent') - Number(a === 'rent'))

  return (
    <PanelSection title={t('detail.sectionPlatforms')} testId="listings-by-platform">
      {types.map((type) => (
        <div key={type} className="detail-platforms" data-testid={`platform-rows-${type}`}>
          {groups[type].map((listing, index) => {
            const url = sanitizeListingUrl(listing.url)
            const chips = attributeChips(listing)
            return (
              <div
                key={`${listing.platform}-${listing.platform_listing_id}-${index}`}
                className="detail-platform-row"
                data-testid="platform-row"
              >
                <span className="detail-plat">{formatPlatform(listing.platform)}</span>
                <span className="detail-muted">{type === 'rent' ? t('common.rent') : t('common.sale')}</span>
                <span className="detail-platform-price">
                  {/* Same check as the card: a missing or zero price is a dash. */}
                  {listing.price ? formatCurrency(listing.price, locale) : t('common.emDash')}
                </span>
                {url ? (
                  <a href={url} className="detail-link" target="_blank" rel="noopener noreferrer">
                    {t('detail.openOnPlatform')}
                  </a>
                ) : (
                  <span className="detail-note">{t('detail.linkUnavailable')}</span>
                )}
                {chips.length > 0 && (
                  <span className="detail-tags detail-platform-attrs">
                    {chips.map((chip) => (
                      <span key={chip.slug} className="detail-tag" data-testid={`attr-chip-${chip.slug}`}>
                        {t(chip.labelKey)}
                      </span>
                    ))}
                  </span>
                )}
              </div>
            )
          })}
        </div>
      ))}
    </PanelSection>
  )
}
