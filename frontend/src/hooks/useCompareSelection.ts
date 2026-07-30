import { useState, useCallback } from 'react'

const MAX_COMPARE = 4

export interface UseCompareSelectionOptions {
  onLimitReached?: () => void
  initialIds?: Array<string | number>
}

export interface UseCompareSelectionResult {
  selectedIds: string[]
  toggle: (id: string | number | null | undefined) => void
  clear: () => void
  replace: (ids: Array<string | number> | null | undefined) => void
  isSelected: (id: string | number | null | undefined) => boolean
  canCompare: boolean
  maxCompare: number
}

/** Ordered multi-select for property comparison (2–4 ids). */
export function useCompareSelection(
  { onLimitReached, initialIds = [] }: UseCompareSelectionOptions = {},
): UseCompareSelectionResult {
  const [selectedIds, setSelectedIds] = useState<string[]>(() => normalizeIds(initialIds))

  const isSelected = useCallback(
    (id: string | number | null | undefined) => selectedIds.includes(String(id)),
    [selectedIds],
  )

  const toggle = useCallback(
    (id: string | number | null | undefined) => {
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
  const replace = useCallback((ids: Array<string | number> | null | undefined) => {
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

function normalizeIds(ids: Array<string | number> | null | undefined): string[] {
  if (!Array.isArray(ids)) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of ids) {
    if (id == null || id === '') continue
    const key = String(id)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(key)
  }
  return out
}
