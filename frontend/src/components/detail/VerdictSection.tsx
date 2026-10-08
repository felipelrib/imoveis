import {
  labelSentimentCategory,
  labelStatBand,
  labelVisualCategory,
  reasoningStatBand,
} from '../../i18n/index.js'
import { percentileSentences, type PercentileSentence } from '../../utils/percentile.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'
import PanelSection, { type DetailSectionProps } from './PanelSection.jsx'

/** Structured sub-shapes carried inside `ai_analysis` / `stat_analysis`. */
interface VisualAnalysis {
  category?: string | null
  reasoning?: string | null
  features_detected?: string[]
  issues_detected?: string[]
}

interface SentimentAnalysis {
  category?: string | null
  reasoning?: string | null
  green_flags?: string[]
  red_flags?: string[]
}

interface StatAnalysis {
  category?: string | null
  reasoning?: string | null
}

/**
 * The sentence for one cohort. A Property with Listings of both types names
 * the cohort (`dos aluguéis do bairro`); a single-type one keeps the short form.
 */
function percentileSentenceText(sentence: PercentileSentence, t: TFunction): string {
  if (!sentence.dual) return t('detail.percentileSentence', { n: sentence.n })
  return sentence.type === 'rent'
    ? t('detail.percentileSentenceRent', { n: sentence.n })
    : t('detail.percentileSentenceSale', { n: sentence.n })
}

function score(value: number | null | undefined, emDash: string): string {
  return value != null ? (value * 100).toFixed(0) : emDash
}

function TagList({ label, items, warn = false }: { label: string; items: string[]; warn?: boolean }) {
  if (items.length === 0) return null
  return (
    <div className="detail-taglist">
      <div className="detail-sublabel">{label}</div>
      <div className="detail-tags">
        {items.map((item) => (
          <span key={item} className={`detail-tag${warn ? ' detail-tag--warn' : ''}`}>{item}</span>
        ))}
      </div>
    </div>
  )
}

/** Why this verdict: percentile sentence, deal summary, analyses, scores. */
export default function VerdictSection({ property: p, t, locale }: DetailSectionProps) {
  const visual: VisualAnalysis = (p.ai_analysis?.visual as VisualAnalysis | undefined) ?? {}
  const sentiment: SentimentAnalysis = (p.ai_analysis?.sentiment as SentimentAnalysis | undefined) ?? {}
  const stat: StatAnalysis = (p.stat_analysis as StatAnalysis | undefined) ?? {}
  const emDash = t('common.emDash')

  const listingTypes = (p.listings || []).map((l) => l.listing_type || 'sale')
  const sentences = percentileSentences(p, listingTypes)

  const scores: [string, number | null | undefined][] = [
    [t('detail.scoreCombined'), p.combined_score],
    [t('detail.scoreStatistical'), p.stat_score],
    [t('detail.scoreAiQuality'), p.ai_score],
  ]

  return (
    <PanelSection title={t('detail.sectionVerdict')} testId="detail-section-verdict">
      {sentences.map((sentence) => (
        <p
          key={sentence.type}
          className="detail-sentence"
          data-testid={`detail-percentile-sentence-${sentence.type}`}
        >
          {t('detail.percentilePrefix')} <b>{percentileSentenceText(sentence, t)}</b>.
        </p>
      ))}

      {p.deal_summary && (
        <div className="detail-block" data-testid="detail-deal-verdict">
          <div className="detail-sublabel">{t('detail.dealVerdict')}</div>
          <p className="detail-lead">{p.deal_summary}</p>
        </div>
      )}

      {stat.category && (
        <div className="detail-block">
          <p className="detail-lead">
            {t('detail.statisticalCategory', { category: labelStatBand(locale, stat.category) })}
          </p>
          <p className="detail-text">{reasoningStatBand(locale, stat.category, stat.reasoning)}</p>
        </div>
      )}

      {visual.category && (
        <div className="detail-block">
          <p className="detail-lead">
            {t('detail.visualCondition', { category: labelVisualCategory(locale, visual.category) })}
          </p>
          {visual.reasoning && <p className="detail-text">{visual.reasoning}</p>}
        </div>
      )}

      {sentiment.category && (
        <div className="detail-block" data-testid="ad-claims-section">
          <p className="detail-lead">
            {t('detail.adClaimsListing', { category: labelSentimentCategory(locale, sentiment.category) })}
          </p>
          {sentiment.reasoning && <p className="detail-text">{sentiment.reasoning}</p>}
        </div>
      )}

      <TagList label={t('detail.modernFeatures')} items={visual.features_detected ?? []} />
      <TagList label={t('detail.issuesDetected')} items={visual.issues_detected ?? []} warn />
      <TagList label={t('detail.claimsPositives')} items={sentiment.green_flags ?? []} />
      <TagList label={t('detail.claimsConcerns')} items={sentiment.red_flags ?? []} warn />

      <div className="detail-kv-list" data-testid="detail-scores">
        {scores.map(([label, value]) => (
          <div key={label} className="detail-kv">
            <span className="detail-kv-key">{label}</span>
            <span className="detail-kv-val">{score(value, emDash)}</span>
          </div>
        ))}
      </div>
    </PanelSection>
  )
}
