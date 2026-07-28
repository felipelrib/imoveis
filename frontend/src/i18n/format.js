/**
 * Locale-aware number/date helpers (BIN-99).
 * Currency stays BRL; digit grouping follows the active UI locale.
 */

/**
 * @param {string|null|undefined} locale
 */
function resolveLocale(locale) {
  return locale || 'en'
}

/**
 * @param {number|null|undefined} value
 * @param {string} [locale]
 */
export function formatNumber(value, locale) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString(resolveLocale(locale))
}

/**
 * @param {number|null|undefined} value
 * @param {string} [locale]
 */
export function formatCurrency(value, locale) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `R$ ${Number(value).toLocaleString(resolveLocale(locale))}`
}

/**
 * @param {number|null|undefined} value
 * @param {string} [locale]
 */
export function formatCurrencyBRL(value, locale) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toLocaleString(resolveLocale(locale), {
    style: 'currency',
    currency: 'BRL',
  })
}

/**
 * @param {number|null|undefined} value
 * @param {string} [locale]
 */
export function formatPricePerM2(value, locale) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `R$ ${Math.round(Number(value)).toLocaleString(resolveLocale(locale))}/m²`
}

/**
 * @param {string|number|Date|null|undefined} value
 * @param {string} [locale]
 * @param {Intl.DateTimeFormatOptions} [options]
 */
export function formatDate(value, locale, options = { day: '2-digit', month: '2-digit' }) {
  if (value == null) return '?'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '?'
  return d.toLocaleDateString(resolveLocale(locale), options)
}

/**
 * @param {string|number|Date|null|undefined} value
 * @param {string} [locale]
 * @param {Intl.DateTimeFormatOptions} [options]
 */
export function formatDateTime(value, locale, options = {
  hour: '2-digit',
  minute: '2-digit',
  day: '2-digit',
  month: '2-digit',
}) {
  if (value == null) return '—'
  const d = typeof value === 'number'
    ? new Date(value > 1e12 ? value : value * 1000)
    : (value instanceof Date ? value : new Date(value))
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(resolveLocale(locale), options)
}

/**
 * @param {string|number|Date|null|undefined} value
 * @param {string} [locale]
 */
export function formatTime(value, locale) {
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
