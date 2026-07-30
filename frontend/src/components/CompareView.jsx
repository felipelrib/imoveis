import { useEffect, useRef, useState } from 'react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts'
import { fetchPropertiesByIds, fetchPriceHistory } from '../api.js'
import { formatPlatform } from '../labels.js'
import { useLocale } from '../i18n/LocaleContext.jsx'
import { labelRiskFlag } from '../i18n/index.js'
import { formatCurrency, formatDate, formatPricePerM2 } from '../i18n/format.js'
import { decisioningPrice } from '../utils/primaryListing.js'

function formatScore(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return (Number(value) * 100).toFixed(0)
}

function buildChartData(priceHistory, locale) {
  const grouped = {}
  for (const ph of priceHistory) {
    const lineKey = `${ph.listing_type || 'sale'}|${ph.platform || 'unknown'}`
    if (!grouped[lineKey]) grouped[lineKey] = []
    const date = ph.start_ts ? formatDate(ph.start_ts, locale) : '?'
    grouped[lineKey].push({ date, price: ph.price, lineKey })
  }
  const allDates = [...new Set(
    priceHistory.map((ph) => (ph.start_ts ? formatDate(ph.start_ts, locale) : '?')),
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

const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]), '
  + 'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

const ATTR_ROWS = [
  { key: 'title', labelKey: 'attr.title', get: (p) => p.title || '—' },
  { key: 'address', labelKey: 'attr.address', get: (p) => p.address || '—' },
  { key: 'neighborhood', labelKey: 'attr.neighbourhood', get: (p) => p.neighborhood_name || '—' },
  {
    key: 'neighbourhood_score',
    labelKey: 'attr.neighbourhoodQuality',
    get: (p) => formatScore(p.neighbourhood_quality?.neighbourhood_score),
  },
  {
    key: 'amenity_score',
    labelKey: 'attr.amenityScore',
    get: (p) => formatScore(p.neighbourhood_quality?.amenity_score),
  },
  {
    key: 'transit_score',
    labelKey: 'attr.transitScore',
    get: (p) => formatScore(p.neighbourhood_quality?.transit_score),
  },
  {
    key: 'access_score',
    labelKey: 'attr.accessScore',
    get: (p) => formatScore(p.neighbourhood_quality?.access_score),
  },
  {
    key: 'safety_score',
    labelKey: 'attr.safetyScore',
    get: (p) => formatScore(p.neighbourhood_quality?.safety_score),
  },
  {
    key: 'risk_flags',
    labelKey: 'attr.neighbourhoodRisks',
    get: (p, { locale }) => {
      const flags = p.neighbourhood_quality?.risk_flags
      return Array.isArray(flags) && flags.length
        ? flags.map((f) => labelRiskFlag(locale, f)).join(', ')
        : '—'
    },
  },
  { key: 'platform', labelKey: 'attr.platform', get: (p) => formatPlatform(p.platform || p.primary_listing?.platform) },
  {
    key: 'listing_type',
    labelKey: 'attr.listingType',
    get: (p, { t }) => {
      const type = p.primary_listing?.listing_type
      if (type === 'rent') return t('common.rent')
      if (type === 'sale') return t('common.sale')
      return '—'
    },
  },
  { key: 'price', labelKey: 'attr.price', get: (p, { locale }) => formatCurrency(decisioningPrice(p), locale) },
  { key: 'price_per_m2', labelKey: 'attr.pricePerM2', get: (p, { locale }) => formatPricePerM2(p.price_per_m2, locale) },
  {
    key: 'price_per_m2_rent',
    labelKey: 'attr.pricePerM2Rent',
    get: (p, { locale }) => formatPricePerM2(p.price_per_m2_rent, locale),
  },
  {
    key: 'neighborhood_mean_rent',
    labelKey: 'attr.neighbourhoodAvgPerM2Rent',
    get: (p, { locale }) => formatPricePerM2(p.neighborhood_mean_rent, locale),
  },
  {
    key: 'price_per_m2_sale',
    labelKey: 'attr.pricePerM2Sale',
    get: (p, { locale }) => formatPricePerM2(p.price_per_m2_sale, locale),
  },
  {
    key: 'neighborhood_mean_sale',
    labelKey: 'attr.neighbourhoodAvgPerM2Sale',
    get: (p, { locale }) => formatPricePerM2(p.neighborhood_mean_sale, locale),
  },
  { key: 'area', labelKey: 'attr.area', get: (p) => (p.area_m2 != null ? `${p.area_m2} m²` : '—') },
  { key: 'bedrooms', labelKey: 'attr.bedrooms', get: (p) => (p.bedrooms != null ? String(p.bedrooms) : '—') },
  { key: 'bathrooms', labelKey: 'attr.bathrooms', get: (p) => (p.bathrooms != null ? String(p.bathrooms) : '—') },
  { key: 'parking', labelKey: 'attr.parking', get: (p) => (p.parking != null ? String(p.parking) : '—') },
  { key: 'combined_score', labelKey: 'attr.combinedScore', get: (p) => formatScore(p.combined_score) },
  { key: 'combined_score_rent', labelKey: 'attr.combinedScoreRent', get: (p) => formatScore(p.combined_score_rent) },
  { key: 'combined_score_sale', labelKey: 'attr.combinedScoreSale', get: (p) => formatScore(p.combined_score_sale) },
  { key: 'stat_score', labelKey: 'attr.statisticalScore', get: (p) => formatScore(p.stat_score) },
  { key: 'stat_score_rent', labelKey: 'attr.statisticalScoreRent', get: (p) => formatScore(p.stat_score_rent) },
  { key: 'stat_score_sale', labelKey: 'attr.statisticalScoreSale', get: (p) => formatScore(p.stat_score_sale) },
  {
    key: 'z_score_rent',
    labelKey: 'attr.zScoreRent',
    get: (p) => (p.z_score_rent != null ? p.z_score_rent.toFixed(3) : '—'),
  },
  {
    key: 'z_score_sale',
    labelKey: 'attr.zScoreSale',
    get: (p) => (p.z_score_sale != null ? p.z_score_sale.toFixed(3) : '—'),
  },
  { key: 'ai_score', labelKey: 'attr.aiScore', get: (p) => formatScore(p.ai_score) },
  { key: 'deal_summary', labelKey: 'attr.dealSummary', get: (p) => p.deal_summary || '—' },
]

/**
 * Side-by-side compare for 2–4 properties from the batch projection + price history.
 * @param {{ ids: string[], onClose: () => void, onClearSelection: () => void }} props
 */
export default function CompareView({ ids, onClose, onClearSelection }) {
  const { t, locale } = useLocale()
  const [properties, setProperties] = useState([])
  const [histories, setHistories] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const dialogRef = useRef(null)

  // Initial focus management: move focus into the dialog on open (mirrors PropertyModal).
  useEffect(() => {
    const first = dialogRef.current?.querySelector(FOCUSABLE_SELECTOR)
    first?.focus()
  }, [])

  // Escape-to-close + Tab focus trap (mirrors PropertyModal.jsx's Escape handling).
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab' || !dialogRef.current) return
      const focusable = Array.from(dialogRef.current.querySelectorAll(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

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
          setError(err?.message || t('compare.failedLoad'))
          setProperties([])
          setHistories({})
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => { cancelled = true }
  }, [ids]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div
      className="compare-view"
      data-testid="compare-view"
      role="dialog"
      aria-modal="true"
      aria-label={t('compare.ariaLabel')}
      ref={dialogRef}
    >
      <div className="compare-view-header">
        <h2 className="compare-view-title">{t('compare.title')}</h2>
        <div className="compare-view-actions">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="compare-exit"
            onClick={onClose}
          >
            {t('compare.backToGrid')}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="compare-exit-clear"
            onClick={onClearSelection}
          >
            {t('compare.clearAndExit')}
          </button>
        </div>
      </div>

      {loading && (
        <div className="compare-view-status" data-testid="compare-loading">{t('compare.loading')}</div>
      )}
      {error && (
        <div className="compare-view-status compare-view-status--error" data-testid="compare-error">
          {error}
        </div>
      )}

      {!loading && !error && properties.length === 0 && (
        <div className="compare-view-status" data-testid="compare-empty">
          {t('compare.empty')}
        </div>
      )}

      {!loading && !error && properties.length > 0 && (
        <div className="compare-view-scroll">
          <div className="compare-table-wrap">
            <table className="compare-table" data-testid="compare-table">
              <thead>
                <tr>
                  <th scope="col" className="compare-attr-col">{t('compare.attribute')}</th>
                  {properties.map((p) => (
                    <th key={p.id} scope="col" data-testid={`compare-col-${p.id}`}>
                      {p.title || t('common.propertyFallback', { id: p.id })}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ATTR_ROWS.map((row) => (
                  <tr key={row.key} data-testid={`compare-row-${row.key}`}>
                    <th scope="row">{t(row.labelKey)}</th>
                    {properties.map((p) => (
                      <td key={p.id}>{row.get(p, { t, locale })}</td>
                    ))}
                  </tr>
                ))}
                <tr data-testid="compare-row-price-history">
                  <th scope="row">{t('compare.priceHistory')}</th>
                  {properties.map((p) => {
                    const history = histories[p.id] || []
                    if (history.length === 0) {
                      return (
                        <td key={p.id}>
                          <span className="compare-placeholder" data-testid={`compare-history-empty-${p.id}`}>
                            {t('compare.noPriceHistory')}
                          </span>
                        </td>
                      )
                    }
                    if (history.length < 2) {
                      return (
                        <td key={p.id}>
                          <span className="compare-placeholder" data-testid={`compare-history-short-${p.id}`}>
                            {t('compare.needsTwoPoints')}
                          </span>
                        </td>
                      )
                    }
                    const { chartData, lineKeys } = buildChartData(history, locale)
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
                                formatter={(value) => formatCurrency(value, locale)}
                              />
                              <Legend wrapperStyle={{ fontSize: 10, color: 'var(--text-muted)' }} />
                              {lineKeys.map((key, i) => {
                                const [type, platform] = key.split('|')
                                const label = t('common.listingTypeRentSale', {
                                  type: type === 'rent' ? t('common.rent') : t('common.sale'),
                                  platform: formatPlatform(platform),
                                })
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
