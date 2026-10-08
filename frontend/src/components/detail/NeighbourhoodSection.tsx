import { labelRiskFlag } from '../../i18n/index.js'
import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'

/** Objective neighbourhood quality profile; absent when the Property has none. */
export default function NeighbourhoodSection({ property: p, t, locale }: DetailSectionProps) {
  const quality = p.neighbourhood_quality
  if (!quality) return null

  const emDash = t('common.emDash')
  const pct = (value: number | null | undefined) => (value != null ? `${(value * 100).toFixed(0)}%` : emDash)
  const scores: [string, number | null | undefined][] = [
    [t('attr.amenity'), quality.amenity_score],
    [t('attr.transit'), quality.transit_score],
    [t('attr.access'), quality.access_score],
    [t('attr.safety'), quality.safety_score],
  ]
  const riskFlags = quality.risk_flags || []

  return (
    <PanelSection
      title={t('detail.neighbourhoodQuality')}
      testId="neighbourhood-quality-section"
      aside={quality.neighbourhood_score != null ? pct(quality.neighbourhood_score) : null}
    >
      <div className="detail-kv-list">
        {scores.map(([label, value]) => (
          <div key={label} className="detail-kv">
            <span className="detail-kv-key">{label}</span>
            <span className="detail-kv-val">{pct(value)}</span>
          </div>
        ))}
      </div>
      {riskFlags.length > 0 && (
        <div className="detail-tags detail-tags--spaced">
          {riskFlags.map((flag) => (
            <span key={flag} className="detail-tag detail-tag--warn">{labelRiskFlag(locale, flag)}</span>
          ))}
        </div>
      )}
      {quality.quality_notes && <p className="detail-text">{quality.quality_notes}</p>}
    </PanelSection>
  )
}
