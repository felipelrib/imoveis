import { useState, useEffect } from 'react'
import { fetchProperties } from '../api.js'
import PropertyModal from '../components/PropertyModal.jsx'

const SORT_OPTIONS = [
  { value: 'combined_score', label: '⭐ Best Score' },
  { value: 'price', label: '💰 Price (asc)' },
  { value: 'price_desc', label: '💰 Price (desc)' },
  { value: 'created_at', label: '🕒 Newest' },
  { value: 'area_m2', label: '📐 Area' },
]

export default function Properties() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [sortBy, setSortBy] = useState('combined_score')
  const [sortDir, setSortDir] = useState('desc')
  const [maxPrice, setMaxPrice] = useState('')
  const [minBedrooms, setMinBedrooms] = useState('')
  const [minScore, setMinScore] = useState('')
  const [selectedId, setSelectedId] = useState(null)

  const load = async (p = page) => {
    setLoading(true)
    try {
      const isPriceDesc = sortBy === 'price_desc'
      const actualSortBy = isPriceDesc ? 'price' : sortBy
      const actualSortDir = sortBy === 'price' ? 'asc' : isPriceDesc ? 'desc' : sortDir

      const res = await fetchProperties({
        page: p,
        sortBy: actualSortBy,
        sortDir: actualSortDir,
        maxPrice: maxPrice ? parseFloat(maxPrice) : undefined,
        minBedrooms: minBedrooms ? parseInt(minBedrooms) : undefined,
        minScore: minScore ? parseFloat(minScore) : undefined,
      })
      setData(res)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load(1); setPage(1) }, [sortBy, maxPrice, minBedrooms, minScore])
  useEffect(() => { load(page) }, [page])

  const properties = data?.properties || []
  const pages = data?.pages || 1

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Properties</h1>
        <p className="page-subtitle">
          {data ? `${data.total.toLocaleString()} properties found` : 'Loading…'}
        </p>
      </div>

      {/* Toolbar */}
      <div className="toolbar">
        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Sort by</label>
          <select className="form-select" style={{ width: 160 }} value={sortBy} onChange={e => setSortBy(e.target.value)}>
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Max price R$</label>
          <input
            className="form-input" style={{ width: 120 }}
            type="number" placeholder="Any"
            value={maxPrice} onChange={e => setMaxPrice(e.target.value)}
          />
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Min bedrooms</label>
          <select className="form-select" style={{ width: 90 }} value={minBedrooms} onChange={e => setMinBedrooms(e.target.value)}>
            <option value="">Any</option>
            {[1,2,3,4,5].map(n => <option key={n} value={n}>{n}+</option>)}
          </select>
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>Min AI score</label>
          <select className="form-select" style={{ width: 100 }} value={minScore} onChange={e => setMinScore(e.target.value)}>
            <option value="">Any</option>
            <option value="0.7">0.7+</option>
            <option value="0.8">0.8+</option>
            <option value="0.9">0.9+</option>
          </select>
        </div>

        <button className="btn btn-ghost btn-sm" onClick={() => { setMaxPrice(''); setMinBedrooms(''); setMinScore('') }}>
          ✕ Clear
        </button>
      </div>

      {/* Grid */}
      {loading ? (
        <div className="loading-grid">
          {Array.from({ length: 12 }).map((_, i) => <div key={i} className="skeleton" />)}
        </div>
      ) : properties.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🏚️</div>
          <h3>No properties yet</h3>
          <p>Go to Scraper Control and trigger your first ingestion job to start building the database.</p>
          <a href="/scraper" className="btn btn-primary">Go to Scraper Control →</a>
        </div>
      ) : (
        <>
          <div className="property-grid">
            {properties.map(p => (
              <PropertyCard key={p.id} property={p} onClick={() => setSelectedId(p.id)} />
            ))}
          </div>

          {pages > 1 && (
            <div className="pagination">
              <button className="page-btn" onClick={() => setPage(1)} disabled={page === 1}>«</button>
              <button className="page-btn" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}>‹</button>
              {Array.from({ length: Math.min(7, pages) }, (_, i) => {
                const n = Math.max(1, Math.min(pages - 6, page - 3)) + i
                return (
                  <button key={n} className={`page-btn ${n === page ? 'active' : ''}`} onClick={() => setPage(n)}>
                    {n}
                  </button>
                )
              })}
              <button className="page-btn" onClick={() => setPage(p => Math.min(pages, p + 1))} disabled={page === pages}>›</button>
              <button className="page-btn" onClick={() => setPage(pages)} disabled={page === pages}>»</button>
            </div>
          )}
        </>
      )}

      {selectedId && <PropertyModal id={selectedId} onClose={() => setSelectedId(null)} />}
    </div>
  )
}

function scoreColor(v) {
  if (v == null) return 'var(--text-muted)'
  if (v >= 0.7) return 'var(--score-high)'
  if (v >= 0.4) return 'var(--score-mid)'
  return 'var(--score-low)'
}

function PropertyCard({ property: p, onClick }) {
  const img = (p.image_urls || [])[0]
  const combined = p.combined_score

  return (
    <div className="property-card" onClick={onClick}>
      {img
        ? <img className="property-image" src={img} alt={p.title || 'property'} loading="lazy" onError={e => { e.target.style.display='none'; e.target.nextSibling.style.display='flex' }} />
        : null
      }
      <div className="property-image-placeholder" style={{ display: img ? 'none' : 'flex' }}>🏠</div>

      <div className="property-body">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div className="property-price">
            R$ {p.price ? p.price.toLocaleString('pt-BR') : '—'}
          </div>
          {(p.available_for_rent || p.available_for_sale) && (
            <div style={{ display: 'flex', gap: 4 }}>
              {p.available_for_rent && <span style={{ padding: '2px 6px', fontSize: 10, background: 'rgba(99,102,241,0.2)', color: '#818cf8', borderRadius: 4, fontWeight: 700 }}>ALUGUEL</span>}
              {p.available_for_sale && <span style={{ padding: '2px 6px', fontSize: 10, background: 'rgba(16,185,129,0.2)', color: '#34d399', borderRadius: 4, fontWeight: 700 }}>VENDA</span>}
            </div>
          )}
        </div>
        <div className="property-title">{p.title || p.address || 'Sem título'}</div>

        <div className="property-attrs">
          {p.bedrooms != null  && <span className="property-attr">🛏 {p.bedrooms}</span>}
          {p.bathrooms != null && <span className="property-attr">🚿 {p.bathrooms}</span>}
          {p.parking != null   && <span className="property-attr">🚗 {p.parking}</span>}
          {p.area_m2 != null   && <span className="property-attr">📐 {p.area_m2}m²</span>}
          {p.price_per_m2      && <span className="property-attr" style={{ color: 'var(--text-muted)' }}>R${Math.round(p.price_per_m2)}/m²</span>}
          {p.neighborhood_name && <span className="property-attr" style={{ color: 'var(--text-muted)' }}>📍 {p.neighborhood_name}</span>}
        </div>
        
        {p.description && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
            {p.description}
          </div>
        )}

        {/* Scores */}
        <div className="property-scores" style={{ marginTop: 12 }}>
            {p.combined_score != null && (
              <div className="score-badge combined">
                <span className="score-badge-label">Score</span>
                <span className="score-badge-val" style={{ color: scoreColor(p.combined_score) }}>
                  {(p.combined_score * 100).toFixed(0)}
                </span>
              </div>
            )}
            
            <div className="score-badge stat">
              <span className="score-badge-label">Stat</span>
              <span className="score-badge-val">{p.stat_score != null ? (p.stat_score * 100).toFixed(0) : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 'normal' }}>⌛ Calc</span>}</span>
            </div>
            
            <div className="score-badge ai">
              <span className="score-badge-label">AI</span>
              <span className="score-badge-val">{p.ai_score != null ? (p.ai_score * 100).toFixed(0) : <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 'normal' }}>⌛ Calc</span>}</span>
            </div>
          </div>

        {/* AI flags */}
        {((p.ai_green_flags || []).length > 0 || (p.ai_red_flags || []).length > 0) && (
          <div className="flags" style={{ marginTop: 10 }}>
            {(p.ai_green_flags || []).slice(0, 2).map(f => (
              <span key={f} className="flag green">✔ {f}</span>
            ))}
            {(p.ai_red_flags || []).slice(0, 1).map(f => (
              <span key={f} className="flag red">✖ {f}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
