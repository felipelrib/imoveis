import { useState, useEffect } from 'react'
import { fetchStatus, type SystemStatus } from '../api.js'

export interface UseSystemStatusResult {
  status: SystemStatus | null
  loading: boolean
  error: string | null
}

export function useSystemStatus(intervalMs = 8000): UseSystemStatusResult {
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const data = await fetchStatus()
        if (!cancelled) { setStatus(data); setError(null) }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    poll()
    const id = setInterval(poll, intervalMs)
    return () => { cancelled = true; clearInterval(id) }
  }, [intervalMs])

  return { status, loading, error }
}
