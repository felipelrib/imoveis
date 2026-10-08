import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'

/** The ad's own description text, as published. */
export default function DescriptionSection({ property: p, t }: DetailSectionProps) {
  if (!p.description) return null
  return (
    <PanelSection title={t('detail.sectionDescription')} testId="detail-section-description">
      <p className="detail-text detail-description">{p.description}</p>
    </PanelSection>
  )
}
