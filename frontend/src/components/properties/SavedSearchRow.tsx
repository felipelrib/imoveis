import { useState, type FocusEvent, type KeyboardEvent, type SyntheticEvent } from 'react'
import type { SavedSearchItem, SavedSearchPatch } from '../../api.js'
import { useToast } from '../ToastProvider.jsx'
import { useLocale } from '../../i18n/LocaleContext.jsx'
import { formatNumber } from '../../i18n/format.js'
import { formatPlatform, PROPERTY_TYPE_OPTIONS } from '../../labels.js'
import { filterCapPercent } from '../../utils/percentile.js'
import {
  formatDropThreshold,
  parseDropThreshold,
  sameDropThreshold,
  savedSearchHasQuery,
  savedSearchSummaryParts,
  type SavedSearchSummaryPart,
} from '../../utils/savedSearchRow.js'

interface SavedSearchRowProps {
  search: SavedSearchItem
  onApply: (filters: Record<string, unknown>) => void
  onDelete: (e: SyntheticEvent, id: string) => void
  /** Writes through `PATCH /saved-searches/{id}`; resolves to the stored item. */
  onPatch: (id: string, patch: SavedSearchPatch) => Promise<SavedSearchItem>
}

/**
 * One saved search in the Painel sidebar (v0.14-s1.10, UX-DR13): name, filter
 * summary, the alert switch and the minimum price drop that alerts, per
 * search. Both controls write at once and show the stored value; a write that
 * fails puts the old value back and says so in a toast. A search that cannot
 * produce alerts says so instead of offering the controls.
 */
export default function SavedSearchRow({ search, onApply, onDelete, onPatch }: SavedSearchRowProps) {
  const { t, locale } = useLocale()
  const showToast = useToast()
  // Optimistic values, set only while their request is in flight.
  const [pendingNotify, setPendingNotify] = useState<boolean | null>(null)
  const [pendingDrop, setPendingDrop] = useState<{ value: number | null } | null>(null)
  // What is being typed; `null` shows the stored value.
  const [draft, setDraft] = useState<string | null>(null)
  const [invalid, setInvalid] = useState(false)

  const { id } = search
  const storedDrop = search.min_price_drop ?? null
  const notify = pendingNotify ?? Boolean(search.notify_new_matches)
  const drop = pendingDrop ? pendingDrop.value : storedDrop
  const supported = search.new_match_alerts_supported !== false

  const partLabel = (part: SavedSearchSummaryPart): string => {
    switch (part.kind) {
      case 'listingType':
        return t(part.value === 'rent' ? 'common.rent' : 'common.sale')
      case 'propertyType': {
        const option = PROPERTY_TYPE_OPTIONS.find((o) => o.value === part.value)
        return option ? t(option.labelKey) : part.value
      }
      case 'maxPrice':
        return t(
          part.priceType === 'rent'
            ? 'properties.savedSearchSummaryMaxPriceRent'
            : 'properties.savedSearchSummaryMaxPriceSale',
          { amount: formatNumber(part.value, locale) },
        )
      case 'minBedrooms':
        return t(
          part.value === 1 ? 'properties.savedSearchSummaryBedsOne' : 'properties.savedSearchSummaryBedsMany',
          { n: part.value },
        )
      case 'minParking':
        return t(
          part.value === 1
            ? 'properties.savedSearchSummaryParkingOne'
            : 'properties.savedSearchSummaryParkingMany',
          { n: part.value },
        )
      case 'neighborhood':
      case 'city':
        return part.value
      case 'percentileCap':
        return t('properties.amongCheapest', { n: formatNumber(filterCapPercent(part.value), locale) })
      case 'platform':
        return formatPlatform(part.value)
      case 'furnished':
        return t('properties.furnished')
      case 'pets':
        return t('properties.petFriendly')
      case 'minScore':
        return t('properties.savedSearchSummaryMinScore', { n: formatNumber(part.value, locale) })
      case 'query':
        return t('properties.savedSearchSummaryQuery', { q: part.value })
    }
  }

  const parts = savedSearchSummaryParts(search.filters)
  const summary = parts.length > 0
    ? parts.map(partLabel).join(' · ')
    : t('properties.savedSearchNoFilters')

  let stateLine: string
  if (!notify) stateLine = t('properties.savedSearchAlertsOff')
  else if (drop == null) stateLine = t('properties.savedSearchAlertsNew')
  else if (drop === 0) stateLine = t('properties.savedSearchAlertsNewAndAnyDrop')
  else {
    stateLine = t('properties.savedSearchAlertsNewAndDrops', {
      amount: formatDropThreshold(drop, locale),
    })
  }

  const toggleNotify = async () => {
    if (pendingNotify !== null) return
    const next = !notify
    setPendingNotify(next)
    try {
      await onPatch(id, { notify_new_matches: next })
    } catch (err) {
      console.error('Saved-search alert switch failed:', err)
      showToast(t('properties.toastAlertUpdateFailed'), { type: 'error' })
    } finally {
      // The stored value shows again: the new one on success, the old on failure.
      setPendingNotify(null)
    }
  }

  const commitDrop = async (raw: string) => {
    if (pendingDrop !== null) return
    const parsed = parseDropThreshold(raw)
    if (!parsed.ok) {
      // Not a value: nothing is sent, the field keeps the text and says so.
      setInvalid(true)
      return
    }
    setInvalid(false)
    setDraft(null)
    if (sameDropThreshold(parsed.value, storedDrop)) return
    setPendingDrop({ value: parsed.value })
    try {
      await onPatch(id, { min_price_drop: parsed.value })
    } catch (err) {
      console.error('Saved-search minimum drop failed:', err)
      showToast(t('properties.toastAlertUpdateFailed'), { type: 'error' })
    } finally {
      setPendingDrop(null)
    }
  }

  const onDropBlur = (e: FocusEvent<HTMLInputElement>) => {
    if (draft === null) return
    void commitDrop(e.currentTarget.value)
  }

  const onDropKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      void commitDrop(e.currentTarget.value)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      setDraft(null)
      setInvalid(false)
    }
  }

  const notifySwitch = (
    <span className="saved-search-control">
      <button
        type="button"
        role="switch"
        aria-checked={notify}
        aria-label={t('properties.savedSearchNotify')}
        className="saved-search-switch"
        data-testid={`saved-search-notify-${id}`}
        onClick={toggleNotify}
      >
        <span className="saved-search-switch-knob" aria-hidden="true" />
      </button>
      <span className="saved-search-control-label" aria-hidden="true">
        {t('properties.savedSearchNotify')}
      </span>
    </span>
  )

  return (
    <div className="saved-search-row" data-testid={`saved-search-row-${id}`}>
      <div className="saved-search-head">
        <button
          type="button"
          className="saved-search-name"
          onClick={() => onApply(search.filters)}
        >
          {search.name}
        </button>
        <button
          type="button"
          className="saved-search-delete"
          onClick={(e) => onDelete(e, id)}
          title={t('common.delete')}
          aria-label={t('common.removeItem', { name: search.name })}
        >
          ✕
        </button>
      </div>
      <div className="saved-search-summary">{summary}</div>

      {supported ? (
        <>
          <div className="saved-search-controls">
            {notifySwitch}
            <label className="saved-search-control">
              <span className="saved-search-control-label">
                {t('properties.savedSearchMinDrop')} <span aria-hidden="true">R$</span>
              </span>
              <input
                type="text"
                inputMode="decimal"
                autoComplete="off"
                className="saved-search-drop-input"
                data-testid={`saved-search-drop-${id}`}
                placeholder={t('properties.savedSearchMinDropPlaceholder')}
                value={draft ?? formatDropThreshold(drop, locale)}
                // Not editable while its write is in flight: an edit made then
                // could not be told from the value coming back.
                readOnly={pendingDrop !== null}
                aria-invalid={invalid || undefined}
                aria-describedby={invalid ? `saved-search-drop-error-${id}` : undefined}
                onChange={(e) => {
                  setDraft(e.target.value)
                  if (invalid) setInvalid(false)
                }}
                onBlur={onDropBlur}
                onKeyDown={onDropKeyDown}
              />
            </label>
          </div>
          {invalid ? (
            <div className="saved-search-invalid" role="alert" id={`saved-search-drop-error-${id}`}>
              {t('properties.savedSearchMinDropInvalid')}
            </div>
          ) : (
            <div className="saved-search-state" data-testid={`saved-search-alert-state-${id}`}>
              {stateLine}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="saved-search-state" data-testid={`saved-search-alerts-muted-${id}`}>
            {t(
              savedSearchHasQuery(search.filters)
                ? 'properties.savedSearchAlertsUnsupportedQuery'
                : 'properties.savedSearchAlertsUnsupported',
            )}
          </div>
          {/* Still on from before: the switch stays so it can be switched off. */}
          {notify && <div className="saved-search-controls">{notifySwitch}</div>}
        </>
      )}
    </div>
  )
}
