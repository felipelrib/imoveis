/**
 * Product default locale (v0.13-s1.6: pt-BR; `en` stays a switchable preference).
 *
 * It lives in its own module — rather than only in `index.ts` — because
 * `format.ts` needs it and is imported directly by Node-side callers (the
 * Playwright formatter specs). `index.ts` pulls in the JSON catalogs, which Node
 * refuses to import without a `type: json` attribute.
 */
export const DEFAULT_LOCALE = 'pt-BR'
