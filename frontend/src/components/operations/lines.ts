/**
 * The Operações text lines and label lookups, kept out of the components so they
 * can be asserted directly (v0.13-s1.6 review pass 2) and shared with the Painel
 * health strip (pass 3). Every branch here exists because the naive rendering
 * states something the data does not support, so each one is a regression lock,
 * not a formatting preference.
 */
import { formatNumber } from '../../i18n/format.js'
import type { BackfillState, SignalCoverage } from '../../api.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'

/** Wire enum (English) → catalog key. The vocabulary never changes; only the label. */
const STATE_KEYS: Record<BackfillState, string> = {
  idle: 'operations.stateIdle',
  running: 'operations.stateRunning',
  paused: 'operations.statePaused',
  'backing-off': 'operations.stateBackingOff',
  blocked: 'operations.stateBlocked',
}

export function stateLabel(state: string | undefined, t: TFunction): string {
  const key = STATE_KEYS[state as BackfillState]
  // An unknown state word is rendered verbatim rather than mapped to a wrong
  // pt-BR label — honest over pretty (UX-DR3).
  return key ? t(key) : String(state ?? '')
}

export function signalLabel(taskClass: string, t: TFunction): string {
  const key = `operations.signal.${taskClass}`
  const label = t(key)
  // A signal class with no catalog entry renders under its wire name rather than
  // being hidden — a measured signal is never dropped from the list.
  return label === key ? taskClass : label
}

/**
 * The signal the `minimum_fraction` actually came from, or null when no signal
 * has a measurable one. The Painel chip quotes that minimum, and "the lowest
 * coverage" is only checkable if it says which signal is lowest — routinely one
 * the backfill's own scope cannot move (`embedding` is never cloud-eligible), so
 * an unnamed minimum reads as a verdict on the run the chip sits next to.
 */
export function lowestSignal(signals: SignalCoverage[] | undefined): SignalCoverage | null {
  let lowest: SignalCoverage | null = null
  for (const s of signals ?? []) {
    if (s.fraction == null) continue
    if (lowest == null || s.fraction < (lowest.fraction as number)) lowest = s
  }
  return lowest
}

/**
 * The catalogs carry one plural form per key, so the singular cases get their own
 * keys rather than a `~1 dias` / `~1 days` agreement bug. A rate under one row a
 * day is stated as such instead of rounding to the zero the story forbids.
 */
export function throughputLine(throughput: number, t: TFunction, locale: string): string {
  const rounded = Math.round(throughput)
  if (rounded < 1) return t('operations.throughputBelowOne')
  if (rounded === 1) return t('operations.throughputOne')
  return t('operations.throughputLine', { n: formatNumber(rounded, locale) })
}

/**
 * Anything inside `[1.0, 1.5)` rounds to 1, and `ETA: ~1 dias` is the plural bug;
 * anything under a day is said as "under a day" rather than rounded to zero.
 */
export function etaLine(etaDays: number, t: TFunction, locale: string): string {
  if (etaDays < 1) return t('operations.etaUnderOneDay')
  const rounded = Math.round(etaDays)
  if (rounded === 1) return t('operations.etaOneDay')
  return t('operations.etaLine', { n: formatNumber(rounded, locale) })
}
