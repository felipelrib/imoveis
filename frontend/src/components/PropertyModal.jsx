import { useState, useEffect } from 'react'
import { fetchProperty } from '../api.js'

export default function PropertyModal({ id, onClose }) {
  const [property, setProperty] = useState(null)
  const [loading, setLoading] = useState(true)
  const [imgIndex, setImgIndex] = useState(0)

  useEffect(() => {
    fetchProperty(id)
      .then(setProperty)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [id])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const p = property
  const images = p?.image_urls || []
  const visual = p?.ai_analysis?.visual || {}
  const sentiment = p?.ai_analysis?.sentiment || {}
  const statAnalysis = p?.stat_analysis || {}

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div>
            <div style={{ fontSize: 22, fontWeight: 800, background: 'var(--grad-primary)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
              {loading ? '…' : `R$ ${p?.price?.toLocaleString('pt-BR') || '—'}`}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 3 }}>
              {loading ? '' : (p?.title || p?.address || 'Sem título')}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {!loading && p?.listings && p.listings.map((l, i) => (
              <a 
                key={`${l.platform}-${l.platform_id}-${l.listing_type}`}
                href={l.url} 
                target="_blank" 
                rel="noreferrer"
                className="btn btn-ghost btn-sm"
                style={{ fontSize: 13 }}
              >
                🔗 {l.platform} ({l.listing_type === 'rent' ? 'Aluguel' : 'Venda'}) - R$ {l.price?.toLocaleString('pt-BR')}
              </a>
            ))}
            {!loading && (!p?.listings || p.listings.length === 0) && p?.platform_id && (
              <a 
                href={`https://www.quintoandar.com.br/imovel/${p.platform_id}`} 
                target="_blank" 
                rel="noreferrer"
                className="btn btn-ghost btn-sm"
                style={{ fontSize: 13 }}
              >
                🔗 Ver Original
              </a>
            )}
            <button className="modal-close" onClick={onClose}>✕</button>
          </div>
        </div>

        <div className="modal-body">
          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
              <span className="spinner" style={{ width: 36, height: 36 }} />
            </div>
          ) : (
            <>
              {/* Image gallery */}
              {images.length > 0 && (
                <div style={{ marginBottom: 20 }}>
                  <img
                    src={images[imgIndex]}
                    alt=""
                    style={{ width: '100%', height: 220, objectFit: 'cover', borderRadius: 12, display: 'block', marginBottom: 8 }}
                    onError={e => e.target.style.display = 'none'}
                  />
                  {images.length > 1 && (
                    <div style={{ display: 'flex', gap: 6, overflowX: 'auto' }}>
                      {images.map((url, i) => (
                        <img
                          key={i}
                          src={url}
                          alt=""
                          onClick={() => setImgIndex(i)}
                          style={{ width: 60, height: 45, objectFit: 'cover', borderRadius: 6, cursor: 'pointer', opacity: i === imgIndex ? 1 : 0.5, border: i === imgIndex ? '2px solid var(--accent)' : '2px solid transparent', flexShrink: 0 }}
                          onError={e => e.target.style.display = 'none'}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Key details */}
              <div style={{ marginBottom: 20 }}>
                {[
                  ['Platform', p.platform],
                  ['Address', p.address],
                  ['Neighbourhood', p.neighborhood_name],
                  ['Area', p.area_m2 ? `${p.area_m2} m²` : '—'],
                  ['Bedrooms', p.bedrooms ?? '—'],
                  ['Bathrooms', p.bathrooms ?? '—'],
                  ['Parking', p.parking ?? '—'],
                  ['Price / m²', p.price_per_m2 ? `R$ ${Math.round(p.price_per_m2)}/m²` : '—'],
                  ['Neighbourhood avg / m²', p.neighborhood_mean ? `R$ ${Math.round(p.neighborhood_mean)}/m²` : '—'],
                  ['Percentile in neighbourhood', p.percentile_rank != null ? `${(p.percentile_rank * 100).toFixed(1)}th pct` : '—'],
                  ['Z-score', p.z_score != null ? p.z_score.toFixed(3) : '—'],
                ].filter(([, v]) => v && v !== '—' || v === '—').map(([k, v]) => (
                  <div key={k} className="detail-row">
                    <span className="detail-key">{k}</span>
                    <span className="detail-val">{v}</span>
                  </div>
                ))}
              </div>

              {/* Score bars */}
              <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
                {[
                  { label: 'Combined', val: p.combined_score, color: '#6366f1' },
                  { label: 'Statistical', val: p.stat_score, color: '#06b6d4' },
                  { label: 'AI Quality', val: p.ai_score, color: '#10b981' },
                ].map(({ label, val, color }) => (
                  <div key={label} style={{ flex: 1, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '12px', textAlign: 'center' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.6px', marginBottom: 6 }}>{label}</div>
                    <div style={{ fontSize: 26, fontWeight: 800, color: val != null ? color : 'var(--text-muted)' }}>
                      {val != null ? (val * 100).toFixed(0) : '—'}
                    </div>
                    {val != null && (
                      <div style={{ height: 3, borderRadius: 2, background: 'rgba(255,255,255,0.08)', marginTop: 8 }}>
                        <div style={{ height: '100%', width: `${val * 100}%`, background: color, borderRadius: 2, transition: 'width 0.4s' }} />
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* Score Explanations */}
              <div style={{ marginBottom: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
                {statAnalysis.category && (
                  <div style={{ padding: '12px', background: 'rgba(6, 182, 212, 0.1)', border: '1px solid rgba(6, 182, 212, 0.2)', borderRadius: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#0891b2', marginBottom: 4 }}>Statistical: {statAnalysis.category}</div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{statAnalysis.reasoning}</div>
                  </div>
                )}
                
                {visual.category && (
                  <div style={{ padding: '12px', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.2)', borderRadius: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#059669', marginBottom: 4 }}>Visual Condition: {visual.category}</div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{visual.reasoning}</div>
                  </div>
                )}

                {sentiment.category && (
                  <div style={{ padding: '12px', background: 'rgba(139, 92, 246, 0.1)', border: '1px solid rgba(139, 92, 246, 0.2)', borderRadius: 8 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#7c3aed', marginBottom: 4 }}>Location Sentiment: {sentiment.category}</div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{sentiment.reasoning}</div>
                  </div>
                )}
              </div>

              {/* AI analysis */}
              {(visual.features_detected?.length > 0 || visual.issues_detected?.length > 0 || sentiment.green_flags?.length > 0 || sentiment.red_flags?.length > 0) && (
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                    🤖 AI Analysis
                  </div>

                  {visual.features_detected?.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Modern features</div>
                      <div className="flags">
                        {visual.features_detected.map(f => <span key={f} className="flag feature">✦ {f}</span>)}
                      </div>
                    </div>
                  )}

                  {visual.issues_detected?.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Issues detected</div>
                      <div className="flags">
                        {visual.issues_detected.map(f => <span key={f} className="flag red">⚠ {f}</span>)}
                      </div>
                    </div>
                  )}

                  {sentiment.green_flags?.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Location positives</div>
                      <div className="flags">
                        {sentiment.green_flags.map(f => <span key={f} className="flag green">✔ {f}</span>)}
                      </div>
                    </div>
                  )}

                  {sentiment.red_flags?.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>Location concerns</div>
                      <div className="flags">
                        {sentiment.red_flags.map(f => <span key={f} className="flag red">✖ {f}</span>)}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Description */}
              {p.description && (
                <div style={{ marginTop: 16, padding: '14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8, fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                  {p.description}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
