'use client'

import { Fragment, useEffect, useState } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import { useApiUrl } from '@/lib/api-url-context'

type Binding = {
  id: string
  prompt_key: string
  library_id: string
  scope: string
  chain_id: string | null
  location_id: string | null
  priority: number
  is_active: boolean
  chain_name?: string | null
  created_at?: string | null
  updated_at?: string | null
}

type PromptRow = {
  id: string
  key: string
  category: string
  content_role: string
  content: string
  version: number
  is_active: boolean
  created_at?: string | null
  updated_at?: string | null
  bindings: Binding[]
  binding_count: number
}

type Chain = { id: string; name: string; normalized_name: string }

const CATEGORIES = ['', 'receipt', 'classification', 'system', 'analysis'] as const
const CATEGORY_LABELS: Record<string, string> = {
  '': 'All',
  receipt: 'Receipt',
  classification: 'Classification',
  system: 'System',
  analysis: 'Analysis',
}

/** Only Super Admin (9) can edit these system first-round prompts. */
const PROTECTED_PROMPT_KEYS = ['vision_primary', 'vision_escalation', 'classification']

export default function AdminPromptsPage() {
  const apiBaseUrl = useApiUrl()
  const [rows, setRows] = useState<PromptRow[]>([])
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [category, setCategory] = useState<string>('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState<Record<string, string>>({})
  const [savingId, setSavingId] = useState<string | null>(null)
  const [chains, setChains] = useState<Chain[]>([])
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [addKey, setAddKey] = useState('')
  const [addCategory, setAddCategory] = useState('receipt')
  const [addContentRole, setAddContentRole] = useState('system')
  const [addContent, setAddContent] = useState('')
  const [addIsActive, setAddIsActive] = useState(true)
  const [addBindToChain, setAddBindToChain] = useState(false)
  const [addChainId, setAddChainId] = useState('')
  const [addBindPriority, setAddBindPriority] = useState(50)
  const [addSubmitting, setAddSubmitting] = useState(false)
  const [addingBindingForId, setAddingBindingForId] = useState<string | null>(null)
  const [newBindingChainId, setNewBindingChainId] = useState('')
  const [newBindingPriority, setNewBindingPriority] = useState(50)
  const [clearCacheLoading, setClearCacheLoading] = useState(false)
  const [toast, setToast] = useState<{ type: 'ok' | 'err'; msg: string } | null>(null)
  /** When false (default), hide prompts with is_active === false. When true, show all. */
  const [showInactive, setShowInactive] = useState(false)
  /** 7 = admin (store-only), 9 = super_admin (can edit system prompts). From GET /api/admin/prompts. */
  const [currentUserClass, setCurrentUserClass] = useState(9)

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setToken(user ? await user.getIdToken() : null)
    })
    return () => unsubscribe()
  }, [])

  const fetchPrompts = async () => {
    if (!token) return
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      if (category) params.set('category', category)
      const res = await fetch(`${apiBaseUrl}/api/admin/prompts?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setRows(data.data || [])
      if (typeof data.current_user_class === 'number') setCurrentUserClass(data.current_user_class)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }

  const fetchChains = async () => {
    if (!token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/store-review/chains?active_only=false`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setChains(data.data || [])
      }
    } catch (_) {}
  }

  useEffect(() => {
    if (token) {
      fetchPrompts()
      fetchChains()
    }
  }, [token, category])

  const showToast = (type: 'ok' | 'err', msg: string) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 3000)
  }

  const handleSaveContent = async (id: string) => {
    if (!token) return
    const content = editContent[id]
    if (content === undefined) return
    setSavingId(id)
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/prompts/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ content }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Save failed')
      }
      setEditContent((p) => {
        const next = { ...p }
        delete next[id]
        return next
      })
      showToast('ok', 'Saved')
      fetchPrompts()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSavingId(null)
    }
  }

  const handleAddBinding = async (promptId: string) => {
    if (!token || !newBindingChainId) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/prompts/${promptId}/bindings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          prompt_key: rows.find((r) => r.id === promptId)?.key,
          scope: 'chain',
          chain_id: newBindingChainId,
          priority: newBindingPriority,
        }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Add binding failed')
      }
      setNewBindingChainId('')
      setNewBindingPriority(50)
      setAddingBindingForId(null)
      showToast('ok', 'Binding added')
      fetchPrompts()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Add binding failed')
    }
  }

  const handleRemoveBinding = async (bindingId: string) => {
    if (!token) return
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/prompts/bindings/${bindingId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error('Remove binding failed')
      showToast('ok', 'Binding deactivated')
      fetchPrompts()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Remove failed')
    }
  }

  const handleClearCache = async () => {
    if (!token) return
    setClearCacheLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/prompts/cache/clear`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(await res.text())
      showToast('ok', 'Cache cleared')
    } catch (e) {
      showToast('err', e instanceof Error ? e.message : 'Clear cache failed')
    } finally {
      setClearCacheLoading(false)
    }
  }

  const handleCreatePrompt = async () => {
    if (!token || !addKey.trim()) return
    setAddSubmitting(true)
    setError(null)
    try {
      const body: Record<string, unknown> = {
        key: addKey.trim(),
        category: addCategory,
        content_role: addContentRole,
        content: addContent,
        is_active: addIsActive,
      }
      if (addBindToChain && addChainId) {
        body.bind_to_chain_id = addChainId
        body.bind_scope = 'chain'
        body.bind_priority = addBindPriority
      } else {
        body.bind_scope = 'default'
        body.bind_priority = 10
      }
      const res = await fetch(`${apiBaseUrl}/api/admin/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Create failed')
      setAddModalOpen(false)
      setAddKey('')
      setAddCategory('receipt')
      setAddContentRole('system')
      setAddContent('')
      setAddIsActive(true)
      setAddBindToChain(false)
      setAddChainId('')
      setAddBindPriority(50)
      showToast('ok', 'Prompt created')
      fetchPrompts()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setAddSubmitting(false)
    }
  }

  const expandRow = (r: PromptRow) => {
    setExpandedId(expandedId === r.id ? null : r.id)
    if (editContent[r.id] === undefined) setEditContent((p) => ({ ...p, [r.id]: r.content }))
  }

  const formatDate = (s: string | null | undefined) => {
    if (!s) return '—'
    try {
      const d = new Date(s)
      return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    } catch {
      return '—'
    }
  }

  /** Scope is only from prompt_binding (enum: default | chain | location). No binding = loaded by key, show N/A. */
  const scopeDisplay = (r: PromptRow) => {
    if (r.binding_count === 0) return '—'
    const scopes = [...new Set(r.bindings.map((b) => b.scope))]
    return scopes.join(', ')
  }

  const boundToDisplay = (r: PromptRow) => {
    const chainBindings = r.bindings.filter((b) => b.scope === 'chain' && b.chain_name)
    if (chainBindings.length === 0) return '—'
    return chainBindings.map((b) => b.chain_name).join(', ')
  }

  const filteredRows = showInactive ? rows : rows.filter((r) => r.is_active)

  if (!token) {
    return (
      <div className="text-center py-8 text-theme-mid">
        Please sign in first.
      </div>
    )
  }

  return (
    <div>
      <h2 className="font-heading text-lg sm:text-xl font-semibold mb-4 text-theme-dark">
        Prompt Management
      </h2>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        {CATEGORIES.map((cat) => (
          <button
            key={cat || '_all'}
            type="button"
            onClick={() => setCategory(cat)}
            className={`px-3 py-1.5 rounded border text-sm font-medium ${
              category === cat
                ? 'border-theme-orange bg-theme-orange/15 text-theme-dark'
                : 'border-theme-light-gray bg-white text-theme-dark/90 hover:bg-theme-cream/80'
            }`}
          >
            {CATEGORY_LABELS[cat] ?? cat}
          </button>
        ))}
        <label className="flex items-center gap-2 text-sm text-theme-dark/90">
          <input
            type="checkbox"
            checked={showInactive}
            onChange={(e) => setShowInactive(e.target.checked)}
            className="rounded border-theme-light-gray"
          />
          Show inactive
        </label>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => setAddModalOpen(true)}
          className="px-3 py-1.5 rounded border border-theme-orange bg-theme-orange/20 text-theme-dark hover:bg-theme-orange/30 text-sm font-medium"
        >
          + Add Prompt
        </button>
        <button
          type="button"
          onClick={handleClearCache}
          disabled={clearCacheLoading}
          className="px-3 py-1.5 rounded border border-theme-mid/40 bg-theme-cream/60 hover:bg-theme-cream disabled:opacity-50 text-sm"
        >
          {clearCacheLoading ? 'Clearing…' : 'Clear Cache'}
        </button>
      </div>

      {toast && (
        <div
          className={`mb-4 px-3 py-2 rounded text-sm ${
            toast.type === 'ok' ? 'bg-green-100 text-green-800' : 'bg-theme-red/15 text-theme-red'
          }`}
        >
          {toast.msg}
        </div>
      )}
      {error && (
        <div className="mb-4 p-2 bg-theme-red/15 text-theme-red rounded text-sm">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-theme-mid">Loading…</p>
      ) : (
        <div className="overflow-x-auto bg-white rounded-lg shadow">
          <table className="min-w-full divide-y divide-theme-light-gray text-sm">
            <thead className="bg-theme-cream/80">
              <tr>
                <th className="px-3 py-2 text-left w-8" aria-label="Expand" />
                <th className="px-3 py-2 text-left">Key</th>
                <th className="px-3 py-2 text-left">Role</th>
                <th className="px-3 py-2 text-left" title="From prompt_binding: default, chain, or location. — = no binding (prompt loaded by key).">Scope</th>
                <th className="px-3 py-2 text-left">Bound To</th>
                <th className="px-3 py-2 text-left">Updated</th>
                <th className="px-3 py-2 text-left">Active</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-theme-light-gray">
              {filteredRows.map((r) => (
                <Fragment key={r.id}>
                  <tr
                    className="cursor-pointer hover:bg-theme-cream/60"
                    onClick={() => expandRow(r)}
                  >
                    <td className="px-3 py-2 text-theme-mid">
                      {expandedId === r.id ? '▼' : '▶'}
                    </td>
                    <td className="px-3 py-2 font-medium text-theme-dark">
                      {r.key}
                      {r.binding_count > 0 && (
                        <span className="ml-1 text-theme-mid font-normal">
                          ({r.binding_count} binding{r.binding_count !== 1 ? 's' : ''})
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-theme-dark/90">{r.content_role}</td>
                    <td className="px-3 py-2 text-theme-dark/90">{scopeDisplay(r)}</td>
                    <td className="px-3 py-2 text-theme-dark/90 max-w-[180px] truncate">
                      {boundToDisplay(r)}
                    </td>
                    <td className="px-3 py-2 text-theme-dark/90">{formatDate(r.updated_at)}</td>
                    <td className="px-3 py-2">{r.is_active ? '✓' : '—'}</td>
                  </tr>
                  {expandedId === r.id && (
                    <tr className="bg-theme-cream/30">
                      <td colSpan={7} className="px-3 py-4">
                        <div className="space-y-4">
                          <div>
                            {currentUserClass < 9 && PROTECTED_PROMPT_KEYS.includes(r.key) && (
                              <p className="text-xs text-theme-mid mb-2">Only Super Admin can edit this system prompt.</p>
                            )}
                            <p className="text-xs text-theme-mid mb-1">
                              Placeholders (e.g. user_template): {'{reference_date}'}, {'{failure_reason}'}, {'{primary_notes}'}
                            </p>
                            <textarea
                              className="w-full border border-theme-light-gray rounded-lg px-2 py-2 text-sm font-mono min-h-[200px] text-theme-dark bg-white disabled:bg-theme-cream/50 disabled:cursor-not-allowed"
                              value={editContent[r.id] ?? r.content}
                              onChange={(e) => setEditContent((p) => ({ ...p, [r.id]: e.target.value }))}
                              onClick={(e) => e.stopPropagation()}
                              readOnly={currentUserClass < 9 && PROTECTED_PROMPT_KEYS.includes(r.key)}
                            />
                            {!(currentUserClass < 9 && PROTECTED_PROMPT_KEYS.includes(r.key)) && (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  handleSaveContent(r.id)
                                }}
                                disabled={savingId === r.id}
                                className="mt-2 px-3 py-1.5 rounded border border-theme-orange bg-theme-orange/20 text-theme-dark hover:bg-theme-orange/30 text-sm disabled:opacity-50"
                              >
                                {savingId === r.id ? 'Saving…' : 'Save Changes'}
                              </button>
                            )}
                          </div>
                          {r.bindings.length > 0 && (
                            <div>
                              <h4 className="text-sm font-semibold text-theme-dark mb-2">Bindings</h4>
                              <table className="min-w-full divide-y divide-theme-light-gray text-sm bg-white rounded border border-theme-light-gray">
                                <thead className="bg-theme-cream/60">
                                  <tr>
                                    <th className="px-2 py-1.5 text-left">Scope</th>
                                    <th className="px-2 py-1.5 text-left">Chain / Location</th>
                                    <th className="px-2 py-1.5 text-left">Priority</th>
                                    <th className="px-2 py-1.5 text-left">Active</th>
                                    <th className="px-2 py-1.5 text-left">Action</th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-theme-light-gray">
                                  {r.bindings.map((b) => (
                                    <tr key={b.id}>
                                      <td className="px-2 py-1.5">{b.scope}</td>
                                      <td className="px-2 py-1.5">
                                        {b.scope === 'chain' && b.chain_name ? b.chain_name : b.scope === 'location' ? b.location_id ?? '—' : '—'}
                                      </td>
                                      <td className="px-2 py-1.5">{b.priority}</td>
                                      <td className="px-2 py-1.5">{b.is_active ? '✓' : '—'}</td>
                                      <td className="px-2 py-1.5">
                                        {b.is_active && (
                                          <button
                                            type="button"
                                            onClick={(e) => {
                                              e.stopPropagation()
                                              handleRemoveBinding(b.id)
                                            }}
                                            className="text-theme-red text-xs hover:underline"
                                          >
                                            Remove
                                          </button>
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                          <div>
                            {addingBindingForId === r.id ? (
                              <div className="flex flex-wrap items-center gap-2 p-2 bg-white rounded border border-theme-light-gray">
                                <select
                                  value={newBindingChainId}
                                  onChange={(e) => setNewBindingChainId(e.target.value)}
                                  className="border rounded px-2 py-1 text-sm"
                                >
                                  <option value="">Select chain…</option>
                                  {chains.map((c) => (
                                    <option key={c.id} value={c.id}>
                                      {c.name}
                                    </option>
                                  ))}
                                </select>
                                <input
                                  type="number"
                                  value={newBindingPriority}
                                  onChange={(e) => setNewBindingPriority(Number(e.target.value) || 50)}
                                  className="border rounded px-2 py-1 w-20 text-sm"
                                  placeholder="Priority"
                                />
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleAddBinding(r.id)
                                  }}
                                  disabled={!newBindingChainId}
                                  className="px-2 py-1 rounded border border-theme-orange bg-theme-orange/20 text-sm disabled:opacity-50"
                                >
                                  Confirm
                                </button>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    setAddingBindingForId(null)
                                    setNewBindingChainId('')
                                  }}
                                  className="px-2 py-1 rounded border text-sm"
                                >
                                  Cancel
                                </button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setAddingBindingForId(r.id)
                                  setNewBindingChainId('')
                                  setNewBindingPriority(50)
                                }}
                                className="px-2 py-1 rounded border border-theme-mid/40 bg-theme-cream/60 text-sm"
                              >
                                + Add Chain Binding
                              </button>
                            )}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {addModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={() => !addSubmitting && setAddModalOpen(false)}
          role="dialog"
          aria-modal="true"
          aria-labelledby="add-prompt-title"
        >
          <div
            className="bg-white rounded-xl shadow-lg max-w-2xl w-full max-h-[90vh] overflow-y-auto mx-4 p-6"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="add-prompt-title" className="font-heading text-lg font-semibold mb-4 text-theme-dark">
              Add Prompt
            </h3>
            {currentUserClass < 9 && (
              <p className="text-sm text-theme-mid mb-3">Admin can only add store-specific prompts; you must bind to a chain.</p>
            )}
            <div className="space-y-3 text-sm">
              <div>
                <label className="block font-medium text-theme-dark mb-1">Library Key</label>
                <input
                  type="text"
                  value={addKey}
                  onChange={(e) => setAddKey(e.target.value)}
                  placeholder="e.g. costco_second_round"
                  className="w-full border border-theme-light-gray rounded-lg px-2 py-1.5 text-theme-dark"
                />
              </div>
              <div>
                <label className="block font-medium text-theme-dark mb-1">Category</label>
                <select
                  value={addCategory}
                  onChange={(e) => setAddCategory(e.target.value)}
                  className="w-full border border-theme-light-gray rounded-lg px-2 py-1.5 text-theme-dark"
                >
                  <option value="receipt">receipt</option>
                  <option value="classification">classification</option>
                  <option value="system">system</option>
                  <option value="analysis">analysis</option>
                </select>
              </div>
              <div>
                <label className="block font-medium text-theme-dark mb-1">Content Role</label>
                <select
                  value={addContentRole}
                  onChange={(e) => setAddContentRole(e.target.value)}
                  className="w-full border border-theme-light-gray rounded-lg px-2 py-1.5 text-theme-dark"
                >
                  <option value="system">system</option>
                  <option value="user_template">user_template</option>
                  <option value="schema">schema</option>
                </select>
              </div>
              <div>
                <label className="block font-medium text-theme-dark mb-1">Content</label>
                <textarea
                  value={addContent}
                  onChange={(e) => setAddContent(e.target.value)}
                  className="w-full border border-theme-light-gray rounded-lg px-2 py-1.5 min-h-[120px] font-mono text-theme-dark"
                  placeholder="Prompt text…"
                />
              </div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={addIsActive}
                  onChange={(e) => setAddIsActive(e.target.checked)}
                />
                <span className="text-theme-dark">Is Active</span>
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={addBindToChain}
                  onChange={(e) => setAddBindToChain(e.target.checked)}
                />
                <span className="text-theme-dark">Immediately bind to a chain</span>
              </label>
              {addBindToChain && (
                <div className="flex flex-wrap gap-3 pl-6">
                  <div>
                    <label className="block font-medium text-theme-dark mb-1">Chain</label>
                    <select
                      value={addChainId}
                      onChange={(e) => setAddChainId(e.target.value)}
                      className="border border-theme-light-gray rounded-lg px-2 py-1.5 text-theme-dark"
                    >
                      <option value="">Select chain…</option>
                      {chains.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block font-medium text-theme-dark mb-1">Priority</label>
                    <input
                      type="number"
                      value={addBindPriority}
                      onChange={(e) => setAddBindPriority(Number(e.target.value) || 50)}
                      className="border border-theme-light-gray rounded-lg px-2 py-1.5 w-24 text-theme-dark"
                    />
                  </div>
                </div>
              )}
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => !addSubmitting && setAddModalOpen(false)}
                disabled={addSubmitting}
                className="px-3 py-1.5 rounded border border-theme-light-gray text-theme-dark hover:bg-theme-cream/60 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreatePrompt}
                disabled={
                  addSubmitting ||
                  !addKey.trim() ||
                  (currentUserClass < 9 && (!addBindToChain || !addChainId))
                }
                className="px-3 py-1.5 rounded border border-theme-orange bg-theme-orange/20 text-theme-dark hover:bg-theme-orange/30 disabled:opacity-50"
              >
                {addSubmitting ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
