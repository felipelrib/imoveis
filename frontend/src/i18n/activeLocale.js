import { DEFAULT_LOCALE } from './index.js'

/** Module-level locale for non-React callers (api.js). */
let activeLocale = DEFAULT_LOCALE

/** @param {string} locale */
export function setActiveLocale(locale) {
  activeLocale = locale || DEFAULT_LOCALE
}

export function getActiveLocale() {
  return activeLocale
}
