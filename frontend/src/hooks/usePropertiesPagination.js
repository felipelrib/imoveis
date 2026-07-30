import { useState } from 'react'

const PAGE_WINDOW = 7

/**
 * Owns the current page number for the Properties/Favourites list.
 * `pages` (total page count) is derived from fetched data and stays owned
 * by the caller — this hook only tracks the raw `page` navigation state.
 *
 * Deliberately a thin wrapper around `useState`: Properties.jsx's refetch
 * effects key off `page` directly (`useEffect(..., [page])`), and returning
 * the plain state setter (not a memoized action) preserves the existing
 * "navigating back to page 1 always refetches" behavior (BIN-141 split —
 * no behavior change).
 */
export function usePropertiesPagination(initialPage = 1) {
  const [page, setPage] = useState(initialPage)
  return { page, setPage }
}

/**
 * Sliding window of page numbers to render around the current page
 * (max `windowSize`, default 7) — same formula as the pre-split inline
 * pager in Properties.jsx.
 */
export function getPageWindow(page, pages, windowSize = PAGE_WINDOW) {
  return Array.from({ length: Math.min(windowSize, pages) }, (_, i) => (
    Math.max(1, Math.min(pages - (windowSize - 1), page - Math.floor(windowSize / 2))) + i
  ))
}
