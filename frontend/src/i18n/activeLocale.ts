import { DEFAULT_LOCALE } from './index.js'

/** Module-level locale for non-React callers (api.ts). */
let activeLocale: string = DEFAULT_LOCALE

export function setActiveLocale(locale: string | null | undefined): void {
  activeLocale = locale || DEFAULT_LOCALE
}

export function getActiveLocale(): string {
  return activeLocale
}
