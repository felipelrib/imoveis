/** Outbound listing links of the detail panel: only trusted platform hosts. */

const TRUSTED_HOSTS = ['olx.com.br', 'quintoandar.com.br', 'zapimoveis.com.br']

/**
 * Returns the URL only if it is https and its host is a known platform host
 * (the host itself or one of its subdomains). Returns null otherwise.
 */
export function sanitizeListingUrl(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'https:') return null
    const host = parsed.hostname
    if (!TRUSTED_HOSTS.some((trusted) => host === trusted || host.endsWith(`.${trusted}`))) return null
    return parsed.href
  } catch {
    return null
  }
}

/**
 * "View original" fallback from a platform + platform id, used when a
 * Property has no Listing rows. Only platforms whose detail page is reachable
 * from the id alone get a template; the others (OLX, ZapImóveis: slug-based
 * URLs) return null, so a wrong-platform link is never rendered (BIN-158).
 */
export function platformFallbackUrl(
  platform: string | null | undefined,
  platformId: string | null | undefined,
): string | null {
  if (!platformId) return null
  if (platform === 'quintoandar') {
    return sanitizeListingUrl(`https://www.quintoandar.com.br/imovel/${encodeURIComponent(platformId)}`)
  }
  return null
}
