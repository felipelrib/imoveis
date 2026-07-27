import React from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { useSystemStatus } from './hooks/useSystemStatus.js'
import { ToastProvider } from './components/ToastProvider.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import CredentialGate from './components/CredentialGate.jsx'
import { isPropertiesSurface } from './routes/propertyPaths.js'

const Dashboard = React.lazy(() => import('./pages/Dashboard.jsx'))
const ScraperControl = React.lazy(() => import('./pages/ScraperControl.jsx'))
const Properties = React.lazy(() => import('./pages/Properties.jsx'))

/** Leaf marker so layout routes match without rendering a second page. */
function RouteMatch() {
  return null
}

const NAV = [
  { path: '/',          icon: '⚡', label: 'Dashboard', end: true },
  { path: '/scraper',   icon: '🕸️', label: 'Scraper Control', end: true },
  { path: '/properties',icon: '🏘️', label: 'Properties', end: false, propertiesSurface: true },
]

export default function App() {
  const { status, loading } = useSystemStatus(6000)

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
            {NAV.map(({ path, icon, label, end, propertiesSurface }) => (
              <NavItem
                key={path}
                path={path}
                icon={icon}
                label={label}
                end={end}
                propertiesSurface={propertiesSurface}
              />
            ))}
          </nav>

          <div className="sidebar-footer">
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>System</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <ServiceDot label="Database"  ok={status?.database?.status === 'ok'} loading={loading} />
              <ServiceDot label="Redis"     ok={status?.redis?.status === 'ok'} loading={loading} />
              <ServiceDot label="Ollama"    ok={status?.ollama?.status === 'ok'} loading={loading} />
              <ServiceDot label="AI Worker" ok={!status?.ai_workers_paused} loading={loading} />
            </div>
            <CredentialGate />
          </div>
        </aside>

        {/* ── Main ── */}
        <main className="main-content">
          <ErrorBoundary>
            <React.Suspense fallback={<div style={{ padding: '24px', color: 'var(--text-secondary)' }}>Loading...</div>}>
              <Routes>
                <Route path="/"           element={<Dashboard status={status} loading={loading} />} />
                <Route path="/scraper"    element={<ScraperControl />} />
                {/* Layout route keeps Properties mounted across deep-link navigations */}
                <Route element={<Properties />}>
                  <Route path="properties" element={<RouteMatch />} />
                  <Route path="properties/:propertyId" element={<RouteMatch />} />
                  <Route path="favourites" element={<RouteMatch />} />
                  <Route path="compare/:compareIds" element={<RouteMatch />} />
                </Route>
              </Routes>
            </React.Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </BrowserRouter>
    </ToastProvider>
  )
}

function NavItem({ path, icon, label, end, propertiesSurface }) {
  const location = useLocation()
  return (
    <NavLink
      to={path}
      end={end}
      className={({ isActive }) => {
        const active = propertiesSurface
          ? isPropertiesSurface(location.pathname)
          : isActive
        return `nav-link${active ? ' active' : ''}`
      }}
    >
      <span className="nav-icon">{icon}</span>
      {label}
    </NavLink>
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
