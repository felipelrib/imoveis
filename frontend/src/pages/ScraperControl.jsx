import { useState, useEffect, useRef } from 'react'
import { fetchPlatforms, triggerScrape, pauseWorkers, resumeWorkers, fetchPipeline, fetchSchedule, updateSchedule } from '../api.js'
import { useSystemStatus } from '../hooks/useSystemStatus.js'
import { useToast } from '../components/ToastProvider.jsx'

function ts() {
  return new Date().toLocaleTimeString('pt-BR')
}

export default function ScraperControl() {
  const { status, loading: statusLoading } = useSystemStatus(5000)
  const [platforms, setPlatforms] = useState([])
  const [selectedPlatform, setSelectedPlatform] = useState('')
  const [scrapeType, setScrapeType] = useState('both')
  const [scraping, setScraping] = useState(false)
  const [taskId, setTaskId] = useState(null)
  const [workerPaused, setWorkerPaused] = useState(false)
  const logRef = useRef(null)
  const showToast = useToast()

  // Pipeline tracking state
  const [pipeline, setPipeline] = useState({
    queues: { scrapers: 0, ai: 0 },
    scrapers_status: {},
    ai_metrics: { throughput_per_min: 0, avg_duration_sec: 0, total_recorded: 0 }
  })

  // Schedule state
  const [schedules, setSchedules] = useState([])
  const [editingPlatform, setEditingPlatform] = useState(null)
  const [editInterval, setEditInterval] = useState('')
  const [savingSchedule, setSavingSchedule] = useState(false)

  // Logs state initialized from localStorage
  const [logs, setLogs] = useState(() => {
    const saved = localStorage.getItem('scraperLogs')
    if (saved) {
      try { return JSON.parse(saved) } catch (e) { /* ignore */ }
    }
    return [{ type: 'info', text: `[${ts()}] System ready. Select a platform and click Run Scraper.` }]
  })

  // Poll pipeline status
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const p = await fetchPipeline()
        if (!cancelled) setPipeline(p)
      } catch (e) { /* ignore polling errors */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Poll schedule status
  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const s = await fetchSchedule()
        if (!cancelled && s?.schedules) setSchedules(s.schedules)
      } catch (e) { /* ignore */ }
    }
    poll()
    const id = setInterval(poll, 15000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Save logs to localStorage on change (capped at 200)
  useEffect(() => {
    localStorage.setItem('scraperLogs', JSON.stringify(logs))
  }, [logs])

  useEffect(() => {
    fetchPlatforms().then(p => {
      setPlatforms(p)
      if (p.length > 0) setSelectedPlatform(p[0].name)
    }).catch(e => {
      showToast('Failed to load platforms: ' + e.message, { type: 'error' })
    })
  }, [])

  useEffect(() => {
    if (status) setWorkerPaused(status.ai_workers_paused)
  }, [status])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs])

  const addLog = (type, text) => setLogs(prev => [...prev.slice(-199), { type, text }])

  const handleScrape = async () => {
    if (!selectedPlatform) return
    setScraping(true)
    addLog('info', `[${ts()}] Triggering scraper for platform: ${selectedPlatform} (Type: ${scrapeType})`)
    try {
      const r = await triggerScrape(selectedPlatform, {}, scrapeType)
      setTaskId(r.task_id)
      addLog('success', `[${ts()}] ✔ Task enqueued — ID: ${r.task_id}`)
      addLog('info', `[${ts()}] Celery worker is processing. Watch the live pipeline below.`)
      showToast(`Scraper enqueued for ${selectedPlatform}`, { type: 'success' })
    } catch (e) {
      addLog('error', `[${ts()}] ✖ Error: ${e.message}`)
      showToast('Scrape failed: ' + e.message, { type: 'error' })
    } finally {
      setScraping(false)
    }
  }

  const handlePauseResume = async () => {
    try {
      if (workerPaused) {
        await resumeWorkers()
        setWorkerPaused(false)
        addLog('success', `[${ts()}] ✔ AI workers resumed`)
        showToast('AI workers resumed', { type: 'success' })
      } else {
        await pauseWorkers()
        setWorkerPaused(true)
        addLog('warn', `[${ts()}] ⏸ AI workers paused — scraping continues, enrichment queued`)
        showToast('AI workers paused', { type: 'warning' })
      }
    } catch (e) {
      addLog('error', `[${ts()}] ✖ ${e.message}`)
      showToast('Worker toggle failed: ' + e.message, { type: 'error' })
    }
  }

  const clearLogs = () => {
    const fresh = [{ type: 'info', text: `[${ts()}] Logs cleared.` }]
    setLogs(fresh)
    localStorage.setItem('scraperLogs', JSON.stringify(fresh))
  }

  const handleSaveSchedule = async (platform) => {
    const minutes = parseInt(editInterval, 10)
    if (isNaN(minutes) || minutes < 0) return
    setSavingSchedule(true)
    try {
      await updateSchedule(platform, minutes)
      addLog('success', `[${ts()}] ✔ Schedule updated: ${platform} → every ${minutes === 0 ? 'manual only' : minutes + ' min'} (restart beat to apply)`)
      showToast(`Schedule updated: ${platform}`, { type: 'success' })
      setEditingPlatform(null)
      setEditInterval('')
      // Refresh schedules
      const s = await fetchSchedule()
      if (s?.schedules) setSchedules(s.schedules)
    } catch (e) {
      addLog('error', `[${ts()}] ✖ ${e.message}`)
      showToast('Schedule update failed: ' + e.message, { type: 'error' })
    } finally {
      setSavingSchedule(false)
    }
  }

  const formatTs = (ts) => {
    if (!ts) return '—'
    return new Date(ts * 1000).toLocaleString('pt-BR', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
  }

  const aiOk = status?.ollama?.status === 'ok'
  const dbOk = status?.database?.status === 'ok'

  const activeScrapers = Object.entries(pipeline.scrapers_status).filter(([_, s]) => s.status === 'running')

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Scraper Control</h1>
        <p className="page-subtitle">Trigger ingestion jobs and manage worker behaviour</p>
      </div>

      <div className="control-panel">
        {/* ── Left: Launch controls ── */}
        <div className="card">
          <div className="panel-section-title">🕸️ Ingestion Pipeline</div>

          {!dbOk && !statusLoading && (
            <div style={{ padding: '10px 14px', borderRadius: 8, background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.25)', fontSize: 13, color: '#fda4af', marginBottom: 16 }}>
              ⚠ Database offline — start the stack with <code style={{ background: 'rgba(0,0,0,0.3)', padding: '1px 6px', borderRadius: 4 }}>.\start.ps1</code> first
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label className="form-label">Platform</label>
              <select
                className="form-select"
                value={selectedPlatform}
                onChange={e => setSelectedPlatform(e.target.value)}
              >
                {platforms.length === 0
                  ? <option value="">Loading platforms…</option>
                  : platforms.map(p => (
                      <option key={p.name} value={p.name} disabled={!p.enabled}>
                        {p.name} {!p.enabled ? '(disabled)' : ''} {p.rate_limit ? `— ${p.rate_limit} req/min` : ''}
                      </option>
                    ))
                }
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Scrape Type</label>
              <select className="form-select" value={scrapeType} onChange={e => setScrapeType(e.target.value)}>
                <option value="both">Both (Rent & Sale)</option>
                <option value="rent">Rent only</option>
                <option value="sale">Sale only</option>
              </select>
            </div>

            <button
              className="btn btn-primary"
              onClick={handleScrape}
              disabled={scraping || !selectedPlatform || (!dbOk && !statusLoading)}
              style={{ width: '100%', justifyContent: 'center', padding: '12px' }}
            >
              {scraping ? <><span className="spinner" /> Enqueuing…</> : '▶ Run Scraper'}
            </button>

            {/* Live Pipeline Status */}
            <div style={{ marginTop: 12, padding: 12, background: 'var(--bg-app)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Live Pipeline</div>

              <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
                <div style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-card)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Scraper Queue</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: pipeline.queues.scrapers > 0 ? 'var(--accent-amber)' : 'var(--text-primary)' }}>{pipeline.queues.scrapers}</span>
                </div>
                <div style={{ flex: 1, padding: '8px 12px', background: 'var(--bg-card)', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid var(--border-subtle)' }}>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>AI Queue</span>
                  <span style={{ fontSize: 14, fontWeight: 700, color: pipeline.queues.ai > 0 ? 'var(--accent-cyan)' : 'var(--text-primary)' }}>{pipeline.queues.ai}</span>
                </div>
              </div>

              {activeScrapers.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                  {activeScrapers.map(([plat, s]) => (
                    <div key={plat} style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="spinner" style={{ width: 12, height: 12, borderWidth: 2 }} />
                      <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{plat}</span>
                      <span style={{ color: 'var(--text-muted)' }}>— {s.processed} processed, {s.skipped} skipped, {s.errors} err</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginBottom: 12 }}>No active scrapers running.</div>
              )}

              <div style={{ paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.5px' }}>⚡ AI Performance</div>
                <div style={{ display: 'flex', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Throughput</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--accent-emerald)' }}>
                      {pipeline?.ai_metrics?.throughput_per_min ?? 0} <span style={{ fontSize: 11, fontWeight: 400 }}>props/min</span>
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Avg Speed</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {pipeline?.ai_metrics?.avg_duration_sec ?? 0} <span style={{ fontSize: 11, fontWeight: 400 }}>sec/prop</span>
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Recorded</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                      {pipeline?.ai_metrics?.total_recorded ?? 0}
                    </div>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>

        {/* ── Right: Worker controls ── */}
        <div className="card">
          <div className="panel-section-title">⚙️ Worker Management</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

            {/* AI worker pause */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>AI Enrichment Workers</div>
                <div style={{ fontSize: 12, color: workerPaused ? 'var(--accent-amber)' : 'var(--accent-emerald)', marginTop: 3 }}>
                  {workerPaused ? '⏸ Paused' : '▶ Running'}
                </div>
              </div>
              <button
                className={`btn btn-sm ${workerPaused ? 'btn-success' : 'btn-ghost'}`}
                onClick={handlePauseResume}
              >
                {workerPaused ? '▶ Resume' : '⏸ Pause'}
              </button>
            </div>

            {/* Ollama status */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10 }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>Ollama VLM Server</div>
                <div style={{ fontSize: 12, color: statusLoading ? 'var(--text-muted)' : aiOk ? 'var(--accent-emerald)' : 'var(--accent-rose)', marginTop: 3 }}>
                  {statusLoading ? '⏳ Checking status...' : aiOk ? `✔ Online — ${(status?.ollama?.models || []).join(', ') || 'no models'}` : '✖ Offline'}
                </div>
              </div>
              {!aiOk && !statusLoading && (
                <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="btn btn-sm btn-ghost">
                  Install
                </a>
              )}
            </div>

            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6, padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
              💡 <strong style={{ color: 'var(--text-secondary)' }}>Tip:</strong> Pausing AI workers lets scraping continue while you conserve GPU resources. Enrichment jobs queue up and run when resumed.
            </div>
          </div>
        </div>
      </div>

      {/* ── Scheduled Runs ── */}
      <div className="card">
        <div className="panel-section-title">🕐 Scheduled Runs</div>
        {schedules.length === 0 ? (
          <div style={{ fontSize: 13, color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No platforms configured for scheduling.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {schedules.map(s => (
              <div key={s.platform} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
                <div style={{ minWidth: 100 }}>
                  <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', textTransform: 'capitalize' }}>{s.platform}</div>
                </div>
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 16, fontSize: 12 }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Interval: </span>
                    {editingPlatform === s.platform ? (
                      <input
                        type="number"
                        value={editInterval}
                        onChange={e => setEditInterval(e.target.value)}
                        min="0"
                        style={{ width: 56, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border-subtle)', background: 'var(--bg-app)', color: 'var(--text-primary)', fontSize: 12 }}
                      />
                    ) : (
                      <span style={{ fontWeight: 600, color: s.interval_minutes > 0 ? 'var(--accent-emerald)' : 'var(--text-muted)' }}>
                        {s.interval_minutes > 0 ? `${s.interval_minutes} min` : 'manual'}
                      </span>
                    )}
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Last: </span>
                    <span style={{ color: 'var(--text-secondary)' }}>{formatTs(s.last_run)}</span>
                  </div>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Next: </span>
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
                        {savingSchedule ? 'Saving…' : 'Save'}
                      </button>
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => { setEditingPlatform(null); setEditInterval('') }}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => { setEditingPlatform(s.platform); setEditInterval(String(s.interval_minutes)) }}
                    >
                      Edit
                    </button>
                  )}
                </div>
              </div>
            ))}
            <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '0 4px' }}>
              💡 Interval changes persist in Redis and take effect when the Celery beat process restarts.
            </div>
          </div>
        )}
      </div>

      {/* Activity log */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div className="panel-section-title" style={{ marginBottom: 0 }}>📋 Activity Log</div>
          <button className="btn btn-sm btn-ghost" onClick={clearLogs}>Clear</button>
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
