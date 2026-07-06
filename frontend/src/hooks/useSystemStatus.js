import { useState, useEffect, useRef } from 'react'
import { fetchStatus } from '../api.js'

export function useSystemStatus(intervalMs = 8000) {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const data = await fetchStatus()
        if (!cancelled) { setStatus(data); setError(null) }
      } catch (e) {
        if (!cancelled) setError(e.message)
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
