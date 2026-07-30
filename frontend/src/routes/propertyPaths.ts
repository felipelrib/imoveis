/** Shareable SPA paths for properties, favourites, and compare (public_id). */

export const PROPERTIES_PATH = '/properties'
export const FAVOURITES_PATH = '/favourites'

/** @param publicId sequential properties.public_id */
export function propertyPath(publicId: string | number): string {
  return `${PROPERTIES_PATH}/${Number(publicId)}`
}

/** Comma-separated sequential public ids. */
export function comparePath(publicIds: Array<string | number>): string {
  return `/compare/${publicIds.map((id) => String(Number(id))).join(',')}`
}

/** Parse `/compare/:compareIds` segment (`14,22,31`) into ordered unique public ids. */
export function parseCompareIds(segment: string | undefined | null): string[] {
  if (!segment || typeof segment !== 'string') return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of segment.split(',')) {
    const part = raw.trim()
    if (!/^\d+$/.test(part) || seen.has(part)) continue
    seen.add(part)
    out.push(part)
  }
  return out
}

/** @returns numeric public_id string, or null if invalid */
export function parsePropertyId(param: string | undefined | null): string | null {
  if (!param || typeof param !== 'string') return null
  return /^\d+$/.test(param) ? param : null
}

/** Minimal shape needed to derive a shareable link id. */
export interface LinkableProperty {
  public_id?: number | string | null
  id?: string | number | null
}

/** Prefer sequential public_id for URLs; fall back only if missing (legacy mocks). */
export function linkIdForProperty(property: LinkableProperty | null | undefined): string | null {
  if (!property) return null
  if (property.public_id != null && property.public_id !== '') {
    return String(property.public_id)
  }
  if (property.id != null && /^\d+$/.test(String(property.id))) {
    return String(property.id)
  }
  return null
}

/** Whether the path belongs to the properties deal surface (nav highlight). */
export function isPropertiesSurface(pathname: string): boolean {
  return (
    pathname === PROPERTIES_PATH
    || pathname.startsWith(`${PROPERTIES_PATH}/`)
    || pathname === FAVOURITES_PATH
    || pathname.startsWith(`${FAVOURITES_PATH}/`)
    || pathname.startsWith('/compare/')
  )
}
