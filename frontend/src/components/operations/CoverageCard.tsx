import type { EnrichmentCoverage, SignalCoverage } from '../../api.js'
import { useLocale } from '../../i18n/LocaleContext.jsx'
import { wholePercent } from '../../i18n/format.js'
import { signalLabel } from './lines.js'
import type { TFunction } from '../../i18n/LocaleContext.jsx'
import type { BackfillFailure, UseBackfillResult } from '../../hooks/useBackfill.js'

export interface CoverageCardProps {
  backfill: UseBackfillResult
}

/**
 * Per-signal AI coverage (UX-DR6): one text line per signal the API returns, in
 * the API's order, label left and percentage right — hairline separators, no
 * bars or tracks. A null `fraction` (an empty denominator) keeps its label and
 * omits the value entirely; it is never rendered as `0%`.
 */
export default function CoverageCard({ backfill }: CoverageCardProps) {
  const { t } = useLocale()
  const { coverage, coverageError, credentialed } = backfill

  return (
    <section className="meia ops-card" data-testid="coverage-card">
      <h2 className="ops-card-title">{t('operations.coverageTitle')}</h2>
      {!credentialed ? (
        <p className="ops-hint" data-testid="coverage-credential-hint">
          {t('operations.credentialHint')}
        </p>
      ) : (
        <CoverageBody coverage={coverage} error={coverageError} t={t} />
      )}
    </section>
  )
}

function CoverageBody({
  coverage, error, t,
}: { coverage: EnrichmentCoverage | null; error: BackfillFailure | null; t: TFunction }) {
  // Said, not silently frozen: percentages that survived the failed read would
  // keep claiming a coverage nobody just measured. A rejected credential says so
  // rather than blaming the database it never reached.
  if (error) {
    return (
      <p className="ops-fail" data-testid="coverage-error">
        {t(error.kind === 'auth'
          ? 'operations.coverageUnauthorized'
          : 'operations.coverageFailed')}
      </p>
    )
  }
  if (!coverage) {
    return <p className="ops-hint">{t('common.ellipsis')}</p>
  }
  const signals: SignalCoverage[] = coverage.signals ?? []
  if (signals.length === 0) {
    return <p className="ops-hint">{t('operations.coverageUnavailable')}</p>
  }
  return (
    <>
      <div className="cov-rows">
        {signals.map((s) => (
          <div className="cov-row" key={s.task_class} data-testid={`coverage-row-${s.task_class}`}>
            <span className="cov-label">{signalLabel(s.task_class, t)}</span>
            {s.fraction != null && (
              <span className="cov-value">{wholePercent(s.fraction)}%</span>
            )}
          </div>
        ))}
      </div>
      {coverage.minimum_fraction != null && (
        <p className="cov-foot" data-testid="coverage-footnote">
          {t('operations.coverageFootnote', { pct: wholePercent(coverage.minimum_fraction) })}
        </p>
      )}
    </>
  )
}
