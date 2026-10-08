import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend,
} from 'recharts'
import { formatPlatform } from '../../labels.js'
import { formatCurrency, formatDate } from '../../i18n/format.js'
import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'

interface ChartPoint {
  date: string
  [lineKey: string]: string | number
}

// Series are told apart by stroke pattern, never by colour: DESIGN.md keeps
// the verdict colours out of the price-history chart.
// Six patterns: three platforms times two listing types.
const DASHES: (string | undefined)[] = [undefined, '5 5', '2 4', '9 3 2 3', '12 4', '1 6']

/** Price history per listing type and platform; needs two points to plot. */
export default function PriceHistorySection({ priceHistory, t, locale }: DetailSectionProps) {
  if (priceHistory.length === 0) return null

  if (priceHistory.length < 2) {
    return (
      <PanelSection title={t('detail.sectionPriceHistory')} testId="detail-section-price-history">
        <p className="detail-note">{t('detail.priceHistoryNeedPoints')}</p>
      </PanelSection>
    )
  }

  const dateOf = (ts: string | null | undefined) => (ts ? formatDate(ts, locale) : '?')
  const grouped: Record<string, { date: string; price: number }[]> = {}
  for (const point of priceHistory) {
    const lineKey = `${point.listing_type || 'sale'}|${point.platform || 'unknown'}`
    if (!grouped[lineKey]) grouped[lineKey] = []
    grouped[lineKey].push({ date: dateOf(point.start_ts), price: point.price })
  }
  const dates = [...new Set(priceHistory.map((point) => dateOf(point.start_ts)))]
  const chartData: ChartPoint[] = dates.map((date) => {
    const row: ChartPoint = { date }
    for (const [key, entries] of Object.entries(grouped)) {
      const match = entries.find((entry) => entry.date === date)
      if (match) row[key] = match.price
    }
    return row
  })
  const lineKeys = Object.keys(grouped)
  const tick = { fill: 'var(--text-muted)', fontSize: 10.5 }
  const axisLine = { stroke: 'var(--border-hairline)' }

  return (
    <PanelSection title={t('detail.sectionPriceHistory')} testId="detail-section-price-history">
      <div className="detail-chart">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={chartData}>
            <XAxis dataKey="date" tick={tick} tickLine={false} axisLine={axisLine} />
            <YAxis
              tick={tick}
              tickLine={false}
              axisLine={axisLine}
              tickFormatter={(v: number) => `R$${(v / 1000).toFixed(0)}k`}
            />
            <Tooltip
              contentStyle={{
                background: 'var(--surface-card)',
                border: '1px solid var(--border-hairline)',
                borderRadius: 7,
                color: 'var(--text-primary)',
                fontSize: 12,
              }}
              formatter={(value) => formatCurrency(value as number, locale)}
            />
            <Legend wrapperStyle={{ fontSize: 11.5, color: 'var(--text-muted)' }} />
            {lineKeys.map((key, i) => {
              const [type, platform] = key.split('|')
              const label = t('common.listingTypeRentSale', {
                type: type === 'rent' ? t('common.rent') : t('common.sale'),
                platform: formatPlatform(platform),
              })
              return (
                <Line
                  key={key}
                  type="linear"
                  dataKey={key}
                  name={label}
                  stroke="var(--text-secondary)"
                  strokeWidth={1.8}
                  strokeDasharray={DASHES[i % DASHES.length]}
                  // The default legend icon ignores the dash; this one draws it.
                  legendType="plainline"
                  dot={{ r: 2.5 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              )
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </PanelSection>
  )
}
