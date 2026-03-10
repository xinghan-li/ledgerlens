'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'
import { useAuth } from '@/lib/auth-context'
import { type UserCat } from '@/app/dashboard/CategoryTreeSelector'

function toTitleCase(s: string) {
  if (!s) return s
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

type TreeNode = UserCat & { children: TreeNode[] }

function buildTree(cats: UserCat[]): TreeNode[] {
  const byId = new Map<string, TreeNode>()
  for (const c of cats) byId.set(c.id, { ...c, children: [] })
  const roots: TreeNode[] = []
  for (const node of byId.values()) {
    if (!node.parent_id) roots.push(node)
    else byId.get(node.parent_id)?.children.push(node)
  }
  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.name.localeCompare(b.name))
    for (const n of nodes) sortNodes(n.children)
  }
  sortNodes(roots)
  return roots
}

type Mode = 'idle' | 'add' | 'edit' | 'delete'

interface AddEditState {
  mode: Mode
  nodeId?: string // for edit/delete
  parentId?: string // for add
  name: string
  error: string | null
  saving: boolean
}

const initState: AddEditState = { mode: 'idle', name: '', error: null, saving: false }

function CategoryRow({
  node,
  depth,
  onAdd,
  onEdit,
  onDelete,
}: {
  node: TreeNode
  depth: number
  onAdd: (parentId: string) => void
  onEdit: (node: TreeNode) => void
  onDelete: (node: TreeNode) => void
}) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = node.children.length > 0
  return (
    <div>
      <div
        className={`flex items-center gap-1 py-1 px-2 rounded hover:bg-theme-cream-f0 group ${depth === 0 ? 'font-semibold' : ''}`}
        style={{ paddingLeft: `${8 + depth * 20}px` }}
      >
        {/* Expand toggle */}
        {hasChildren ? (
          <button
            type="button"
            className="text-theme-mid w-4 text-xs shrink-0"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '▾' : '▸'}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}

        {/* Name */}
        <span className={`flex-1 text-sm ${node.is_locked ? 'text-theme-dark' : 'text-theme-dark/90'}`}>
          {toTitleCase(node.name)}
          {node.is_locked && (
            <span className="ml-2 text-[10px] text-theme-mid/70 font-normal align-middle bg-theme-light-gray/60 px-1 py-0.5 rounded">
              system
            </span>
          )}
        </span>

        {/* Actions — visible on hover */}
        <span className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            type="button"
            onClick={() => onAdd(node.id)}
            className="text-xs text-theme-mid hover:text-theme-dark px-1.5 py-0.5 rounded hover:bg-theme-light-gray/60"
            title="Add subcategory"
          >
            + sub
          </button>
          {!node.is_locked && (
            <>
              <button
                type="button"
                onClick={() => onEdit(node)}
                className="text-xs text-theme-mid hover:text-theme-dark px-1.5 py-0.5 rounded hover:bg-theme-light-gray/60"
                title="Rename"
              >
                rename
              </button>
              <button
                type="button"
                onClick={() => onDelete(node)}
                className="text-xs text-theme-red/70 hover:text-theme-red px-1.5 py-0.5 rounded hover:bg-theme-red/10"
                title="Delete"
              >
                ×
              </button>
            </>
          )}
        </span>
      </div>

      {/* Children */}
      {expanded && node.children.map((child) => (
        <CategoryRow
          key={child.id}
          node={child}
          depth={depth + 1}
          onAdd={onAdd}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}

export default function CategoriesPage() {
  const apiBaseUrl = useApiUrl()
  const auth = useAuth()
  const [categories, setCategories] = useState<UserCat[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState<AddEditState>(initState)
  const [deleteConfirm, setDeleteConfirm] = useState<{ node: TreeNode; childAction: 'move_to_parent' | 'delete_recursive' } | null>(null)

  const headers = useCallback(() => ({
    'Content-Type': 'application/json',
    Authorization: `Bearer ${auth?.token ?? ''}`,
  }), [auth?.token])

  const fetchCategories = useCallback(async () => {
    if (!auth?.token) return
    const res = await fetch(`${apiBaseUrl}/api/me/categories`, { headers: { Authorization: `Bearer ${auth.token}` } })
    if (res.ok) {
      const json = await res.json()
      setCategories(json?.data ?? [])
      setError(null)
    } else {
      setError('Failed to load categories')
    }
  }, [apiBaseUrl, auth?.token])

  useEffect(() => {
    if (!auth?.token) { setLoading(false); return }
    setLoading(true)
    fetchCategories().finally(() => setLoading(false))
  }, [auth?.token, fetchCategories])

  const tree = useMemo(() => buildTree(categories), [categories])

  const getParentName = (parentId: string | undefined): string => {
    if (!parentId) return ''
    const cat = categories.find((c) => c.id === parentId)
    return cat ? toTitleCase(cat.name) : ''
  }

  const handleAddClick = (parentId: string) => {
    setForm({ mode: 'add', parentId, name: '', error: null, saving: false })
  }

  const handleEditClick = (node: TreeNode) => {
    setForm({ mode: 'edit', nodeId: node.id, name: node.name, error: null, saving: false })
  }

  const handleDeleteClick = (node: TreeNode) => {
    setDeleteConfirm({ node, childAction: 'move_to_parent' })
  }

  const submitAdd = async () => {
    const name = form.name.trim()
    if (!name) { setForm((f) => ({ ...f, error: 'Name is required' })); return }
    setForm((f) => ({ ...f, saving: true, error: null }))
    try {
      const res = await fetch(`${apiBaseUrl}/api/me/categories`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ parent_id: form.parentId, name }),
      })
      if (res.ok) {
        await fetchCategories()
        setForm(initState)
      } else {
        const data = await res.json().catch(() => ({}))
        setForm((f) => ({ ...f, saving: false, error: data?.detail ?? 'Failed to create' }))
      }
    } catch {
      setForm((f) => ({ ...f, saving: false, error: 'Network error' }))
    }
  }

  const submitEdit = async () => {
    const name = form.name.trim()
    if (!name) { setForm((f) => ({ ...f, error: 'Name is required' })); return }
    setForm((f) => ({ ...f, saving: true, error: null }))
    try {
      const res = await fetch(`${apiBaseUrl}/api/me/categories/${form.nodeId}`, {
        method: 'PATCH',
        headers: headers(),
        body: JSON.stringify({ name }),
      })
      if (res.ok) {
        await fetchCategories()
        setForm(initState)
      } else {
        const data = await res.json().catch(() => ({}))
        setForm((f) => ({ ...f, saving: false, error: data?.detail ?? 'Failed to update' }))
      }
    } catch {
      setForm((f) => ({ ...f, saving: false, error: 'Network error' }))
    }
  }

  const submitDelete = async () => {
    if (!deleteConfirm) return
    const { node, childAction } = deleteConfirm
    setDeleteConfirm(null)
    try {
      const res = await fetch(
        `${apiBaseUrl}/api/me/categories/${node.id}?child_action=${childAction}`,
        { method: 'DELETE', headers: headers() }
      )
      if (res.ok) {
        await fetchCategories()
      } else {
        const data = await res.json().catch(() => ({}))
        setError(data?.detail ?? 'Failed to delete')
      }
    } catch {
      setError('Network error')
    }
  }

  if (!auth?.token) {
    return <div className="p-4 text-theme-mid">Please sign in.</div>
  }

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <div className="flex items-center justify-between gap-4 mb-6">
        <h1 className="text-xl font-semibold text-theme-dark">My Categories</h1>
        <Link href="/dashboard" className="text-sm text-theme-dark/70 hover:underline">← Back</Link>
      </div>

      <p className="text-sm text-theme-dark/70 mb-4">
        Customize your category tree. <strong>System categories</strong> (marked &quot;system&quot;) are your L1 roots and cannot be renamed or deleted. Add as many subcategories as you like beneath them.
      </p>

      {error && (
        <div className="mb-4 text-sm text-theme-red bg-theme-red/10 px-3 py-2 rounded">{error}</div>
      )}

      {loading ? (
        <div className="text-center text-theme-mid py-8">Loading…</div>
      ) : (
        <div className="bg-white rounded-xl shadow border border-theme-light-gray/50 overflow-hidden">
          <div className="p-3 border-b border-theme-light-gray/50">
            <span className="text-xs text-theme-mid">Hover over a row to add subcategories, rename, or delete</span>
          </div>
          <div className="p-2">
            {tree.map((node) => (
              <CategoryRow
                key={node.id}
                node={node}
                depth={0}
                onAdd={handleAddClick}
                onEdit={handleEditClick}
                onDelete={handleDeleteClick}
              />
            ))}
          </div>
        </div>
      )}

      {/* Add / Edit inline form */}
      {(form.mode === 'add' || form.mode === 'edit') && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl border border-theme-light-gray/50 max-w-sm w-full p-6">
            <h3 className="font-semibold text-theme-dark mb-1">
              {form.mode === 'add'
                ? `Add subcategory under "${getParentName(form.parentId)}"`
                : 'Rename category'}
            </h3>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value, error: null }))}
              onKeyDown={(e) => {
                if (e.key === 'Enter') form.mode === 'add' ? submitAdd() : submitEdit()
                if (e.key === 'Escape') setForm(initState)
              }}
              placeholder="Category name"
              autoFocus
              className="w-full mt-2 px-3 py-2 border border-theme-mid rounded-lg text-sm focus:ring-2 focus:ring-theme-orange focus:border-theme-orange"
            />
            {form.error && <p className="mt-2 text-sm text-theme-red">{form.error}</p>}
            <div className="mt-4 flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setForm(initState)}
                className="px-4 py-2 text-sm text-theme-dark/80 hover:bg-theme-cream-f0 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={form.saving}
                onClick={form.mode === 'add' ? submitAdd : submitEdit}
                className="px-4 py-2 text-sm font-medium bg-theme-orange text-white rounded-lg hover:opacity-90 disabled:opacity-50"
              >
                {form.saving ? 'Saving…' : form.mode === 'add' ? 'Add' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="bg-white rounded-xl shadow-xl border border-theme-light-gray/50 max-w-sm w-full p-6">
            <h3 className="font-semibold text-theme-dark mb-2">
              Delete &quot;{toTitleCase(deleteConfirm.node.name)}&quot;?
            </h3>
            {deleteConfirm.node.children.length > 0 && (
              <div className="mb-4">
                <p className="text-sm text-theme-dark/80 mb-2">
                  This category has subcategories. What should happen to them?
                </p>
                <label className="flex items-start gap-2 text-sm text-theme-dark/80 mb-1">
                  <input
                    type="radio"
                    name="childAction"
                    value="move_to_parent"
                    checked={deleteConfirm.childAction === 'move_to_parent'}
                    onChange={() => setDeleteConfirm((d) => d ? { ...d, childAction: 'move_to_parent' } : d)}
                    className="mt-0.5"
                  />
                  Move subcategories up to parent
                </label>
                <label className="flex items-start gap-2 text-sm text-theme-dark/80">
                  <input
                    type="radio"
                    name="childAction"
                    value="delete_recursive"
                    checked={deleteConfirm.childAction === 'delete_recursive'}
                    onChange={() => setDeleteConfirm((d) => d ? { ...d, childAction: 'delete_recursive' } : d)}
                    className="mt-0.5"
                  />
                  Delete all subcategories too
                </label>
              </div>
            )}
            <p className="text-sm text-theme-dark/70 mb-4">
              Items currently assigned to this category will lose their category assignment.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-sm text-theme-dark/80 hover:bg-theme-cream-f0 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitDelete}
                className="px-4 py-2 text-sm font-medium bg-theme-red text-white rounded-lg hover:opacity-90"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
