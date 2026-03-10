'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'

type PeriodType = '' | 'month' | 'quarter' | 'year'

/** Inline SVG circles for Top 3 rank — same look on all platforms (no emoji) */
function RankCircle({ rank }: { rank: 0 | 1 | 2 }) {
  const colors = ['#FFD700', '#9CA3AF', '#B87333'] as const // gold (emoji-style), silver, bronze
  const fill = colors[rank]
  const size = 18
  return (
    <span className="inline-flex shrink-0 items-center justify-center" aria-hidden style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 18 18" fill="none" xmlns="http://www.w3.org/2000/svg" className="block">
        <circle cx="9" cy="9" r="8" fill={fill} stroke="#fff" strokeWidth="1.5" />
      </svg>
    </span>
  )
}

function buildMonthOptions(): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = []
  const now = new Date()
  for (let i = 0; i < 24; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const y = d.getFullYear()
    const m = d.getMonth() + 1
    const value = `${y}-${String(m).padStart(2, '0')}`
    const label = d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
    out.push({ value, label })
  }
  return out
}

function buildQuarterOptions(): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = []
  const now = new Date()
  const currentQ = Math.floor(now.getMonth() / 3) + 1
  for (let i = 0; i < 8; i++) {
    const q = currentQ - i
    let y = now.getFullYear()
    let qq = q
    if (qq < 1) { qq += 4; y -= 1 }
    out.push({ value: `${y}-Q${qq}`, label: `${y} Q${qq}` })
  }
  return out
}

function buildYearOptions(): { value: string; label: string }[] {
  const y = new Date().getFullYear()
  return Array.from({ length: 5 }, (_, i) => ({ value: String(y - i), label: String(y - i) }))
}

type UserCategoryNode = {
  user_category_id: string
  name: string
  path: string
  parent_id: string | null
  level: number
  is_locked: boolean
  amount_cents: number
}

type Summary = {
  total_receipts: number
  total_amount_cents: number
  by_store: Array<{ name: string; amount_cents: number; count: number }>
  by_payment: Array<{ name: string; amount_cents: number; count: number }>
  by_category_l1: Array<{ name: string; amount_cents: number }>
  by_category_l2: Array<{ name: string; amount_cents: number }>
  by_category_l3: Array<{ name: string; amount_cents: number }>
  by_user_category?: Array<UserCategoryNode>
  unclassified_count?: number
  unclassified_amount_cents?: number
}

function formatDollars(cents: number): string {
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const TABLE_DEFAULT_MOBILE = 5
const TABLE_DEFAULT_DESKTOP = 10

/** Returns 0.5 on narrow viewport (e.g. mobile) for half indentation, 1 otherwise. */
function useIndentScale(): number {
  const [scale, setScale] = useState(1)
  useEffect(() => {
    const m = window.matchMedia('(max-width: 640px)')
    const update = () => setScale(m.matches ? 0.5 : 1)
    update()
    m.addEventListener('change', update)
    return () => m.removeEventListener('change', update)
  }, [])
  return scale
}

function TableWithPct({
  title,
  rows,
  totalCents,
  showCount = false,
  showAllDesktop,
}: {
  title: string
  rows: Array<{ name: string; amount_cents: number; count?: number }>
  totalCents: number
  showCount?: boolean
  showAllDesktop: boolean
}) {
  const [showAllMobile, setShowAllMobile] = useState(false)

  if (rows.length === 0) return null
  const total = totalCents || 1
  const mobileHiddenCount = Math.max(0, rows.length - TABLE_DEFAULT_MOBILE)
  return (
    <div className="bg-white rounded-xl shadow p-3 sm:p-4 mb-4 overflow-hidden w-full min-w-0">
      <h3 className="text-sm font-semibold text-theme-dark/90 mb-3">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-theme-light-gray text-left text-theme-mid">
              <th className="py-2 pr-4">Name</th>
              {showCount && <th className="py-2 pr-4 text-right">Count</th>}
              <th className="py-2 pr-4 text-right">Amount</th>
              <th className="py-2 text-right">%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const mobileVisible = showAllMobile || i < TABLE_DEFAULT_MOBILE
              const desktopVisible = showAllDesktop || i < TABLE_DEFAULT_DESKTOP
              let rowClass = ''
              if (!mobileVisible && !desktopVisible) rowClass = 'hidden'
              else if (!mobileVisible && desktopVisible) rowClass = 'hidden sm:table-row'
              else if (mobileVisible && !desktopVisible) rowClass = 'sm:hidden'
              return (
                <tr key={i} className={`border-b border-theme-light-gray/50 hover:bg-theme-cream/50 transition-colors duration-150 ${rowClass}`}>
                  <td className="py-2 pr-4 font-medium text-theme-dark">{r.name}</td>
                  {showCount && (
                    <td className="py-2 pr-4 text-right tabular-nums text-theme-dark/90">
                      {(r as { count?: number }).count ?? '—'}
                    </td>
                  )}
                  <td className="py-2 pr-4 text-right tabular-nums">{formatDollars(r.amount_cents)}</td>
                  <td className="py-2 text-right tabular-nums text-theme-dark/90">
                    {((r.amount_cents / total) * 100).toFixed(1)}%
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {/* Mobile: per-card Show more/less, only if > 5 rows */}
      {mobileHiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAllMobile((v) => !v)}
          className="sm:hidden mt-2 text-sm text-theme-orange hover:underline px-1 py-1"
        >
          {showAllMobile ? 'Show less' : `Show ${mobileHiddenCount} more`}
        </button>
      )}
    </div>
  )
}


type PeriodOption = { value: string; label: string }

export default function DataAnalysisSection({ token }: { token: string | null }) {
  const apiBaseUrl = useApiUrl()
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [periodType, setPeriodType] = useState<PeriodType>('')
  const [periodValue, setPeriodValue] = useState<string>('')
  const [monthOptions, setMonthOptions] = useState<PeriodOption[]>([])
  const [quarterOptions, setQuarterOptions] = useState<PeriodOption[]>([])
  const [yearOptions, setYearOptions] = useState<PeriodOption[]>([])

  // Session-level dismiss for the unclassified banner (reappears on page refresh)
  const [unclassifiedBannerDismissed, setUnclassifiedBannerDismissed] = useState(false)

  // Shared show-all for By store + By payment card (same toggle keeps them aligned)
  const [showAllStores, setShowAllStores] = useState(false)

  useEffect(() => {
    setMonthOptions(buildMonthOptions())
    setQuarterOptions(buildQuarterOptions())
    setYearOptions(buildYearOptions())
  }, [])


  useEffect(() => {
    if (!token) { setLoading(false); return }
    fetch(`${apiBaseUrl}/api/me/idk-now-classified`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then(() => {})
      .catch(() => {})
  }, [token, apiBaseUrl])

  useEffect(() => {
    if (!token) { setLoading(false); return }
    let cancelled = false
    setLoading(true)
    setError(null)
    const params = new URLSearchParams()
    if (periodType && periodValue) {
      params.set('period', periodType)
      params.set('value', periodValue)
    }
    const url = `${apiBaseUrl}/api/analytics/summary` + (params.toString() ? `?${params}` : '')
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText)
        return res.json()
      })
      .then((data) => { if (!cancelled) setSummary(data) })
      .catch((e) => { if (!cancelled) setError(e.message || 'Failed to load') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [token, periodType, periodValue, apiBaseUrl])

  const periodOptions: { value: PeriodType; label: string }[] = [
    { value: '', label: 'All time' },
    { value: 'month', label: 'By month' },
    { value: 'quarter', label: 'By quarter' },
    { value: 'year', label: 'By year' },
  ]
  const valueOptions =
    periodType === 'month' ? monthOptions
    : periodType === 'quarter' ? quarterOptions
    : periodType === 'year' ? yearOptions
    : []

  return (
    <div className="mb-6 sm:mb-8 w-full max-w-full">
      <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-4 w-full">
        <h2 className="font-heading text-xl font-semibold mb-4 text-theme-dark">Spending Analysis</h2>
        <p className="text-sm text-theme-dark/90 mb-4">
          Spending data summary from your receipts by store, payment type, and category.
        </p>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <label className="flex items-center gap-2 text-sm text-theme-dark/90">
            <span>Filter:</span>
            <select
              className="border border-theme-mid rounded px-2 py-1.5 text-sm bg-white"
              value={periodType}
              onChange={(e) => {
                const v = e.target.value as PeriodType
                setPeriodType(v)
                if (v === 'month') setPeriodValue(monthOptions[0]?.value ?? '')
                else if (v === 'quarter') setPeriodValue(quarterOptions[0]?.value ?? '')
                else if (v === 'year') setPeriodValue(yearOptions[0]?.value ?? '')
                else setPeriodValue('')
              }}
            >
              {periodOptions.map((o) => (
                <option key={o.value || 'all'} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          {periodType && valueOptions.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-theme-dark/90">
              <span>Period:</span>
              <select
                className="border border-theme-mid rounded px-2 py-1.5 text-sm bg-white"
                value={periodValue}
                onChange={(e) => setPeriodValue(e.target.value)}
              >
                {valueOptions.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </label>
          )}
        </div>
        {loading && (
          <div className="py-8 text-center text-theme-mid">
            <span className="inline-block animate-spin text-2xl mr-2">⏳</span>
            Loading…
          </div>
        )}
        {error && !loading && <p className="text-theme-red text-sm">{error}</p>}
        {!loading && !error && (!summary || (summary.total_receipts === 0 && summary.by_store.length === 0)) && (
          <p className="text-theme-mid text-sm">No receipt data for this period. Upload receipts or choose another period.</p>
        )}
        {!loading && !error && summary && (summary.total_receipts > 0 || summary.by_store.length > 0) && (
          <>
            {/* Mobile: 2 cols, Top 3 full width below */}
            <div className="grid grid-cols-2 sm:hidden gap-x-6 gap-y-2 text-sm items-end">
              <div>
                <span className="text-theme-mid block">Total Receipts</span>
                <p className="font-semibold text-theme-dark">{summary.total_receipts}</p>
              </div>
              <div>
                <span className="text-theme-mid block">Total Amount</span>
                <p className="font-semibold text-theme-dark">{formatDollars(summary.total_amount_cents)}</p>
              </div>
              <div className="col-span-2">
                <span className="text-theme-mid block">Top 3 Spending</span>
                {summary.by_category_l1.length > 0 ? (
                  <div className="grid grid-cols-[auto_1fr_5.5rem_2.5rem] gap-x-2 items-center font-medium text-theme-dark tabular-nums">
                    {[...summary.by_category_l1]
                      .sort((a, b) => b.amount_cents - a.amount_cents)
                      .slice(0, 3)
                      .map((r, i) => {
                        const total = summary.by_category_l1.reduce((s, x) => s + x.amount_cents, 0) || summary.total_amount_cents || 1
                        const pct = ((r.amount_cents / total) * 100).toFixed(1)
                        return (
                          <span key={i} className="contents">
                            <RankCircle rank={i as 0 | 1 | 2} />
                            <span className="truncate min-w-0" title={r.name}>{r.name}</span>
                            <span className="text-right">{formatDollars(r.amount_cents)}</span>
                            <span className="text-right text-theme-dark/90">{pct}%</span>
                          </span>
                        )
                      })}
                  </div>
                ) : (
                  <p className="font-semibold text-theme-dark">—</p>
                )}
              </div>
            </div>
            {/* Desktop: left = Total Receipts + Total Amount stacked; right = Top 3 Spending */}
            <div className="hidden sm:grid sm:grid-cols-2 gap-6 text-sm items-start">
              <div className="space-y-3">
                <div>
                  <span className="text-theme-mid block">Total Receipts</span>
                  <p className="font-semibold text-theme-dark">{summary.total_receipts}</p>
                </div>
                <div>
                  <span className="text-theme-mid block">Total Amount</span>
                  <p className="font-semibold text-theme-dark tabular-nums">{formatDollars(summary.total_amount_cents)}</p>
                </div>
              </div>
              <div>
                <span className="text-theme-mid block mb-1">Top 3 Spending</span>
                {summary.by_category_l1.length > 0 ? (
                  <div className="grid grid-cols-[auto_1fr_auto_auto] gap-x-2 items-center font-medium text-theme-dark tabular-nums">
                    {[...summary.by_category_l1]
                      .sort((a, b) => b.amount_cents - a.amount_cents)
                      .slice(0, 3)
                      .map((r, i) => {
                        const total = summary.by_category_l1.reduce((s, x) => s + x.amount_cents, 0) || summary.total_amount_cents || 1
                        const pct = ((r.amount_cents / total) * 100).toFixed(1)
                        return (
                          <span key={i} className="contents">
                            <RankCircle rank={i as 0 | 1 | 2} />
                            <span className="truncate min-w-0" title={r.name}>{r.name}</span>
                            <span className="text-right shrink-0">{formatDollars(r.amount_cents)}</span>
                            <span className="text-right shrink-0 text-theme-dark/90">{pct}%</span>
                          </span>
                        )
                      })}
                  </div>
                ) : (
                  <p className="font-semibold text-theme-dark">—</p>
                )}
              </div>
            </div>
          </>
        )}
      </div>

      {!loading && !error && summary && (summary.total_receipts > 0 || summary.by_store.length > 0) && (
        <>
          {/* Top 3 columns: By Store | By Payment Type | By System Category */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full max-w-full">
            <div className="w-full min-w-0">
              <TableWithPct title="By store" rows={summary.by_store} totalCents={summary.total_amount_cents} showCount showAllDesktop={showAllStores} />
            </div>
            <div className="w-full min-w-0">
              <TableWithPct title="By payment type" rows={summary.by_payment} totalCents={summary.total_amount_cents} showCount showAllDesktop={showAllStores} />
            </div>
            <div className="w-full min-w-0">
              <SystemCategoryCard rows={summary.by_category_l1} totalCents={summary.total_amount_cents} />
            </div>
          </div>
          {/* Desktop: shared Show more/less for store + payment only */}
          {(summary.by_store.length > TABLE_DEFAULT_DESKTOP || summary.by_payment.length > TABLE_DEFAULT_DESKTOP) && (
            <div className="hidden sm:flex justify-center -mt-2 mb-2">
              <button
                type="button"
                onClick={() => setShowAllStores((v) => !v)}
                className="text-sm text-theme-orange hover:underline px-3 py-1"
              >
                {showAllStores
                  ? 'Show less'
                  : `Show ${Math.max(
                      Math.max(0, summary.by_store.length - TABLE_DEFAULT_DESKTOP),
                      Math.max(0, summary.by_payment.length - TABLE_DEFAULT_DESKTOP)
                    )} more`}
              </button>
            </div>
          )}

          {/* Unclassified banner */}
          {(summary.unclassified_count ?? 0) > 0 && !unclassifiedBannerDismissed && (
            <div className="mt-4 flex items-stretch gap-0">
              <Link
                href="/dashboard/unclassified"
                className="flex-1 flex items-center justify-between px-4 py-3 rounded-l-lg border border-r-0 border-amber-300 bg-amber-50 hover:bg-amber-100 transition-colors duration-150"
              >
                <span className="text-sm font-medium text-amber-900">
                  ⚠️ {summary.unclassified_count} unclassified item(s) — {formatDollars(summary.unclassified_amount_cents ?? 0)}
                </span>
                <span className="text-xs text-amber-600 shrink-0 ml-3">Review →</span>
              </Link>
              <button
                type="button"
                onClick={() => setUnclassifiedBannerDismissed(true)}
                title="Dismiss"
                className="px-3 rounded-r-lg border border-amber-300 bg-amber-50 hover:bg-amber-100 text-amber-500 hover:text-amber-700 transition-colors duration-150 text-base leading-none"
              >
                ×
              </button>
            </div>
          )}

          {/* By Sub-Category section (user-defined custom categories) */}
          {(summary.by_user_category ?? []).length > 0 && (
            <SubCategorySection
              rows={summary.by_user_category!}
              totalCents={summary.total_amount_cents}
            />
          )}
        </>
      )}
    </div>
  )
}

/** By System Category card — top 10 default, scroll for rest */
function SystemCategoryCard({
  rows,
  totalCents,
}: {
  rows: Array<{ name: string; amount_cents: number }>
  totalCents: number
}) {
  const TOP_N = 10
  const [showAll, setShowAll] = useState(false)
  const total = totalCents || 1
  const displayRows = showAll ? rows : rows.slice(0, TOP_N)
  const hiddenCount = Math.max(0, rows.length - TOP_N)

  if (rows.length === 0) return null

  return (
    <div className="bg-white rounded-xl shadow p-3 sm:p-4 mb-4 overflow-hidden w-full min-w-0">
      <h3 className="text-sm font-semibold text-theme-dark/90 mb-3">By system category</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-theme-light-gray text-left text-theme-mid">
              <th className="py-2 pr-4">Name</th>
              <th className="py-2 pr-4 text-right">Amount</th>
              <th className="py-2 text-right">%</th>
            </tr>
          </thead>
          <tbody>
            {displayRows.map((r, i) => (
              <tr key={i} className="border-b border-theme-light-gray/50 hover:bg-theme-cream/50 transition-colors duration-150">
                <td className="py-2 pr-4 font-medium text-theme-dark capitalize">{r.name}</td>
                <td className="py-2 pr-4 text-right tabular-nums">{formatDollars(r.amount_cents)}</td>
                <td className="py-2 text-right tabular-nums text-theme-dark/90">
                  {((r.amount_cents / total) * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-xs text-theme-orange hover:underline"
        >
          {showAll ? 'Show less' : `Show ${hiddenCount} more…`}
        </button>
      )}
    </div>
  )
}

/** Builds tree from flat rows, then computes subtree totals bottom-up (pivot-table style) */
type UCTreeNode = UserCategoryNode & { children: UCTreeNode[] }

function sumSubtree(node: UCTreeNode): number {
  const childSum = node.children.reduce((s, c) => s + sumSubtree(c), 0)
  node.amount_cents = node.amount_cents + childSum
  return node.amount_cents
}

function buildUCTree(rows: UserCategoryNode[]): UCTreeNode[] {
  const byId = new Map<string, UCTreeNode>()
  for (const r of rows) byId.set(r.user_category_id, { ...r, children: [] })
  const roots: UCTreeNode[] = []
  for (const node of byId.values()) {
    if (!node.parent_id || !byId.has(node.parent_id)) roots.push(node)
    else byId.get(node.parent_id)!.children.push(node)
  }
  // Compute subtree totals so each parent shows the sum of its entire subtree
  for (const root of roots) sumSubtree(root)
  return roots
}

/** Collect node ids by depth (0 = roots) and max depth for level expand/collapse bubbles */
function getIdsByDepth(roots: UCTreeNode[]): { byDepth: Map<number, string[]>; maxDepth: number } {
  const byDepth = new Map<number, string[]>()
  let maxDepth = -1
  function walk(nodes: UCTreeNode[], depth: number) {
    if (depth > maxDepth) maxDepth = depth
    for (const n of nodes) {
      if (!byDepth.has(depth)) byDepth.set(depth, [])
      byDepth.get(depth)!.push(n.user_category_id)
      if (n.children.length) walk(n.children, depth + 1)
    }
  }
  walk(roots, 0)
  return { byDepth, maxDepth }
}

const LEVEL_LABELS = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']

/** Value column mode: amount, or % of total, or % of parent */
type SubCatValueCol = 'amount' | 'pct_total' | 'pct_parent'
type SubCatSortCol = 'name' | 'value'

function toTitleCaseUC(s: string) {
  if (!s) return s
  return s.replace(/\b\w/g, (c) => c.toUpperCase())
}

function SubCatRow({
  node,
  depth,
  maxDepth,
  grandTotal,
  parentTotal,
  valueCol,
  indentScale,
  createSortFn,
  collapsed,
  onToggle,
}: {
  node: UCTreeNode
  depth: number
  maxDepth: number
  grandTotal: number
  parentTotal: number
  valueCol: SubCatValueCol
  indentScale: number
  createSortFn: (grandTotal: number, parentTotal: number) => (a: UCTreeNode, b: UCTreeNode) => number
  collapsed: Set<string>
  onToggle: (id: string) => void
}) {
  const denom = valueCol === 'pct_total' ? (grandTotal || 1) : (parentTotal || 1)
  const pct = ((node.amount_cents / denom) * 100).toFixed(1)
  const hasChildren = node.children.length > 0
  const isCollapsed = collapsed.has(node.user_category_id)
  const rowSort = createSortFn(grandTotal, parentTotal)
  const sortedChildren = hasChildren ? [...node.children].sort(rowSort) : []

  // Indent: base 8px + 20px per depth level; right padding for alignment. On mobile (indentScale=0.5) halved.
  const baseLeft = 8 + depth * 20
  const basePrPx = 12
  const numPrPx = basePrPx + (maxDepth - depth) * 20
  const depthWeight = depth === 0 ? 'font-semibold' : 'font-normal'
  const depthOpacity = depth <= 2 ? 'text-theme-dark' : depth === 3 ? 'text-theme-dark/90' : 'text-theme-dark/80'

  const displayValue = valueCol === 'amount' ? formatDollars(node.amount_cents) : `${pct}%`

  return (
    <>
      <tr className="border-b border-theme-light-gray/40 hover:bg-theme-cream/50 transition-colors duration-150">
        <td className="py-1.5 pr-1 overflow-hidden" style={{ paddingLeft: `${baseLeft * indentScale}px` }}>
          <div className="flex items-center gap-0.5 min-w-0">
            {hasChildren ? (
              <button
                type="button"
                className="text-theme-mid w-4 text-xs shrink-0 text-left leading-none"
                onClick={() => onToggle(node.user_category_id)}
                title={isCollapsed ? 'Expand' : 'Collapse'}
              >
                {isCollapsed ? '▸' : '▾'}
              </button>
            ) : (
              <span className="w-4 shrink-0" />
            )}
            <span className={`text-sm truncate ${depth === 0 ? 'font-semibold text-theme-dark' : 'font-medium text-theme-dark/90'}`} title={node.name}>
              {toTitleCaseUC(node.name)}
              {node.is_locked && (
                <span className="ml-1.5 text-[9px] text-theme-mid/60 font-normal bg-theme-light-gray/60 px-1 py-0.5 rounded align-middle">
                  system
                </span>
              )}
            </span>
          </div>
        </td>
        <td className={`py-1.5 text-right tabular-nums text-sm whitespace-nowrap ${depthOpacity} ${depthWeight}`} style={{ paddingRight: `${numPrPx * indentScale}px` }}>
          {displayValue}
        </td>
      </tr>
      {!isCollapsed && sortedChildren.map((child) => (
        <SubCatRow
          key={child.user_category_id}
          node={child}
          depth={depth + 1}
          maxDepth={maxDepth}
          grandTotal={grandTotal}
          parentTotal={node.amount_cents}
          valueCol={valueCol}
          indentScale={indentScale}
          createSortFn={createSortFn}
          collapsed={collapsed}
          onToggle={onToggle}
        />
      ))}
    </>
  )
}

const VALUE_COL_LABELS: Record<SubCatValueCol, string> = {
  amount: 'Amount',
  pct_total: '% of total',
  pct_parent: '% of parent',
}

function SubCategorySection({
  rows,
  totalCents,
}: {
  rows: UserCategoryNode[]
  totalCents: number
}) {
  const [valueCol, setValueCol] = useState<SubCatValueCol>('amount')
  const [valueDropdownOpen, setValueDropdownOpen] = useState(false)
  const [sortCol, setSortCol] = useState<SubCatSortCol>('value')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const indentScale = useIndentScale()

  const roots = useMemo(() => buildUCTree(rows), [rows])
  const { byDepth, maxDepth } = useMemo(() => getIdsByDepth(roots), [roots])

  const hasCustom = rows.some((r) => !r.is_locked)
  if (!hasCustom) return null

  /** Open Level d: expand only parents (depth 0..d-1) so level d rows are visible but level d nodes stay collapsed (no d+1). */
  const expandLevel = (depth: number) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      for (let d = 0; d < depth; d++) (byDepth.get(d) ?? []).forEach((id) => next.delete(id))
      return next
    })
  }
  /** Close Level d: collapse parent level (depth d-1) so level-d rows are hidden. */
  const collapseLevel = (depth: number) => {
    const parentDepth = depth - 1
    if (parentDepth < 0) return
    const ids = byDepth.get(parentDepth) ?? []
    setCollapsed((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.add(id))
      return next
    })
  }
  /** Level d is "open" when parent level (depth d-1) is expanded so level-d rows are visible. */
  const isLevelExpanded = (depth: number) => {
    if (depth <= 0) return true
    const parentIds = byDepth.get(depth - 1) ?? []
    return parentIds.length > 0 && parentIds.every((id) => !collapsed.has(id))
  }

  const handleSortClick = (col: SubCatSortCol) => {
    if (sortCol === col) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortCol(col); setSortDir('desc') }
  }

  const handleToggle = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const createSortFn = useCallback(
    (grandTotal: number, parentTotal: number) => {
      return (a: UCTreeNode, b: UCTreeNode): number => {
        let cmp = 0
        if (sortCol === 'name') {
          cmp = a.name.localeCompare(b.name)
        } else {
          if (valueCol === 'amount') {
            cmp = a.amount_cents - b.amount_cents
          } else {
            const denom = valueCol === 'pct_total' ? (grandTotal || 1) : (parentTotal || 1)
            cmp = a.amount_cents / denom - b.amount_cents / denom
          }
        }
        return sortDir === 'asc' ? cmp : -cmp
      }
    },
    [sortCol, sortDir, valueCol]
  )

  const sortFnRoot = useMemo(() => createSortFn(totalCents, totalCents), [createSortFn, totalCents])
  const sortedRoots = [...roots].sort(sortFnRoot)

  const thBase = 'py-2 text-sm font-bold text-black cursor-pointer select-none transition-colors duration-100 whitespace-nowrap'
  const thActive = 'text-black'
  const thInactive = 'text-black/80 hover:text-black'

  return (
    <div className="mt-6">
      <div className="flex items-center justify-between mb-3 px-1">
        <h3 className="text-sm font-semibold text-theme-dark/90">By sub-category</h3>
      </div>

      {/* One button per level: "Level II", "Level III", …; pressed = open, raised = closed. */}
      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        {maxDepth >= 1 &&
          Array.from({ length: maxDepth }, (_, i) => i + 1).map((d) => {
            const levelName = `Level ${LEVEL_LABELS[d] ?? String(d + 1)}`
            const expanded = isLevelExpanded(d)
            return (
              <button
                key={d}
                type="button"
                onClick={() => (expanded ? collapseLevel(d) : expandLevel(d))}
                title={expanded ? `Close ${levelName}` : `Open ${levelName}`}
                className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors duration-150 ${
                  expanded
                    ? 'bg-theme-orange text-white border-theme-orange shadow-inner'
                    : 'bg-white text-theme-dark border-theme-mid/50 hover:border-theme-orange hover:bg-theme-cream'
                }`}
              >
                {levelName}
              </button>
            )
          })}
      </div>

      <div className="bg-white rounded-xl shadow overflow-hidden w-full p-3 sm:p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-theme-light-gray text-left">
              <th className={`${thBase} ${sortCol === 'name' ? thActive : thInactive} pl-0 pr-4 text-left`} onClick={() => handleSortClick('name')}>
                Category
              </th>
              <th
                className={`${thBase} ${sortCol === 'value' ? thActive : thInactive} pr-0 text-right`}
                onClick={(e) => { if (!(e.target as HTMLElement).closest('button')) handleSortClick('value') }}
              >
                <div className="relative inline-block text-right">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setValueDropdownOpen((o) => !o) }}
                    className="inline-flex items-center gap-1 rounded border border-theme-mid/50 bg-white px-1.5 py-0.5 text-xs font-medium text-theme-dark hover:bg-theme-cream focus:outline-none focus:ring-1 focus:ring-theme-orange"
                    aria-haspopup="listbox"
                    aria-expanded={valueDropdownOpen}
                  >
                    {VALUE_COL_LABELS[valueCol]}
                    <span className="text-theme-mid" aria-hidden>▾</span>
                  </button>
                  {valueDropdownOpen && (
                    <>
                      <div className="fixed inset-0 z-10" aria-hidden onClick={() => setValueDropdownOpen(false)} />
                      <ul
                        className="absolute right-0 top-full z-20 mt-0.5 min-w-40 rounded border border-theme-light-gray bg-white py-1 shadow-lg"
                        role="listbox"
                      >
                        {(['amount', 'pct_total', 'pct_parent'] as const).map((opt) => (
                          <li key={opt} role="option" aria-selected={valueCol === opt}>
                            <button
                              type="button"
                              className={`w-full px-2.5 py-1.5 text-left text-xs hover:bg-theme-cream ${
                                valueCol === opt ? 'bg-theme-cream font-medium text-theme-orange' : 'text-theme-dark'
                              }`}
                              onClick={() => {
                                setValueCol(opt)
                                setValueDropdownOpen(false)
                              }}
                            >
                              {VALUE_COL_LABELS[opt]}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedRoots.map((node) => (
              <SubCatRow
                key={node.user_category_id}
                node={node}
                depth={0}
                maxDepth={maxDepth}
                grandTotal={totalCents}
                parentTotal={totalCents}
                valueCol={valueCol}
                indentScale={indentScale}
                createSortFn={createSortFn}
                collapsed={collapsed}
                onToggle={handleToggle}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
