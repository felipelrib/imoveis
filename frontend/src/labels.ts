/** Display labels for canonical API / storage values (locale-aware types — BIN-99). */

/** Translator function shape (compatible with `t` from i18n and `useT()`). */
export type TranslateFn = (key: string, params?: Record<string, string | number>) => string

export const PLATFORM_LABELS: Record<string, string> = {
  olx: 'OLX',
  quintoandar: 'QuintoAndar',
}

export function formatPlatform(slug: string | null | undefined): string {
  if (slug == null || slug === '') return '—'
  return PLATFORM_LABELS[slug] || slug
}

export interface PropertyTypeOption {
  value: string
  labelKey: string
}

export const PROPERTY_TYPE_OPTIONS: PropertyTypeOption[] = [
  { value: 'apartment', labelKey: 'labels.propertyType.apartment' },
  { value: 'house', labelKey: 'labels.propertyType.house' },
  { value: 'condo_house', labelKey: 'labels.propertyType.condo_house' },
  { value: 'studio', labelKey: 'labels.propertyType.studio' },
]

export function formatPropertyType(type: string | null | undefined, t?: TranslateFn): string {
  if (type == null || type === '') return '—'
  const opt = PROPERTY_TYPE_OPTIONS.find((o) => o.value === type)
  if (opt && typeof t === 'function') return t(opt.labelKey)
  if (opt) {
    const fallback: Record<string, string> = {
      apartment: 'Apartment',
      house: 'House',
      condo_house: 'Condo house',
      studio: 'Studio',
    }
    return fallback[type] || type
  }
  return type
}
