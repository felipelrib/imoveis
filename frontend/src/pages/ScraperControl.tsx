import { useState, useEffect, useRef } from 'react'
import {
  fetchPlatforms, triggerScrape, pauseWorkers, resumeWorkers, fetchPipeline,
  fetchSchedule, updateSchedule, hasApiKey, triggerAvailabilityRecheck,
} from '../api.js'
import { useSystemStatus } from '../hooks/useSystemStatus.js'
import { useToast } from '../components/ToastProvider.jsx'
import { formatPlatform } from '../labels.js'
import { useLocale } from '../i18n/LocaleContext.jsx'
import { formatTime, formatDateTime } from '../i18n/format.js'
import type { DateLike } from '../i18n/format.js'

const SEEN_RUN_IDS_KEY = 'scraperLogSeenRunIds'
const SEEN_RUN_IDS_MAX = 200
/** Only surface recent runs on first load so Redis history does not flood the log. */
const SCRAPE_RUN_LOG_MAX_AGE_SEC = 3600

// ── Local "views" over loosely-typed (Record<string, unknown>) API responses. ──
interface ScraperStatusRow { status?: string; processed?: number; skipped?: number; errors?: number; proxy_host?: string }
interface AiMetrics { throughput_per_min?: number; avg_duration_sec?: number; total_recorded?: number }
interface ScrapeRun {
  run_id?: string
  platform?: string
  processed?: number
  skipped?: number
  errors?: number
  status?: string
  timestamp?: number | string
}
interface ProxyInfo { proxy_mode?: string; pool_size?: number; proxy_host?: string }
interface ScraperPipeline {
  queues: { scrapers: number; ai: number }
  scrapers_status: Record<string, ScraperStatusRow>
  ai_metrics?: AiMetrics
  recent_scrape_runs?: ScrapeRun[]
  proxy?: ProxyInfo
}
interface ScheduleRow {
  platform: string
  interval_minutes: number
  last_run?: DateLike
  next_run?: DateLike
}
interface PlatformRow { name: string; enabled?: boolean; rate_limit?: number }
interface LogEntry { type: string; text: string }
interface OllamaInfo { status?: string; models?: string[] }
interface ServiceInfo { status?: string }

const errMessage = (e: unknown): string => (e instanceof Error ? e.message : String(e))

function loadSeenRunIds(): Set<string> {
  try {
    const raw = localStorage.getItem(SEEN_RUN_IDS_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return new Set<string>(Array.isArray(parsed) ? parsed : [])
  } catch {
    return new Set<string>()
  }
}

function persistSeenRunIds(seen: Set<string>) {
  const ids = [...seen].slice(-SEEN_RUN_IDS_MAX)
  localStorage.setItem(SEEN_RUN_IDS_KEY, JSON.stringify(ids))
}

export default function ScraperControl() {
  const { t, locale } = useLocale()
  // Refs so the mount-only "poll pipeline status" effect below always reads the
  // *current* locale/t instead of the values captured at mount (BIN-154 — mirrors
  // the tRef/localeRef pattern in MapView.tsx). logScrapeRun (only ever invoked from
  // that effect's async poll callback, never during render) reads these directly
  // instead of calling `ts()`, so accessing `.current` here never happens at render
  // time (react-hooks/refs forbids reading ref.current during render).
  const tRef = useRef(t)
  const localeRef = useRef(locale)
  useEffect(() => { tRef.current = t }, [t])
  useEffect(() => { localeRef.current = locale }, [locale])
  const ts = () => formatTime(new Date(), locale)
  const { status, loading: statusLoading } = useSystemStatus(5000)
  const [platforms, setPlatforms] = useState<PlatformRow[]>([])
  const [selectedPlatform, setSelectedPlatform] = useState('')
  const [scrapeType, setScrapeType] = useState('both')
  const [scraping, setScraping] = useState(false)
  const [workerPaused, setWorkerPaused] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)
  const seenRunIdsRef = useRef<Set<string> | null>(null)
  const showToast = useToast()

  // Pipeline tracking state
  const [pipeline, setPipeline] = useState<ScraperPipeline>({
    queues: { scrapers: 0, ai: 0 },
    scrapers_status: {},
    ai_metrics: { throughput_per_min: 0, avg_duration_sec: 0, total_recorded: 0 },
    recent_scrape_runs: [],
  })

  // Schedule state
  const [schedules, setSchedules] = useState<ScheduleRow[]>([])
  const [editingPlatform, setEditingPlatform] = useState<string | null>(null)
  const [editInterval, setEditInterval] = useState('')
  const [savingSchedule, setSavingSchedule] = useState(false)
  const [scheduleAuthNeeded, setScheduleAuthNeeded] = useState(() => !hasApiKey())
  const scheduleAuthToastShown = useRef(false)
  const [recheckingAvailability, setRecheckingAvailability] = useState(false)

  // Logs state initialized from localStorage
  const [logs, setLogs] = useState<LogEntry[]>(() => {
    const saved = localStorage.getItem('scraperLogs')
    if (saved) {
      try { return JSON.parse(saved) } catch { /* ignore malformed localStorage payload */ }
    }
    return [{ type: 'info', text: t('scraper.logReady', { time: ts() }) }]
  })

  if (seenRunIdsRef.current === null) {
    seenRunIdsRef.current = loadSeenRunIds()
  }

  const addLog = (type: string, text: string) => setLogs(prev => [...prev.slice(-199), { type, text }])

  const rememberRunId = (runId: string): boolean => {
    const seen = seenRunIdsRef.current
    if (!seen || seen.has(runId)) return false
    seen.add(runId)
    persistSeenRunIds(seen)
    return true
  }

  const logScrapeRun = (run: ScrapeRun) => {
    const translate = tRef.current
    const platform = formatPlatform(run.platform || 'unknown')
    const processed = run.processed ?? 0
    const skipped = run.skipped ?? 0
    const errors = run.errors ?? 0
    const counts = translate('scraper.logCounts', { processed, skipped, errors })
    // Only ever called from the poll callback below (never during render), so
    // reading localeRef.current directly here (instead of the render-scoped
    // ts()) is safe and keeps the log line's timestamp locale-fresh (BIN-154).
    const time = formatTime(new Date(), localeRef.current)
    if (run.status === 'failed') {
      addLog('error', translate('scraper.logScrapeFailed', { time, platform, counts }))
    } else if (errors > 0) {
      addLog('warn', translate('scraper.logScrapeWarn', { time, platform, counts }))
    } else {
      addLog('success', translate('scraper.logScrapeOk', { time, platform, counts }))
    }
    setScraping(false)
  }

  // Poll pipeline status
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const p = await fetchPipeline() as unknown as ScraperPipeline
        if (cancelled) return
        setPipeline(p)
        const runs = Array.isArray(p?.recent_scrape_runs) ? p.recent_scrape_runs : []
        const nowSec = Date.now() / 1000
        // Newest-first from API; process oldest-first so log order matches wall clock.
        for (const run of [...runs].reverse()) {
          const runId = run?.run_id
          if (!runId) continue
          const isNew = rememberRunId(runId)
          if (!isNew) continue
          const age = nowSec - (Number(run.timestamp) || 0)
          if (age > SCRAPE_RUN_LOG_MAX_AGE_SEC) continue
          logScrapeRun(run)
        }
      } catch { /* ignore polling errors */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(id) }
    // logScrapeRun is a plain (unmemoized) function redefined every render — adding it here
    // would tear down/recreate this polling interval on every render instead of every 3s.
    // It reads locale/t via tRef/localeRef (BIN-154) so log lines stay correctly localized
    // across a mid-session locale switch without needing to restart this interval.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Poll schedule status — only when an API credential is present (admin-gated).
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      if (!hasApiKey()) {
        if (!cancelled) {
          setScheduleAuthNeeded(true)
          setSchedules([])
        }
        return
      }
      try {
        const s = await fetchSchedule() as { schedules?: ScheduleRow[] }
        if (cancelled) return
        setScheduleAuthNeeded(false)
        scheduleAuthToastShown.current = false
        if (s?.schedules) setSchedules(s.schedules)
      } catch (e) {
        if (cancelled) return
        setScheduleAuthNeeded(true)
        if (!scheduleAuthToastShown.current) {
          scheduleAuthToastShown.current = true
          showToast(
            errMessage(e) || t('scraper.toastAuthSchedule'),
            { type: 'error' },
          )
        }
      }
    }
    poll()
    const id = setInterval(poll, 15000)
    return () => { cancelled = true; clearInterval(id) }
  }, [showToast, t])

  // Save logs to localStorage on change (capped at 200)
  useEffect(() => {
    localStorage.setItem('scraperLogs', JSON.stringify(logs))
  }, [logs])

  useEffect(() => {
    fetchPlatforms().then(raw => {
      const rows = raw as unknown as PlatformRow[]
      setPlatforms(rows)
      if (rows.length > 0) setSelectedPlatform(rows[0].name)
    }).catch(() => {
      showToast(t('scraper.toastPlatformsFailed'), { type: 'error' })
    })
  }, [showToast, t])

  useEffect(() => {
    // Mirrors polled server status into local (optimistically-toggled) state — status
    // is owned by a separate hook (useSystemStatus), so this sync can't move to render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (status) setWorkerPaused(status.ai_workers_paused)
  }, [status])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const scrapeTypeLabel = (type: string) => {
    if (type === 'rent') return t('scraper.rentOnly')
    if (type === 'sale') return t('scraper.saleOnly')
    return t('scraper.bothRentSale')
  }

  const handleScrape = async () => {
    if (!selectedPlatform) return
    if (!hasApiKey()) {
      showToast(t('scraper.toastAuthScrape'), { type: 'error' })
      return
    }
    setScraping(true)
    addLog('info', t('scraper.logTrigger', { platform: formatPlatform(selectedPlatform), type: scrapeTypeLabel(scrapeType) }))
    try {
      await triggerScrape(selectedPlatform, {}, scrapeType)
      addLog('success', t('scraper.logEnqueued', { time: ts() }))
      showToast(t('scraper.toastEnqueued'), { type: 'success' })
    } catch (e) {
      addLog('error', t('scraper.logError', { time: ts(), message: errMessage(e) }))
      showToast(t('scraper.toastScrapeFailed'), { type: 'error' })
    } finally {
      setScraping(false)
    }
  }

  const handlePauseResume = async () => {
    try {
      if (workerPaused) {
        await resumeWorkers()
        setWorkerPaused(false)
        addLog('success', t('scraper.logResumed', { time: ts() }))
        showToast(t('scraper.toastWorkersResumed'), { type: 'success' })
      } else {
        await pauseWorkers()
        setWorkerPaused(true)
        addLog('warn', t('scraper.logPaused', { time: ts() }))
        showToast(t('scraper.toastWorkersPaused'), { type: 'warning' })
      }
    } catch (e) {
      addLog('error', t('scraper.logGenericError', { time: ts(), message: errMessage(e) }))
      showToast(t('scraper.toastWorkerToggleFailed'), { type: 'error' })
    }
  }

  const clearLogs = () => {
    const fresh: LogEntry[] = [{ type: 'info', text: t('scraper.logCleared', { time: ts() }) }]
    setLogs(fresh)
    localStorage.setItem('scraperLogs', JSON.stringify(fresh))
  }

  const handleSaveSchedule = async (platform: string) => {
    const minutes = parseInt(editInterval, 10)
    if (isNaN(minutes) || minutes < 0) return
    setSavingSchedule(true)
    try {
      await updateSchedule(platform, minutes)
      const interval = minutes === 0 ? t('scraper.manualOnly') : t('scraper.intervalMin', { n: minutes })
      addLog('success', t('scraper.logScheduleUpdated', { time: ts(), platform: formatPlatform(platform), interval }))
      showToast(t('scraper.toastScheduleUpdated'), { type: 'success' })
      setEditingPlatform(null)
      setEditInterval('')
      // Refresh schedules
      if (hasApiKey()) {
        const s = await fetchSchedule() as { schedules?: ScheduleRow[] }
        if (s?.schedules) setSchedules(s.schedules)
        setScheduleAuthNeeded(false)
      }
    } catch (e) {
      addLog('error', t('scraper.logGenericError', { time: ts(), message: errMessage(e) }))
      showToast(t('scraper.toastScheduleFailed'), { type: 'error' })
    } finally {
      setSavingSchedule(false)
    }
  }

  const handleAvailabilityRecheck = async () => {
    if (!hasApiKey()) {
      showToast(t('scraper.toastAuthRecheck'), { type: 'error' })
      return
    }
    setRecheckingAvailability(true)
    try {
      const r = await triggerAvailabilityRecheck() as { batch_size?: number | string; task_id?: string }
      addLog(
        'success',
        t('scraper.logRecheckEnqueued', {
          time: ts(),
          batch: r.batch_size ?? t('common.emDash'),
          taskId: r.task_id ?? t('common.emDash'),
        }),
      )
      showToast(t('scraper.toastRecheckEnqueued'), { type: 'success' })
    } catch (e) {
      addLog('error', t('scraper.logGenericError', { time: ts(), message: errMessage(e) }))
      showToast(t('scraper.toastRecheckFailed'), { type: 'error' })
    } finally {
      setRecheckingAvailability(false)
    }
  }

  const formatTs = (value: DateLike) => {
    if (!value) return t('common.emDash')
    return formatDateTime(value, locale)
  }

  const ollama = status?.ollama as OllamaInfo | undefined
  const database = status?.database as ServiceInfo | undefined
  const aiOk = ollama?.status === 'ok'
  const dbOk = database?.status === 'ok'
  const proxy = pipeline.proxy

  const activeScrapers = Object.entries(pipeline.scrapers_status).filter(([, s]) => s.status === 'running')

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">{t('scraper.title')}</h1>
        <p className="page-subtitle">{t('scraper.subtitle')}</p>
      </div>

      <div className="control-panel">
        {/* ── Left: Launch controls ── */}
        <div className="card">
          <div className="panel-section-title">{t('scraper.ingestionPipeline')}</div>

          {!dbOk && !statusLoading && (
            <div style={{ padding: '10px 14px', borderRadius: 8, background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.25)', fontSize: 13, color: '#fda4af', marginBottom: 16 }}>
              {t('scraper.dbOffline', { cmd: '.\\start.ps1' })}
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label className="form-label">{t('common.platform')}</label>
              <select
                className="form-select"
                value={selectedPlatform}
                onChange={e => setSelectedPlatform(e.target.value)}
                data-testid="scraper-platform-select"
              >
                {platforms.length === 0
                  ? <option value="">{t('scraper.loadingPlatforms')}</option>
                  : platforms.map(p => (
                      <option key={p.name} value={p.name} disabled={!p.enabled}>
                        {formatPlatform(p.name)}{!p.enabled ? ` ${t('scraper.platformDisabled')}` : ''}{p.rate_limit ? ` ${t('scraper.platformRateLimit', { n: p.rate_limit })}` : ''}
                      </option>
                    ))
                }
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">{t('scraper.scrapeType')}</label>
              <select className="form-select" value={scrapeType} onChange={e => setScrapeType(e.target.value)}>
                <option value="both">{t('scraper.bothRentSale')}</option>
                <option value="rent">{t('scraper.rentOnly')}</option>
                <option value="sale">{t('scraper.saleOnly')}</option>
              </select>
            </div>

            <button
              className="btn btn-primary"
              onClick={handleScrape}
              disabled={scraping || !selectedPlatform || (!dbOk && !statusLoading)}
              style={{ width: '100%', justifyContent: 'center', padding: '12px' }}
            >
              {scraping ? <><span className="spinner" /> {t('scraper.enqueuing')}</> : t('scraper.runScraper')}
            </button>

            {/* Live Pipeline Status */}
            <div style={{ marginTop: 12, padding: 12, background: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{t('scraper.livePipeline')}</div>

              {proxy && (
                <div
                  data-testid="scraper-proxy-line"
                  style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 10 }}
                >
                  {proxy.proxy_mode === 'pool'
                    ? t('scraper.proxyModeLinePool', {
                        mode: proxy.proxy_mode,
                        n: proxy.pool_size ?? 0,
                      })
                    : t('scraper.proxyModeLine', { mode: proxy.proxy_mode || 'direct' })}
                  {(() => {
                    const runningHost = activeScrapers
                      .map(([, s]) => s.proxy_host)
                      .find((h) => h)
                    const host = runningHost || proxy.proxy_host
                    return host ? t('scraper.proxyHostLine', { host }) : null
                  })()}
                </div>
              )}

              <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                <div style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-card)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('scraper.scraperQueue')}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: pipeline.queues.scrapers > 0 ? 'var(--accent-amber)' : 'var(--text-primary)' }}>{pipeline.queues.scrapers}</span>
                </div>
                <div style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-card)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t('scraper.aiQueue')}</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: pipeline.queues.ai > 0 ? 'var(--accent-cyan)' : 'var(--text-primary)' }}>{pipeline.queues.ai}</span>
                </div>
              </div>

              {activeScrapers.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                  {activeScrapers.map(([plat, s]) => (
                    <div key={plat} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{formatPlatform(plat)}</span>
                      <span style={{ color: 'var(--text-muted)' }}>{t('scraper.activeProgress', { processed: s.processed, skipped: s.skipped, errors: s.errors })}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 12 }}>{t('scraper.noActiveScrapers')}</div>
              )}

              <div style={{ paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>{t('scraper.aiPerformance')}</div>
                <div style={{ display: 'flex', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t('scraper.throughput')}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-emerald)' }}>
                      {pipeline.ai_metrics?.throughput_per_min ?? 0} <span style={{ fontSize: 11, fontWeight: 400 }}>{t('scraper.propsPerMin')}</span>
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t('scraper.avgSpeed')}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {pipeline.ai_metrics?.avg_duration_sec ?? 0} <span style={{ fontSize: 11, fontWeight: 400 }}>{t('scraper.secPerProp')}</span>
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t('scraper.recorded')}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {pipeline.ai_metrics?.total_recorded ?? 0}
                    </div>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>

        {/* ── Right: Worker controls ── */}
        <div className="card">
          <div className="panel-section-title">{t('scraper.workerManagement')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

            {/* AI worker pause */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{t('scraper.aiEnrichmentWorkers')}</div>
                <div style={{ fontSize: 12, color: workerPaused ? 'var(--accent-amber)' : 'var(--accent-emerald)', marginTop: 3 }}>
                  {workerPaused ? `⏸ ${t('scraper.paused')}` : `▶ ${t('scraper.running')}`}
                </div>
              </div>
              <button
                className={`btn btn-sm ${workerPaused ? 'btn-success' : 'btn-ghost'}`}
                onClick={handlePauseResume}
              >
                {workerPaused ? `▶ ${t('scraper.resume')}` : `⏸ ${t('scraper.pause')}`}
              </button>
            </div>

            {/* Ollama status */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{t('scraper.ollamaServer')}</div>
                <div style={{ fontSize: 12, color: statusLoading ? 'var(--text-muted)' : aiOk ? 'var(--accent-emerald)' : 'var(--accent-rose)', marginTop: 3 }}>
                  {statusLoading
                    ? `⏳ ${t('scraper.checkingStatus')}`
                    : aiOk
                      ? t('scraper.onlineModels', { models: (ollama?.models || []).join(', ') || t('scraper.noModels') })
                      : `✖ ${t('scraper.offline')}`}
                </div>
              </div>
              {!aiOk && !statusLoading && (
                <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="btn btn-sm btn-ghost">
                  {t('scraper.install')}
                </a>
              )}
            </div>

            {/* Listing availability recheck (BIN-123) */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '14px 16px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{t('scraper.availabilityRecheck')}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3, lineHeight: 1.45 }}>
                  {t('scraper.availabilityRecheckHelp')}
                </div>
              </div>
              <button
                className="btn btn-sm btn-ghost"
                onClick={handleAvailabilityRecheck}
                disabled={recheckingAvailability}
                data-testid="availability-recheck"
              >
                {recheckingAvailability
                  ? <><span className="spinner" /> {t('scraper.availabilityRecheckBusy')}</>
                  : t('scraper.availabilityRecheckRun')}
              </button>
            </div>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6, padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
              💡 <strong style={{ color: 'var(--text-secondary)' }}>{t('scraper.tipTitle')}:</strong> {t('scraper.tipBody')}
            </div>
          </div>
        </div>
      </div>

      {/* ── Scheduled Runs ── */}
      <div className="card">
        <div className="panel-section-title">{t('scraper.scheduledRuns')}</div>
        {scheduleAuthNeeded ? (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            {t('scraper.pasteCredential')}
          </div>
        ) : schedules.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            {t('scraper.noSchedules')}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {schedules.map(s => (
              <div key={s.platform} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
                <div style={{ minWidth: 100 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{formatPlatform(s.platform)}</div>
                </div>
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>{t('scraper.interval')}</span>
                    {editingPlatform === s.platform ? (
                      <input
                        type="text"
                        inputMode="numeric"
                        pattern="[0-9]*"
                        data-testid="schedule-interval-input"
                        value={editInterval}
                        onChange={e => setEditInterval(e.target.value.replace(/[^\d]/g, ''))}
                        style={{ width: 56, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border-subtle)', background: 'var(--bg-app)', color: 'var(--text-primary)', fontSize: 12 }}
                      />
                    ) : (
                      <span style={{ fontWeight: 600, color: s.interval_minutes > 0 ? 'var(--accent-emerald)' : 'var(--text-muted)' }}>
                        {s.interval_minutes > 0 ? t('scraper.intervalMin', { n: s.interval_minutes }) : t('scraper.manual')}
                      </span>
                    )}
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>{t('scraper.last')}</span>
                    <span style={{ color: 'var(--text-secondary)' }}>{formatTs(s.last_run)}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>{t('scraper.next')}</span>
                    <span style={{ color: 'var(--accent-cyan)' }}>{formatTs(s.next_run)}</span>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {editingPlatform === s.platform ? (
                    <>
                      <button
                        className="btn btn-sm btn-success"
                        onClick={() => handleSaveSchedule(s.platform)}
                        disabled={savingSchedule}
                      >
                        {savingSchedule ? t('common.saving') : t('common.save')}
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => { setEditingPlatform(null); setEditInterval('') }}
                      >
                        {t('common.cancel')}
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => { setEditingPlatform(s.platform); setEditInterval(String(s.interval_minutes)) }}
                    >
                      {t('common.edit')}
                    </button>
                  )}
                </div>
              </div>
            ))}
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '0 4px' }}>
              💡 {t('scraper.scheduleTip')}
            </div>
          </div>
        )}
      </div>

      {/* Activity log */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="panel-section-title" style={{ marginBottom: 0 }}>{t('scraper.activityLog')}</div>
          <button className="btn btn-sm btn-ghost" onClick={clearLogs}>{t('scraper.clearLogs')}</button>
        </div>
        <div className="activity-log" ref={logRef}>
          {logs.map((l, i) => (
            <div key={i} className={`log-entry ${l.type}`}>{l.text}</div>
          ))}
        </div>
      </div>
    </div>
  )
}
