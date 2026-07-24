import { useState, useEffect } from 'react'
import { fetchProperty, checkWatchlist, addToWatchlist, removeFromWatchlist, checkFavourite, addFavourite, removeFavourite, fetchPriceHistory } from '../api.js'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend
} from 'recharts'

/**
 * Returns the URL only if it starts with https:// and matches a known platform host.
 * Returns null if the URL is unsafe or invalid.
 */
function sanitizeListingUrl(url) {
    if (!url) return null;
    try {
        const parsed = new URL(url);
        if (parsed.protocol !== 'https:') return null;
        const trusted = ['olx.com.br', 'quintoandar.com.br', 'zapimoveis.com.br'];
        if (!trusted.some(host => parsed.hostname.endsWith(host))) return null;
        return parsed.href;
    } catch {
        return null;
    }
}

export default function PropertyModal({ id, onClose }) {
  const [property, setProperty] = useState(null)
  const [loading, setLoading] = useState(true)
  const [imgIndex, setImgIndex] = useState(0)
  const [isWatched, setIsWatched] = useState(false)
  const [isFavourited, setIsFavourited] = useState(false)
  const [priceHistory, setPriceHistory] = useState([])

  useEffect(() => {
    fetchProperty(id)
      .then(setProperty)
      .catch(console.error)
      .finally(() => setLoading(false))
    checkWatchlist(id)
      .then(data => setIsWatched(data.watched))
      .catch(() => {})
    checkFavourite(id)
      .then(data => setIsFavourited(data.favourited))
      .catch(() => {})
    fetchPriceHistory(id)
      .then(setPriceHistory)
      .catch(() => {})
  }, [id])

  const [dropPct, setDropPct] = useState(5)

  const toggleWatchlist = async () => {
    try {
      if (isWatched) {
        await removeFromWatchlist(id)
        setIsWatched(false)
      } else {
        await addToWatchlist(id, dropPct)
        setIsWatched(true)
      }
    } catch (err) {
      console.error('Watchlist toggle failed:', err)
    }
  }

  const toggleFavourite = async () => {
    try {
      if (isFavourited) {
        await removeFavourite(id)
        setIsFavourited(false)
      } else {
        await addFavourite(id)
        setIsFavourited(true)
      }
    } catch (err) {
      console.error('Favourite toggle failed:', err)
    }
  }

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
              {loading ? '' : (p?.title || p?.address || 'Untitled')}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {!loading && (
              <>
                <button
                  className={`favourite-btn ${isFavourited ? 'favourited' : ''}`}
                  onClick={toggleFavourite}
                  title={isFavourited ? 'Remove from favourites' : 'Add to favourites'}
                  aria-label={isFavourited ? 'Remove from favourites' : 'Add to favourites'}
                  style={{ fontSize: 18, padding: '6px 10px' }}
                >
                  {isFavourited ? '★' : '☆'}
                </button>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'var(--bg-card)', padding: '4px 12px', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
                  {!isWatched && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Alert at</span>
                      <input
                        type="number"
                        min="1" max="50"
                        value={dropPct}
                        onChange={e => setDropPct(Number(e.target.value))}
                        style={{ width: 44, padding: '2px 4px', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 4, color: 'var(--text-primary)', textAlign: 'center' }}
                      />
                      <span style={{ color: 'var(--text-secondary)' }}>% drop</span>
                    </div>
                  )}
                  <button
                    className={`watchlist-btn ${isWatched ? 'watched' : ''}`}
                    onClick={toggleWatchlist}
                    title={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
                    aria-label={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
                    style={{ fontSize: 18, padding: '6px 10px', background: 'none', border: 'none' }}
                  >
                    {isWatched ? '🔔' : '☆'}
                  </button>
                </div>
              </>
            )}
            {!loading && p?.listings && p.listings.map((l, i) => {
              const safeUrl = sanitizeListingUrl(l.url);
              if (!safeUrl) return null;
              return (
                <a
                  key={`${l.platform}-${l.platform_id}-${l.listing_type}`}
                  href={safeUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-ghost btn-sm"
                  style={{ fontSize: 13 }}
                >
                  🔗 {l.platform} ({l.listing_type === 'rent' ? 'Rent' : 'Sale'}) - R$ {l.price?.toLocaleString('pt-BR')}
                </a>
              )
            })}
            {!loading && (!p?.listings || p.listings.length === 0) && p?.platform_id && (
              <a
                href={`https://www.quintoandar.com.br/imovel/${p.platform_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-ghost btn-sm"
                style={{ fontSize: 13 }}
              >
                🔗 View original
              </a>
            )}
            <button className="modal-close" onClick={onClose} aria-label="Close modal">✕</button>
          </div>
        </div>

        <div className="modal-body">
          {loading ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
              <span className="spinner" style={{ width: 36, height: 36 }} />
            </div>
          ) : (
            <>
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
                          alt={`Thumbnail ${i + 1}`}
                          onClick={() => setImgIndex(i)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              setImgIndex(i);
                            }
                          }}
                          style={{ width: 60, height: 45, objectFit: 'cover', borderRadius: 6, cursor: 'pointer', opacity: i === imgIndex ? 1 : 0.5, border: i === imgIndex ? '2px solid var(--accent)' : '2px solid transparent', flexShrink: 0 }}
                          onError={e => e.target.style.display = 'none'}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

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

              {/* Per-platform listings table */}
              {p?.listings && p.listings.length > 0 && (() => {
                const groups = {}
                for (const l of p.listings) {
                  const key = l.listing_type || 'sale'
                  if (!groups[key]) groups[key] = []
                  groups[key].push(l)
                }
                const typeLabel = (t) => t === 'rent' ? 'Rent' : 'Sale'
                const typeColor = (t) => t === 'rent'
                  ? { bg: 'rgba(99,102,241,0.1)', border: 'rgba(99,102,241,0.3)', header: '#818cf8' }
                  : { bg: 'rgba(16,185,129,0.1)', border: 'rgba(16,185,129,0.3)', header: '#34d399' }
                const money = (v) => (v != null && v !== 0 ? `R$ ${Number(v).toLocaleString('pt-BR')}` : '—')
                return (
                  <div style={{ marginBottom: 20 }} data-testid="listings-by-platform">
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                      Listings by Platform
                    </div>
                    {Object.entries(groups).map(([type, listings]) => {
                      const colors = typeColor(type)
                      const minPrice = Math.min(...listings.map(l => l.price ?? Infinity))
                      return (
                        <div key={type} style={{ marginBottom: 12 }}>
                          <div style={{ fontSize: 12, fontWeight: 700, color: colors.header, marginBottom: 6, padding: '4px 8px', background: colors.bg, border: `1px solid ${colors.border}`, borderRadius: '6px 6px 0 0' }}>
                            {typeLabel(type)} ({listings.length} {listings.length === 1 ? 'listing' : 'listings'})
                          </div>
                          <div style={{ overflowX: 'auto' }}>
                            <table className="listings-table">
                              <thead>
                                <tr>
                                  <th>Platform</th>
                                  <th>Price</th>
                                  <th>Base</th>
                                  <th>Condo</th>
                                  <th>IPTU</th>
                                  <th></th>
                                </tr>
                              </thead>
                              <tbody>
                                {listings.sort((a, b) => (a.price || Infinity) - (b.price || Infinity)).map((l) => {
                                  const isBest = l.price !== null && l.price !== undefined && l.price === minPrice
                                  return (
                                    <tr key={`${l.platform}-${l.platform_listing_id || l.platform_id}`} className={isBest ? 'best-price' : ''}>
                                      <td style={{ fontWeight: 600 }}>
                                        {l.platform}
                                        {l.fees_bundled ? (
                                          <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-muted)' }} title="Condo/IPTU bundled or derived">bundled fees</span>
                                        ) : null}
                                      </td>
                                      <td style={{ fontWeight: isBest ? 800 : 400, color: isBest ? '#34d399' : 'inherit' }}>
                                        {isBest && '★ '}{money(l.price)}
                                      </td>
                                      <td>{money(l.base_price)}</td>
                                      <td>{money(l.condo_fee)}</td>
                                      <td>{money(l.iptu)}</td>
                                      <td>
                                        {sanitizeListingUrl(l.url) ? (
                                          <a href={sanitizeListingUrl(l.url)} target="_blank" rel="noopener noreferrer" className="listing-link" title="Open on platform">
                                            →
                                          </a>
                                        ) : (
                                          <span className="listing-link-unavailable" title="Link unavailable">✕</span>
                                        )}
                                      </td>
                                    </tr>
                                  )
                                })}
                              </tbody>
                            </table>
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '8px 4px 0' }} data-testid={`listing-attrs-${type}`}>
                            {listings.map((l) => {
                              const chips = []
                              if (l.is_furnished === true) chips.push('Furnished')
                              else if (l.is_furnished === false) chips.push('Unfurnished')
                              if (l.accepts_pets === true) chips.push('Pets OK')
                              else if (l.accepts_pets === false) chips.push('No pets')
                              if (!chips.length) return null
                              return (
                                <div key={`attrs-${l.platform}-${l.platform_listing_id}`} style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                                  <span style={{ fontWeight: 600, marginRight: 6 }}>{l.platform}:</span>
                                  {chips.map((c) => (
                                    <span
                                      key={c}
                                      data-testid={`attr-chip-${c.toLowerCase().replace(/\s+/g, '-')}`}
                                      style={{
                                        display: 'inline-block',
                                        marginRight: 6,
                                        padding: '2px 8px',
                                        borderRadius: 999,
                                        border: '1px solid var(--border-subtle)',
                                        background: 'var(--bg-card)',
                                      }}
                                    >
                                      {c}
                                    </span>
                                  ))}
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}

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

              {p.deal_summary && (
                <div style={{
                  marginBottom: 20,
                  padding: '16px 20px',
                  background: 'linear-gradient(135deg, rgba(99,102,241,0.15), rgba(139,92,246,0.15))',
                  border: '1px solid rgba(99,102,241,0.3)',
                  borderRadius: 12,
                }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: 6 }}>
                    💡 Deal verdict
                  </div>
                  <div style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.5, background: 'linear-gradient(135deg, #6366f1, #a78bfa)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                    {p.deal_summary}
                  </div>
                </div>
              )}

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

              {/* Price history chart */}
              {priceHistory.length >= 2 && (() => {
                // Group by listing_type + platform for separate lines
                const grouped = {}
                for (const ph of priceHistory) {
                  const lineKey = `${ph.listing_type || 'sale'}|${ph.platform || 'unknown'}`
                  if (!grouped[lineKey]) grouped[lineKey] = []
                  const date = ph.start_ts ? new Date(ph.start_ts).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) : '?'
                  grouped[lineKey].push({ date, price: ph.price, lineKey })
                }
                // Build unified date-based data
                const allDates = [...new Set(priceHistory.map(ph => ph.start_ts ? new Date(ph.start_ts).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) : '?'))]
                const chartData = allDates.map(date => {
                  const point = { date }
                  for (const [key, entries] of Object.entries(grouped)) {
                    const match = entries.find(e => e.date === date)
                    if (match) point[key] = match.price
                  }
                  return point
                })
                const lineKeys = Object.keys(grouped)
                const colors = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#06b6d4']
                return (
                  <div style={{ marginBottom: 20 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.8px' }}>
                      📈 Price History
                    </div>
                    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: '12px 8px 0' }}>
                      <ResponsiveContainer width="100%" height={200}>
                        <LineChart data={chartData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                          <XAxis dataKey="date" tick={{ fill: 'var(--text-muted)', fontSize: 11 }} tickLine={false} axisLine={false} />
                          <YAxis
                            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                            tickLine={false} axisLine={false}
                            tickFormatter={(v) => `R$${(v / 1000).toFixed(0)}k`}
                          />
                          <Tooltip
                            contentStyle={{ background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8, color: 'var(--text-primary)', fontSize: 12 }}
                            formatter={(value) => `R$ ${Number(value).toLocaleString('pt-BR')}`}
                          />
                          <Legend wrapperStyle={{ fontSize: 11, color: 'var(--text-muted)' }} />
                          {lineKeys.map((key, i) => {
                            const [type, platform] = key.split('|')
                            const label = `${type === 'rent' ? 'Rent' : 'Sale'} (${platform})`
                            return (
                              <Line key={key} type="monotone" dataKey={key} stroke={colors[i % colors.length]}
                                strokeWidth={2} dot={{ r: 3 }} name={label} connectNulls={false} />
                            )
                          })}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                )
              })()}
              {priceHistory.length > 0 && priceHistory.length < 2 && (
                <div style={{ marginBottom: 20, padding: '10px 14px', borderRadius: 8, background: 'var(--bg-card)', border: '1px solid var(--border-subtle)', fontSize: 12, color: 'var(--text-muted)' }}>
                  Price history needs at least 2 data points to display a chart.
                </div>
              )}

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
