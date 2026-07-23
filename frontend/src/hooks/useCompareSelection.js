import { useState, useCallback } from 'react'

const MAX_COMPARE = 4

/**
 * Ordered multi-select for property comparison (2–4 ids).
 * @param {{ onLimitReached?: () => void }} [opts]
 */
export function useCompareSelection({ onLimitReached } = {}) {
  const [selectedIds, setSelectedIds] = useState([])

  const isSelected = useCallback(
    (id) => selectedIds.includes(id),
    [selectedIds],
  )

  const toggle = useCallback(
    (id) => {
      if (!id) return
      if (selectedIds.includes(id)) {
        setSelectedIds((prev) => prev.filter((x) => x !== id))
        return
      }
      if (selectedIds.length >= MAX_COMPARE) {
        onLimitReached?.()
        return
      }
      setSelectedIds((prev) => [...prev, id])
    },
    [selectedIds, onLimitReached],
  )

  const clear = useCallback(() => {
    setSelectedIds([])
  }, [])

  const canCompare = selectedIds.length >= 2 && selectedIds.length <= MAX_COMPARE

  return {
    selectedIds,
    toggle,
    clear,
    isSelected,
    canCompare,
    maxCompare: MAX_COMPARE,
  }
}
