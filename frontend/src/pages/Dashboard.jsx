import { useSystemStatus } from '../hooks/useSystemStatus.js'
import { ensureOllama, recalculateScores } from '../api.js'
import { useState } from 'react'
import { useToast } from '../components/ToastProvider.jsx'

const SERVICES = [
  { key: 'database', icon: '🗄️', label: 'PostgreSQL',  sub: (s) => s?.database?.status === 'ok' ? 'Connected' : s?.database?.detail || 'Offline' },
  { key: 'redis',    icon: '⚡', label: 'Redis',        sub: (s) => s?.redis?.status === 'ok' ? 'Connected' : 'Offline' },
  { key: 'ollama',   icon: '🤖', label: 'Ollama VLM',   sub: (s) => s?.ollama?.status === 'ok' ? `${(s.ollama.models || []).length} model(s) loaded` : 'Offline' },
  { key: 'workers',  icon: '⚙️', label: 'AI Workers',   sub: (s) => s?.ai_workers_paused ? '⏸ Paused' : '▶ Running' },
]

function svcStatus(key, s) {
  if (!s) return 'loading'
  if (key === 'workers') return s.ai_workers_paused ? 'warn' : 'ok'
  return s[key]?.status === 'ok' ? 'ok' : 'err'
}

export default function Dashboard({ status, loading }) {
  const [recalculating, setRecalculating] = useState(false)
  const [recalcResult, setRecalcResult] = useState(null)
  const [ollamaLoading, setOllamaLoading] = useState(false)
  const showToast = useToast()

  const stats = status?.stats || {}

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
