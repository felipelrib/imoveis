import { getPageWindow } from '../../hooks/usePropertiesPagination.js'

/**
 * Numbered pager for the properties grid. Mirrors the exact button set +
 * sliding page-number window from the pre-split Properties.jsx (BIN-141) —
 * `onPageChange` is the raw `setPage` state setter, so it accepts either a
 * page number or a functional updater exactly as before (this matters for
 * "next"/"prev", which use functional updates).
 *
 * Rendering (whether `pages > 1`, whether we're in the favourites view) is
 * still gated by the caller, same as pre-split.
 */
export default function PropertiesPagination({ page, pages, onPageChange }) {
  return (
    <div className="pagination">
      <button className="page-btn" onClick={() => onPageChange(1)} disabled={page === 1}>«</button>
      <button className="page-btn" onClick={() => onPageChange((p) => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
      {getPageWindow(page, pages).map((n) => (
        <button key={n} className={`page-btn ${n === page ? 'active' : ''}`} onClick={() => onPageChange(n)}>{n}</button>
      ))}
      <button className="page-btn" onClick={() => onPageChange((p) => Math.min(pages, p + 1))} disabled={page === pages}>›</button>
      <button className="page-btn" onClick={() => onPageChange(pages)} disabled={page === pages}>»</button>
    </div>
  )
}
