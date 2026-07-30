import { useEffect, useMemo, useRef, useState } from 'react'
import { useT } from '../i18n/LocaleContext.jsx'

/**
 * Ant Design–style searchable multi-select: closed until clicked, tags with ×,
 * optional group headers, checkmarks on selected rows.
 *
 * @param {object} props
 * @param {{ value: string, label: string, group?: string|null }[]} props.options
 * @param {string[]} props.value
 * @param {(next: string[]) => void} props.onChange
 * @param {string} [props.placeholder]
 * @param {string} [props.searchPlaceholder]
 * @param {boolean} [props.loading]
 * @param {string} [props['data-testid']]
 * @param {boolean} [props.groupByCity] — when true, options with `.group` are sectioned
 */
export default function SearchableMultiSelect({
  options = [],
  value = [],
  onChange,
  placeholder,
  searchPlaceholder,
  loading = false,
  'data-testid': testId,
  groupByCity = false,
}) {
  const t = useT()
  const resolvedPlaceholder = placeholder ?? t('common.selectEllipsis')
  const resolvedSearchPlaceholder = searchPlaceholder ?? t('common.searchEllipsis')
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [activeIndex, setActiveIndex] = useState(-1)
  const rootRef = useRef(null)
  const searchRef = useRef(null)
  const triggerRef = useRef(null)
  const optionRefs = useRef([])
  const selected = useMemo(() => new Set(value), [value])

  useEffect(() => {
    if (!open) return undefined
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false)
        setSearch('')
        setActiveIndex(-1)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus()
    }
  }, [open])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return options
    return options.filter((o) => {
      const hay = `${o.label} ${o.group || ''}`.toLowerCase()
      return hay.includes(q)
    })
  }, [options, search])

  const grouped = useMemo(() => {
    if (!groupByCity) {
      return [{ group: null, items: filtered }]
    }
    const map = new Map()
    for (const opt of filtered) {
      const g = opt.group || t('common.otherGroup')
      if (!map.has(g)) map.set(g, [])
      map.get(g).push(opt)
    }
    return Array.from(map.entries()).map(([group, items]) => ({ group, items }))
  }, [filtered, groupByCity, t])

  // Flattened option list (group order preserved) for arrow-key roving navigation.
  const flatOptions = useMemo(() => grouped.flatMap((g) => g.items), [grouped])

  useEffect(() => {
    optionRefs.current = optionRefs.current.slice(0, flatOptions.length)
  }, [flatOptions])

  useEffect(() => {
    if (activeIndex >= 0) {
      optionRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' })
    }
  }, [activeIndex])

  const toggle = (optValue) => {
    if (selected.has(optValue)) {
      onChange(value.filter((v) => v !== optValue))
    } else {
      onChange([...value, optValue])
    }
  }

  const removeTag = (e, optValue) => {
    e.stopPropagation()
    onChange(value.filter((v) => v !== optValue))
  }

  const labelFor = (v) => options.find((o) => o.value === v)?.label || v

  const moveActive = (delta) => {
    if (flatOptions.length === 0) return
    setActiveIndex((idx) => {
      let next = idx + delta
      if (next < 0) next = flatOptions.length - 1
      if (next >= flatOptions.length) next = 0
      return next
    })
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      setOpen(false)
      setSearch('')
      setActiveIndex(-1)
      triggerRef.current?.focus()
      return
    }
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveActive(1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveActive(-1)
    } else if (e.key === 'Enter' && activeIndex >= 0 && flatOptions[activeIndex]) {
      e.preventDefault()
      toggle(flatOptions[activeIndex].value)
    }
  }

  return (
    <div className="sms" ref={rootRef} data-testid={testId} onKeyDown={handleKeyDown}>
      <button
        type="button"
        ref={triggerRef}
        className={`sms-control${open ? ' sms-control--open' : ''}`}
        onClick={() => {
          setOpen((o) => !o)
          setActiveIndex(-1)
        }}
        aria-expanded={open}
        aria-haspopup="listbox"
        data-testid={testId ? `${testId}-trigger` : undefined}
      >
        <div className="sms-tags">
          {value.length === 0 && (
            <span className="sms-placeholder">{loading ? t('common.loading') : resolvedPlaceholder}</span>
          )}
          {value.map((v) => (
            <span key={v} className="sms-tag">
              {labelFor(v)}
              <span
                role="button"
                tabIndex={0}
                className="sms-tag-remove"
                aria-label={t('common.removeItem', { name: labelFor(v) })}
                onClick={(e) => removeTag(e, v)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') removeTag(e, v)
                }}
              >
                ×
              </span>
            </span>
          ))}
        </div>
        <span className="sms-chevron" aria-hidden>▾</span>
      </button>

      {open && (
        <div className="sms-dropdown" role="listbox" data-testid={testId ? `${testId}-dropdown` : undefined}>
          <div className="sms-search-wrap">
            <input
              ref={searchRef}
              type="search"
              className="sms-search"
              placeholder={resolvedSearchPlaceholder}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setActiveIndex(-1)
              }}
              onClick={(e) => e.stopPropagation()}
              data-testid={testId ? `${testId}-search` : undefined}
              role="combobox"
              aria-expanded={open}
              aria-controls={testId ? `${testId}-dropdown` : undefined}
              aria-activedescendant={
                activeIndex >= 0 && testId ? `${testId}-option-${activeIndex}` : undefined
              }
            />
          </div>
          <div className="sms-options">
            {grouped.every((g) => g.items.length === 0) && (
              <div className="sms-empty">{t('common.noMatches')}</div>
            )}
            {(() => {
              let flatIdx = -1
              return grouped.map(({ group, items }) => (
                <div key={group ?? '__flat'} className="sms-group">
                  {groupByCity && group && items.length > 0 && (
                    <div className="sms-group-label">{group}</div>
                  )}
                  {items.map((opt) => {
                    flatIdx += 1
                    const idx = flatIdx
                    const isOn = selected.has(opt.value)
                    const isActive = idx === activeIndex
                    return (
                      <button
                        key={`${opt.group || ''}::${opt.value}`}
                        ref={(el) => { optionRefs.current[idx] = el }}
                        id={testId ? `${testId}-option-${idx}` : undefined}
                        type="button"
                        role="option"
                        aria-selected={isOn}
                        className={`sms-option${isOn ? ' sms-option--selected' : ''}${isActive ? ' sms-option--active' : ''}`}
                        onClick={() => toggle(opt.value)}
                        onMouseEnter={() => setActiveIndex(idx)}
                      >
                        <span className="sms-option-label">{opt.label}</span>
                        {isOn && <span className="sms-check" aria-hidden>✓</span>}
                      </button>
                    )
                  })}
                </div>
              ))
            })()}
          </div>
        </div>
      )}
    </div>
  )
}
