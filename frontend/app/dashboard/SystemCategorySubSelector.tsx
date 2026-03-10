'use client'

/**
 * SystemCategorySubSelector
 *
 * Two-panel category editor:
 *   Left:  a <select> listing the locked L1 system categories
 *   Right: CategoryTreeSelector for L2+ under the selected L1.
 *          Create-new lives inside the dropdown: "+ Create Sub Category at this level" at top, "+ sub-level" on each row.
 *
 * Props:
 *   categories   flat list from /api/categories (all levels)
 *   value        currently selected user_category_id (or null)
 *   onChange     called with new user_category_id when the user confirms a selection
 *   placeholder  optional placeholder for the right-side tree selector
 *   disabled     whether the entire selector is disabled
 *   onRefetchCategories  called after creating a category so parent can refresh the list
 *   onCreateCategory     (parentId, name) => Promise<newId | null> to create a category via API
 */

import { useMemo, useState, useEffect } from 'react'
import CategoryTreeSelector, { type UserCat } from './CategoryTreeSelector'

function toTitleCase(s: string) {
  if (!s) return s
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

interface Props {
  categories: UserCat[]
  value: string | null
  onChange: (id: string | null) => void
  placeholder?: string
  disabled?: boolean
  onRefetchCategories?: () => Promise<void>
  onCreateCategory?: (parentId: string, name: string) => Promise<string | null>
}

export default function SystemCategorySubSelector({
  categories,
  value,
  onChange,
  placeholder = 'Select sub-category…',
  disabled = false,
  onRefetchCategories,
  onCreateCategory,
}: Props) {
  // L1 nodes (locked system categories)
  const l1Nodes = useMemo(
    () =>
      categories
        .filter((c) => c.level === 1)
        .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name)),
    [categories]
  )

  // Determine initial L1 selection from current value
  const initialL1Id = useMemo(() => {
    if (!value) return null
    // Walk up to find the L1 ancestor
    const byId = new Map(categories.map((c) => [c.id, c]))
    let cur = byId.get(value)
    while (cur) {
      if (cur.level === 1) return cur.id
      cur = cur.parent_id ? byId.get(cur.parent_id) : undefined
    }
    return null
  }, [value, categories])

  const [selectedL1Id, setSelectedL1Id] = useState<string | null>(initialL1Id)

  // When categories load (e.g. after refetch), sync L1 selection from current value so
  // the correct system category and its sub-categories are shown.
  useEffect(() => {
    if (initialL1Id != null) setSelectedL1Id(initialL1Id)
  }, [initialL1Id])

  // Children of the selected L1 (L2+) for the right-side tree
  const subCategories = useMemo(() => {
    if (!selectedL1Id) return []
    // Collect all descendants of selectedL1Id
    const result: UserCat[] = []
    const queue = [selectedL1Id]
    const byParent = new Map<string | null, UserCat[]>()
    for (const c of categories) {
      const pid = c.parent_id ?? null
      if (!byParent.has(pid)) byParent.set(pid, [])
      byParent.get(pid)!.push(c)
    }
    const visited = new Set<string>()
    while (queue.length) {
      const pid = queue.shift()!
      for (const child of byParent.get(pid) ?? []) {
        if (visited.has(child.id)) continue
        visited.add(child.id)
        result.push(child)
        queue.push(child.id)
      }
    }
    return result
  }, [selectedL1Id, categories])

  // Determine the sub-category value: if the current value is under the selected L1, use it; else null
  const subValue = useMemo(() => {
    if (!value || !selectedL1Id) return null
    const ids = new Set(subCategories.map((c) => c.id))
    return ids.has(value) ? value : null
  }, [value, selectedL1Id, subCategories])

  const handleL1Change = (l1Id: string) => {
    setSelectedL1Id(l1Id)
    // When L1 changes, emit the L1 itself as the current selection (user can then refine in sub-tree)
    onChange(l1Id)
  }

  const handleSubChange = (subId: string | null) => {
    if (subId) {
      onChange(subId)
    } else if (selectedL1Id) {
      // Cleared sub-selection → fall back to L1
      onChange(selectedL1Id)
    } else {
      onChange(null)
    }
  }

  return (
    <div className="flex gap-1.5 w-full min-w-0">
      {/* Left: System Category (L1) dropdown */}
      <div className="shrink-0" style={{ minWidth: '7rem', maxWidth: '9rem', flex: '0 0 auto' }}>
        <select
          disabled={disabled}
          value={selectedL1Id ?? ''}
          onChange={(e) => {
            const id = e.target.value
            if (id) handleL1Change(id)
          }}
          className={`w-full h-full min-h-7 border rounded text-xs px-1.5 py-0.5 bg-white appearance-none truncate ${
            disabled
              ? 'border-theme-light-gray text-theme-mid cursor-not-allowed bg-theme-light-gray/40'
              : 'border-theme-light-gray hover:border-theme-mid focus:outline-none focus:ring-1 focus:ring-theme-orange'
          }`}
        >
          <option value="" disabled>
            System cat…
          </option>
          {l1Nodes.map((n) => (
            <option key={n.id} value={n.id}>
              {toTitleCase(n.name)}
            </option>
          ))}
        </select>
      </div>

      {/* Right: Sub-category tree (L2+). Create-new is inside the dropdown. */}
      <div className="flex-1 min-w-0">
        {selectedL1Id ? (
          <CategoryTreeSelector
            categories={subCategories}
            value={subValue}
            onChange={handleSubChange}
            placeholder={placeholder}
            disabled={disabled}
            rootParentId={selectedL1Id}
            onCreateCategory={onCreateCategory}
            onRefetchCategories={onRefetchCategories}
          />
        ) : (
          <div className="w-full px-2 py-1 border rounded text-xs text-theme-mid border-theme-light-gray bg-white min-h-7 flex items-center opacity-50">
            Select system category first
          </div>
        )}
      </div>
    </div>
  )
}
