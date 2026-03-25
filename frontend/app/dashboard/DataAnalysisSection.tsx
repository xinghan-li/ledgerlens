'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'
import { useDashboardActions } from './dashboard-actions-context'

type PeriodType = '' | 'month' | 'quarter' | 'year'


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
  total_tax_cents?: number
  total_fees_cents?: number
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

// ===== Visualization: Color Palette =====

const CAT_PALETTE = [
  '#3B82F6', // blue
  '#F97316', // orange
  '#22C55E', // green
  '#EF4444', // red
  '#A855F7', // purple
  '#06B6D4', // cyan
  '#EAB308', // yellow
  '#EC4899', // pink
  '#14B8A6', // teal
  '#F59E0B', // amber
  '#6366F1', // indigo
  '#84CC16', // lime
]
const CAT_COLOR_OVERRIDES: Record<string, string> = {
  grocery: '#22C55E', groceries: '#22C55E',
  household: '#6366F1',
  health: '#F97316', healthcare: '#F97316',
  'personal care': '#EF4444', beauty: '#EF4444',
  tax: '#94A3B8', fees: '#94A3B8', 'tax & fees': '#94A3B8',
  restaurant: '#F43F5E', dining: '#F43F5E', 'food & dining': '#F43F5E',
  entertainment: '#A855F7',
  transport: '#3B82F6', transportation: '#3B82F6',
  clothing: '#EC4899', apparel: '#EC4899',
  electronics: '#06B6D4',
}

function getCatColor(name: string, idx: number): string {
  return CAT_COLOR_OVERRIDES[name.toLowerCase().trim()] ?? CAT_PALETTE[idx % CAT_PALETTE.length]
}


type SpendingSegment = { name: string; amount_cents: number; color: string; pct: number }

function buildSegments(
  cats: Array<{ name: string; amount_cents: number }>,
  totalCents: number,
  extras?: Array<{ name: string; amount_cents: number; color: string }>,
): SpendingSegment[] {
  const total = totalCents || 1
  const sorted = [...cats].sort((a, b) => b.amount_cents - a.amount_cents)
  const main: SpendingSegment[] = []
  let otherCents = 0
  sorted.forEach((cat, i) => {
    const pct = (cat.amount_cents / total) * 100
    if (pct < 2) { otherCents += cat.amount_cents; return }
    main.push({ name: cat.name, amount_cents: cat.amount_cents, color: getCatColor(cat.name, i), pct })
  })
  if (otherCents > 0)
    main.push({ name: 'Other', amount_cents: otherCents, color: '#9E9E9E', pct: (otherCents / total) * 100 })
  if (extras) {
    for (const ex of extras) {
      if (ex.amount_cents > 0)
        main.push({ name: ex.name, amount_cents: ex.amount_cents, color: ex.color, pct: (ex.amount_cents / total) * 100 })
    }
  }
  return main
}

// ===== Feature 1: Stacked Horizontal Progress Bar =====

function StackedProgressBar({ segments }: { segments: SpendingSegment[] }) {
  const [hovered, setHovered] = useState<number | null>(null)
  if (segments.length === 0) return null
  return (
    <div className="mt-5 pt-4 border-t border-theme-light-gray">
      <p className="text-xs font-medium text-theme-mid mb-2">Spending by category</p>
      <div
        className="relative w-full rounded-full overflow-hidden h-4 bg-theme-light-gray"
        role="img"
        aria-label="Spending category breakdown"
      >
        <div className="absolute inset-0 flex">
          {segments.map((seg, i) => (
            <div
              key={seg.name}
              style={{
                flex: `${seg.pct} 0 0`,
                backgroundColor: seg.color,
                opacity: hovered !== null && hovered !== i ? 0.45 : 1,
                transition: 'opacity 150ms ease-out',
                borderRight: i < segments.length - 1 ? '1.5px solid rgba(255,255,255,0.6)' : 'none',
              }}
              title={`${seg.name}: ${formatDollars(seg.amount_cents)} (${seg.pct.toFixed(1)}%)`}
              aria-label={`${seg.name}: ${formatDollars(seg.amount_cents)}, ${seg.pct.toFixed(1)}%`}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
              className="h-full cursor-pointer"
            />
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-2 mt-3">
        {segments.map((seg, i) => (
          <div
            key={seg.name}
            className="flex items-center gap-1.5 text-xs cursor-default"
            style={{ opacity: hovered !== null && hovered !== i ? 0.4 : 1, transition: 'opacity 150ms ease-out' }}
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: seg.color }} aria-hidden />
            <span className="text-theme-dark/80">{seg.name}</span>
            <span className="tabular-nums text-theme-mid">{formatDollars(seg.amount_cents)}</span>
            <span className="tabular-nums text-theme-mid/60">{seg.pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ===== Feature 3: Drillable Donut Chart =====

function polarToXY(cx: number, cy: number, r: number, deg: number) {
  const rad = ((deg - 90) * Math.PI) / 180
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) }
}

function donutArcPath(cx: number, cy: number, oR: number, iR: number, s: number, e: number): string {
  if (e - s >= 360) e = s + 359.9
  const large = e - s > 180 ? 1 : 0
  const o1 = polarToXY(cx, cy, oR, s)
  const o2 = polarToXY(cx, cy, oR, e)
  const i1 = polarToXY(cx, cy, iR, e)
  const i2 = polarToXY(cx, cy, iR, s)
  return `M${o1.x} ${o1.y}A${oR} ${oR} 0 ${large} 1 ${o2.x} ${o2.y}L${i1.x} ${i1.y}A${iR} ${iR} 0 ${large} 0 ${i2.x} ${i2.y}Z`
}

type DonutSeg = SpendingSegment & { id: string; hasChildren: boolean }
type ArcSeg = DonutSeg & { startDeg: number; endDeg: number; midDeg: number }
type DrillItem = { id: string; name: string; color: string }

function DonutChartCard({ summary }: { summary: Summary }) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)
  const [drillPath, setDrillPath] = useState<DrillItem[]>([])

  // Stat cards data
  const avgPerTrip = summary.total_receipts > 0 ? Math.round(summary.total_amount_cents / summary.total_receipts) : 0
  const topStore = [...(summary.by_store ?? [])].sort((a, b) => (b.count ?? 0) - (a.count ?? 0))[0] ?? null
  const topCat = [...(summary.by_category_l1 ?? [])].sort((a, b) => b.amount_cents - a.amount_cents)[0] ?? null

  const ucTree = useMemo(
    () => (summary.by_user_category && summary.by_user_category.length > 0 ? buildUCTree(summary.by_user_category) : []),
    [summary.by_user_category]
  )
  const hasUCTree = ucTree.length > 0

  const findById = useCallback((nodes: UCTreeNode[], id: string, depth = 0): UCTreeNode | null => {
    if (!nodes || depth > 50) return null
    for (const n of nodes) {
      if (n.user_category_id === id) return n
      const found = findById(n.children, id, depth + 1)
      if (found) return found
    }
    return null
  }, [])

  const { segs, levelTotal, canDrill } = useMemo((): { segs: DonutSeg[]; levelTotal: number; canDrill: boolean } => {
    if (hasUCTree) {
      let currentNodes: UCTreeNode[] = ucTree
      if (drillPath.length > 0) {
        const last = drillPath[drillPath.length - 1]
        const parentNode = findById(ucTree, last.id)
        currentNodes = parentNode ? parentNode.children : []
      }

      const sorted = [...currentNodes].sort((a, b) => b.amount_cents - a.amount_cents).filter(c => c.amount_cents > 0)
      // At root level, use total_amount_cents so percentages are relative to total spending
      const isRoot = drillPath.length === 0
      const levelTotal = isRoot
        ? (summary.total_amount_cents || 1)
        : (sorted.reduce((s, c) => s + c.amount_cents, 0) || 1)

      const segs: DonutSeg[] = sorted.map((node, i) => {
        let color: string
        color = getCatColor(node.name, i)
        return {
          id: node.user_category_id,
          name: node.name,
          amount_cents: node.amount_cents,
          color,
          pct: (node.amount_cents / levelTotal) * 100,
          hasChildren: node.children.filter(c => c.amount_cents > 0).length > 0,
        }
      })

      // At root level, add tax, fees, and uncategorized segments
      if (isRoot) {
        const extras: Array<{ id: string; name: string; amount_cents: number; color: string }> = [
          { id: '__tax__', name: 'Tax', amount_cents: summary.total_tax_cents ?? 0, color: '#B0BEC5' },
          { id: '__fees__', name: 'Fees', amount_cents: summary.total_fees_cents ?? 0, color: '#CFD8DC' },
          { id: '__uncategorized__', name: 'Uncategorized', amount_cents: summary.unclassified_amount_cents ?? 0, color: '#E0E0E0' },
        ]
        for (const ex of extras) {
          if (ex.amount_cents > 0) {
            segs.push({
              id: ex.id,
              name: ex.name,
              amount_cents: ex.amount_cents,
              color: ex.color,
              pct: (ex.amount_cents / levelTotal) * 100,
              hasChildren: false,
            })
          }
        }
      }

      return { segs, levelTotal, canDrill: true }
    }

    // Fallback: system L1 categories, non-drillable
    const total = summary.total_amount_cents || 1
    const segs: DonutSeg[] = buildSegments(summary.by_category_l1, total, [
      { name: 'Tax', amount_cents: summary.total_tax_cents ?? 0, color: '#B0BEC5' },
      { name: 'Fees', amount_cents: summary.total_fees_cents ?? 0, color: '#CFD8DC' },
      { name: 'Uncategorized', amount_cents: summary.unclassified_amount_cents ?? 0, color: '#E0E0E0' },
    ]).map(s => ({
      ...s,
      id: s.name,
      hasChildren: false,
    }))
    return { segs, levelTotal: total, canDrill: false }
  }, [hasUCTree, ucTree, drillPath, summary, findById])

  const SIZE = 260
  const CX = SIZE / 2
  const CY = SIZE / 2
  const OUTER_R = 108
  const INNER_R = 64
  const PULL = 8

  const arcSegs: ArcSeg[] = useMemo(() => {
    let cumDeg = 0
    return segs.map((seg) => {
      const spanDeg = (seg.amount_cents / levelTotal) * 360
      const start = cumDeg
      cumDeg += spanDeg
      return { ...seg, startDeg: start, endDeg: cumDeg, midDeg: start + spanDeg / 2 }
    })
  }, [segs, levelTotal])

  const handleSegClick = (seg: ArcSeg) => {
    if (!canDrill || !seg.hasChildren) return
    setDrillPath(prev => [...prev, { id: seg.id, name: seg.name, color: drillPath.length === 0 ? seg.color : drillPath[0].color }])
    setHoveredIdx(null)
  }

  const handleBreadcrumb = (idx: number) => {
    setDrillPath(prev => prev.slice(0, idx))
    setHoveredIdx(null)
  }

  const centerLabel = drillPath.length > 0 ? drillPath[drillPath.length - 1].name : 'Total'
  const centerValue = formatDollars(levelTotal)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6 lg:items-stretch">

      {/* Donut card — spans 2 of 3 cols on lg */}
      <div className="lg:col-span-2 bg-white rounded-xl shadow p-4 sm:p-6 flex flex-col">
          <h3 className="text-sm font-semibold text-theme-dark/90 mb-2 shrink-0">Spending Breakdown</h3>

          {/* Breadcrumb */}
          {drillPath.length > 0 && (
            <nav className="flex items-center gap-1 text-xs text-theme-mid mb-3 flex-wrap shrink-0" aria-label="Category navigation">
              <button type="button" className="hover:text-theme-orange transition-colors" onClick={() => handleBreadcrumb(0)}>
                All Categories
              </button>
              {drillPath.map((item, i) => (
                <span key={item.id} className="flex items-center gap-1">
                  <span className="text-theme-light-gray">›</span>
                  <button
                    type="button"
                    className={`hover:text-theme-orange transition-colors ${i === drillPath.length - 1 ? 'text-theme-dark font-medium' : ''}`}
                    onClick={() => handleBreadcrumb(i + 1)}
                  >
                    {item.name}
                  </button>
                </span>
              ))}
            </nav>
          )}

          {segs.length === 0 ? (
            <p className="text-sm text-theme-mid py-6 text-center">No spending data available.</p>
          ) : (
            <div className="flex-1 flex flex-col sm:flex-row items-center gap-4">
              {/* Donut SVG */}
              <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
                <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Spending breakdown donut chart">
                  {arcSegs.map((seg, i) => {
                    const isHovered = hoveredIdx === i
                    const mid = seg.midDeg
                    const rad = ((mid - 90) * Math.PI) / 180
                    const dx = isHovered ? Math.cos(rad) * PULL : 0
                    const dy = isHovered ? Math.sin(rad) * PULL : 0
                    const clickable = canDrill && seg.hasChildren
                    return (
                      <path
                        key={seg.name}
                        d={donutArcPath(CX, CY, OUTER_R, INNER_R, seg.startDeg, seg.endDeg)}
                        fill={seg.color}
                        transform={`translate(${dx},${dy})`}
                        style={{
                          transition: 'transform 200ms ease-out, opacity 150ms ease-out',
                          cursor: clickable ? 'pointer' : 'default',
                          opacity: hoveredIdx !== null && hoveredIdx !== i ? 0.72 : 1,
                        }}
                        onMouseEnter={() => setHoveredIdx(i)}
                        onMouseLeave={() => setHoveredIdx(null)}
                        onClick={() => handleSegClick(seg)}
                        aria-label={`${seg.name}: ${formatDollars(seg.amount_cents)}, ${seg.pct.toFixed(1)}%`}
                        role={clickable ? 'button' : undefined}
                        tabIndex={clickable ? 0 : undefined}
                        onKeyDown={clickable ? (e) => { if (e.key === 'Enter' || e.key === ' ') handleSegClick(seg) } : undefined}
                      />
                    )
                  })}
                  <text x={CX} y={CY - 10} textAnchor="middle" style={{ fontSize: 11, fill: '#b0aea5', fontFamily: 'inherit' }}>
                    {centerLabel}
                  </text>
                  <text x={CX} y={CY + 12} textAnchor="middle" style={{ fontSize: 16, fontWeight: 700, fill: '#141413', fontFamily: 'inherit' }}>
                    {centerValue}
                  </text>
                </svg>
                {hoveredIdx !== null && arcSegs[hoveredIdx] && (
                  <div
                    className="absolute left-1/2 bottom-0 -translate-x-1/2 translate-y-2 bg-theme-dark text-white text-xs rounded px-2.5 py-1.5 pointer-events-none whitespace-nowrap shadow-lg"
                    style={{ zIndex: 10 }}
                  >
                    <span className="font-medium">{arcSegs[hoveredIdx].name}</span>
                    {' · '}{formatDollars(arcSegs[hoveredIdx].amount_cents)}
                    {' · '}{arcSegs[hoveredIdx].pct.toFixed(1)}%
                    {canDrill && arcSegs[hoveredIdx].hasChildren && (
                      <span className="ml-1 opacity-60"> — click to expand</span>
                    )}
                  </div>
                )}
              </div>

              {/* Legend */}
              <div className="flex-1 min-w-0 w-full sm:pt-2">
                <div className="space-y-0.5">
                  {arcSegs.map((seg, i) => (
                    <div
                      key={seg.name}
                      className="flex items-center gap-2 text-sm rounded px-2 py-1.5 transition-colors duration-100"
                      style={{
                        backgroundColor: hoveredIdx === i ? '#faf9f5' : 'transparent',
                        cursor: canDrill && seg.hasChildren ? 'pointer' : 'default',
                      }}
                      onMouseEnter={() => setHoveredIdx(i)}
                      onMouseLeave={() => setHoveredIdx(null)}
                      onClick={() => handleSegClick(seg)}
                    >
                      <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: seg.color }} aria-hidden />
                      <span className="flex-1 truncate text-theme-dark/90 min-w-0">{seg.name}</span>
                      <span className="tabular-nums text-theme-dark font-medium shrink-0">{formatDollars(seg.amount_cents)}</span>
                      <span className="tabular-nums text-theme-mid shrink-0 w-12 text-right">{seg.pct.toFixed(1)}%</span>
                      {canDrill && seg.hasChildren && (
                        <span className="text-theme-mid/60 text-xs shrink-0">›</span>
                      )}
                    </div>
                  ))}
                </div>
                {drillPath.length > 0 && (
                  <button
                    type="button"
                    className="mt-3 text-xs text-theme-orange hover:underline px-2"
                    onClick={() => handleBreadcrumb(drillPath.length - 1)}
                  >
                    ← {drillPath.length > 1 ? `Back to ${drillPath[drillPath.length - 2].name}` : 'All Categories'}
                  </button>
                )}
              </div>
            </div>
          )}
        </div>

      {/* Stat cards — stacked in 1/3 column on lg */}
      <div className="flex flex-row lg:flex-col gap-6">
        <div className="flex-1 bg-white rounded-xl shadow p-4 sm:p-6">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-theme-mid mb-1">AVG PER TRIP</p>
          <p className="text-2xl font-bold text-theme-dark">{formatDollars(avgPerTrip)}</p>
          <p className="text-xs text-theme-mid/80 mt-0.5">{summary.total_receipts} receipt{summary.total_receipts !== 1 ? 's' : ''}</p>
        </div>
        {topStore && (
          <div className="flex-1 bg-white rounded-xl shadow p-4 sm:p-6">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-theme-mid mb-1">MOST VISITED</p>
            <p className="text-xl font-bold text-theme-dark truncate" title={topStore.name}>{topStore.name}</p>
            <p className="text-xs text-theme-mid/80 mt-0.5">{topStore.count ?? 0} visit{(topStore.count ?? 0) !== 1 ? 's' : ''} · {formatDollars(topStore.amount_cents)}</p>
          </div>
        )}
        {topCat && (
          <div className="flex-1 bg-white rounded-xl shadow p-4 sm:p-6">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-theme-mid mb-1">TOP CATEGORY</p>
            <p className="text-xl font-bold text-theme-dark truncate" title={topCat.name}>{topCat.name}</p>
            <p className="text-xs text-theme-mid/80 mt-0.5">{formatDollars(topCat.amount_cents)}</p>
          </div>
        )}
        {((summary.total_tax_cents ?? 0) + (summary.total_fees_cents ?? 0)) > 0 && (
          <div className="flex-1 bg-white rounded-xl shadow p-4 sm:p-6">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-theme-mid mb-1">TAX & FEES</p>
            <p className="text-2xl font-bold text-theme-dark">{formatDollars((summary.total_tax_cents ?? 0) + (summary.total_fees_cents ?? 0))}</p>
            <p className="text-xs text-theme-mid/80 mt-0.5">
              {(summary.total_tax_cents ?? 0) > 0 && `Tax ${formatDollars(summary.total_tax_cents ?? 0)}`}
              {(summary.total_tax_cents ?? 0) > 0 && (summary.total_fees_cents ?? 0) > 0 && ' · '}
              {(summary.total_fees_cents ?? 0) > 0 && `Fees ${formatDollars(summary.total_fees_cents ?? 0)}`}
            </p>
          </div>
        )}
      </div>

    </div>
  )
}

// ===== Feature 0: Monthly Spending Bar Chart =====

type MonthPoint = { month: string; label: string; total_cents: number; segments: SpendingSegment[] }
type ChartTooltip = { x: number; y: number; point: MonthPoint }

function niceChartMax(maxCents: number): { ceilCents: number; stepCents: number } {
  const d = maxCents / 100
  let step: number
  if (d <= 200) step = 50
  else if (d <= 500) step = 100
  else if (d <= 2000) step = 500
  else if (d <= 10000) step = 1000
  else if (d <= 20000) step = 2000
  else step = 5000
  const ceil = Math.ceil(Math.max(d, step) / step) * step
  return { ceilCents: ceil * 100, stepCents: step * 100 }
}

function fmtAxisLabel(cents: number): string {
  const d = cents / 100
  return '$' + Math.round(d).toLocaleString('en-US')
}

function MonthlySpendingChart({ token, apiBaseUrl }: { token: string | null; apiBaseUrl: string }) {
  const [data, setData] = useState<MonthPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)
  const [tooltip, setTooltip] = useState<ChartTooltip | null>(null)
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const m = window.matchMedia('(max-width: 639px)')
    const update = () => setIsMobile(m.matches)
    update()
    m.addEventListener('change', update)
    return () => m.removeEventListener('change', update)
  }, [])

  const allMonths = useMemo(() => {
    const result: string[] = []
    const now = new Date()
    for (let i = 11; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
      result.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
    }
    return result
  }, [])

  useEffect(() => {
    if (!token) { setLoading(false); return }
    let cancelled = false
    Promise.all(
      allMonths.map(m =>
        fetch(`${apiBaseUrl}/api/analytics/summary?period=month&value=${m}`, {
          headers: { Authorization: `Bearer ${token}` },
        }).then(r => r.ok ? r.json() : null).catch(() => null)
      )
    ).then(results => {
      if (cancelled) return
      setData(allMonths.map((m, i) => {
        const r = results[i]
        const [yr, mo] = m.split('-')
        const label = new Date(+yr, +mo - 1, 1).toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
        if (!r?.total_amount_cents) return { month: m, label, total_cents: 0, segments: [] }
        return { month: m, label, total_cents: r.total_amount_cents, segments: buildSegments(r.by_category_l1 ?? [], r.total_amount_cents) }
      }))
      setLoading(false)
    })
    return () => { cancelled = true }
  }, [token, apiBaseUrl, allMonths])

  const visibleData = isMobile ? data.slice(-6) : data
  const hasData = data.some(d => d.total_cents > 0)
  const selectedData = visibleData.find(d => d.month === selectedMonth)
  const maxCents = Math.max(...data.map(d => d.total_cents), 1)
  const { ceilCents, stepCents } = niceChartMax(maxCents)

  const CHART_H = 160
  const Y_AXIS_W = 58
  const BAR_GAP = 8
  const numTicks = Math.round(ceilCents / stepCents)
  const yTicks = Array.from({ length: numTicks }, (_, i) => {
    const v = stepCents * (i + 1)
    return { v, label: fmtAxisLabel(v), top: Math.round(CHART_H * (1 - v / ceilCents)) }
  })

  const legendItems = useMemo(() => {
    const seen = new Map<string, string>()
    data.forEach(p => p.segments.forEach(s => { if (!seen.has(s.name)) seen.set(s.name, s.color) }))
    return [...seen.entries()].map(([name, color]) => ({ name, color }))
  }, [data])

  if (loading) {
    return (
      <div className="h-36 flex items-center justify-center text-theme-mid text-sm gap-2">
        <span className="inline-block animate-spin">⏳</span> Loading…
      </div>
    )
  }
  if (!hasData) return <p className="text-sm text-theme-mid py-4 text-center">No spending history yet.</p>

  return (
    <div onMouseLeave={() => setTooltip(null)}>
      {/* Chart: Y-axis + bars area */}
      <div style={{ position: 'relative', paddingLeft: Y_AXIS_W }}>
        {/* Y-axis labels (absolutely on the left strip) */}
        <div style={{ position: 'absolute', left: 0, top: 0, width: Y_AXIS_W, height: CHART_H }}>
          {yTicks.map(t => (
            <div key={t.v} style={{ position: 'absolute', top: t.top - 8, right: 6, whiteSpace: 'nowrap' }}
              className="text-[10px] text-theme-mid">{t.label}</div>
          ))}
        </div>
        {/* Bars area fills remaining width */}
        <div style={{ position: 'relative', height: CHART_H }}>
          {/* Gridlines */}
          {yTicks.map(t => (
            <div key={t.v} style={{ position: 'absolute', top: t.top, left: 0, right: 0 }}
              className="border-t border-theme-light-gray/60 pointer-events-none" />
          ))}
          <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0 }}
            className="border-t border-theme-light-gray pointer-events-none" />
          {/* Bars — flex:1 fills full width */}
          <div className="absolute inset-0 flex items-end" style={{ gap: BAR_GAP, paddingLeft: '7%', paddingRight: '7%' }}>
            {visibleData.map(point => {
              const barH = (point.total_cents / ceilCents) * CHART_H
              const isSelected = selectedMonth === point.month
              return (
                <div key={point.month} style={{ flex: 0.9, height: '100%', minWidth: 20 }}
                  className="relative flex flex-col justify-end">
                  {point.total_cents > 0 ? (
                    <div
                      style={{ height: barH }}
                      className={`w-full flex flex-col-reverse overflow-hidden rounded-t cursor-pointer transition-all duration-150 ${isSelected ? 'shadow-[0_0_0_2px_#d97757,0_0_0_3px_white]' : 'hover:brightness-105'}`}
                      onClick={() => setSelectedMonth(prev => prev === point.month ? null : point.month)}
                      onMouseEnter={e => {
                        const rect = e.currentTarget.getBoundingClientRect()
                        setTooltip({ x: rect.left + rect.width / 2, y: rect.top, point })
                      }}
                      onMouseLeave={() => setTooltip(null)}
                    >
                      {point.segments.map(seg => (
                        <div
                          key={seg.name}
                          style={{
                            height: `${seg.pct}%`,
                            backgroundColor: seg.color,
                            flexShrink: 0,
                            transition: 'opacity 150ms',
                            opacity: tooltip && tooltip.point.month !== point.month ? 0.55 : 1,
                          }}
                        />
                      ))}
                    </div>
                  ) : (
                    <div style={{ height: 3, backgroundColor: '#e8e6dc', borderRadius: 2 }} className="w-full" />
                  )}
                </div>
              )
            })}
          </div>
        </div>
        {/* X-axis labels — flex:1 mirrors bars */}
        <div className="flex mt-1.5" style={{ gap: BAR_GAP, paddingLeft: '7%', paddingRight: '7%' }}>
          {visibleData.map(point => (
            <div
              key={point.month}
              style={{ flex: 0.9, minWidth: 20 }}
              className={`text-center text-[10px] cursor-pointer select-none ${selectedMonth === point.month ? 'text-theme-orange font-semibold' : 'text-theme-mid'}`}
              onClick={() => setSelectedMonth(prev => prev === point.month ? null : point.month)}
            >
              {point.label}
              {selectedMonth === point.month && <div className="w-1.5 h-1.5 rounded-full bg-theme-orange mx-auto mt-0.5" />}
            </div>
          ))}
        </div>
      </div>

      {/* Legend */}
      {legendItems.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3 pt-3 border-t border-theme-light-gray/60">
          {legendItems.map(item => (
            <div key={item.name} className="flex items-center gap-1.5 text-xs">
              <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: item.color }} aria-hidden />
              <span className="text-theme-dark/70">{item.name}</span>
            </div>
          ))}
        </div>
      )}

      {/* Selected month breakdown */}
      {selectedData && selectedData.total_cents > 0 && (
        <div className="mt-3 p-3 rounded-lg bg-theme-cream-alt">
          <p className="text-xs font-semibold text-theme-dark mb-2">{selectedData.label} — {formatDollars(selectedData.total_cents)}</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
            {selectedData.segments.map(seg => (
              <div key={seg.name} className="flex items-center gap-2 text-xs">
                <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: seg.color }} aria-hidden />
                <span className="flex-1 text-theme-dark/80 min-w-0 truncate">{seg.name}</span>
                <span className="tabular-nums text-theme-dark font-medium shrink-0">{formatDollars(seg.amount_cents)}</span>
                <span className="tabular-nums text-theme-mid/80 shrink-0 w-9 text-right">{seg.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Floating tooltip */}
      {tooltip && (
        <div
          style={{ position: 'fixed', left: tooltip.x, top: tooltip.y - 6, transform: 'translate(-50%, -100%)', zIndex: 1000, pointerEvents: 'none' }}
          className="bg-theme-dark text-white text-xs rounded px-3 py-2 shadow-xl whitespace-nowrap"
        >
          <p className="font-semibold mb-1.5 text-white/80">{tooltip.point.label}</p>
          {tooltip.point.segments.map(seg => (
            <div key={seg.name} className="flex items-center gap-2 py-0.5">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: seg.color }} />
              <span className="flex-1">{seg.name}</span>
              <span className="text-white/50 tabular-nums w-10 text-right">{seg.pct.toFixed(1)}%</span>
              <span className="tabular-nums text-right">{formatDollars(seg.amount_cents)}</span>
            </div>
          ))}
          <div className="mt-1.5 pt-1.5 border-t border-white/20 flex justify-between gap-4">
            <span className="text-white/60">Total</span>
            <span className="tabular-nums font-semibold">{formatDollars(tooltip.point.total_cents)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function TableWithPct({
  title,
  rows,
  totalCents,
  showCount = false,
}: {
  title: string
  rows: Array<{ name: string; amount_cents: number; count?: number }>
  totalCents: number
  showCount?: boolean
}) {
  const [showAll, setShowAll] = useState(false)

  if (rows.length === 0) return null
  const total = totalCents || 1
  const hiddenCount = Math.max(0, rows.length - TABLE_DEFAULT_DESKTOP)
  const displayRows = showAll ? rows : rows.slice(0, TABLE_DEFAULT_DESKTOP)
  return (
    <div className="bg-white rounded-xl shadow p-3 sm:p-4 overflow-hidden w-full min-w-0 h-full flex flex-col">
      <h3 className="text-sm font-semibold text-theme-dark/90 mb-3">{title}</h3>
      <div className="overflow-x-auto flex-1">
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
            {displayRows.map((r, i) => (
              <tr key={i} className="border-b border-theme-light-gray/50 hover:bg-theme-cream/50 transition-colors duration-150">
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
            ))}
          </tbody>
        </table>
      </div>
      {hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-xs text-theme-orange hover:underline px-1 py-1"
        >
          {showAll ? 'Show less' : `View ${hiddenCount} more`}
        </button>
      )}
    </div>
  )
}


type PeriodOption = { value: string; label: string }

export default function DataAnalysisSection({ token }: { token: string | null }) {
  const apiBaseUrl = useApiUrl()
  const { setUnclassifiedCount } = useDashboardActions()
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
    setSummary(null)
    const params = new URLSearchParams()
    if (periodType && periodValue) {
      params.set('period', periodType)
      params.set('value', periodValue)
    }
    const url = `${apiBaseUrl}/api/analytics/summary` + (params.toString() ? `?${params}` : '')
    fetch(url, { cache: 'no-store', headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText)
        return res.json()
      })
      .then((data) => { if (!cancelled) { setSummary(data); if (data?.unclassified_count != null) setUnclassifiedCount(data.unclassified_count) } })
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
      <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 w-full">
        <h2 className="font-heading text-xl font-semibold mb-1 text-theme-dark">Spending Analysis</h2>
        <p className="text-sm text-theme-dark/90 mb-5">
          Spending data summary from your receipts by store, payment type, and category.
        </p>

        {/* Monthly chart — always visible, independent of period filter */}
        <MonthlySpendingChart token={token} apiBaseUrl={apiBaseUrl} />
      </div>

      <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 w-full">
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
        {!loading && !error && (!summary || (summary.total_receipts === 0 && summary.total_amount_cents === 0)) && (
          <p className="text-theme-mid text-sm">No receipt data for this period. Upload receipts or choose another period.</p>
        )}
        {!loading && !error && summary && (summary.total_receipts > 0 || summary.total_amount_cents > 0) && (
          <>
            {/* Total Receipts + Total Amount */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-2 text-sm items-end">
              <div>
                <span className="text-theme-mid block">Total Receipts</span>
                <p className="font-semibold text-theme-dark">{summary.total_receipts}</p>
              </div>
              <div>
                <span className="text-theme-mid block">Total Amount</span>
                <p className="font-semibold text-theme-dark tabular-nums">{formatDollars(summary.total_amount_cents)}</p>
              </div>
              <div>
                <span className="text-theme-mid block">Tax</span>
                <p className="font-semibold text-theme-dark tabular-nums">{formatDollars(summary.total_tax_cents ?? 0)}</p>
              </div>
              <div>
                <span className="text-theme-mid block">Fees</span>
                <p className="font-semibold text-theme-dark tabular-nums">{formatDollars(summary.total_fees_cents ?? 0)}</p>
              </div>
            </div>
            {/* Feature 1: Stacked Progress Bar */}
            {summary.by_category_l1.length > 0 && (
              <StackedProgressBar segments={buildSegments(summary.by_category_l1, summary.total_amount_cents, [
                { name: 'Tax', amount_cents: summary.total_tax_cents ?? 0, color: '#B0BEC5' },
                { name: 'Fees', amount_cents: summary.total_fees_cents ?? 0, color: '#CFD8DC' },
                { name: 'Uncategorized', amount_cents: summary.unclassified_amount_cents ?? 0, color: '#E0E0E0' },
              ])} />
            )}
          </>
        )}
      </div>

      {!loading && !error && summary && (summary.total_receipts > 0 || summary.by_store.length > 0) && (
        <>
          {/* Donut + Stat Cards */}
          <DonutChartCard summary={summary} />

          {/* Top 3 columns: By Store | By Payment Type | By System Category */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 w-full max-w-full items-stretch">
            <div className="w-full min-w-0 h-full">
              <TableWithPct title="By store" rows={summary.by_store} totalCents={summary.total_amount_cents} showCount />
            </div>
            <div className="w-full min-w-0 h-full">
              <TableWithPct title="By payment type" rows={summary.by_payment} totalCents={summary.total_amount_cents} showCount />
            </div>
            <div className="w-full min-w-0 h-full">
              <SystemCategoryCard rows={summary.by_category_l1} totalCents={summary.total_amount_cents} />
            </div>
          </div>

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
    <div className="bg-white rounded-xl shadow p-3 sm:p-4 overflow-hidden w-full min-w-0 h-full flex flex-col">
      <h3 className="text-sm font-semibold text-theme-dark/90 mb-3">By system category</h3>
      <div className="overflow-x-auto flex-1">
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

  // Indent: base 8px + 20px per depth level; right padding for amount alignment by depth.
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
        <td
          className={`py-1.5 text-right tabular-nums text-sm whitespace-nowrap ${depthOpacity} ${depthWeight}`}
          style={{ paddingRight: `${numPrPx * indentScale}px` }}
        >
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
                className={`${thBase} ${sortCol === 'value' ? thActive : thInactive} text-right pr-[52px]`}
                onClick={(e) => { if (!(e.target as HTMLElement).closest('button')) handleSortClick('value') }}
              >
                <div className="relative inline-block text-right">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setValueDropdownOpen((o) => !o) }}
                    className="inline-flex items-center gap-1 font-medium text-theme-dark hover:text-theme-orange focus:outline-none focus:ring-0"
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
