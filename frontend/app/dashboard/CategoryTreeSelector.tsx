'use client'

/**
 * CategoryTreeSelector
 *
 * A searchable, collapsible tree-based category selector.
 * - Default: only L1 categories shown, collapsed
 * - Click chevron bubble to expand/collapse children
 * - Click category name to select it
 * - Search mode: shows all matching nodes flat (ignores collapse state)
 * - "+ sub-level" to create child under any node
 */

import { useMemo, useState, useRef, useEffect, useCallback } from 'react'

export type UserCat = {
  id: string
  parent_id: string | null
  level: number
  name: string
  path: string | null
  is_locked?: boolean
  sort_order?: number
}

type TreeNode = UserCat & { children: TreeNode[] }

function buildTree(cats: UserCat[]): TreeNode[] {
  const byId = new Map<string, TreeNode>()
  for (const c of cats) byId.set(c.id, { ...c, children: [] })
  const roots: TreeNode[] = []
  for (const node of byId.values()) {
    if (!node.parent_id) {
      roots.push(node)
    } else {
      const parent = byId.get(node.parent_id)
      if (parent) parent.children.push(node)
      else roots.push(node)
    }
  }
  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name))
    for (const n of nodes) sortNodes(n.children)
  }
  sortNodes(roots)
  return roots
}

function flattenWithDepth(nodes: TreeNode[], depth = 0): { node: TreeNode; depth: number }[] {
  const out: { node: TreeNode; depth: number }[] = []
  for (const n of nodes) {
    out.push({ node: n, depth })
    out.push(...flattenWithDepth(n.children, depth + 1))
  }
  return out
}

function toTitleCase(s: string) {
  if (!s) return s
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

function getCategoryPath(cats: UserCat[], id: string): string {
  const byId = new Map(cats.map((c) => [c.id, c]))
  const parts: string[] = []
  let cur: UserCat | undefined = byId.get(id)
  while (cur) {
    parts.unshift(toTitleCase(cur.name))
    cur = cur.parent_id ? byId.get(cur.parent_id) : undefined
  }
  return parts.join(' › ')
}

/** Collect all ancestor IDs for a given category so we can auto-expand the path to the selected value */
function getAncestorIds(cats: UserCat[], id: string): Set<string> {
  const byId = new Map(cats.map((c) => [c.id, c]))
  const ancestors = new Set<string>()
  let cur = byId.get(id)
  while (cur?.parent_id) {
    ancestors.add(cur.parent_id)
    cur = byId.get(cur.parent_id)
  }
  return ancestors
}

interface Props {
  categories: UserCat[]
  value: string | null
  onChange: (id: string | null) => void
  placeholder?: string
  disabled?: boolean
  rootParentId?: string
  onCreateCategory?: (parentId: string, name: string) => Promise<string | UserCat | null>
  onRefetchCategories?: () => Promise<void>
  onCategoryCreated?: (cat: UserCat) => void
}

export default function CategoryTreeSelector({
  categories,
  value,
  onChange,
  placeholder = 'Select category…',
  disabled = false,
  rootParentId,
  onCreateCategory,
  onRefetchCategories,
  onCategoryCreated,
}: Props) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [creatingUnder, setCreatingUnder] = useState<string | null>(null)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Expanded state: which L1/L2 nodes are expanded
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    // Auto-expand path to selected value
    if (value) return getAncestorIds(categories, value)
    return new Set()
  })

  const tree = useMemo(() => buildTree(categories), [categories])
  const flat = useMemo(() => flattenWithDepth(tree), [tree])

  const isSearching = search.trim().length > 0

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim()
    if (!q) return flat
    return flat.filter(({ node }) =>
      node.name.toLowerCase().includes(q) ||
      (node.path ?? '').toLowerCase().includes(q)
    )
  }, [flat, search])

  // In normal (non-search) mode, only show nodes whose parents are all expanded
  const visibleNodes = useMemo(() => {
    if (isSearching) return filtered
    return flat.filter(({ node, depth }) => {
      if (depth === 0) return true // L1 always visible
      // Check all ancestors are expanded
      const byId = new Map(categories.map((c) => [c.id, c]))
      let cur = byId.get(node.parent_id ?? '')
      while (cur) {
        if (!expanded.has(cur.id)) return false
        if (!cur.parent_id) break
        cur = byId.get(cur.parent_id)
      }
      return true
    })
  }, [flat, filtered, isSearching, expanded, categories])

  const selectedLabel = useMemo(() => {
    if (!value) return null
    return getCategoryPath(categories, value)
  }, [categories, value])

  const toggleExpanded = useCallback((id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Update expanded when value changes (auto-expand path to selected)
  useEffect(() => {
    if (value) {
      const ancestors = getAncestorIds(categories, value)
      if (ancestors.size > 0) {
        setExpanded(prev => {
          const next = new Set(prev)
          for (const a of ancestors) next.add(a)
          return next
        })
      }
    }
  }, [value, categories])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleOpen = () => {
    if (disabled) return
    setOpen(true)
    setTimeout(() => inputRef.current?.focus(), 0)
  }

  const handleSelect = (id: string | null) => {
    onChange(id)
    setOpen(false)
    setSearch('')
  }

  const handleCreateSubmit = async () => {
    const parentId = creatingUnder ?? rootParentId
    const name = newCategoryName.trim()
    if (!name || !parentId || !onCreateCategory) return
    setCreating(true)
    setCreateError(null)
    try {
      const result = await onCreateCategory(parentId, name)
      if (result != null) {
        const newId = typeof result === 'string' ? result : result.id
        const fullCat: UserCat | null =
          typeof result === 'object' && result && 'id' in result && 'name' in result
            ? {
                id: result.id,
                parent_id: result.parent_id ?? null,
                name: result.name,
                path: result.path ?? null,
                level: result.level ?? 2,
                is_locked: result.is_locked,
                sort_order: result.sort_order,
              }
            : null
        if (fullCat) onCategoryCreated?.(fullCat)
        if (onRefetchCategories) await onRefetchCategories()
        // Auto-expand the parent so the new child is visible
        setExpanded(prev => { const n = new Set(prev); n.add(parentId); return n })
        onChange(newId)
        setNewCategoryName('')
        setCreatingUnder(null)
        setOpen(false)
      } else {
        setCreateError('Failed to create')
      }
    } catch {
      setCreateError('Failed to create')
    } finally {
      setCreating(false)
    }
  }

  const canCreate = Boolean(rootParentId && onCreateCategory && !disabled)

  /** Check if a node has children */
  const hasChildren = useCallback((nodeId: string): boolean => {
    return categories.some(c => c.parent_id === nodeId)
  }, [categories])

  return (
    <div ref={containerRef} className="relative w-full">
      {/* Trigger button */}
      <button
        type="button"
        onClick={handleOpen}
        disabled={disabled}
        className={`w-full text-left px-2 py-1 border rounded text-xs flex items-center justify-between gap-1 ${
          disabled
            ? 'bg-theme-light-gray/40 text-theme-mid border-theme-light-gray cursor-not-allowed'
            : 'bg-white border-theme-light-gray hover:border-theme-mid focus:outline-none focus:ring-1 focus:ring-theme-orange'
        }`}
      >
        <span className={`truncate ${selectedLabel ? 'text-theme-dark' : 'text-theme-mid'}`}>
          {selectedLabel ?? placeholder}
        </span>
        <span className="text-theme-mid shrink-0">{open ? '▲' : '▼'}</span>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 mt-1 w-full min-w-[220px] bg-white border border-theme-light-gray rounded-lg shadow-lg overflow-hidden">
          {/* Search */}
          <div className="p-2 border-b border-theme-light-gray">
            <input
              ref={inputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search…"
              className="w-full px-2 py-1 text-xs border border-theme-light-gray rounded focus:outline-none focus:ring-1 focus:ring-theme-orange"
            />
          </div>

          {/* Options */}
          <div className="max-h-60 overflow-y-auto py-1">
            {/* Clear option */}
            {value && (
              <button
                type="button"
                onClick={() => handleSelect(null)}
                className="w-full text-left px-3 py-1.5 text-xs text-theme-mid hover:bg-theme-cream-f0 italic"
              >
                — Clear selection
              </button>
            )}

            {/* Create sub-category at top (under L1) */}
            {canCreate && rootParentId && (
              <>
                {creatingUnder === rootParentId ? (
                  <div className="px-3 py-1.5 flex items-center gap-1.5 flex-wrap border-t border-theme-light-gray/50 mt-1 pt-1">
                    <input
                      type="text"
                      value={newCategoryName}
                      onChange={(e) => { setNewCategoryName(e.target.value); setCreateError(null) }}
                      placeholder="New sub-category…"
                      className="flex-1 min-w-0 px-2 py-1 text-xs border border-theme-light-gray rounded focus:outline-none focus:ring-1 focus:ring-theme-orange"
                      onKeyDown={(e) => e.key === 'Enter' && handleCreateSubmit()}
                      autoFocus
                    />
                    <button type="button" onClick={handleCreateSubmit} disabled={creating || !newCategoryName.trim()} className="px-2 py-1 text-xs bg-theme-orange text-white rounded hover:bg-theme-orange/90 disabled:opacity-50">Add</button>
                    <button type="button" onClick={() => { setCreatingUnder(null); setNewCategoryName(''); setCreateError(null) }} className="px-2 py-1 text-xs text-theme-mid hover:text-theme-dark">Cancel</button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setCreatingUnder(rootParentId); setNewCategoryName(''); setCreateError(null) }}
                    className="w-full text-left px-3 py-1.5 text-xs text-theme-orange hover:bg-theme-cream-f0 font-medium"
                  >
                    + Create Sub Category at this level
                  </button>
                )}
              </>
            )}

            {visibleNodes.length === 0 && !canCreate && (
              <p className="px-3 py-2 text-xs text-theme-mid italic">No categories found</p>
            )}

            {visibleNodes.map(({ node, depth }) => {
              const isSelected = node.id === value
              const indentPx = depth * 16
              const showCreateUnderThis = creatingUnder === node.id
              const nodeHasChildren = hasChildren(node.id)
              const isExpanded = expanded.has(node.id)
              return (
                <div key={node.id} className="flex flex-col">
                  <div
                    className={`flex items-center w-full text-left px-2 py-1.5 text-xs gap-0.5 min-w-0 ${
                      isSelected ? 'bg-theme-orange/15 text-theme-dark font-medium' : 'text-theme-dark hover:bg-theme-cream-f0'
                    }`}
                    style={{ paddingLeft: `${8 + indentPx}px` }}
                  >
                    {/* Expand/collapse chevron */}
                    {nodeHasChildren && !isSearching ? (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); toggleExpanded(node.id) }}
                        className="shrink-0 w-5 h-5 flex items-center justify-center rounded-full bg-theme-light-gray/60 hover:bg-theme-light-gray text-theme-mid text-[9px] mr-1"
                        title={isExpanded ? 'Collapse' : 'Expand'}
                      >
                        {isExpanded ? '▼' : '▶'}
                      </button>
                    ) : (
                      <span className="shrink-0 w-5 mr-1" />
                    )}
                    {/* Category name (clickable to select) */}
                    <button
                      type="button"
                      onClick={() => handleSelect(node.id)}
                      className="flex-1 min-w-0 flex items-center gap-1 text-left"
                    >
                      <span className="truncate">{toTitleCase(node.name)}</span>
                      {node.is_locked && <span className="ml-0.5 text-theme-mid text-[10px] shrink-0">L1</span>}
                    </button>
                    {/* Create sub-level button */}
                    {canCreate && (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setCreatingUnder(showCreateUnderThis ? null : node.id); setNewCategoryName(''); setCreateError(null); if (!isExpanded) toggleExpanded(node.id) }}
                        className="shrink-0 px-1.5 py-0.5 text-theme-orange hover:bg-theme-orange/15 rounded text-[10px]"
                        title="Create sub-level"
                      >
                        +
                      </button>
                    )}
                  </div>
                  {showCreateUnderThis && (
                    <div className="flex items-center gap-1.5 flex-wrap pr-2 py-1 bg-theme-cream-f0/50 border-b border-theme-light-gray/30" style={{ paddingLeft: `${8 + indentPx + 22}px` }}>
                      <input
                        type="text"
                        value={newCategoryName}
                        onChange={(e) => { setNewCategoryName(e.target.value); setCreateError(null) }}
                        placeholder="New sub-category…"
                        className="flex-1 min-w-0 px-2 py-1 text-xs border border-theme-light-gray rounded focus:outline-none focus:ring-1 focus:ring-theme-orange"
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateSubmit()}
                        autoFocus
                      />
                      <button type="button" onClick={handleCreateSubmit} disabled={creating || !newCategoryName.trim()} className="px-2 py-1 text-xs bg-theme-orange text-white rounded hover:bg-theme-orange/90 disabled:opacity-50">Add</button>
                      <button type="button" onClick={() => { setCreatingUnder(null); setNewCategoryName(''); setCreateError(null) }} className="px-2 py-1 text-xs text-theme-mid hover:text-theme-dark">×</button>
                    </div>
                  )}
                </div>
              )
            })}

            {visibleNodes.length === 0 && canCreate && (
              <p className="px-3 py-2 text-xs text-theme-mid italic">No sub-categories yet. Use &quot;+ Create Sub Category at this level&quot; above.</p>
            )}

            {createError && <p className="px-3 py-1 text-xs text-theme-red">{createError}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
