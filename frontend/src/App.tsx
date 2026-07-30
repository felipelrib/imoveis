import React from 'react'
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom'
import { useSystemStatus } from './hooks/useSystemStatus.js'
import { ToastProvider } from './components/ToastProvider.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import CredentialGate from './components/CredentialGate.jsx'
import { LocaleProvider, useLocale } from './i18n/LocaleContext.jsx'
import { localeLabelKey } from './i18n/index.js'
import { isPropertiesSurface } from './routes/propertyPaths.js'

const Dashboard = React.lazy(() => import('./pages/Dashboard.jsx'))
const ScraperControl = React.lazy(() => import('./pages/ScraperControl.jsx'))
const Properties = React.lazy(() => import('./pages/Properties.jsx'))

/** Leaf marker so layout routes match without rendering a second page. */
function RouteMatch() {
  return null
}

interface NavEntry {
  path: string
  icon: string
  labelKey: string
  end: boolean
  propertiesSurface?: boolean
}

const NAV: NavEntry[] = [
  { path: '/',           icon: '⚡', labelKey: 'nav.dashboard', end: true },
  { path: '/scraper',    icon: '🕸️', labelKey: 'nav.scraper', end: true },
  { path: '/properties', icon: '🏘️', labelKey: 'nav.properties', end: false, propertiesSurface: true },
]

export default function App() {
  return (
    <ToastProvider>
      <LocaleProvider>
        <BrowserRouter>
          <AppShell />
        </BrowserRouter>
      </LocaleProvider>
    </ToastProvider>
  )
}

function AppShell() {
  const { status, loading } = useSystemStatus(6000)
  const { t, locale, setLocale, supported } = useLocale()

  return (
    <div className="app-shell">
      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-logo">
          <div className="sidebar-logo-icon">🏙️</div>
          <div>
            <div className="sidebar-logo-text">Imóveis AI</div>
            <div className="sidebar-logo-sub">{t('brand.tagline')}</div>
          </div>
        </div>

        <nav className="nav-section">
          <div className="nav-label">{t('nav.label')}</div>
          {NAV.map(({ path, icon, labelKey, end, propertiesSurface }) => (
            <NavItem
              key={path}
              path={path}
              icon={icon}
              label={t(labelKey)}
              end={end}
              propertiesSurface={propertiesSurface}
            />
          ))}
        </nav>

        <div className="sidebar-footer">
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
            {t('chrome.system')}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <ServiceDot label={t('chrome.database')} ok={status?.database?.status === 'ok'} loading={loading} />
            <ServiceDot label={t('chrome.redis')} ok={status?.redis?.status === 'ok'} loading={loading} />
            <ServiceDot label={t('chrome.ollama')} ok={status?.ollama?.status === 'ok'} loading={loading} />
            <ServiceDot label={t('chrome.aiWorker')} ok={!status?.ai_workers_paused} loading={loading} />
          </div>

          <div className="locale-switcher" data-testid="locale-switcher">
            <label htmlFor="locale-select" className="locale-switcher-label">
              {t('locale.label')}
            </label>
            <select
              id="locale-select"
              className="form-input locale-switcher-select"
              value={locale}
              onChange={(e) => setLocale(e.target.value)}
              data-testid="locale-select"
              aria-label={t('locale.label')}
            >
              {supported.map((code) => (
                <option key={code} value={code}>
                  {t(localeLabelKey(code))}
                </option>
              ))}
            </select>
          </div>

          <CredentialGate />
        </div>
      </aside>

      {/* ── Main ── */}
      <main className="main-content">
        <ErrorBoundary>
          <React.Suspense fallback={<div style={{ padding: '24px', color: 'var(--text-secondary)' }}>{t('chrome.loading')}</div>}>
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
  )
}

interface NavItemProps {
  path: string
  icon: string
  label: string
  end: boolean
  propertiesSurface?: boolean
}

function NavItem({ path, icon, label, end, propertiesSurface }: NavItemProps) {
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

interface ServiceDotProps {
  label: string
  ok: boolean
  loading: boolean
}

function ServiceDot({ label, ok, loading }: ServiceDotProps) {
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
