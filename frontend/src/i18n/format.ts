/**
 * Locale-aware number/date helpers (BIN-99 / BIN-116).
 * Currency stays BRL; digit grouping / date order follow the active UI locale.
 */

import { DEFAULT_LOCALE } from './defaultLocale.js'

/** Values these formatters accept for date-like inputs. */
export type DateLike = string | number | Date | null | undefined

function resolveLocale(locale: string | null | undefined): string {
  // Falls back to the product default (pt-BR) rather than a hardcoded 'en', so an
  // unlocalized caller formats numbers/dates the same way the chrome reads.
  return locale || DEFAULT_LOCALE
}

/**
 * Whole-number percent from a `[0, 1]` fraction (`0.617` → `62`). Coverage is
 * never quoted to a precision it does not have; `null` in stays `null` out so
 * callers render absence rather than `0%`.
 *
 * Rounding is deliberately *not* symmetric at the two ends, because both ends
 * carry a claim the corpus does not support (v0.13-s1.6 review):
 *
 * * `0.996` rounds to `100` and would report a finished corpus while ~8 rows of
 *   2000 are still unenriched — so anything strictly below 1 tops out at `99`.
 * * a tiny but non-zero fraction rounds to `0` and would report "nothing
 *   measured" for a signal that has in fact started — so anything strictly
 *   above 0 floors at `1`.
 *
 * Non-finite input (`NaN`, `±Infinity`) is undefined coverage, i.e. `null`.
 */
export function wholePercent(fraction: number | null | undefined): number | null {
  if (fraction == null) return null
  const value = Number(fraction)
  if (!Number.isFinite(value)) return null
  const pct = value * 100
  if (pct >= 100) return 100
  if (pct <= 0) return 0
  const rounded = Math.round(pct)
  if (rounded >= 100) return 99
  if (rounded <= 0) return 1
  return rounded
}

export function formatNumber(value: number | null | undefined, locale?: string): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString(resolveLocale(locale))
}

export function formatCurrency(value: number | null | undefined, locale?: string): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `R$ ${Number(value).toLocaleString(resolveLocale(locale))}`
}

export function formatCurrencyBRL(value: number | null | undefined, locale?: string): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString(resolveLocale(locale), {
    style: 'currency',
    currency: 'BRL',
  })
}

export function formatPricePerM2(value: number | null | undefined, locale?: string): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `R$ ${Math.round(Number(value)).toLocaleString(resolveLocale(locale))}/m²`
}

export function formatDate(
  value: DateLike,
  locale?: string,
  options: Intl.DateTimeFormatOptions = { day: '2-digit', month: '2-digit' },
): string {
  if (value == null) return '?'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '?'
  return d.toLocaleDateString(resolveLocale(locale), options)
}

export function formatDateTime(
  value: DateLike,
  locale?: string,
  options: Intl.DateTimeFormatOptions = {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: '2-digit',
  },
): string {
  if (value == null) return '—'
  const d = typeof value === 'number'
    ? new Date(value > 1e12 ? value : value * 1000)
    : (value instanceof Date ? value : new Date(value))
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(resolveLocale(locale), options)
}

export function formatTime(value: DateLike, locale?: string): string {
  const d = value == null
    ? new Date()
    : (value instanceof Date ? value : new Date(value))
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString(resolveLocale(locale), {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
