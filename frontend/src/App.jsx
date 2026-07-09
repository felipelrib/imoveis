import { useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import ScraperControl from './pages/ScraperControl.jsx'
import Properties from './pages/Properties.jsx'
import { useSystemStatus } from './hooks/useSystemStatus.js'
import { ToastProvider } from './components/ToastProvider.jsx'

const NAV = [
  { path: '/',          icon: '⚡', label: 'Dashboard' },
  { path: '/scraper',   icon: '🕸️', label: 'Scraper Control' },
  { path: '/properties',icon: '🏘️', label: 'Properties' },
]

export default function App() {
  const { status, loading } = useSystemStatus(6000)
  const apiOk = !loading && status?.database?.status === 'ok'

  return (
    <ToastProvider>
    <BrowserRouter>
      <div className="app-shell">
        {/* ── Sidebar ── */}
        <aside className="sidebar">
          <div className="sidebar-logo">
            <div className="sidebar-logo-icon">🏙️</div>
            <div>
              <div className="sidebar-logo-text">Imóveis AI</div>
              <div className="sidebar-logo-sub">Real Estate Ingestor</div>
            </div>
          </div>

          <nav className="nav-section">
            <div className="nav-label">Navigation</div>
            {NAV.map(({ path, icon, label }) => (
              <NavLink
                key={path}
                to={path}
                end={path === '/'}
                className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              >
                <span className="nav-icon">{icon}</span>
                {label}
              </NavLink>
            ))}
          </nav>

          <div style={{ marginTop: 'auto', padding: '16px 20px 0', borderTop: '1px solid var(--border-subtle)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>System</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <ServiceDot label="Database"  ok={status?.database?.status === 'ok'} loading={loading} />
              <ServiceDot label="Redis"     ok={status?.redis?.status === 'ok'} loading={loading} />
              <ServiceDot label="Ollama"    ok={status?.ollama?.status === 'ok'} loading={loading} />
              <ServiceDot label="AI Worker" ok={!status?.ai_workers_paused} loading={loading} />
            </div>
          </div>
        </aside>

        {/* ── Main ── */}
        <main className="main-content">
          <Routes>
            <Route path="/"           element={<Dashboard status={status} loading={loading} />} />
            <Route path="/scraper"    element={<ScraperControl />} />
            <Route path="/properties" element={<Properties />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
    </ToastProvider>
  )
}

function ServiceDot({ label, ok, loading }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
      <span
        className={`status-dot ${loading ? 'loading' : ok ? 'ok' : 'err'}`}
        style={{ background: loading ? 'var(--accent)' : ok ? 'var(--accent-emerald)' : 'var(--accent-rose)' }}
      />
      {label}
    </div>
  )
}
