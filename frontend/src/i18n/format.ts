/**
 * Locale-aware number/date helpers (BIN-99 / BIN-116).
 * Currency stays BRL; digit grouping / date order follow the active UI locale.
 */

/** Values these formatters accept for date-like inputs. */
export type DateLike = string | number | Date | null | undefined

function resolveLocale(locale: string | null | undefined): string {
  return locale || 'en'
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
