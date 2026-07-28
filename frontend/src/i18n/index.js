/**
 * Lightweight message catalogs (BIN-98).
 * Add a locale by dropping a JSON file here and registering it in CATALOGS.
 */
import en from './locales/en.json'
import ptBR from './locales/pt-BR.json'

export const DEFAULT_LOCALE = 'en'

/** @type {Record<string, typeof en>} */
export const CATALOGS = {
  en,
  'pt-BR': ptBR,
}

export const SUPPORTED_LOCALES = Object.keys(CATALOGS)

/**
 * Resolve a dotted key in a nested catalog object.
 * @param {unknown} node
 * @param {string} path
 * @returns {string|undefined}
 */
function lookup(node, path) {
  const parts = path.split('.')
  let cur = node
  for (const part of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = cur[part]
  }
  return typeof cur === 'string' ? cur : undefined
}

/**
 * Interpolate `{name}` placeholders from params.
 * @param {string} template
 * @param {Record<string, string|number>|undefined} params
 */
function interpolate(template, params) {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (_, key) =>
    params[key] != null ? String(params[key]) : `{${key}}`
  )
}

/**
 * Translate a catalog key for the given locale.
 * Falls back to English, then to the key itself.
 * @param {string} locale
 * @param {string} key
 * @param {Record<string, string|number>} [params]
 */
export function t(locale, key, params) {
  const primary = CATALOGS[locale] || CATALOGS[DEFAULT_LOCALE]
  const raw =
    lookup(primary, key) ??
    lookup(CATALOGS[DEFAULT_LOCALE], key) ??
    key
  return interpolate(raw, params)
}

/**
 * Normalize an API/config locale to a catalog key.
 * @param {string|null|undefined} value
 */
export function normalizeLocale(value) {
  if (value && CATALOGS[value]) return value
  return DEFAULT_LOCALE
}
