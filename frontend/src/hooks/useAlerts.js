import { useState, useEffect } from 'react'
import { fetchAlerts } from '../api.js'

export function useAlerts(pollInterval = 30000) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const poll = async () => {
      try {
        const data = await fetchAlerts()
        if (cancelled) return
        setAlerts(data)
        setError(null)
      } catch (err) {
        if (!cancelled) setError(err.message)
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
