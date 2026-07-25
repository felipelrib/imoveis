/** Display labels for canonical API / storage values (EN product language). */

export const PLATFORM_LABELS = {
  olx: 'OLX',
  quintoandar: 'QuintoAndar',
}

/** @param {string | null | undefined} slug */
export function formatPlatform(slug) {
  if (slug == null || slug === '') return '—'
  return PLATFORM_LABELS[slug] || slug
}

export const PROPERTY_TYPE_OPTIONS = [
  { value: 'apartment', label: 'Apartment' },
  { value: 'house', label: 'House' },
  { value: 'condo_house', label: 'Condo house' },
  { value: 'studio', label: 'Studio' },
]

export const PROPERTY_TYPE_LABELS = Object.fromEntries(
  PROPERTY_TYPE_OPTIONS.map((o) => [o.value, o.label]),
)

/** @param {string | null | undefined} type */
export function formatPropertyType(type) {
  if (type == null || type === '') return '—'
  return PROPERTY_TYPE_LABELS[type] || type
}
