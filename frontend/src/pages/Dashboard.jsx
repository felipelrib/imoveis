import { useSystemStatus } from '../hooks/useSystemStatus.js'
import { useAlerts } from '../hooks/useAlerts.js'
import { ensureOllama, recalculateScores, fetchPipeline } from '../api.js'
import { useState, useEffect, useRef } from 'react'
import { useToast } from '../components/ToastProvider.jsx'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  BarChart, Bar, Legend
} from 'recharts'

const SERVICES = [
  { key: 'database', icon: '🗄️', label: 'PostgreSQL',  sub: (s) => s?.database?.status === 'ok' ? 'Connected' : s?.database?.detail || 'Offline' },
  { key: 'redis',    icon: '⚡', label: 'Redis',        sub: (s) => s?.redis?.status === 'ok' ? 'Connected' : 'Offline' },
  { key: 'ollama',   icon: '🤖', label: 'Ollama VLM',   sub: (s) => s?.ollama?.status === 'ok' ? `${(s.ollama.models || []).length} model(s) loaded` : 'Offline' },
  { key: 'workers',  icon: '⚙️', label: 'Celery Workers', sub: (s) => s?.workers?.status === 'ok' ? (s?.ai_workers_paused ? '⏸ Paused' : '▶ Running') : 'Offline' },
]

function svcStatus(key, s) {
  if (!s) return 'loading'
  if (key === 'workers') {
    if (s?.workers?.status !== 'ok') return 'err'
    return s.ai_workers_paused ? 'warn' : 'ok'
  }
  return s[key]?.status === 'ok' ? 'ok' : 'err'
}

export default function Dashboard({ status, loading }) {
  const [recalculating, setRecalculating] = useState(false)
  const [recalcResult, setRecalcResult] = useState(null)
  const [ollamaLoading, setOllamaLoading] = useState(false)
  const [pipeline, setPipeline] = useState(null)
  const [throughputHistory, setThroughputHistory] = useState([])
  const { alerts, loading: alertsLoading, setAlerts } = useAlerts()
  const showToast = useToast()

  const stats = status?.stats || {}

  // Poll pipeline telemetry for chart data
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const data = await fetchPipeline()
        if (cancelled) return
        setPipeline(data)
        const now = new Date()
        const timeLabel = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        setThroughputHistory(prev => {
          const next = [...prev, { time: timeLabel, throughput: data.ai_metrics?.throughput_per_min || 0, scraperQueue: data.queues?.scrapers || 0, aiQueue: data.queues?.ai || 0 }]
          // Keep last 20 data points
          return next.slice(-20)
        })
      } catch {
        // silently ignore — pipeline data is non-critical
      }
    }
    poll()
    const id = setInterval(poll, 8000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const handleEnsureOllama = async () => {
    setOllamaLoading(true)
    try {
      const r = await ensureOllama()
      showToast(r.status === 'already_running' ? 'Ollama is already running!' : 'Ollama started successfully!', { type: 'success' })
    } catch (e) {
      showToast('Error: ' + e.message, { type: 'error' })
    } finally {
      setOllamaLoading(false)
    }
  }

  const handleRecalculate = async () => {
    setRecalculating(true)
    setRecalcResult(null)
    try {
      const r = await recalculateScores()
      setRecalcResult(`✔ Recalculated ${r.combined_rows_updated} properties`)
      showToast(`Recalculated ${r.combined_rows_updated} properties`, { type: 'success' })
    } catch (e) {
      setRecalcResult('✖ Error: ' + e.message)
      showToast('Recalculation failed: ' + e.message, { type: 'error' })
    } finally {
      setRecalculating(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-subtitle">Real-time overview of your data pipeline and system health</p>
      </div>

      {/* Charts row */}
      {throughputHistory.length >= 2 && (
        <>
          <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
            📈 Pipeline Metrics
          </h2>
          <div className="chart-grid">
            <div className="chart-panel">
              <div className="chart-title">AI Throughput (tasks/min)</div>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={throughputHistory}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                  <XAxis dataKey="time" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
                  <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 }}
                    labelStyle={{ color: 'var(--text-secondary)' }}
                  />
                  <Line type="monotone" dataKey="throughput" stroke="var(--accent-cyan)" strokeWidth={2} dot={false} name="Tasks/min" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-panel">
              <div className="chart-title">Queue Depth</div>
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
                  <Bar dataKey="scraperQueue" fill="var(--accent-amber)" name="Scrapers" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="aiQueue" fill="var(--accent)" name="AI" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
      {throughputHistory.length > 0 && throughputHistory.length < 2 && (
        <div className="chart-empty-state">Collecting pipeline data… charts appear after 2+ data points.</div>
      )}

      {/* Alerts row */}
      {!alertsLoading && alerts.length > 0 && (
        <>
          <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.8px', display: 'flex', justifyContent: 'space-between' }}>
            <span>🚨 Price Drop Alerts</span>
            <button 
              className="btn btn-ghost" 
              style={{ padding: '4px 8px', fontSize: 12, height: 'auto' }} 
              onClick={() => setAlerts([])}
            >
              Dismiss All
            </button>
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 32 }}>
            {alerts.slice(0, 10).map((alert, idx) => (
              <div key={idx} style={{ padding: '12px 16px', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--accent-rose)' }}>
                <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                  📉 {alert.drop_pct?.toFixed(1)}% drop on {alert.platform}
                </div>
                <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                  {alert.title} — Was: {alert.old_price?.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })} | Now: <span style={{ color: 'var(--accent-emerald)', fontWeight: 600 }}>{alert.new_price?.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {/* Stats row */}
      <div className="stats-grid">
        <StatCard label="Total Properties" value={loading ? '…' : (stats.total_properties ?? 0).toLocaleString()} sub="in database" />
        <StatCard label="AI Enriched" value={loading ? '…' : (stats.enriched_properties ?? 0).toLocaleString()} sub="VLM analysed" />
        <StatCard
          label="Enrichment Rate"
          value={loading || !stats.total_properties ? '—' : `${Math.round((stats.enriched_properties / stats.total_properties) * 100)}%`}
          sub="of total scraped"
        />
        <StatCard
          label="Ollama Models"
          value={loading ? '…' : (status?.ollama?.models?.length ?? 0)}
          sub={status?.ollama?.models?.[0] ?? 'none loaded'}
        />
      </div>

      {/* Services */}
      <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
        Service Status
      </h2>
      <div className="services-grid" style={{ marginBottom: 28 }}>
        {SERVICES.map(({ key, icon, label, sub }) => {
          const st = svcStatus(key, status)
          return (
            <div key={key} className="service-card">
              <div className={`service-icon ${st === 'warn' ? 'loading' : st}`}>{icon}</div>
              <div className="service-info">
                <div className="service-name">{label}</div>
                <div className={`service-status ${st === 'warn' ? 'loading' : st}`}>
                  {loading ? 'Checking…' : sub(status)}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {/* Quick actions */}
      <h2 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 14, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
        Quick Actions
      </h2>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 32 }}>
        <button className="btn btn-primary" onClick={handleEnsureOllama} disabled={ollamaLoading}>
          {ollamaLoading ? <span className="spinner" /> : '🤖'} Ensure Ollama Running
        </button>
        <button className="btn btn-ghost" onClick={handleRecalculate} disabled={recalculating}>
          {recalculating ? <span className="spinner" /> : '📊'} Recalculate All Scores
        </button>
      </div>
      {recalcResult && (
        <div style={{ marginBottom: 24, padding: '10px 16px', borderRadius: 8, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 13, color: recalcResult.startsWith('✔') ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}>
          {recalcResult}
        </div>
      )}

      {/* Ollama models list */}
      {status?.ollama?.status === 'ok' && (status.ollama.models || []).length > 0 && (
        <div className="card">
          <div className="panel-section-title">🤖 Loaded Ollama Models</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {status.ollama.models.map(m => (
              <div key={m} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', background: 'var(--bg-card)', borderRadius: 8, border: '1px solid var(--border-subtle)', fontSize: 13 }}>
                <span style={{ color: 'var(--accent-emerald)' }}>✔</span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{m}</span>
                {m.includes('vision') && <span className="flag feature">vision</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
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
