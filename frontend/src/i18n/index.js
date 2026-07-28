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

/**
 * Humanize an unknown snake_case code for display fallback.
 * @param {string} code
 */
function humanizeCode(code) {
  return String(code)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Normalize legacy EN titles or codes to snake_case catalog keys.
 * @param {string|null|undefined} raw
 * @param {Record<string, string>} aliases
 */
function toCode(raw, aliases) {
  if (raw == null || raw === '') return null
  const key = String(raw).trim().toLowerCase().replace(/-/g, '_')
  if (aliases[key]) return aliases[key]
  const spaced = key.replace(/_/g, ' ')
  if (aliases[spaced]) return aliases[spaced]
  return key.includes('_') ? key : spaced.replace(/ /g, '_')
}

const STAT_ALIASES = {
  'highly undervalued': 'highly_undervalued',
  'slightly undervalued': 'slightly_undervalued',
  average: 'average',
  'slightly overvalued': 'slightly_overvalued',
  'highly overvalued': 'highly_overvalued',
  highly_undervalued: 'highly_undervalued',
  slightly_undervalued: 'slightly_undervalued',
  slightly_overvalued: 'slightly_overvalued',
  highly_overvalued: 'highly_overvalued',
}

const VISUAL_ALIASES = {
  pristine: 'pristine',
  good: 'good',
  average: 'average',
  'needs renovation': 'needs_renovation',
  needs_renovation: 'needs_renovation',
  poor: 'poor',
}

const SENTIMENT_ALIASES = {
  'highly desirable': 'highly_desirable',
  highly_desirable: 'highly_desirable',
  good: 'good',
  average: 'average',
  undesirable: 'undesirable',
  poor: 'poor',
  standard: 'average',
}

/**
 * @param {string} locale
 * @param {string|null|undefined} codeOrLabel
 */
export function labelStatBand(locale, codeOrLabel) {
  const code = toCode(codeOrLabel, STAT_ALIASES)
  if (!code) return ''
  const labeled = t(locale, `ai.statBand.${code}.label`)
  if (labeled !== `ai.statBand.${code}.label`) return labeled
  return humanizeCode(code)
}

/**
 * @param {string} locale
 * @param {string|null|undefined} codeOrLabel
 * @param {string|null|undefined} [storedReasoning]
 */
export function reasoningStatBand(locale, codeOrLabel, storedReasoning) {
  const code = toCode(codeOrLabel, STAT_ALIASES)
  if (code) {
    const fromCatalog = t(locale, `ai.statBand.${code}.reasoning`)
    if (fromCatalog !== `ai.statBand.${code}.reasoning`) return fromCatalog
  }
  return storedReasoning || ''
}

/**
 * @param {string} locale
 * @param {string|null|undefined} codeOrLabel
 */
export function labelVisualCategory(locale, codeOrLabel) {
  const code = toCode(codeOrLabel, VISUAL_ALIASES)
  if (!code) return ''
  const labeled = t(locale, `ai.visualCategory.${code}`)
  if (labeled !== `ai.visualCategory.${code}`) return labeled
  return humanizeCode(code)
}

/**
 * @param {string} locale
 * @param {string|null|undefined} codeOrLabel
 */
export function labelSentimentCategory(locale, codeOrLabel) {
  const code = toCode(codeOrLabel, SENTIMENT_ALIASES)
  if (!code) return ''
  const labeled = t(locale, `ai.sentimentCategory.${code}`)
  if (labeled !== `ai.sentimentCategory.${code}`) return labeled
  return humanizeCode(code)
}

/**
 * @param {string} locale
 * @param {string|null|undefined} code
 */
export function labelRiskFlag(locale, code) {
  if (code == null || code === '') return ''
  const key = String(code).trim()
  const labeled = t(locale, `ai.riskFlags.${key}`)
  if (labeled !== `ai.riskFlags.${key}`) return labeled
  return humanizeCode(key)
}
