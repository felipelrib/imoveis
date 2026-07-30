import { useState, useEffect, type Dispatch, type SetStateAction } from 'react'
import { fetchAlerts, type AlertItem } from '../api.js'

export interface UseAlertsResult {
  alerts: AlertItem[]
  loading: boolean
  error: string | null
  setAlerts: Dispatch<SetStateAction<AlertItem[]>>
}

export function useAlerts(pollInterval = 30000): UseAlertsResult {
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const data = await fetchAlerts()
        if (cancelled) return
        setAlerts(data)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    poll()
    const id = setInterval(poll, pollInterval)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [pollInterval])

  return { alerts, loading, error, setAlerts }
}
