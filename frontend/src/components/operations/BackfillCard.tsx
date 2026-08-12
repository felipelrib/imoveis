import { useState } from 'react'
import {
  ApiError, apiErrorDetail,
  type BackfillStartResult, type BackfillStatus, type EnrichmentCoverage,
} from '../../api.js'
import { useToast } from '../ToastProvider.jsx'
import { useLocale } from '../../i18n/LocaleContext.jsx'
import { etaLine, stateLabel, throughputLine } from './lines.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'
import type { BackfillFailure, UseBackfillResult } from '../../hooks/useBackfill.js'

export interface BackfillCardProps {
  backfill: UseBackfillResult
}

/**
 * Operações backfill card (UX-DR5). Text only: no bars, no spinners over content,
 * and every figure is omitted entirely when the control plane cannot supply it —
 * a missing ETA is an absent line, never a fabricated one.
 */
export default function BackfillCard({ backfill }: BackfillCardProps) {
  const { t, locale } = useLocale()
  const showToast = useToast()
  const [busy, setBusy] = useState(false)
  const { status, coverage, credentialed, statusError, start, pause, resume } = backfill

  const runAction = async <T,>(
    action: () => Promise<T>,
    onSuccess: (result: T) => void,
    { conflictKey }: { conflictKey?: string } = {},
  ) => {
    setBusy(true)
    try {
      onSuccess(await action())
    } catch (e) {
      const detail = apiErrorDetail(e)
      if (conflictKey && detail && e instanceof ApiError && e.status === 409) {
        // Non-blocking: the 409 detail names the run already holding the lease.
        showToast(t(conflictKey, { detail }), { type: 'warning' })
      } else {
        showToast(
          t('operations.toastActionFailed', { message: e instanceof Error ? e.message : String(e) }),
          { type: 'error' },
        )
      }
    } finally {
      setBusy(false)
    }
  }

  /**
   * A 202 from `/admin/backfill/start` says the *request was recorded*, not that
   * anything is going to run it: with no host-side `--serve` supervisor beating,
   * `runner_present` is false and the request sits until it expires. Toasting
   * "requested" there would rebuild exactly the button-that-does-nothing story
   * 1.5 added `runner_present` to prevent, so each outcome gets its own words.
   */
  const startToast = (result: BackfillStartResult) => {
    if (!result.runner_present) {
      showToast(t('operations.toastStartNoRunner'), { type: 'warning' })
    } else if (result.already_requested) {
      showToast(t('operations.toastStartAlreadyRequested'), { type: 'warning' })
    } else {
      showToast(t('operations.toastStartRequested'), { type: 'success' })
    }
  }

  return (
    <section className="meia ops-card" data-testid="backfill-card">
      <h2 className="ops-card-title">{t('operations.backfillTitle')}</h2>

      {!credentialed ? (
        <p className="ops-hint" data-testid="backfill-credential-hint">
          {t('operations.credentialHint')}
        </p>
      ) : (
        <BackfillBody
          status={status}
          statusError={statusError}
          coverage={coverage}
          busy={busy}
          t={t}
          locale={locale}
          onStart={() => runAction(start, startToast, {
            conflictKey: 'operations.toastStartConflict',
          })}
          onPause={() => runAction(pause, () => showToast(t('operations.toastPaused'), { type: 'success' }))}
          onResume={() => runAction(resume, () => showToast(t('operations.toastResumed'), { type: 'success' }))}
        />
      )}
    </section>
  )
}

interface BackfillBodyProps {
  status: BackfillStatus | null
  statusError: BackfillFailure | null
  coverage: EnrichmentCoverage | null
  busy: boolean
  t: TFunction
  locale: string
  onStart: () => void
  onPause: () => void
  onResume: () => void
}

function BackfillBody({
  status, statusError, coverage, busy, t, locale, onStart, onPause, onResume,
}: BackfillBodyProps) {
  // `active` (the lease) is the liveness signal — `state` only says what the run
  // is doing, and it decays on a TTL (DW-20), so a live run can read back `idle`.
  const active = Boolean(status?.active)
  const state = status?.state
  const progress = coverage?.backfill

  // Holding the lease is not the same as getting anywhere. `paused`,
  // `backing-off` (waiting out the provider's rate limit) and `blocked` all keep
  // the lease while nothing is enriched, and the server's throughput window is
  // clamped to the *lease*, not to the work — so it keeps quoting the rate
  // measured before the stop, and an ETA counted from it that no longer has
  // anything moving towards it. `idle` is deliberately not in this list: the
  // state key decays on a TTL under a slow row (DW-20) and a live run reads back
  // `idle` while it is very much enriching.
  const stalled = state === 'paused' || state === 'backing-off' || state === 'blocked'
  const advancing = active && !stalled

  const budget = status?.budget
  // Clamped: retries can push `consumed` past the daily limit, and a card that
  // reports "104% used" of a hard cap reads as a bug, not as an overrun.
  const budgetPct = active && budget && budget.limit > 0 && Number.isFinite(budget.consumed)
    ? Math.min(100, Math.max(0, Math.round((budget.consumed / budget.limit) * 100)))
    : null
  // A non-positive or non-finite rate is no rate at all — the API already sends
  // null there, and anything that slips through is dropped rather than rounded
  // down to a fabricated `~0 imóveis/dia`. The budget line above survives a stall
  // on purpose: today's consumed quota is a fact whatever the runner is doing.
  const throughputRaw = advancing ? progress?.throughput_per_day : null
  const throughput = throughputRaw != null && Number.isFinite(throughputRaw) && throughputRaw > 0
    ? throughputRaw
    : null
  const etaRaw = advancing ? progress?.eta_days : null
  const etaDays = etaRaw != null && Number.isFinite(etaRaw) && etaRaw >= 0 ? etaRaw : null

  // `pending_requests` reports *levels*, not transient requests: `pause` is
  // present for as long as the pause key is set, which is the entire duration of
  // the pause (`pending_control_requests` derives it from `control.is_paused()`).
  // So the level is what enables resume, while the "waiting for the runner"
  // line is only the window before the level has been applied — without that
  // split a run paused on Monday still reads "pausa solicitada" on Friday.
  const pending = status?.pending_requests ?? []
  const pauseLevel = pending.includes('pause')
  // `active` as well: the pause *level* lives for seven days, while the state key
  // expires in two minutes and the lease in fifteen. A runner that died while
  // paused therefore leaves `pause` set with no run and no `paused` word behind
  // it, and without this the card spends the rest of the week telling the
  // operator it is "waiting for the runner to apply it" — the same Monday-pause-
  // reads-Friday defect this split was introduced to fix, through the other door.
  const pausePending = pauseLevel && active && state !== 'paused'
  const stopPending = pending.includes('stop') && active
  const startPending = Boolean(status?.start_requested_at) && !active
  // A queued start with nothing listening is not "waiting for the runner to pick
  // it up" — nothing is going to. The click-time toast says so, but it is gone by
  // the next reload and the line would keep promising a pickup (UX-DR3).
  const startStranded = startPending && status?.runner_present === false

  // A start into a blocked control plane (or during a primary migration) is
  // refused after the click; the control says so up front instead.
  const migrationBlocked = Boolean(status?.migration_active)
  const startBlocked = state === 'blocked' || migrationBlocked

  // Straight off the wire: `heartbeat_active` *is* "rows are being enriched right
  // now", which is exactly what holds the `backfill:gemma:active` key that
  // migrate-primary.sh refuses on. Deriving it from `active && state !== 'paused'`
  // re-guessed it from two fields that disagree with it — a paused run whose
  // state key has decayed to `idle` (DW-20) is not beating, and would have raised
  // the warning anyway.
  const warn = Boolean(status?.heartbeat_active)

  return (
    <>
      {status && (
        <div className="ops-state" data-testid="backfill-state">
          {stateLabel(state, t)}
        </div>
      )}

      {/* A revoked credential or a Redis-side 500 is said out loud; the figures
          are gone with the read that produced them, never left frozen on screen. */}
      {statusError && (
        <div className="ops-fail" data-testid="backfill-error">
          {/* A rejected credential is the operator's own key, not a Redis outage;
              sending them at the control plane for it costs the wrong debugging
              session entirely. */}
          {t(statusError.kind === 'auth'
            ? 'operations.statusUnauthorized'
            : 'operations.statusUnavailable')}
        </div>
      )}

      {!status && !statusError && (
        <div className="ops-state" data-testid="backfill-state-pending">{t('common.ellipsis')}</div>
      )}

      {(budgetPct != null || throughput != null || etaDays != null) && (
        <div className="ops-lines" data-testid="backfill-lines">
          {budgetPct != null && (
            <div className="ops-line" data-testid="backfill-budget-line">
              {t('operations.budgetLine', { pct: budgetPct })}
            </div>
          )}
          {throughput != null && (
            <div className="ops-line" data-testid="backfill-throughput-line">
              {throughputLine(throughput, t, locale)}
            </div>
          )}
          {etaDays != null && (
            <div className="ops-line" data-testid="backfill-eta-line">
              {etaLine(etaDays, t, locale)}
            </div>
          )}
        </div>
      )}

      {(pausePending || stopPending || startPending || startBlocked) && (
        <div className="ops-pending" data-testid="backfill-pending">
          {pausePending && <div data-testid="backfill-pending-pause">{t('operations.pendingPause')}</div>}
          {stopPending && <div data-testid="backfill-pending-stop">{t('operations.pendingStop')}</div>}
          {startPending && (
            <div data-testid="backfill-pending-start">
              {t(startStranded ? 'operations.pendingStartNoRunner' : 'operations.pendingStart')}
            </div>
          )}
          {/* A disabled control with no stated reason reads as a broken button. */}
          {startBlocked && (
            <div data-testid="backfill-start-blocked">
              {t(migrationBlocked
                ? 'operations.startBlockedMigration'
                : 'operations.startBlockedPlane')}
            </div>
          )}
        </div>
      )}

      <div className="ops-actions">
        <button
          type="button"
          className="btn btn-sm btn-primary"
          data-testid="backfill-start"
          disabled={busy || !status || active || startBlocked || startPending}
          onClick={onStart}
        >
          {t('operations.start')}
        </button>
        <button
          type="button"
          // The lease, not the published state, says a run can be paused: under a
          // slow row the state key expires and decays to `idle` while the run is
          // very much alive (DW-20), and keying off `state === 'running'` locked
          // the operator out of pausing exactly then.
          className="btn btn-sm btn-ghost"
          data-testid="backfill-pause"
          disabled={busy || !active || pauseLevel || state === 'paused'}
          onClick={onPause}
        >
          {t('operations.pause')}
        </button>
        <button
          type="button"
          // Resume clears the pause level, so it is offered only when there is
          // one to clear *and* a run still holds the lease. A `paused` state word
          // outliving its runner (the state key survives the crash that dropped
          // the lease) would otherwise arm a button whose POST clears nothing and
          // still toasts "Backfill retomado". `backing-off` is not a pause at
          // all — it is the client waiting out the provider's rate limit, and
          // nothing about it is resumable.
          className="btn btn-sm btn-ghost"
          data-testid="backfill-resume"
          disabled={busy || !active || !(pauseLevel || state === 'paused')}
          onClick={onResume}
        >
          {t('operations.resume')}
        </button>
      </div>

      {warn && (
        <div className="ops-warn" data-testid="backfill-warning">
          <span className="glyph" aria-hidden="true">⚠</span>
          {t('operations.runningWarning')}
        </div>
      )}
    </>
  )
}
