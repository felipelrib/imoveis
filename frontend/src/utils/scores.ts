/** Filter-aware score selection (BIN-83). */

import type { ListingType } from '../api.js'

/**
 * Score-bearing property shape. Extends the base combined/stat scores with the
 * dual rent/sale variants (BIN-83 / v0.7) that `api.ts`'s Property omits.
 */
export interface ScoredProperty {
  combined_score?: number | null
  combined_score_rent?: number | null
  combined_score_sale?: number | null
  stat_score?: number | null
  stat_score_rent?: number | null
  stat_score_sale?: number | null
}

export function combinedScoreForListingType(
  property: ScoredProperty,
  listingType: ListingType | string | null | undefined,
): number | null {
  if (listingType === 'rent') {
    return property.combined_score_rent ?? property.combined_score ?? null
  }
  if (listingType === 'sale') {
    return property.combined_score_sale ?? property.combined_score ?? null
  }
  return property.combined_score ?? null
}

export function statScoreForListingType(
  property: ScoredProperty,
  listingType: ListingType | string | null | undefined,
): number | null {
  if (listingType === 'rent') {
    return property.stat_score_rent ?? property.stat_score ?? null
  }
  if (listingType === 'sale') {
    return property.stat_score_sale ?? property.stat_score ?? null
  }
  return property.stat_score ?? null
}

export function hasDualScores(property: ScoredProperty): boolean {
  return property.combined_score_rent != null && property.combined_score_sale != null
}

export function formatScorePercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return (Number(value) * 100).toFixed(0)
}
