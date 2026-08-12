/**
 * Lightweight message catalogs (BIN-98).
 * Add a locale by dropping a JSON file here and registering it in CATALOGS.
 */
import en from './locales/en.json'
import ptBR from './locales/pt-BR.json'
import { DEFAULT_LOCALE } from './defaultLocale.js'

export { DEFAULT_LOCALE }

/** A catalog node: either a leaf string or a nested subtree of more nodes. */
export type MessageNode = string | { [key: string]: MessageNode }

/** A full message catalog for one locale (dotted keys resolved via `lookup`). */
export type Catalog = Record<string, MessageNode>

/**
 * `{placeholder}` interpolation params passed to `t()`. Values may be null/undefined —
 * `interpolate` renders those as the literal `{key}` placeholder (unchanged runtime
 * behaviour), so callers can forward optional fields without pre-coercing them.
 */
export type TranslateParams = Record<string, string | number | null | undefined>

export const CATALOGS: Record<string, Catalog> = {
  en,
  'pt-BR': ptBR,
}

export const SUPPORTED_LOCALES: string[] = Object.keys(CATALOGS)

/**
 * Catalog key for a locale switcher option label (`en` → `locale.en`,
 * `pt-BR` → `locale.ptBR`). Prefer this over hardcoded `code === …` branches.
 * @param code BCP-47 tag from the preference allowlist
 */
export function localeLabelKey(code: string): string {
  const camel = String(code).replace(/-([A-Za-z]+)/g, (_, part: string) => part)
  return `locale.${camel}`
}

/** Resolve a dotted key in a nested catalog object. */
function lookup(node: MessageNode | undefined, path: string): string | undefined {
  const parts = path.split('.')
  let cur: MessageNode | undefined = node
  for (const part of parts) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = cur[part]
  }
  return typeof cur === 'string' ? cur : undefined
}

/** Interpolate `{name}` placeholders from params. */
function interpolate(template: string, params?: TranslateParams): string {
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    params[key] != null ? String(params[key]) : `{${key}}`
  )
}

/**
 * Translate a catalog key for the given locale.
 * Falls back to English, then to the key itself.
 *
 * The fallback catalog is pinned to `en` rather than to `DEFAULT_LOCALE`: the
 * product default is now pt-BR (v0.13-s1.6), and following it here would render
 * Portuguese inside an English session for any key added to one catalog only —
 * a missing translation that reads as a translation. English in a pt-BR session
 * is the visible failure the "both catalogs, always" rule wants.
 */
export function t(locale: string, key: string, params?: TranslateParams): string {
  const primary = CATALOGS[locale] || CATALOGS[DEFAULT_LOCALE]
  const raw =
    lookup(primary, key) ??
    lookup(CATALOGS.en, key) ??
    key
  return interpolate(raw, params)
}

/** Normalize an API/config locale to a catalog key. */
export function normalizeLocale(value: string | null | undefined): string {
  if (value && CATALOGS[value]) return value
  return DEFAULT_LOCALE
}

/** Humanize an unknown snake_case code for display fallback. */
function humanizeCode(code: string): string {
  return String(code)
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Normalize legacy EN titles or codes to snake_case catalog keys. */
function toCode(
  raw: string | null | undefined,
  aliases: Record<string, string>,
): string | null {
  if (raw == null || raw === '') return null
  const key = String(raw).trim().toLowerCase().replace(/-/g, '_')
  if (aliases[key]) return aliases[key]
  const spaced = key.replace(/_/g, ' ')
  if (aliases[spaced]) return aliases[spaced]
  return key.includes('_') ? key : spaced.replace(/ /g, '_')
}

const STAT_ALIASES: Record<string, string> = {
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

const VISUAL_ALIASES: Record<string, string> = {
  pristine: 'pristine',
  good: 'good',
  average: 'average',
  'needs renovation': 'needs_renovation',
  needs_renovation: 'needs_renovation',
  poor: 'poor',
}

const SENTIMENT_ALIASES: Record<string, string> = {
  'highly desirable': 'highly_desirable',
  highly_desirable: 'highly_desirable',
  good: 'good',
  average: 'average',
  undesirable: 'undesirable',
  poor: 'poor',
  standard: 'average',
}

export function labelStatBand(locale: string, codeOrLabel: string | null | undefined): string {
  const code = toCode(codeOrLabel, STAT_ALIASES)
  if (!code) return ''
  const labeled = t(locale, `ai.statBand.${code}.label`)
  if (labeled !== `ai.statBand.${code}.label`) return labeled
  return humanizeCode(code)
}

export function reasoningStatBand(
  locale: string,
  codeOrLabel: string | null | undefined,
  storedReasoning?: string | null,
): string {
  const code = toCode(codeOrLabel, STAT_ALIASES)
  if (code) {
    const fromCatalog = t(locale, `ai.statBand.${code}.reasoning`)
    if (fromCatalog !== `ai.statBand.${code}.reasoning`) return fromCatalog
  }
  return storedReasoning || ''
}

export function labelVisualCategory(locale: string, codeOrLabel: string | null | undefined): string {
  const code = toCode(codeOrLabel, VISUAL_ALIASES)
  if (!code) return ''
  const labeled = t(locale, `ai.visualCategory.${code}`)
  if (labeled !== `ai.visualCategory.${code}`) return labeled
  return humanizeCode(code)
}

export function labelSentimentCategory(
  locale: string,
  codeOrLabel: string | null | undefined,
): string {
  const code = toCode(codeOrLabel, SENTIMENT_ALIASES)
  if (!code) return ''
  const labeled = t(locale, `ai.sentimentCategory.${code}`)
  if (labeled !== `ai.sentimentCategory.${code}`) return labeled
  return humanizeCode(code)
}

export function labelRiskFlag(locale: string, code: string | null | undefined): string {
  if (code == null || code === '') return ''
  const key = String(code).trim()
  const labeled = t(locale, `ai.riskFlags.${key}`)
  if (labeled !== `ai.riskFlags.${key}`) return labeled
  return humanizeCode(key)
}
