import { createContext, useContext, useState, useCallback, useRef } from 'react'

const ToastContext = createContext(null)

const TOAST_STYLES = {
  success: {
    background: 'rgba(16,185,129,0.15)',
    border: '1px solid rgba(16,185,129,0.3)',
    color: '#34d399',
    icon: '✔',
  },
  error: {
    background: 'rgba(244,63,94,0.15)',
    border: '1px solid rgba(244,63,94,0.3)',
    color: '#fda4af',
    icon: '✖',
  },
  warning: {
    background: 'rgba(251,191,36,0.15)',
    border: '1px solid rgba(251,191,36,0.3)',
    color: '#fbbf24',
    icon: '⚠',
  },
  info: {
    background: 'rgba(99,102,241,0.15)',
    border: '1px solid rgba(99,102,241,0.3)',
    color: '#818cf8',
    icon: 'ℹ',
  },
}

let toastIdCounter = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timersRef = useRef({})

  const removeToast = useCallback((id) => {
    if (timersRef.current[id]) {
      clearTimeout(timersRef.current[id])
      delete timersRef.current[id]
    }
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  const showToast = useCallback((message, { type = 'info', duration = 4000 } = {}) => {
    const id = ++toastIdCounter
    setToasts(prev => [...prev, { id, message, type }])
    if (duration > 0) {
      timersRef.current[id] = setTimeout(() => removeToast(id), duration)
    }
    return id
  }, [removeToast])

  return (
    <ToastContext.Provider value={showToast}>
      {children}
      {/* Toast container */}
      <div style={{
        position: 'fixed',
        top: 16,
        right: 16,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        maxWidth: 380,
        pointerEvents: 'none',
      }}>
        {toasts.map(t => {
          const s = TOAST_STYLES[t.type] || TOAST_STYLES.info
          return (
            <div
              key={t.id}
              role="status"
              aria-live="polite"
              tabIndex={0}
              onClick={() => removeToast(t.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Escape') {
                  e.preventDefault()
                  removeToast(t.id)
                }
              }}
              aria-label={`${t.message} — press Enter or Escape to dismiss`}
              style={{
                pointerEvents: 'auto',
                background: s.background,
                border: s.border,
                color: s.color,
                padding: '10px 14px',
                borderRadius: 8,
                fontSize: 13,
                fontWeight: 500,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                boxShadow: '0 4px 20px rgba(0,0,0,0.3)',
                transition: 'opacity 0.2s',
              }}
            >
              <span style={{ fontSize: 14, flexShrink: 0 }} aria-hidden="true">{s.icon}</span>
              <span style={{ flex: 1, lineHeight: 1.4 }}>{t.message}</span>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

// Context + companion hook co-located on purpose (standard React pattern); the resulting
// occasional extra Fast Refresh remount is an acceptable dev-only trade-off here.
// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
