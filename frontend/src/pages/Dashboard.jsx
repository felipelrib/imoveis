import { useAlerts } from '../hooks/useAlerts.js'
import { ensureOllama, recalculateScores, enrichMissing, enrichmentRerun, fetchPipeline, fetchPipelineHistory } from '../api.js'
import { useState, useEffect, useRef } from 'react'
import { useToast } from '../components/ToastProvider.jsx'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  BarChart, Bar, Legend
} from 'recharts'
import { formatPlatform } from '../labels.js'
import { useLocale } from '../i18n/LocaleContext.jsx'
import { formatTime, formatCurrencyBRL, formatNumber } from '../i18n/format.js'

const HISTORY_MAX_POINTS = 120

function toHistoryPoint(tsLabel, throughput, scraperQueue, aiQueue) {
  return { time: tsLabel, throughput, scraperQueue, aiQueue }
}

const SERVICES = [
  {
    key: 'database', icon: '🗄️', labelKey: 'dashboard.svcPostgresql',
    sub: (s, t) => s?.database?.status === 'ok' ? t('dashboard.connected') : (s?.database?.detail || t('dashboard.offline')),
  },
  {
    key: 'redis', icon: '⚡', labelKey: 'dashboard.svcRedis',
    sub: (s, t) => s?.redis?.status === 'ok' ? t('dashboard.connected') : t('dashboard.offline'),
  },
  {
    key: 'ollama', icon: '🤖', labelKey: 'dashboard.svcOllama',
    sub: (s, t) => s?.ollama?.status === 'ok' ? t('dashboard.modelsLoaded', { n: (s.ollama.models || []).length }) : t('dashboard.offline'),
  },
  {
    key: 'workers', icon: '⚙️', labelKey: 'dashboard.svcCelery',
    sub: (s, t) => s?.workers?.status === 'ok' ? (s?.ai_workers_paused ? t('dashboard.paused') : t('dashboard.running')) : t('dashboard.offline'),
  },
]

function svcStatus(key, s) {
  if (!s) return 'loading'
  if (key === 'workers') {
    if (s?.workers?.status !== 'ok') return 'err'
    return s.ai_workers_paused ? 'warn' : 'ok'
  }
  return s[key]?.status === 'ok' ? 'ok' : 'err'
}

function proxyModeLabel(mode, t) {
  switch (mode) {
    case 'pool':
      return t('dashboard.proxyModePool')
    case 'single':
      return t('dashboard.proxyModeSingle')
    case 'override':
      return t('dashboard.proxyModeOverride')
    default:
      return t('dashboard.proxyModeDirect')
  }
}

function proxyHealthClass(health) {
  if (health === 'ok') return 'ok'
  if (health === 'warn') return 'loading'
  return 'ok'
}

function proxySubline(proxy, t) {
  if (!proxy) return t('dashboard.proxyLoading')
  if (!proxy.proxy_enabled) return t('dashboard.proxyDisabled')
  if (proxy.health === 'warn') return t('dashboard.proxyMisconfigured')
  const strategy = proxy.rotation_strategy || 'round_robin'
  if (proxy.proxy_mode === 'pool') {
    return t('dashboard.proxyPoolReady', { n: proxy.pool_size ?? 0, strategy })
  }
  if (proxy.proxy_mode === 'single' || proxy.proxy_mode === 'override') {
    return t('dashboard.proxySingleReady', { strategy })
  }
  return t('dashboard.proxyDisabled')
}

export default function Dashboard({ status, loading }) {
  const { t, locale } = useLocale()
  const [recalculating, setRecalculating] = useState(false)
  const [recalcResult, setRecalcResult] = useState(null)
  const [enriching, setEnriching] = useState(false)
  const [enrichResult, setEnrichResult] = useState(null)
  const [rerunBusy, setRerunBusy] = useState(false)
  const [rerunResult, setRerunResult] = useState(null)
  const [rerunForm, setRerunForm] = useState({
    mode: 'missing',
    stages: 'all',
    city: '',
    platform: '',
    limit: '',
    active_only: true,
    stale_before: '',
  })
  const [ollamaLoading, setOllamaLoading] = useState(false)
  const [pipeline, setPipeline] = useState(null)
  const [throughputHistory, setThroughputHistory] = useState([])
  const { alerts, loading: alertsLoading, setAlerts } = useAlerts()
  const showToast = useToast()

  const stats = status?.stats || {}
  const dbOk = status?.database?.status === 'ok'
  const historyLoaded = useRef(false)

  // Load persisted history once, then poll live tip
  useEffect(() => {
    let cancelled = false
    const loadHistory = async () => {
      try {
        const hist = await fetchPipelineHistory(60)
        if (cancelled || historyLoaded.current) return
        const points = (hist.points || []).map((p) =>
          toHistoryPoint(
            formatTime(p.ts, locale),
            p.throughput_per_min || 0,
            p.scraper_queue || 0,
            p.ai_queue || 0,
          )
        )
        if (points.length) {
          setThroughputHistory(points.slice(-HISTORY_MAX_POINTS))
        }
        historyLoaded.current = true
      } catch {
        historyLoaded.current = true
      }
    }
    const poll = async () => {
      try {
        const data = await fetchPipeline()
        if (cancelled) return
        setPipeline(data)
        const timeLabel = formatTime(new Date(), locale)
        setThroughputHistory((prev) => {
          const next = [
            ...prev,
            toHistoryPoint(
              timeLabel,
              data.ai_metrics?.throughput_per_min || 0,
              data.queues?.scrapers || 0,
              data.queues?.ai || 0,
            ),
          ]
          return next.slice(-HISTORY_MAX_POINTS)
        })
      } catch {
        // silently ignore — pipeline data is non-critical
      }
    }
    loadHistory().then(() => {
      if (!cancelled) poll()
    })
    const id = setInterval(poll, 8000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [locale])

  const handleEnsureOllama = async () => {
    setOllamaLoading(true)
    try {
      const r = await ensureOllama()
      showToast(r.status === 'already_running' ? t('dashboard.toastOllamaAlready') : t('dashboard.toastOllamaStarted'), { type: 'success' })
    } catch (e) {
      showToast(t('dashboard.toastError', { message: e.message }), { type: 'error' })
    } finally {
      setOllamaLoading(false)
    }
  }

  const handleRecalculate = async () => {
    setRecalculating(true)
    setRecalcResult(null)
    try {
      await recalculateScores()
      setRecalcResult(t('dashboard.recalcResultOk'))
      showToast(t('dashboard.toastRecalculated'), { type: 'success' })
    } catch (e) {
      setRecalcResult(t('common.errorCross', { message: e.message }))
      showToast(t('dashboard.toastRecalcFailed'), { type: 'error' })
    } finally {
      setRecalculating(false)
    }
  }

  const handleEnrichMissing = async () => {
    setEnriching(true)
    setEnrichResult(null)
    try {
      const r = await enrichMissing()
      const skipped = r.skipped_no_images || 0
      const msg = skipped
        ? t('dashboard.enrichResultOkSkipped', { n: r.queued_enrichments, skipped })
        : t('dashboard.enrichResultOk', { n: r.queued_enrichments })
      setEnrichResult(msg)
      showToast(t('dashboard.toastEnrichQueued'), { type: 'success' })
    } catch (e) {
      setEnrichResult(t('common.errorCross', { message: e.message }))
      showToast(t('dashboard.toastEnrichFailed'), { type: 'error' })
    } finally {
      setEnriching(false)
    }
  }

  const handleEnrichmentRerun = async (dryRun) => {
    setRerunBusy(true)
    setRerunResult(null)
    try {
      const payload = {
        mode: rerunForm.mode,
        stages: rerunForm.stages,
        dry_run: dryRun,
        active_only: rerunForm.active_only,
        city: rerunForm.city.trim() || undefined,
        platform: rerunForm.platform.trim() || undefined,
        limit: rerunForm.limit === '' ? undefined : Number(rerunForm.limit),
        stale_before: rerunForm.mode === 'stale_before' && rerunForm.stale_before
          ? new Date(rerunForm.stale_before).toISOString()
          : undefined,
      }
      const r = await enrichmentRerun(payload)
      const n = dryRun ? r.would_queue : r.queued
      const verb = dryRun ? t('dashboard.verbWouldQueue') : t('dashboard.verbQueued')
      const skips = [
        r.skipped_no_images ? t('dashboard.rerunSkipNoImages', { n: r.skipped_no_images }) : null,
        r.skipped_too_few_photos ? t('dashboard.rerunSkipPhotoGate', { n: r.skipped_too_few_photos }) : null,
        r.skipped_missing_prior_enrichment ? t('dashboard.rerunSkipMissingPrior', { n: r.skipped_missing_prior_enrichment }) : null,
      ].filter(Boolean)
      const skipNote = skips.length ? ` (${skips.join(', ')})` : ''
      setRerunResult(t('dashboard.rerunResultOk', { verb, n, skipNote }))
      showToast(t('dashboard.toastRerunOk', { verb, n }), { type: 'success' })
    } catch (e) {
      setRerunResult(t('common.errorCross', { message: e.message }))
      showToast(t('dashboard.toastRerunFailed'), { type: 'error' })
    } finally {
      setRerunBusy(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">{t('dashboard.title')}</h1>
        <p className="page-subtitle">{t('dashboard.subtitle')}</p>
      </div>

      {/* Charts row */}
      {throughputHistory.length >= 2 && (
        <>
          <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
            {t('dashboard.pipelineMetrics')}
          </h2>
          <div className="chart-grid">
            <div className="chart-panel">
              <div className="chart-title">{t('dashboard.aiThroughput')} ({t('dashboard.tasksPerMin')})</div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={throughputHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="time" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 }}
                    labelStyle={{ color: 'var(--text-secondary)' }}
                  />
                  <Line type="monotone" dataKey="throughput" stroke="var(--accent-cyan)" strokeWidth={2} dot={false} name={t('dashboard.tasksPerMin')} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-panel">
              <div className="chart-title">{t('dashboard.queueDepth')}</div>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={throughputHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="time" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 }}
                    labelStyle={{ color: 'var(--text-secondary)' }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
                  <Bar dataKey="scraperQueue" fill="var(--accent-amber)" name={t('dashboard.scrapers')} radius={[3, 3, 0, 0]} />
                  <Bar dataKey="aiQueue" fill="var(--accent)" name={t('dashboard.ai')} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
      {throughputHistory.length > 0 && throughputHistory.length < 2 && (
        <div className="chart-empty-state">{t('dashboard.collectingCharts')}</div>
      )}

      {/* Alerts row */}
      {!alertsLoading && alerts.length > 0 && (
        <>
          <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.8px', display: 'flex', justifyContent: 'space-between' }}>
            <span>{t('dashboard.priceDropAlerts')}</span>
            <button
              className="btn btn-ghost"
              style={{ padding: '4px 8px', fontSize: 12, height: 'auto' }}
              onClick={() => setAlerts([])}
              aria-label={t('dashboard.dismissAllAria')}
            >
              {t('dashboard.dismissAll')}
            </button>
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 32 }}>
            {alerts.slice(0, 10).map((alert, idx) => (
              <div key={idx} style={{ padding: '12px 16px', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--accent-rose)' }}>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                  {t('dashboard.alertDrop', { pct: alert.drop_pct?.toFixed(1), platform: formatPlatform(alert.platform) })}
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  {t('dashboard.alertPrices', {
                    title: alert.title,
                    oldPrice: formatCurrencyBRL(alert.old_price, locale),
                    newPrice: formatCurrencyBRL(alert.new_price, locale),
                  })}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Stats row — never show 0 when DB is unhealthy (BIN-60 false-zero) */}
      <div className="stats-grid">
        <StatCard
          label={t('dashboard.totalProperties')}
          value={formatPropertyCount(loading, dbOk, stats.total_properties, t, locale)}
          sub={dbOk ? t('dashboard.inDatabase') : t('dashboard.databaseUnavailable')}
        />
        <StatCard
          label={t('dashboard.aiEnriched')}
          value={formatPropertyCount(loading, dbOk, stats.enriched_properties, t, locale)}
          sub={dbOk ? t('dashboard.vlmAnalysed') : t('dashboard.databaseUnavailable')}
        />
        <StatCard
          label={t('dashboard.enrichmentRate')}
          value={
            loading || !dbOk || !stats.total_properties
              ? t('common.emDash')
              : `${Math.round((stats.enriched_properties / stats.total_properties) * 100)}%`
          }
          sub={t('dashboard.ofTotalScraped')}
        />
        <StatCard
          label={t('dashboard.ollamaModels')}
          value={loading ? t('common.ellipsis') : (status?.ollama?.models?.length ?? 0)}
          sub={status?.ollama?.models?.[0] ?? t('dashboard.noneLoaded')}
        />
      </div>

      {/* Services */}
      <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
        {t('dashboard.serviceStatus')}
      </h2>
      <div className="services-grid" style={{ marginBottom: 28 }}>
        {SERVICES.map(({ key, icon, labelKey, sub }) => {
          const st = svcStatus(key, status)
          return (
            <div key={key} className="service-card">
              <div className={`service-icon ${st === 'warn' ? 'loading' : st}`}>{icon}</div>
              <div className="service-info">
                <div className="service-name">{t(labelKey)}</div>
                <div className={`service-status ${st === 'warn' ? 'loading' : st}`}>
                  {loading ? t('common.checking') : sub(status, t)}
                </div>
              </div>
            </div>
          )
        })}
        <div className="service-card" data-testid="proxy-health-card">
          <div className={`service-icon ${proxyHealthClass(pipeline?.proxy?.health)}`}>🔒</div>
          <div className="service-info">
            <div className="service-name">{t('dashboard.svcProxy')}</div>
            <div className={`service-status ${proxyHealthClass(pipeline?.proxy?.health)}`}>
              {!pipeline?.proxy
                ? t('dashboard.proxyLoading')
                : proxyModeLabel(pipeline.proxy.proxy_mode, t)}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              {proxySubline(pipeline?.proxy, t)}
            </div>
          </div>
        </div>
      </div>

      {/* Quick actions */}
      <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
        {t('dashboard.quickActions')}
      </h2>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 32 }}>
        <button className="btn btn-primary" onClick={handleEnsureOllama} disabled={ollamaLoading}>
          {ollamaLoading ? <span className="spinner" /> : '🤖'} {t('dashboard.ensureOllama')}
        </button>
        <button className="btn btn-ghost" onClick={handleRecalculate} disabled={recalculating}>
          {recalculating ? <span className="spinner" /> : '📊'} {t('dashboard.recalculateScores')}
        </button>
        <button
          className="btn btn-ghost"
          onClick={handleEnrichMissing}
          disabled={enriching}
          data-testid="enrich-missing"
        >
          {enriching ? <span className="spinner" /> : '✨'} {t('dashboard.enrichMissing')}
        </button>
      </div>
      {(recalcResult || enrichResult) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
          {recalcResult && (
            <div style={{ padding: '10px 16px', borderRadius: 8, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 13, color: recalcResult.startsWith('✔') ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
              {recalcResult}
            </div>
          )}
          {enrichResult && (
            <div
              data-testid="enrich-missing-result"
              style={{ padding: '10px 16px', borderRadius: 8, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 13, color: enrichResult.startsWith('✔') ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}
            >
              {enrichResult}
            </div>
          )}
        </div>
      )}

      {/* Selective AI enrichment (BIN-95) */}
      <div className="card" data-testid="enrichment-rerun-panel" style={{ marginBottom: 28 }}>
        <div className="panel-section-title">{t('dashboard.enrichmentRerunTitle')}</div>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 14, lineHeight: 1.45 }}>
          {t('dashboard.enrichmentRerunHelp')}
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 14 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            {t('common.mode')}
            <select
              className="form-select"
              data-testid="enrichment-rerun-mode"
              value={rerunForm.mode}
              onChange={(e) => setRerunForm((f) => ({ ...f, mode: e.target.value }))}
            >
              <option value="missing">{t('dashboard.modeMissing')}</option>
              <option value="force">{t('dashboard.modeForce')}</option>
              <option value="stale_before">{t('dashboard.modeStaleBefore')}</option>
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            {t('common.stages')}
            <select
              className="form-select"
              data-testid="enrichment-rerun-stages"
              value={rerunForm.stages}
              onChange={(e) => setRerunForm((f) => ({ ...f, stages: e.target.value }))}
            >
              <option value="all">{t('dashboard.stagesAll')}</option>
              <option value="visual+sentiment">{t('dashboard.stagesVisualSentiment')}</option>
              <option value="verdict_only">{t('dashboard.stagesVerdictOnly')}</option>
            </select>
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            {t('common.city')}
            <input
              className="form-input"
              data-testid="enrichment-rerun-city"
              value={rerunForm.city}
              onChange={(e) => setRerunForm((f) => ({ ...f, city: e.target.value }))}
              placeholder={t('dashboard.cityPlaceholder')}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            {t('common.platform')}
            <input
              className="form-input"
              data-testid="enrichment-rerun-platform"
              value={rerunForm.platform}
              onChange={(e) => setRerunForm((f) => ({ ...f, platform: e.target.value }))}
              placeholder={t('dashboard.platformPlaceholder')}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
            {t('common.limit')}
            <input
              className="form-input"
              data-testid="enrichment-rerun-limit"
              inputMode="numeric"
              type="text"
              value={rerunForm.limit}
              onChange={(e) => setRerunForm((f) => ({ ...f, limit: e.target.value.replace(/\D/g, '') }))}
              placeholder={t('dashboard.limitPlaceholder')}
            />
          </label>
          {rerunForm.mode === 'stale_before' && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12 }}>
              {t('dashboard.staleBefore')}
              <input
                className="form-input"
                data-testid="enrichment-rerun-stale-before"
                type="datetime-local"
                value={rerunForm.stale_before}
                onChange={(e) => setRerunForm((f) => ({ ...f, stale_before: e.target.value }))}
              />
            </label>
          )}
        </div>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, marginBottom: 14 }}>
          <input
            type="checkbox"
            data-testid="enrichment-rerun-active-only"
            checked={rerunForm.active_only}
            onChange={(e) => setRerunForm((f) => ({ ...f, active_only: e.target.checked }))}
          />
          {t('dashboard.activeListingsOnly')}
        </label>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button
            className="btn btn-ghost"
            data-testid="enrichment-rerun-dry-run"
            disabled={rerunBusy}
            onClick={() => handleEnrichmentRerun(true)}
          >
            {rerunBusy ? <span className="spinner" /> : null} {t('dashboard.dryRun')}
          </button>
          <button
            className="btn btn-primary"
            data-testid="enrichment-rerun-run"
            disabled={rerunBusy}
            onClick={() => handleEnrichmentRerun(false)}
          >
            {rerunBusy ? <span className="spinner" /> : null} {t('dashboard.runEnrichment')}
          </button>
        </div>
        {rerunResult && (
          <div
            data-testid="enrichment-rerun-result"
            style={{
              marginTop: 12,
              padding: '10px 16px',
              borderRadius: 8,
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              fontSize: 13,
              color: rerunResult.startsWith('✔') ? 'var(--accent-emerald)' : 'var(--accent-rose)',
            }}
          >
            {rerunResult}
          </div>
        )}
      </div>

      {/* Ollama models list */}
      {status?.ollama?.status === 'ok' && (status.ollama.models || []).length > 0 && (
        <div className="card">
          <div className="panel-section-title">{t('dashboard.loadedModels')}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {status.ollama.models.map(m => (
              <div key={m} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border-subtle)', fontSize: 13 }}>
                <span style={{ color: 'var(--accent-emerald)' }}>✔</span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{m}</span>
                {m.includes('vision') && <span className="flag feature">{t('common.visionBadge')}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function formatPropertyCount(loading, dbOk, value, t, locale) {
  if (loading) return t('common.ellipsis')
  if (!dbOk || value == null) return t('common.emDash')
  return formatNumber(value, locale)
}

function StatCard({ label, value, sub }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )
}
