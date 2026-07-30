import SearchableMultiSelect from '../SearchableMultiSelect.jsx'
import { formatPlatform, PROPERTY_TYPE_OPTIONS } from '../../labels.js'

const SORT_OPTIONS = [
  { value: 'combined_score', labelKey: 'properties.sortBestScore' },
  { value: 'price', labelKey: 'properties.sortPriceAsc' },
  { value: 'price_desc', labelKey: 'properties.sortPriceDesc' },
  { value: 'created_at', labelKey: 'properties.sortNewest' },
  { value: 'area_m2', labelKey: 'properties.sortArea' },
]

/**
 * Toolbar (search / sort / transaction / source / type / export / view /
 * compare / advanced-toggle) + the collapsible advanced-filters panel for
 * the Properties page. Moved verbatim from the pre-split Properties.jsx
 * (BIN-141) — every data-testid, class name, and the label→select DOM
 * nesting for the Transaction control are unchanged (existing Playwright
 * specs locate that control structurally, not by testid).
 */
export default function PropertiesFilterBar({
  t,
  qDraft,
  setQDraft,
  q,
  setQ,
  sortBy,
  setSortBy,
  listingType,
  setListingType,
  setPriceType,
  platform,
  setPlatform,
  propertyType,
  setPropertyType,
  exporting,
  onExport,
  viewType,
  setViewType,
  compareMode,
  onToggleCompareMode,
  showAdvanced,
  setShowAdvanced,
  maxPrice,
  setMaxPrice,
  priceType,
  minBedrooms,
  setMinBedrooms,
  minParking,
  setMinParking,
  minScore,
  setMinScore,
  isFurnished,
  setIsFurnished,
  acceptsPets,
  setAcceptsPets,
  citiesLoading,
  cities,
  city,
  setCity,
  neighborhoodsLoading,
  neighborhoods,
  neighborhood,
  setNeighborhood,
  onClearAdvanced,
}) {
  return (
    <div className="toolbar" style={{ flexWrap: 'wrap', gap: 12 }}>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', width: '100%', alignItems: 'center' }}>
        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0, flex: '1 1 220px' }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }} htmlFor="semantic-search">{t('properties.searchLabel')}</label>
          <input
            id="semantic-search"
            className="form-input"
            style={{ flex: 1, minWidth: 160 }}
            type="search"
            placeholder={t('properties.searchPlaceholder')}
            value={qDraft}
            onChange={e => setQDraft(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') {
                e.preventDefault()
                setQ(qDraft.trim())
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setQ(qDraft.trim())}
          >
            {t('properties.searchButton')}
          </button>
          {q && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => { setQ(''); setQDraft('') }}
              title={t('properties.clearSearch')}
            >
              ✕
            </button>
          )}
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.sortBy')}</label>
          <select className="form-select" style={{ width: 140 }} value={sortBy} onChange={e => setSortBy(e.target.value)} data-testid="sort-by-filter">
            {SORT_OPTIONS.map(o => <option key={o.value} value={o.value}>{t(o.labelKey)}</option>)}
          </select>
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.transaction')}</label>
          <select
            className="form-select"
            style={{ width: 110 }}
            value={listingType}
            onChange={e => {
              const next = e.target.value
              setListingType(next)
              if (next === 'rent' || next === 'sale') setPriceType(next)
            }}
            data-testid="listing-type-filter"
          >
            <option value="both">{t('properties.rentAndSale')}</option>
            <option value="rent">{t('properties.rentOnly')}</option>
            <option value="sale">{t('properties.saleOnly')}</option>
          </select>
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.source')}</label>
          <select
            className="form-select"
            style={{ width: 130 }}
            value={platform}
            onChange={e => setPlatform(e.target.value)}
            data-testid="platform-filter"
          >
            <option value="">{t('common.any')}</option>
            <option value="olx">{formatPlatform('olx')}</option>
            <option value="quintoandar">{formatPlatform('quintoandar')}</option>
          </select>
        </div>

        <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
          <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.type')}</label>
          <select className="form-select" style={{ width: 120 }} value={propertyType} onChange={e => setPropertyType(e.target.value)} data-testid="property-type-filter">
            <option value="">{t('common.any')}</option>
            {PROPERTY_TYPE_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{t(o.labelKey)}</option>
            ))}
          </select>
        </div>

        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="export-csv"
            disabled={exporting}
            onClick={() => onExport('csv')}
            title={t('properties.exportCsvTitle')}
          >
            {exporting ? t('properties.exporting') : t('properties.exportCsv')}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="export-json"
            disabled={exporting}
            onClick={() => onExport('json')}
            title={t('properties.exportJsonTitle')}
          >
            {exporting ? t('properties.exporting') : t('properties.exportJson')}
          </button>
          <div style={{ display: 'flex', border: '1px solid var(--border-subtle)', borderRadius: 6, overflow: 'hidden' }}>
            <button
              className={`btn btn-sm ${viewType === 'grid' ? '' : 'btn-ghost'}`}
              style={{ borderRadius: 0, padding: '4px 10px', fontSize: 12, fontWeight: 600, background: viewType === 'grid' ? 'var(--accent, #6366f1)' : 'transparent', color: viewType === 'grid' ? 'white' : 'var(--text-secondary)' }}
              onClick={() => setViewType('grid')}
            >
              {t('properties.viewList')}
            </button>
            <button
              className={`btn btn-sm ${viewType === 'map' ? '' : 'btn-ghost'}`}
              style={{ borderRadius: 0, padding: '4px 10px', fontSize: 12, fontWeight: 600, background: viewType === 'map' ? 'var(--accent, #6366f1)' : 'transparent', color: viewType === 'map' ? 'white' : 'var(--text-secondary)', borderLeft: '1px solid var(--border-subtle)' }}
              onClick={() => setViewType('map')}
            >
              {t('properties.viewMap')}
            </button>
          </div>
          <button
            type="button"
            className={`btn btn-sm ${compareMode ? 'btn-primary' : 'btn-ghost'}`}
            data-testid="compare-mode-toggle"
            aria-pressed={compareMode}
            title={compareMode ? t('properties.compareModeOn') : t('properties.compareModeOff')}
            onClick={onToggleCompareMode}
          >
            {compareMode ? t('properties.exitCompare') : t('properties.compare')}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setShowAdvanced(!showAdvanced)}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            {showAdvanced ? t('properties.hideAdvanced') : t('properties.showAdvanced')}
          </button>
        </div>
      </div>

      {showAdvanced && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', width: '100%', alignItems: 'flex-start', background: 'rgba(0,0,0,0.1)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border-subtle)' }}>
          <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
            <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.maxPrice')} R$</label>
            <input
              className="form-input"
              data-testid="max-price-input"
              style={{ width: 110 }}
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              placeholder={t('common.any')}
              value={maxPrice}
              onChange={e => {
                const raw = e.target.value.replace(/[^\d]/g, '')
                setMaxPrice(raw)
              }}
            />
            <select
              className="form-select"
              data-testid="price-type-filter"
              style={{ width: 90 }}
              value={priceType}
              onChange={e => setPriceType(e.target.value)}
              aria-label={t('properties.priceType')}
            >
              <option value="rent">{t('common.rent')}</option>
              <option value="sale">{t('common.sale')}</option>
            </select>
          </div>
          <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
            <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.beds')}</label>
            <select className="form-select" style={{ width: 70 }} value={minBedrooms} onChange={e => setMinBedrooms(e.target.value)}>
              <option value="">{t('common.any')}</option>
              {[1,2,3,4,5].map(n => <option key={n} value={n}>{t('properties.bedsPlus', { n })}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
            <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.parking')}</label>
            <select className="form-select" style={{ width: 70 }} value={minParking} onChange={e => setMinParking(e.target.value)}>
              <option value="">{t('common.any')}</option>
              {[1,2,3,4,5].map(n => <option key={n} value={n}>{t('properties.bedsPlus', { n })}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, margin: 0 }}>
            <label className="form-label" style={{ whiteSpace: 'nowrap', marginBottom: 0 }}>{t('properties.minCombinedScore')}</label>
            <select className="form-select" style={{ width: 80 }} value={minScore} onChange={e => setMinScore(e.target.value)}>
              <option value="">{t('common.any')}</option>
              <option value="0.7">{t('properties.scorePlus', { n: 0.7 })}</option>
              <option value="0.8">{t('properties.scorePlus', { n: 0.8 })}</option>
              <option value="0.9">{t('properties.scorePlus', { n: 0.9 })}</option>
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginLeft: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={isFurnished} onChange={e => setIsFurnished(e.target.checked)} data-testid="furnished-filter" />
              {t('properties.furnished')}
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={acceptsPets} onChange={e => setAcceptsPets(e.target.checked)} data-testid="pets-filter" />
              {t('properties.petFriendly')}
            </label>
          </div>
          <div style={{ marginLeft: 16, display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: '200px' }}>
            <label className="form-label" style={{ marginBottom: 0 }}>
              {t('properties.cities')}
              {citiesLoading && <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>{t('common.loading')}</span>}
            </label>
            <SearchableMultiSelect
              data-testid="city-filter"
              placeholder={t('properties.selectCities')}
              searchPlaceholder={t('properties.searchCities')}
              loading={citiesLoading}
              value={city ? city.split(',') : []}
              onChange={(vals) => setCity(vals.join(','))}
              options={cities.map((c) => ({
                value: c.name,
                label: `${c.name} (${c.count})`,
              }))}
            />
          </div>
          <div style={{ marginLeft: 16, display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: '220px' }}>
            <label className="form-label" style={{ marginBottom: 0 }}>
              {t('properties.neighborhoods')}
              {neighborhoodsLoading && <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>{t('common.loading')}</span>}
            </label>
            <SearchableMultiSelect
              data-testid="neighborhood-filter"
              placeholder={t('properties.selectNeighborhoods')}
              searchPlaceholder={t('properties.searchNeighborhoods')}
              loading={neighborhoodsLoading}
              groupByCity
              value={neighborhood ? neighborhood.split(',') : []}
              onChange={(vals) => setNeighborhood(vals.join(','))}
              options={neighborhoods.map((n) => ({
                value: n.name,
                label: `${n.name} (${n.count})`,
                group: n.city || null,
              }))}
            />
          </div>
          <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={onClearAdvanced}>{t('properties.clearAll')}</button>
        </div>
      )}
    </div>
  )
}
