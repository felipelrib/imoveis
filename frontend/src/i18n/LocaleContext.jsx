import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { fetchLocale, hasApiKey, updateLocale } from '../api.js'
import { useToast } from '../components/ToastProvider.jsx'
import {
  DEFAULT_LOCALE,
  normalizeLocale,
  SUPPORTED_LOCALES,
  t as translate,
} from './index.js'

const LocaleContext = createContext({
  locale: DEFAULT_LOCALE,
  supported: SUPPORTED_LOCALES,
  t: (key, params) => translate(DEFAULT_LOCALE, key, params),
  setLocale: async () => {},
  ready: false,
})

export function LocaleProvider({ children }) {
  const showToast = useToast()
  const [locale, setLocaleState] = useState(DEFAULT_LOCALE)
  const [supported, setSupported] = useState(SUPPORTED_LOCALES)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function boot() {
      if (!hasApiKey()) {
        document.documentElement.lang = DEFAULT_LOCALE
        if (!cancelled) setReady(true)
        return
      }
      try {
        const data = await fetchLocale()
        if (cancelled) return
        const next = normalizeLocale(data.locale)
        setLocaleState(next)
        if (Array.isArray(data.supported) && data.supported.length) {
          setSupported(data.supported.filter((code) => SUPPORTED_LOCALES.includes(code)))
        }
        document.documentElement.lang = next
      } catch {
        document.documentElement.lang = DEFAULT_LOCALE
      } finally {
        if (!cancelled) setReady(true)
      }
    }

    boot()
    return () => {
      cancelled = true
    }
  }, [])

  const setLocale = useCallback(
    async (nextRaw) => {
      const next = normalizeLocale(nextRaw)
      if (!hasApiKey()) {
        showToast(translate(locale, 'locale.needCredential'), { type: 'warning' })
        return
      }
      try {
        const data = await updateLocale(next)
        const applied = normalizeLocale(data.locale)
        setLocaleState(applied)
        document.documentElement.lang = applied
        if (Array.isArray(data.supported) && data.supported.length) {
          setSupported(data.supported.filter((code) => SUPPORTED_LOCALES.includes(code)))
        }
      } catch (err) {
        showToast(err.message || translate(locale, 'locale.saveFailed'), { type: 'error' })
      }
    },
    [locale, showToast]
  )

  const t = useCallback(
    (key, params) => translate(locale, key, params),
    [locale]
  )

  const value = { locale, supported, t, setLocale, ready }

  return (
    <LocaleContext.Provider value={value}>
      {children}
    </LocaleContext.Provider>
  )
}

export function useLocale() {
  return useContext(LocaleContext)
}

export function useT() {
  return useLocale().t
}
