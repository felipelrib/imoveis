import { formatPlatform } from '../../labels.js'
import { formatCurrency } from '../../i18n/format.js'
import { listingCostRows, type CostRow, type CostRowKind } from '../../utils/listingCost.js'
import { groupListings } from '../../utils/primaryListing.js'
import type { PropertyListing } from '../../api.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'
import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'

const ROW_LABEL: Record<CostRowKind, string> = {
  rent: 'detail.costRent',
  condo: 'detail.costCondo',
  condoIptuBundled: 'detail.costCondoIptuBundled',
  iptu: 'detail.costIptu',
  total: 'detail.costTotal',
}

/** What the value cell reads: the stored figure, or the words for its absence. */
function rowValue(row: CostRow, t: TFunction, locale: string): string {
  if (row.value != null) return formatCurrency(row.value, locale)
  return row.state === 'incomplete' ? t('detail.costIncomplete') : t('detail.costUnknown')
}

function rowNote(row: CostRow, t: TFunction): string | null {
  if (row.state === 'bundled') return t('detail.costBundledNote')
  if (row.state === 'incomplete') return t('detail.costIncompleteNote')
  if (row.convertedFromAnnual) return t('detail.costIptuAnnualNote')
  return null
}

/**
 * Stored Total Monthly Cost per Listing (Story 1.2 projection), itemized.
 * A Listing without a `cost` object has no block; the section is absent when
 * no Listing has one.
 */
export default function MonthlyCostSection({ property: p, t, locale }: DetailSectionProps) {
  const groups = groupListings(p.listings || [])
  const ordered = [...(groups.rent || []), ...Object.entries(groups)
    .filter(([type]) => type !== 'rent')
    .flatMap(([, listings]) => listings)]

  const blocks: { listing: PropertyListing; rows: CostRow[] }[] = []
  for (const listing of ordered) {
    const rows = listingCostRows(listing.cost)
    if (rows && rows.length > 0) blocks.push({ listing, rows })
  }
  if (blocks.length === 0) return null

  // "Lowest total" is only true when the deciding Listing was chosen by its
  // stored total, and only when it was compared with another stored total: a
  // rent Listing whose total is incomplete could cost less, so with a single
  // stated total nothing is called the lowest.
  const statedRentTotals = blocks.filter(({ listing, rows }) => (
    (listing.listing_type || 'sale') === 'rent'
    && rows.some((row) => row.kind === 'total' && row.value != null)
  )).length
  const marksDeciding = statedRentTotals > 1
    && p.deciding_rule === 'lowest-complete-total'
    && p.deciding_listing_id != null

  return (
    <PanelSection title={t('detail.sectionCost')} testId="detail-section-cost">
      {blocks.map(({ listing, rows }, index) => {
        const type = listing.listing_type || 'sale'
        const deciding = marksDeciding && listing.id != null && listing.id === p.deciding_listing_id
        return (
          <div
            key={`${listing.platform}-${listing.platform_listing_id}-${type}-${index}`}
            className="detail-cost"
            data-testid={`cost-listing-${type}`}
            data-platform={listing.platform}
          >
            <div className="detail-cost-head">
              <span className="detail-plat">{formatPlatform(listing.platform)}</span>
              <span className="detail-muted">{type === 'rent' ? t('common.rent') : t('common.sale')}</span>
              {deciding && (
                <span className="detail-note" data-testid="cost-deciding">{t('detail.costDeciding')}</span>
              )}
            </div>
            <div className="detail-kv-list">
              {rows.map((row) => {
                const note = rowNote(row, t)
                return (
                  <div
                    key={row.kind}
                    className={`detail-kv${row.kind === 'total' ? ' detail-kv--total' : ''}`}
                    data-testid={`cost-row-${row.kind}`}
                    data-state={row.state}
                  >
                    <span className="detail-kv-key">
                      {t(ROW_LABEL[row.kind])}
                      {note && <span className="detail-note" data-testid="cost-row-note">{note}</span>}
                    </span>
                    <span
                      className={`detail-kv-val${row.value == null ? ' detail-kv-val--absent' : ''}`}
                      data-testid="cost-row-value"
                    >
                      {rowValue(row, t, locale)}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </PanelSection>
  )
}
