/**
 * Saved-search filter wire helpers (BIN-100).
 *
 * Persist snake_case English canonical values; accept both snake_case (API)
 * and camelCase (legacy SPA) on reopen so labels re-localize via t().
 */

const CAMEL_TO_SNAKE = {
  sortBy: 'sort_by',
  sortDir: 'sort_dir',
  listingType: 'listing_type',
  propertyType: 'property_type',
  platform: 'platform',
  maxPrice: 'max_price',
  priceType: 'price_type',
  minBedrooms: 'min_bedrooms',
  minParking: 'min_parking',
  minScore: 'min_score',
  neighborhood: 'neighborhood',
  city: 'city',
  isFurnished: 'is_furnished',
  acceptsPets: 'accepts_pets',
  q: 'q',
}

function isEmptyFilterValue(value) {
  return (
    value === undefined ||
    value === null ||
    value === '' ||
    value === false
  )
}

/**
 * @param {Record<string, unknown>} filters camelCase Properties filter state
 * @returns {Record<string, unknown>} snake_case EN wire for POST /saved-searches
 */
export function toSavedSearchWire(filters) {
  if (!filters || typeof filters !== 'object') return {}
  const out = {}
  for (const [camel, snake] of Object.entries(CAMEL_TO_SNAKE)) {
    const value = filters[camel]
    if (isEmptyFilterValue(value)) continue
    out[snake] = value
  }
  return out
}

function pick(filters, ...keys) {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(filters, key) && filters[key] !== undefined) {
      return filters[key]
    }
  }
  return undefined
}

/**
 * @param {Record<string, unknown>} filters snake_case or camelCase blob from API
 * @returns {Record<string, unknown>} camelCase keys for Properties applyFilters
 */
export function fromSavedSearchWire(filters) {
  if (!filters || typeof filters !== 'object') return {}
  const out = {}

  const sortBy = pick(filters, 'sort_by', 'sortBy')
  if (sortBy !== undefined) out.sortBy = sortBy

  const sortDir = pick(filters, 'sort_dir', 'sortDir')
  if (sortDir !== undefined) out.sortDir = sortDir

  const listingType = pick(filters, 'listing_type', 'listingType')
  if (listingType !== undefined) out.listingType = listingType

  const propertyType = pick(filters, 'property_type', 'propertyType')
  if (propertyType !== undefined) out.propertyType = propertyType

  const platform = pick(filters, 'platform')
  if (platform !== undefined) out.platform = platform

  const maxPrice = pick(filters, 'max_price', 'maxPrice')
  if (maxPrice !== undefined) out.maxPrice = maxPrice

  const priceType = pick(filters, 'price_type', 'priceType')
  if (priceType !== undefined) out.priceType = priceType

  const minBedrooms = pick(filters, 'min_bedrooms', 'minBedrooms')
  if (minBedrooms !== undefined) out.minBedrooms = minBedrooms

  const minParking = pick(filters, 'min_parking', 'minParking')
  if (minParking !== undefined) out.minParking = minParking

  const minScore = pick(filters, 'min_score', 'minScore')
  if (minScore !== undefined) out.minScore = minScore

  let neighborhood = pick(filters, 'neighborhood', 'neighbourhood', 'neighborhood_name')
  if (Array.isArray(neighborhood)) {
    neighborhood = neighborhood.filter(Boolean).join(',')
  }
  if (neighborhood !== undefined) out.neighborhood = neighborhood

  const city = pick(filters, 'city', 'city_name', 'cityName')
  if (city !== undefined) out.city = city

  const isFurnished = pick(filters, 'is_furnished', 'isFurnished', 'furnished')
  if (isFurnished !== undefined) out.isFurnished = Boolean(isFurnished)

  const acceptsPets = pick(filters, 'accepts_pets', 'acceptsPets', 'pets')
  if (acceptsPets !== undefined) out.acceptsPets = Boolean(acceptsPets)

  const q = pick(filters, 'q')
  if (q !== undefined) out.q = q

  return out
}
