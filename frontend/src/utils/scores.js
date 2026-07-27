/** Filter-aware score selection (BIN-83). */

export function combinedScoreForListingType(property, listingType) {
  if (listingType === 'rent') {
    return property.combined_score_rent ?? property.combined_score ?? null
  }
  if (listingType === 'sale') {
    return property.combined_score_sale ?? property.combined_score ?? null
  }
  return property.combined_score ?? null
}

export function statScoreForListingType(property, listingType) {
  if (listingType === 'rent') {
    return property.stat_score_rent ?? property.stat_score ?? null
  }
  if (listingType === 'sale') {
    return property.stat_score_sale ?? property.stat_score ?? null
  }
  return property.stat_score ?? null
}

export function hasDualScores(property) {
  return property.combined_score_rent != null && property.combined_score_sale != null
}

export function formatScorePercent(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return (Number(value) * 100).toFixed(0)
}
