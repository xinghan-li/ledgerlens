'use client'

/**
 * CategoryTreeSelector
 *
 * A searchable tree-based category selector. Create-new is inside the dropdown:
 *   - Top: "+ Create Sub Category at this level" (under L1) when rootParentId + onCreateCategory provided
 *   - Each row: "+ sub-level" on the right to add child under that node
 */

import { useMemo, useState, useRef, useEffect } from 'react'

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
      else roots.push(node) // parent not in this subset → promote to root
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

interface Props {
  categories: UserCat[]
  value: string | null
  onChange: (id: string | null) => void
  placeholder?: string
  disabled?: boolean
  /** When set, show "+ Create Sub Category at this level" at top and allow creating under this parent (L1 id). */
  rootParentId?: string
  /** Create category via API. May return new id (string) or full category object for optimistic UI. */
  onCreateCategory?: (parentId: string, name: string) => Promise<string | UserCat | null>
  onRefetchCategories?: () => Promise<void>
  /** Called when a new category is created so parent can add it to the list optimistically. */
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

  const tree = useMemo(() => buildTree(categories), [categories])
  const flat = useMemo(() => flattenWithDepth(tree), [tree])

  const filtered = useMemo(() => {
    const q = search.toLowerCase().trim()
    if (!q) return flat
    return flat.filter(({ node }) =>
      node.name.toLowerCase().includes(q) ||
      (node.path ?? '').toLowerCase().includes(q)
    )
  }, [flat, search])

  const selectedLabel = useMemo(() => {
    if (!value) return null
    return getCategoryPath(categories, value)
  }, [categories, value])

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
          <div className="max-h-52 overflow-y-auto py-1">
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

            {filtered.length === 0 && !canCreate && (
              <p className="px-3 py-2 text-xs text-theme-mid italic">No categories found</p>
            )}

            {filtered.map(({ node, depth }) => {
              const isSelected = node.id === value
              const indentPx = depth * 12
              const showCreateUnderThis = creatingUnder === node.id
              return (
                <div key={node.id} className="flex flex-col">
                  <div
                    className={`flex items-center w-full text-left px-3 py-1.5 text-xs gap-1 min-w-0 ${
                      isSelected ? 'bg-theme-orange/15 text-theme-dark font-medium' : 'text-theme-dark hover:bg-theme-cream-f0'
                    }`}
                    style={{ paddingLeft: `${12 + indentPx}px` }}
                  >
                    <button
                      type="button"
                      onClick={() => handleSelect(node.id)}
                      className="flex-1 min-w-0 flex items-center gap-1 text-left"
                    >
                      {depth > 0 && <span className="text-theme-mid shrink-0">{'·'.repeat(depth)}</span>}
                      <span className="truncate">{toTitleCase(node.name)}</span>
                      {node.is_locked && <span className="ml-1 text-theme-mid text-[10px] shrink-0">L1</span>}
                    </button>
                    {canCreate && (
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setCreatingUnder(showCreateUnderThis ? null : node.id); setNewCategoryName(''); setCreateError(null) }}
                        className="shrink-0 px-1.5 py-0.5 text-theme-orange hover:bg-theme-orange/15 rounded text-[10px]"
                        title="Create sub-level"
                      >
                        + sub-level
                      </button>
                    )}
                  </div>
                  {showCreateUnderThis && (
                    <div className="flex items-center gap-1.5 flex-wrap pl-3 pr-2 py-1 bg-theme-cream-f0/50 border-b border-theme-light-gray/30" style={{ paddingLeft: `${12 + indentPx + 12}px` }}>
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
                  )}
                </div>
              )
            })}

            {filtered.length === 0 && canCreate && (
              <p className="px-3 py-2 text-xs text-theme-mid italic">No sub-categories yet. Use &quot;+ Create Sub Category at this level&quot; above.</p>
            )}

            {createError && <p className="px-3 py-1 text-xs text-theme-red">{createError}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
