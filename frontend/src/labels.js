/** Display labels for canonical API / storage values (locale-aware types — BIN-99). */

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
  { value: 'apartment', labelKey: 'labels.propertyType.apartment' },
  { value: 'house', labelKey: 'labels.propertyType.house' },
  { value: 'condo_house', labelKey: 'labels.propertyType.condo_house' },
  { value: 'studio', labelKey: 'labels.propertyType.studio' },
]

/**
 * @param {string | null | undefined} type
 * @param {(key: string, params?: Record<string, string|number>) => string} [t]
 */
export function formatPropertyType(type, t) {
  if (type == null || type === '') return '—'
  const opt = PROPERTY_TYPE_OPTIONS.find((o) => o.value === type)
  if (opt && typeof t === 'function') return t(opt.labelKey)
  if (opt) {
    const fallback = {
      apartment: 'Apartment',
      house: 'House',
      condo_house: 'Condo house',
      studio: 'Studio',
    }
    return fallback[type] || type
  }
  return type
}
