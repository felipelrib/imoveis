/**
 * Saved-search row (v0.14-s1.10): what the row says about a stored search and
 * how its minimum-drop field reads and writes a value. Pure: no React, no
 * catalog. The row localises the descriptors.
 */
import { fromSavedSearchWire } from '../savedSearchFilters.js'

/** One fact of the filter summary, in display order. */
export type SavedSearchSummaryPart =
  | { kind: 'listingType'; value: 'rent' | 'sale' }
  | { kind: 'propertyType'; value: string }
  | { kind: 'maxPrice'; value: number; priceType: 'rent' | 'sale' }
  | { kind: 'minBedrooms'; value: number }
  | { kind: 'minParking'; value: number }
  | { kind: 'neighborhood'; value: string }
  | { kind: 'city'; value: string }
  | { kind: 'percentileCap'; value: number }
  | { kind: 'platform'; value: string }
  | { kind: 'furnished' }
  | { kind: 'pets' }
  | { kind: 'minScore'; value: number }
  | { kind: 'query'; value: string }

function text(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return ''
}

function positive(value: unknown): number | null {
  const parsed = typeof value === 'number' ? value : Number.parseFloat(text(value))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/** `Savassi,Lourdes` (the stored list) reads `Savassi, Lourdes`. */
function places(value: unknown): string {
  return text(value)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .join(', ')
}

/**
 * The filters a stored search stands for, as ordered descriptors. Reads the
 * snake_case wire and the legacy camelCase blob alike. Sort order is not a
 * filter and is left out; a value that is not usable is left out as well.
 */
export function savedSearchSummaryParts(
  filters: Record<string, unknown> | null | undefined,
): SavedSearchSummaryPart[] {
  if (!filters || typeof filters !== 'object' || Array.isArray(filters)) return []
  const f = fromSavedSearchWire(filters)
  const parts: SavedSearchSummaryPart[] = []

  const listingType = f.listingType === 'rent' || f.listingType === 'sale' ? f.listingType : null
  if (listingType) parts.push({ kind: 'listingType', value: listingType })

  const propertyType = text(f.propertyType)
  if (propertyType) parts.push({ kind: 'propertyType', value: propertyType })

  const maxPrice = positive(f.maxPrice)
  if (maxPrice != null) {
    // Same default as the list endpoint: the stored price type, else the
    // listing type, else rent.
    const stored = f.priceType === 'rent' || f.priceType === 'sale' ? f.priceType : null
    parts.push({ kind: 'maxPrice', value: maxPrice, priceType: stored ?? listingType ?? 'rent' })
  }

  const minBedrooms = positive(f.minBedrooms)
  if (minBedrooms != null) parts.push({ kind: 'minBedrooms', value: minBedrooms })

  const minParking = positive(f.minParking)
  if (minParking != null) parts.push({ kind: 'minParking', value: minParking })

  const neighborhood = places(f.neighborhood)
  if (neighborhood) parts.push({ kind: 'neighborhood', value: neighborhood })

  const city = places(f.city)
  if (city) parts.push({ kind: 'city', value: city })

  const cap = positive(f.maxPricePerM2Percentile)
  if (cap != null && cap <= 1) parts.push({ kind: 'percentileCap', value: cap })

  const platform = text(f.platform)
  if (platform) parts.push({ kind: 'platform', value: platform })

  if (f.isFurnished === true) parts.push({ kind: 'furnished' })
  if (f.acceptsPets === true) parts.push({ kind: 'pets' })

  const minScore = positive(f.minScore)
  if (minScore != null) parts.push({ kind: 'minScore', value: minScore })

  const query = text(f.q)
  if (query) parts.push({ kind: 'query', value: query })

  return parts
}

/** Whether the stored filters carry a text (semantic) query. */
export function savedSearchHasQuery(filters: Record<string, unknown> | null | undefined): boolean {
  return savedSearchSummaryParts(filters).some((part) => part.kind === 'query')
}

export type DropThresholdInput = { ok: true; value: number | null } | { ok: false }

// `1.500` / `1.500,50` (pt-BR grouping), `1,500` / `1,500.50` (en grouping),
// `1500` / `1500,5` / `1500.50` (no grouping). A lone separator followed by
// exactly three digits is grouping in both locales, so nothing is ambiguous.
const GROUPED_DOT = /^\d{1,3}(\.\d{3})+(,\d{1,2})?$/
const GROUPED_COMMA = /^\d{1,3}(,\d{3})+(\.\d{1,2})?$/
const PLAIN = /^\d+([.,]\d{1,2})?$/

/**
 * What the minimum-drop field holds, as the value to store.
 *
 * Empty is `null` (no drop alerts). Reais, absolute: `240`, `1.500`,
 * `1500,50`, `R$ 240`. A negative number, letters or anything that is not a
 * finite amount is not a value (`ok: false`) and must not be sent.
 */
export function parseDropThreshold(raw: string): DropThresholdInput {
  const cleaned = String(raw ?? '')
    .replace(/^\s*R\$/i, '')
    .replace(/\s+/g, '')
  if (cleaned === '') return { ok: true, value: null }

  let normalised: string
  if (GROUPED_DOT.test(cleaned)) normalised = cleaned.replace(/\./g, '').replace(',', '.')
  else if (GROUPED_COMMA.test(cleaned)) normalised = cleaned.replace(/,/g, '')
  else if (PLAIN.test(cleaned)) normalised = cleaned.replace(',', '.')
  else return { ok: false }

  const value = Number(normalised)
  if (!Number.isFinite(value) || value < 0) return { ok: false }
  return { ok: true, value: Math.round(value * 100) / 100 }
}

/**
 * A stored threshold as the field and the state line show it: whole reais
 * without decimals, anything else with two (`1.500`, `1.500,50`). `''` for no
 * threshold. `parseDropThreshold` reads the result back to the same value.
 */
export function formatDropThreshold(value: number | null | undefined, locale?: string): string {
  if (value == null || !Number.isFinite(value)) return ''
  const digits = Number.isInteger(value) ? 0 : 2
  return value.toLocaleString(locale || undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** Two stored thresholds are the same value (`null` only equals `null`). */
export function sameDropThreshold(
  a: number | null | undefined,
  b: number | null | undefined,
): boolean {
  if (a == null || b == null) return a == null && b == null
  return Math.abs(a - b) < 0.005
}
