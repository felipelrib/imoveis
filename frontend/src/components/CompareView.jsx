import { useEffect, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts'
import { fetchPropertiesByIds, fetchPriceHistory } from '../api.js'

function formatPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `R$ ${Number(value).toLocaleString('pt-BR')}`
}

function formatScore(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return (Number(value) * 100).toFixed(0)
}

function decisioningPrice(property) {
  if (property?.primary_listing?.price != null) return property.primary_listing.price
  if (property?.price != null) return property.price
  return null
}

function formatPricePerM2(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `R$ ${Math.round(Number(value)).toLocaleString('pt-BR')}/m²`
}

function buildChartData(priceHistory) {
  const grouped = {}
  for (const ph of priceHistory) {
    const lineKey = `${ph.listing_type || 'sale'}|${ph.platform || 'unknown'}`
    if (!grouped[lineKey]) grouped[lineKey] = []
    const date = ph.start_ts
      ? new Date(ph.start_ts).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
      : '?'
    grouped[lineKey].push({ date, price: ph.price, lineKey })
  }
  const allDates = [...new Set(
    priceHistory.map((ph) => (
      ph.start_ts
        ? new Date(ph.start_ts).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
        : '?'
    )),
  )]
  const chartData = allDates.map((date) => {
    const point = { date }
    for (const [key, entries] of Object.entries(grouped)) {
      const match = entries.find((e) => e.date === date)
      if (match) point[key] = match.price
    }
    return point
  })
  return { chartData, lineKeys: Object.keys(grouped) }
}

const CHART_COLORS = ['#6366f1', '#10b981', '#f59e0b', '#ef4444', '#06b6d4']

const ATTR_ROWS = [
  { key: 'title', label: 'Title', get: (p) => p.title || '—' },
  { key: 'address', label: 'Address', get: (p) => p.address || '—' },
  { key: 'neighborhood', label: 'Neighbourhood', get: (p) => p.neighborhood_name || '—' },
  { key: 'platform', label: 'Platform', get: (p) => p.platform || p.primary_listing?.platform || '—' },
  {
    key: 'listing_type',
    label: 'Listing type',
    get: (p) => {
      const t = p.primary_listing?.listing_type
      if (t === 'rent') return 'Rent'
      if (t === 'sale') return 'Sale'
      return '—'
    },
  },
  { key: 'price', label: 'Price', get: (p) => formatPrice(decisioningPrice(p)) },
  { key: 'price_per_m2', label: 'Price / m²', get: (p) => formatPricePerM2(p.price_per_m2) },
  { key: 'area', label: 'Area', get: (p) => (p.area_m2 != null ? `${p.area_m2} m²` : '—') },
  { key: 'bedrooms', label: 'Bedrooms', get: (p) => (p.bedrooms != null ? String(p.bedrooms) : '—') },
  { key: 'bathrooms', label: 'Bathrooms', get: (p) => (p.bathrooms != null ? String(p.bathrooms) : '—') },
  { key: 'parking', label: 'Parking', get: (p) => (p.parking != null ? String(p.parking) : '—') },
  { key: 'combined_score', label: 'Combined score', get: (p) => formatScore(p.combined_score) },
  { key: 'stat_score', label: 'Statistical score', get: (p) => formatScore(p.stat_score) },
  { key: 'ai_score', label: 'AI score', get: (p) => formatScore(p.ai_score) },
  { key: 'deal_summary', label: 'Deal summary', get: (p) => p.deal_summary || '—' },
]

/**
 * Side-by-side compare for 2–4 properties from the batch projection + price history.
 * @param {{ ids: string[], onClose: () => void, onClearSelection: () => void }} props
 */
export default function CompareView({ ids, onClose, onClearSelection }) {
  const [properties, setProperties] = useState([])
  const [histories, setHistories] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const batch = await fetchPropertiesByIds(ids)
        const list = Array.isArray(batch?.properties) ? batch.properties : []
        if (cancelled) return
        setProperties(list)

        const entries = await Promise.all(
          list.map(async (p) => {
            try {
              const history = await fetchPriceHistory(p.id)
              return [p.id, Array.isArray(history) ? history : []]
            } catch {
              return [p.id, []]
            }
          }),
        )
        if (cancelled) return
        setHistories(Object.fromEntries(entries))
      } catch (err) {
        if (!cancelled) {
          setError(err?.message || 'Failed to load comparison')
          setProperties([])
          setHistories({})
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [ids])

  return (
    <div className="compare-view" data-testid="compare-view" role="dialog" aria-modal="true" aria-label="Compare properties">
      <div className="compare-view-header">
        <h2 className="compare-view-title">Compare properties</h2>
        <div className="compare-view-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="compare-exit"
            onClick={onClose}
          >
            Back to grid
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="compare-exit-clear"
            onClick={() => {
              onClearSelection()
              onClose()
            }}
          >
            Clear & exit
          </button>
        </div>
      </div>

      {loading && (
        <div className="compare-view-status" data-testid="compare-loading">Loading comparison…</div>
      )}
      {error && (
        <div className="compare-view-status compare-view-status--error" data-testid="compare-error">
          {error}
        </div>
      )}

      {!loading && !error && properties.length === 0 && (
        <div className="compare-view-status" data-testid="compare-empty">
          No properties found for the selected ids.
        </div>
      )}

      {!loading && !error && properties.length > 0 && (
        <div className="compare-view-scroll">
          <div className="compare-table-wrap">
            <table className="compare-table" data-testid="compare-table">
              <thead>
                <tr>
                  <th scope="col" className="compare-attr-col">Attribute</th>
                  {properties.map((p) => (
                    <th key={p.id} scope="col" data-testid={`compare-col-${p.id}`}>
                      {p.title || `Property ${p.id}`}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ATTR_ROWS.map((row) => (
                  <tr key={row.key} data-testid={`compare-row-${row.key}`}>
                    <th scope="row">{row.label}</th>
                    {properties.map((p) => (
                      <td key={p.id}>{row.get(p)}</td>
                    ))}
                  </tr>
                ))}
                <tr data-testid="compare-row-price-history">
                  <th scope="row">Price history</th>
                  {properties.map((p) => {
                    const history = histories[p.id] || []
                    if (history.length === 0) {
                      return (
                        <td key={p.id}>
                          <span className="compare-placeholder" data-testid={`compare-history-empty-${p.id}`}>
                            No price history
                          </span>
                        </td>
                      )
                    }
                    if (history.length < 2) {
                      return (
                        <td key={p.id}>
                          <span className="compare-placeholder" data-testid={`compare-history-short-${p.id}`}>
                            Needs ≥2 points
                          </span>
                        </td>
                      )
                    }
                    const { chartData, lineKeys } = buildChartData(history)
                    return (
                      <td key={p.id}>
                        <div className="compare-history-chart" data-testid={`compare-history-${p.id}`}>
                          <ResponsiveContainer width="100%" height={160}>
                            <LineChart data={chartData}>
                              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                              <XAxis
                                dataKey="date"
                                tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                                tickLine={false}
                                axisLine={false}
                              />
                              <YAxis
                                tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                                tickLine={false}
                                axisLine={false}
                                width={40}
                                tickFormatter={(v) => `R$${(v / 1000).toFixed(0)}k`}
                              />
                              <Tooltip
                                contentStyle={{
                                  background: 'var(--bg-surface)',
                                  border: '1px solid var(--border-subtle)',
                                  borderRadius: 8,
                                  color: 'var(--text-primary)',
                                  fontSize: 11,
                                }}
                                formatter={(value) => `R$ ${Number(value).toLocaleString('pt-BR')}`}
                              />
                              <Legend wrapperStyle={{ fontSize: 10, color: 'var(--text-muted)' }} />
                              {lineKeys.map((key, i) => {
                                const [type, platform] = key.split('|')
                                const label = `${type === 'rent' ? 'Aluguel' : 'Venda'} (${platform})`
                                return (
                                  <Line
                                    key={key}
                                    type="monotone"
                                    dataKey={key}
                                    stroke={CHART_COLORS[i % CHART_COLORS.length]}
                                    strokeWidth={2}
                                    dot={{ r: 2 }}
                                    name={label}
                                    connectNulls={false}
                                  />
                                )
                              })}
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </td>
                    )
                  })}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
