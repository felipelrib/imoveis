/**
 * The Operações text lines and label lookups, kept out of the components so they
 * can be asserted directly (v0.13-s1.6 review pass 2) and shared with the Painel
 * health strip (pass 3). Every branch here exists because the naive rendering
 * states something the data does not support, so each one is a regression lock,
 * not a formatting preference.
 */
import { formatDateTime, formatNumber } from '../../i18n/format.js'
import type { BackfillLastRun, BackfillState, SignalCoverage } from '../../api.js'
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

/**
 * Outcomes of a supervised run that ended the way someone asked for, or that
 * need nothing done. Every other *known* outcome needs the operator and is
 * rendered as a failure line. An unknown word is neither: it is shown verbatim
 * and plainly, because nothing here knows what it means.
 */
const LAST_RUN_QUIET = new Set([
  'complete', 'complete_with_quarantine', 'stopped', 'lease_held',
])

/** Wire outcome (English) → label; an unknown word is rendered verbatim. */
export function lastRunOutcomeLabel(outcome: string, t: TFunction): string {
  const key = `operations.lastRun.${outcome}`
  const label = t(key)
  return label === key ? outcome : label
}

export function lastRunNeedsOperator(outcome: string, t: TFunction): boolean {
  const known = t(`operations.lastRun.${outcome}`) !== `operations.lastRun.${outcome}`
  return known && !LAST_RUN_QUIET.has(outcome)
}

/**
 * Is this `hung` record about the run that holds the lease right now?
 *
 * `hung` is the one ending shown while a run is active, because it is written
 * about a run whose dead lease has not lapsed yet. The record outlives that
 * run (30 days), and a run started by hand writes no record of its own, so
 * without this check an old `hung` is painted over a later, healthy run. The
 * watchdog stamps `finished_at` when it gives a run up, which is after that
 * run took its lease and before any later run took one. When either time is
 * missing or unreadable the line is shown: saying `hung` once too often is the
 * cheaper mistake.
 */
export function hungRunHoldsTheLease(
  lastRun: BackfillLastRun | null | undefined,
  leaseAcquiredAt: string | null | undefined,
): boolean {
  if (lastRun?.outcome !== 'hung') return false
  const gaveUp = Date.parse(lastRun.finished_at ?? '')
  const acquired = Date.parse(leaseAcquiredAt ?? '')
  if (Number.isNaN(gaveUp) || Number.isNaN(acquired)) return true
  return gaveUp >= acquired
}

/**
 * "última execução: <outcome> · <when>". The time is when the run ended, or when
 * it started for an outcome that has no end (`interrupted`); with neither, the
 * line has no time rather than a dash standing in for one.
 */
export function lastRunLine(lastRun: BackfillLastRun, t: TFunction, locale: string): string {
  const outcome = lastRunOutcomeLabel(lastRun.outcome, t)
  const stamp = lastRun.finished_at ?? lastRun.started_at
  const when = stamp ? formatDateTime(stamp, locale) : null
  return when && when !== '—'
    ? t('operations.lastRunLine', { outcome, when })
    : t('operations.lastRunLineNoTime', { outcome })
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
