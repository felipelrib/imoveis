import { useState, useEffect, useCallback, useRef } from 'react'
import {
  ApiError,
  fetchBackfillStatus, fetchEnrichmentCoverage,
  startBackfill, pauseBackfill, resumeBackfill,
  hasApiKey,
  type BackfillStatus, type BackfillStartResult, type BackfillControlResult,
  type EnrichmentCoverage,
} from '../api.js'

/**
 * Poll cadence. The control plane (`/admin/backfill/status`) is cheap and reads
 * Redis, so it polls at `intervalMs` (10s). Coverage is a DB aggregate over the
 * whole `properties` table and moves on a multi-day scale, so it is refreshed
 * every `COVERAGE_EVERY_N_TICKS`-th status tick (~60s) off the *same* interval —
 * one timer, no second scheduler to cancel. Both are refreshed immediately after
 * a mutation, where staleness is actually visible to the operator.
 */
const COVERAGE_EVERY_N_TICKS = 6

/**
 * Why a poll failed. `hasApiKey()` only says a credential is *stored* — a revoked
 * or mistyped one is indistinguishable from it, and reporting that as "the
 * control plane could not be read" sends the operator at Redis for a problem
 * living in their own sessionStorage.
 */
export interface BackfillFailure {
  kind: 'auth' | 'unreachable'
  message: string
}

export interface UseBackfillResult {
  status: BackfillStatus | null
  coverage: EnrichmentCoverage | null
  /**
   * No `loading` or aggregate `error` here on purpose. The cards distinguish the
   * two sources (a Redis-side status failure must not blank the DB-derived
   * coverage), and a `loading` flag that only ever went `true` once — as the
   * first version of this hook's did — is worse than none: a consumer reading it
   * would report "loaded" through every later failure.
   */
  /** `/admin/backfill/status` failed (Redis down, credential revoked); `status` is null. */
  statusError: BackfillFailure | null
  /** `/admin/enrichment/coverage` failed; `coverage` is null. Independent of the above. */
  coverageError: BackfillFailure | null
  /** False when no API credential is stored — nothing is ever requested then. */
  credentialed: boolean
  /** Rejects with an `ApiError` (409 when a run holds the lease) — callers toast it. */
  start: () => Promise<BackfillStartResult>
  pause: () => Promise<BackfillControlResult>
  resume: () => Promise<BackfillControlResult>
}

/**
 * Credential-gated poller for the backfill control plane + enrichment coverage
 * (v0.13-s1.6). Modelled on `useSystemStatus`: cancelled flag, one interval,
 * cleanup on unmount. Without a stored credential it fires no `/admin/*` request
 * at all (the routes are auth-gated; polling them would only spam 403s), and it
 * re-checks on every tick so a credential pasted mid-session starts the polling
 * without a remount.
 */
function toFailure(e: unknown): BackfillFailure {
  const message = e instanceof Error ? e.message : String(e)
  const auth = e instanceof ApiError && (e.status === 401 || e.status === 403)
  return { kind: auth ? 'auth' : 'unreachable', message }
}

export function useBackfill(intervalMs = 10000): UseBackfillResult {
  const [status, setStatus] = useState<BackfillStatus | null>(null)
  const [coverage, setCoverage] = useState<EnrichmentCoverage | null>(null)
  const [statusError, setStatusError] = useState<BackfillFailure | null>(null)
  const [coverageError, setCoverageError] = useState<BackfillFailure | null>(null)
  const [credentialed, setCredentialed] = useState<boolean>(() => hasApiKey())
  const cancelledRef = useRef(false)
  // Generation guard: a mutation-triggered refresh and an interval tick overlap
  // routinely (the mutation POST and the next tick are milliseconds apart), and
  // without this the *older* response can land last and repaint the card with
  // pre-action state. Only the newest load in flight is allowed to write.
  const generationRef = useRef(0)

  const load = useCallback(async (withCoverage: boolean) => {
    if (!hasApiKey()) {
      if (!cancelledRef.current) {
        generationRef.current += 1  // strand any response still in flight
        setCredentialed(false)
        setStatus(null)
        setCoverage(null)
        setStatusError(null)
        setCoverageError(null)
      }
      return
    }
    if (!cancelledRef.current) setCredentialed(true)

    const generation = ++generationRef.current
    // Independent on purpose: coverage is DB-derived and answers a different
    // question than the Redis-backed control state, so a 500 on the status route
    // must not blank the coverage card (and vice versa).
    const [statusResult, coverageResult] = await Promise.allSettled([
      fetchBackfillStatus(),
      withCoverage ? fetchEnrichmentCoverage() : Promise.resolve(null),
    ])
    if (cancelledRef.current || generation !== generationRef.current) return

    if (statusResult.status === 'fulfilled') {
      setStatus(statusResult.value)
      setStatusError(null)
    } else {
      // The last good read is dropped rather than kept: a frozen state line with
      // no failure signal is the one dishonesty this card cannot afford.
      setStatus(null)
      setStatusError(toFailure(statusResult.reason))
    }

    if (withCoverage) {
      if (coverageResult.status === 'fulfilled') {
        setCoverage(coverageResult.value)
        setCoverageError(null)
      } else {
        setCoverage(null)
        setCoverageError(toFailure(coverageResult.reason))
      }
    }
  }, [])

  useEffect(() => {
    cancelledRef.current = false
    let tick = 0
    // The first poll is queued rather than called inline so the effect body never
    // updates state synchronously (react-hooks/set-state-in-effect); every later
    // poll already arrives from the interval callback.
    queueMicrotask(() => { if (!cancelledRef.current) load(true) })
    const id = setInterval(() => {
      tick += 1
      load(tick % COVERAGE_EVERY_N_TICKS === 0)
    }, intervalMs)
    return () => { cancelledRef.current = true; clearInterval(id) }
  }, [intervalMs, load])

  const start = useCallback(async () => {
    try {
      return await startBackfill()
    } finally {
      // Refresh even when the request was refused: a 409 means someone else's run
      // is live, and the card should show that run rather than the stale read.
      await load(true)
    }
  }, [load])

  const pause = useCallback(async () => {
    try {
      return await pauseBackfill()
    } finally {
      await load(true)
    }
  }, [load])

  const resume = useCallback(async () => {
    try {
      return await resumeBackfill()
    } finally {
      await load(true)
    }
  }, [load])

  return {
    status,
    coverage,
    statusError,
    coverageError,
    credentialed,
    start,
    pause,
    resume,
  }
}
