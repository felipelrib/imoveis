import { createContext, useContext, useEffect, useState, useCallback, useRef, type ReactNode } from 'react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastOptions {
  type?: ToastType
  duration?: number
}

/**
 * Imperative toast trigger returned by `useToast()`; resolves to the new toast id.
 *
 * The id is informational — there is no dismiss API to spend it on, and the
 * stack is capped (see `MAX_VISIBLE_TOASTS`), so the toast it names may be
 * evicted before it is ever read. No toast is durable under that cap: a
 * `duration: 0` toast is sticky against the timer, not against eviction.
 */
export type ShowToast = (message: string, options?: ToastOptions) => number

interface Toast {
  id: number
  message: string
  type: ToastType
}

interface ToastStyle {
  background: string
  border: string
  color: string
  icon: string
}

const ToastContext = createContext<ShowToast | null>(null)

const TOAST_STYLES: Record<ToastType, ToastStyle> = {
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

/**
 * DESIGN.md toast contract (UX-DR3): the stack is bottom-anchored and holds at
 * most two — newest wins, the oldest is evicted rather than growing a column
 * that eventually reaches the filter bar.
 */
const MAX_VISIBLE_TOASTS = 2

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const timersRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({})

  const removeToast = useCallback((id: number) => {
    if (timersRef.current[id]) {
      clearTimeout(timersRef.current[id])
      delete timersRef.current[id]
    }
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // Eviction (see MAX_VISIBLE_TOASTS) is the one path that drops a toast without
  // going through removeToast, so this is where its auto-dismiss timer is
  // reclaimed: any timer whose toast is no longer rendered is cleared.
  useEffect(() => {
    const live = new Set(toasts.map(t => t.id))
    for (const key of Object.keys(timersRef.current)) {
      const id = Number(key)
      if (!live.has(id)) {
        clearTimeout(timersRef.current[id])
        delete timersRef.current[id]
      }
    }
  }, [toasts])

  // Mount-scoped, so its cleanup runs on unmount only: the reconcile effect
  // above reclaims timers for toasts already dropped, but a provider that
  // unmounts with toasts still on screen would leave their timers to fire
  // `setToasts` against a dead tree.
  useEffect(() => {
    const timers = timersRef.current
    return () => {
      Object.values(timers).forEach(clearTimeout)
    }
  }, [])

  const showToast = useCallback<ShowToast>((message, { type = 'info', duration = 4000 } = {}) => {
    const id = ++toastIdCounter
    setToasts(prev => [...prev, { id, message, type }].slice(-MAX_VISIBLE_TOASTS))
    if (duration > 0) {
      timersRef.current[id] = setTimeout(() => removeToast(id), duration)
    }
    return id
  }, [removeToast])

  return (
    <ToastContext.Provider value={showToast}>
      {children}
      {/* Toast container — bottom-anchored, right-offset so it clears the
          centred `.compare-bar` (fixed, bottom: 24px) without either surface
          knowing about the other. */}
      <div
        data-testid="toast-container"
        style={{
          position: 'fixed',
          bottom: 16,
          right: 16,
          zIndex: 9999,
          display: 'flex',
          flexDirection: 'column',
          gap: 8,
          maxWidth: 380,
          pointerEvents: 'none',
        }}
      >
        {toasts.map(t => {
          const s = TOAST_STYLES[t.type] || TOAST_STYLES.info
          return (
            <div
              key={t.id}
              data-testid="toast"
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
export function useToast(): ShowToast {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
