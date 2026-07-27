import { useState, useCallback } from 'react'

const MAX_COMPARE = 4

/**
 * Ordered multi-select for property comparison (2–4 ids).
 * @param {{ onLimitReached?: () => void, initialIds?: Array<string|number> }} [opts]
 */
export function useCompareSelection({ onLimitReached, initialIds = [] } = {}) {
  const [selectedIds, setSelectedIds] = useState(() => normalizeIds(initialIds))

  const isSelected = useCallback(
    (id) => selectedIds.includes(String(id)),
    [selectedIds],
  )

  const toggle = useCallback(
    (id) => {
      if (id == null || id === '') return
      const key = String(id)
      if (selectedIds.includes(key)) {
        setSelectedIds((prev) => prev.filter((x) => x !== key))
        return
      }
      if (selectedIds.length >= MAX_COMPARE) {
        onLimitReached?.()
        return
      }
      setSelectedIds((prev) => [...prev, key])
    },
    [selectedIds, onLimitReached],
  )

  const clear = useCallback(() => {
    setSelectedIds([])
  }, [])

  /** Replace selection (e.g. hydrate from `/compare/:ids`). Caps at MAX_COMPARE. */
  const replace = useCallback((ids) => {
    setSelectedIds(normalizeIds(ids).slice(0, MAX_COMPARE))
  }, [])

  const canCompare = selectedIds.length >= 2 && selectedIds.length <= MAX_COMPARE

  return {
    selectedIds,
    toggle,
    clear,
    replace,
    isSelected,
    canCompare,
    maxCompare: MAX_COMPARE,
  }
}

/**
 * @param {Array<string|number>|undefined|null} ids
 * @returns {string[]}
 */
function normalizeIds(ids) {
  if (!Array.isArray(ids)) return []
  const seen = new Set()
  const out = []
  for (const id of ids) {
    if (id == null || id === '') continue
    const key = String(id)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(key)
  }
  return out
}
