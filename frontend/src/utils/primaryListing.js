/** AD-12 primary listing helpers — prefer API projection over local re-derivation. */

/**
 * Decisioning price: primary_listing.price when present, else top-level price.
 * @param {{ primary_listing?: { price?: number|null }, price?: number|null }|null|undefined} property
 * @returns {number|null}
 */
export function decisioningPrice(property) {
  if (property?.primary_listing?.price != null) return property.primary_listing.price
  if (property?.price != null) return property.price
  return null
}

/**
 * Group listings by listing_type, each group sorted by price ascending.
 * @param {Array<{ listing_type?: string, price?: number|null }>|null|undefined} listings
 * @returns {Record<string, Array>}
 */
export function groupListings(listings) {
  if (!listings || listings.length === 0) return {}
  const groups = {}
  for (const l of listings) {
    const key = l.listing_type || 'sale'
    if (!groups[key]) groups[key] = []
    groups[key].push(l)
  }
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => (a.price || Infinity) - (b.price || Infinity))
  }
  return groups
}

/**
 * Best listing for a type: prefer primary_listing when its type matches.
 * @param {{ primary_listing?: { listing_type?: string, price?: number|null }|null }} property
 * @param {string} type
 * @param {Record<string, Array>} grouped
 * @returns {object|null}
 */
export function bestListingForType(property, type, grouped) {
  const primary = property?.primary_listing
  if (primary && (primary.listing_type || 'sale') === type) {
    return primary
  }
  return grouped[type]?.[0] || null
}

/**
 * Whether a listing row matches the property's primary_listing.
 * @param {{ platform?: string, listing_type?: string, price?: number|null }} listing
 * @param {{ primary_listing?: { platform?: string, listing_type?: string, price?: number|null }|null }} property
 */
export function isPrimaryListingRow(listing, property) {
  const primary = property?.primary_listing
  if (!primary || !listing) return false
  const listingType = listing.listing_type || 'sale'
  const primaryType = primary.listing_type || 'sale'
  return (
    listingType === primaryType
    && listing.platform === primary.platform
    && listing.price != null
    && primary.price != null
    && Number(listing.price) === Number(primary.price)
  )
}
