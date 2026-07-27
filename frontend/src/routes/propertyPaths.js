/** Shareable SPA paths for properties, favourites, and compare (public_id). */

export const PROPERTIES_PATH = '/properties'
export const FAVOURITES_PATH = '/favourites'

/**
 * @param {string|number} publicId sequential properties.public_id
 * @returns {string}
 */
export function propertyPath(publicId) {
  return `${PROPERTIES_PATH}/${Number(publicId)}`
}

/**
 * Comma-separated sequential public ids.
 * @param {Array<string|number>} publicIds
 * @returns {string}
 */
export function comparePath(publicIds) {
  return `/compare/${publicIds.map((id) => String(Number(id))).join(',')}`
}

/**
 * Parse `/compare/:compareIds` segment (`14,22,31`) into ordered unique public ids.
 * @param {string|undefined|null} segment
 * @returns {string[]}
 */
export function parseCompareIds(segment) {
  if (!segment || typeof segment !== 'string') return []
  const seen = new Set()
  const out = []
  for (const raw of segment.split(',')) {
    const part = raw.trim()
    if (!/^\d+$/.test(part) || seen.has(part)) continue
    seen.add(part)
    out.push(part)
  }
  return out
}

/**
 * @param {string|undefined|null} param
 * @returns {string|null} numeric public_id string, or null if invalid
 */
export function parsePropertyId(param) {
  if (!param || typeof param !== 'string') return null
  return /^\d+$/.test(param) ? param : null
}

/**
 * Prefer sequential public_id for URLs; fall back only if missing (legacy mocks).
 * @param {{ public_id?: number|string|null, id?: string|number|null }} property
 * @returns {string|null}
 */
export function linkIdForProperty(property) {
  if (!property) return null
  if (property.public_id != null && property.public_id !== '') {
    return String(property.public_id)
  }
  if (property.id != null && /^\d+$/.test(String(property.id))) {
    return String(property.id)
  }
  return null
}

/**
 * Whether the path belongs to the properties deal surface (nav highlight).
 * @param {string} pathname
 */
export function isPropertiesSurface(pathname) {
  return (
    pathname === PROPERTIES_PATH
    || pathname.startsWith(`${PROPERTIES_PATH}/`)
    || pathname === FAVOURITES_PATH
    || pathname.startsWith(`${FAVOURITES_PATH}/`)
    || pathname.startsWith('/compare/')
  )
}
