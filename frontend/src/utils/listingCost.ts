/**
 * Monthly cost rows of one Listing for the detail panel (v0.14-s1.8).
 *
 * A pure view-model over the stored `listings[].cost` object of Story 1.2.
 * Nothing here adds, subtracts, defaults or falls back to the legacy
 * `price` / `base_price` / `condo_fee` / `iptu` fields: a row either carries
 * the stored figure or carries `null` with the state that says why.
 */
import type { ListingCost } from '../api.js'

export type CostRowKind = 'rent' | 'condo' | 'condoIptuBundled' | 'iptu' | 'total'

/**
 * `known`      the stored figure is shown.
 * `bundled`    one combined condo + IPTU figure the platform published.
 * `unknown`    the platform did not publish the component: no figure, never 0.
 * `incomplete` a total that cannot be stated because a component is unknown.
 */
export type CostRowState = 'known' | 'bundled' | 'unknown' | 'incomplete'

export interface CostRow {
  kind: CostRowKind
  value: number | null
  state: CostRowState
  /** IPTU published per year and stored already converted to a month. */
  convertedFromAnnual?: boolean
}

function storedFigure(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** A component row: the figure when it is known and stored, else `unknown`. */
function componentRow(
  kind: CostRowKind,
  state: string | null | undefined,
  value: number | null | undefined,
): CostRow {
  const figure = state === 'known' ? storedFigure(value) : null
  return figure == null
    ? { kind, value: null, state: 'unknown' }
    : { kind, value: figure, state: 'known' }
}

/**
 * Ordered rows for one Listing, or `null` when the payload has no `cost`
 * object (an older API image): the Listing then has no cost block at all.
 *
 * - rent Listing: rent, condo, IPTU, total;
 * - bundled fees: one `condoIptuBundled` row instead of condo and IPTU;
 * - sale Listing (`not-applicable` rent and total): condo and IPTU only.
 */
export function listingCostRows(cost: ListingCost | null | undefined): CostRow[] | null {
  if (!cost) return null
  const rows: CostRow[] = []

  if (cost.rent_state !== 'not-applicable') {
    rows.push(componentRow('rent', cost.rent_state, cost.rent_monthly))
  }

  const bundled = cost.fees_bundled === true
    || cost.condo_fee_state === 'bundled'
    || cost.iptu_state === 'bundled'
  if (bundled) {
    // The combined published figure is held in `condo_fee_monthly`.
    const figure = storedFigure(cost.condo_fee_monthly)
    rows.push(figure == null
      ? { kind: 'condoIptuBundled', value: null, state: 'unknown' }
      : { kind: 'condoIptuBundled', value: figure, state: 'bundled' })
  } else {
    rows.push(componentRow('condo', cost.condo_fee_state, cost.condo_fee_monthly))
    const iptu = componentRow('iptu', cost.iptu_state, cost.iptu_monthly)
    if (iptu.state === 'known' && cost.iptu_periodicity_source === 'annual') {
      iptu.convertedFromAnnual = true
    }
    rows.push(iptu)
  }

  if (cost.total_state !== 'not-applicable') {
    const total = cost.total_state === 'incomplete' ? null : storedFigure(cost.total_monthly_cost)
    rows.push(total == null
      ? { kind: 'total', value: null, state: 'incomplete' }
      : { kind: 'total', value: total, state: 'known' })
  }

  return rows
}
