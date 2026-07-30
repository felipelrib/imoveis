/** AD-12 primary listing helpers — prefer API projection over local re-derivation. */

/** Minimal listing shape these helpers rely on (structural subset of api PropertyListing). */
export interface ListingLike {
  listing_type?: string | null
  price?: number | null
  platform?: string | null
}

/** Minimal property shape: a decisioning price plus its primary listing. */
export interface PropertyLike {
  price?: number | null
  primary_listing?: ListingLike | null
}

/** Decisioning price: primary_listing.price when present, else top-level price. */
export function decisioningPrice(property: PropertyLike | null | undefined): number | null {
  if (property?.primary_listing?.price != null) return property.primary_listing.price
  if (property?.price != null) return property.price
  return null
}

/**
 * Group listings by listing_type, each group sorted by price ascending.
 * Generic so callers passing a richer listing type (e.g. api PropertyListing)
 * get that same type back out, not a widened ListingLike.
 */
export function groupListings<T extends ListingLike>(
  listings: T[] | null | undefined,
): Record<string, T[]> {
  if (!listings || listings.length === 0) return {}
  const groups: Record<string, T[]> = {}
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

/** Best listing for a type: prefer primary_listing when its type matches. */
export function bestListingForType(
  property: PropertyLike | null | undefined,
  type: string,
  grouped: Record<string, ListingLike[]>,
): ListingLike | null {
  const primary = property?.primary_listing
  if (primary && (primary.listing_type || 'sale') === type) {
    return primary
  }
  return grouped[type]?.[0] || null
}

/** Whether a listing row matches the property's primary_listing. */
export function isPrimaryListingRow(
  listing: ListingLike | null | undefined,
  property: PropertyLike | null | undefined,
): boolean {
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
