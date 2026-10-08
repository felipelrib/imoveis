import type { ReactNode } from 'react'
import type { PriceHistoryPoint, PropertyDetail } from '../../api.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'

/**
 * What every section of the detail panel receives. A section is a component
 * that takes these props and returns `null` when it has nothing to say; the
 * shell (`PropertyDetailPanel`) renders them from one ordered list, so a new
 * section is one file plus one line in that list.
 */
export interface DetailSectionProps {
  property: PropertyDetail
  priceHistory: PriceHistoryPoint[]
  t: TFunction
  locale: string
}

export interface PanelSectionProps {
  title: string
  /** `data-testid` of the section element. */
  testId: string
  /** Rendered beside the title, e.g. a score. */
  aside?: ReactNode
  children: ReactNode
}

/** Hairline-separated block with an uppercase muted title (DESIGN.md `detail-panel`). */
export default function PanelSection({ title, testId, aside, children }: PanelSectionProps) {
  return (
    <section className="detail-section" data-testid={testId}>
      <h3 className="detail-section-title">
        {title}
        {aside != null && <span className="detail-section-aside">{aside}</span>}
      </h3>
      {children}
    </section>
  )
}
