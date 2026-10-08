import { formatPlatform } from '../../labels.js'
import { formatPricePerM2 } from '../../i18n/format.js'
import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'

type FactRow = [label: string, value: string | number | null | undefined]

/**
 * Address, size, price per m² and the per-type scores. The legacy
 * `percentile_rank*` fields are not read: the cohort position is the sentence
 * in the verdict section (UX-DR8).
 */
export default function FactsSection({ property: p, t, locale }: DetailSectionProps) {
  const emDash = t('common.emDash')
  const pct = (value: number | null | undefined) => (value != null ? (value * 100).toFixed(0) : emDash)
  const perM2 = (value: number | null | undefined) => (value != null ? formatPricePerM2(value, locale) : emDash)

  const rows: FactRow[] = [
    [t('attr.platform'), formatPlatform(p.platform)],
    [t('attr.address'), p.address],
    [t('attr.neighbourhood'), p.neighborhood_name],
    [t('attr.area'), p.area_m2 ? t('common.areaM2', { n: p.area_m2 }) : emDash],
    [t('attr.bedrooms'), p.bedrooms ?? emDash],
    [t('attr.bathrooms'), p.bathrooms ?? emDash],
    [t('attr.parking'), p.parking ?? emDash],
  ]

  if (p.price_per_m2_rent != null) {
    rows.push(
      [t('attr.pricePerM2Rent'), perM2(p.price_per_m2_rent)],
      [t('attr.neighbourhoodAvgPerM2Rent'), perM2(p.neighborhood_mean_rent)],
    )
  }
  if (p.price_per_m2_sale != null) {
    rows.push(
      [t('attr.pricePerM2Sale'), perM2(p.price_per_m2_sale)],
      [t('attr.neighbourhoodAvgPerM2Sale'), perM2(p.neighborhood_mean_sale)],
    )
  }
  if (p.price_per_m2_rent == null && p.price_per_m2_sale == null) {
    rows.push(
      [t('attr.pricePerM2'), p.price_per_m2 ? perM2(p.price_per_m2) : emDash],
      [t('attr.neighbourhoodAvgPerM2'), p.neighborhood_mean ? perM2(p.neighborhood_mean) : emDash],
    )
  }
  if (p.combined_score_rent != null) {
    rows.push(
      [t('attr.combinedScoreRent'), pct(p.combined_score_rent)],
      [t('attr.statisticalScoreRent'), pct(p.stat_score_rent)],
      [t('attr.zScoreRent'), p.z_score_rent != null ? p.z_score_rent.toFixed(3) : emDash],
    )
  }
  if (p.combined_score_sale != null) {
    rows.push(
      [t('attr.combinedScoreSale'), pct(p.combined_score_sale)],
      [t('attr.statisticalScoreSale'), pct(p.stat_score_sale)],
      [t('attr.zScoreSale'), p.z_score_sale != null ? p.z_score_sale.toFixed(3) : emDash],
    )
  }
  if (p.combined_score_rent == null && p.combined_score_sale == null) {
    rows.push([t('attr.zScore'), p.z_score != null ? p.z_score.toFixed(3) : emDash])
  }

  const shown = rows.filter(([, value]) => value != null && value !== '')
  if (shown.length === 0) return null

  return (
    <PanelSection title={t('detail.sectionFacts')} testId="detail-section-facts">
      <div className="detail-kv-list">
        {shown.map(([label, value]) => (
          <div key={label} className="detail-kv">
            <span className="detail-kv-key">{label}</span>
            <span className="detail-kv-val">{value}</span>
          </div>
        ))}
      </div>
    </PanelSection>
  )
}
