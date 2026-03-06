'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'

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

type Summary = {
  total_receipts: number
  total_amount_cents: number
  by_store: Array<{ name: string; amount_cents: number; count: number }>
  by_payment: Array<{ name: string; amount_cents: number; count: number }>
  by_category_l1: Array<{ name: string; amount_cents: number }>
  by_category_l2: Array<{ name: string; amount_cents: number }>
  by_category_l3: Array<{ name: string; amount_cents: number }>
  unclassified_count?: number
  unclassified_amount_cents?: number
}

function formatDollars(cents: number): string {
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
}

const TABLE_DEFAULT_MOBILE = 5
const TABLE_DEFAULT_DESKTOP = 10

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

function PctToggle({
  mode,
  onChange,
  catLabel,
}: {
  mode: 'total' | 'category'
  onChange: (v: 'total' | 'category') => void
  catLabel: string
}) {
  return (
    <div className="flex items-center gap-1 shrink-0">
      <span className="text-xs text-theme-mid mr-0.5">% of:</span>
      <button
        onClick={() => onChange('total')}
        className={`px-1.5 py-0.5 rounded border text-xs transition-colors duration-150 ${
          mode === 'total'
            ? 'bg-theme-orange text-white border-theme-orange'
            : 'bg-white text-theme-dark border-theme-mid hover:bg-theme-cream'
        }`}
      >
        Total
      </button>
      <button
        onClick={() => onChange('category')}
        className={`px-1.5 py-0.5 rounded border text-xs transition-colors duration-150 max-w-[80px] truncate ${
          mode === 'category'
            ? 'bg-theme-orange text-white border-theme-orange'
            : 'bg-white text-theme-dark border-theme-mid hover:bg-theme-cream'
        }`}
        title={catLabel}
      >
        {catLabel}
      </button>
    </div>
  )
}

function CategoryLevelTable({
  title,
  rows,
  totalCents,
  maxDefault,
  showAll,
  onShowAll,
  onCollapse,
  selectedItem,
  onSelectItem,
  isClickable,
  contentKey,
  pctMode,
  onPctModeChange,
  pctCatLabel,
}: {
  title: string
  rows: Array<{ name: string; amount_cents: number }>
  totalCents: number
  maxDefault?: number
  showAll?: boolean
  onShowAll?: () => void
  onCollapse?: () => void
  selectedItem?: string | null
  onSelectItem?: (name: string) => void
  isClickable?: boolean
  contentKey?: string
  pctMode?: 'total' | 'category'
  onPctModeChange?: (v: 'total' | 'category') => void
  pctCatLabel?: string
}) {
  const total = totalCents || 1
  const displayRows = maxDefault && !showAll ? rows.slice(0, maxDefault) : rows
  const hiddenCount = maxDefault && !showAll ? Math.max(0, rows.length - maxDefault) : 0

  // Fade animation when content key changes (filter applied/removed)
  const [opacity, setOpacity] = useState(1)
  const isFirstRender = useRef(true)
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false
      return
    }
    setOpacity(0)
    const t = setTimeout(() => setOpacity(1), 30)
    return () => clearTimeout(t)
  }, [contentKey])

  return (
    <div className="bg-white rounded-xl shadow p-3 sm:p-4 mb-4 overflow-hidden w-full min-w-0 md:h-full">
      <div className="flex items-center justify-between mb-3 gap-2">
        <h3 className="text-sm font-semibold text-theme-dark/90 shrink-0">{title}</h3>
        {pctCatLabel && pctMode !== undefined && onPctModeChange && (
          <PctToggle mode={pctMode} onChange={onPctModeChange} catLabel={pctCatLabel} />
        )}
      </div>
      <div
        style={{
          opacity,
          transition: 'opacity 220ms ease',
        }}
      >
        {rows.length === 0 ? (
          <p className="text-xs text-theme-mid py-2">No data</p>
        ) : (
          <>
            <div className="min-w-0 overflow-hidden">
              <table className="w-full text-sm table-fixed">
                <thead>
                  <tr className="border-b border-theme-light-gray text-left text-theme-mid">
                    <th className="py-2 pr-2 text-left" style={{ width: '60%', minWidth: '6rem' }}>Name</th>
                    <th className="py-2 pr-2 text-right w-24">Amount</th>
                    <th className="py-2 pl-2 text-right w-14">%</th>
                  </tr>
                </thead>
                <tbody>
                  {displayRows.map((r, i) => {
                    const isSelected = selectedItem === r.name
                    return (
                      <tr
                        key={i}
                        className={`border-b border-theme-light-gray/50 transition-colors duration-150 ${
                          isClickable
                            ? 'cursor-pointer select-none hover:bg-theme-cream/80'
                            : 'hover:bg-theme-cream/50'
                        } ${isSelected ? 'bg-theme-orange/10' : ''}`}
                        onClick={isClickable && onSelectItem ? () => onSelectItem(r.name) : undefined}
                      >
                        <td className={`py-2 pr-2 font-medium transition-colors duration-150 min-w-0 break-words ${isSelected ? 'text-theme-orange' : 'text-theme-dark'}`}>
                          {isSelected && <span className="mr-1 text-xs">▸</span>}
                          {r.name}
                        </td>
                        <td className="py-2 pr-2 text-right tabular-nums shrink-0">{formatDollars(r.amount_cents)}</td>
                        <td className="py-2 pl-2 text-right tabular-nums text-theme-dark/90 shrink-0">
                          {((r.amount_cents / total) * 100).toFixed(1)}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {hiddenCount > 0 && onShowAll && (
              <button
                onClick={onShowAll}
                className="mt-2 text-xs text-theme-orange hover:underline"
              >
                Show {hiddenCount} more…
              </button>
            )}
            {showAll && maxDefault && rows.length > maxDefault && onCollapse && (
              <button
                onClick={onCollapse}
                className="mt-2 text-xs text-theme-mid hover:underline"
              >
                Show less
              </button>
            )}
          </>
        )}
      </div>
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

  // Category interaction state
  const [selectedL1, setSelectedL1] = useState<string | null>(null)
  const [selectedL2, setSelectedL2] = useState<string | null>(null)
  const [showAllL2, setShowAllL2] = useState(false)
  const [showAllL3, setShowAllL3] = useState(false)
  const [pctModeL2, setPctModeL2] = useState<'total' | 'category'>('total')
  const [pctModeL3, setPctModeL3] = useState<'total' | 'category'>('total')

  useEffect(() => {
    setMonthOptions(buildMonthOptions())
    setQuarterOptions(buildQuarterOptions())
    setYearOptions(buildYearOptions())
  }, [])

  // Reset category interaction on data reload
  useEffect(() => {
    setSelectedL1(null)
    setSelectedL2(null)
    setShowAllL2(false)
    setShowAllL3(false)
    setPctModeL2('total')
    setPctModeL3('total')
  }, [summary])

  // Reset L2 and pct modes when L1 selection changes
  useEffect(() => {
    setSelectedL2(null)
    setPctModeL2('total')
    setPctModeL3('total')
  }, [selectedL1])

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
                  <div className="grid grid-cols-[auto_1fr_5.5rem_2.5rem] gap-x-2 items-baseline font-medium text-theme-dark tabular-nums">
                    {[...summary.by_category_l1]
                      .sort((a, b) => b.amount_cents - a.amount_cents)
                      .slice(0, 3)
                      .map((r, i) => {
                        const total = summary.by_category_l1.reduce((s, x) => s + x.amount_cents, 0) || summary.total_amount_cents || 1
                        const pct = ((r.amount_cents / total) * 100).toFixed(1)
                        const medal = ['🪙', '🔘', '🟠'][i]
                        return (
                          <span key={i} className="contents">
                            <span aria-hidden className="shrink-0">{medal}</span>
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
                  <div className="grid grid-cols-[auto_1fr_auto_auto] gap-x-2 items-baseline font-medium text-theme-dark tabular-nums">
                    {[...summary.by_category_l1]
                      .sort((a, b) => b.amount_cents - a.amount_cents)
                      .slice(0, 3)
                      .map((r, i) => {
                        const total = summary.by_category_l1.reduce((s, x) => s + x.amount_cents, 0) || summary.total_amount_cents || 1
                        const pct = ((r.amount_cents / total) * 100).toFixed(1)
                        const medal = ['🪙', '🔘', '🟠'][i]
                        return (
                          <span key={i} className="contents">
                            <span aria-hidden className="shrink-0">{medal}</span>
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
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 w-full max-w-full">
            <div className="w-full min-w-0">
              <TableWithPct title="By store" rows={summary.by_store} totalCents={summary.total_amount_cents} showCount showAllDesktop={showAllStores} />
            </div>
            <div className="w-full min-w-0">
              <TableWithPct title="By payment card" rows={summary.by_payment} totalCents={summary.total_amount_cents} showCount showAllDesktop={showAllStores} />
            </div>
          </div>
          {/* Desktop: shared Show more/less, only if either table > 10 rows */}
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

          <CategorySection
            summary={summary}
            selectedL1={selectedL1}
            setSelectedL1={setSelectedL1}
            selectedL2={selectedL2}
            setSelectedL2={setSelectedL2}
            showAllL2={showAllL2}
            setShowAllL2={setShowAllL2}
            showAllL3={showAllL3}
            setShowAllL3={setShowAllL3}
            pctModeL2={pctModeL2}
            setPctModeL2={setPctModeL2}
            pctModeL3={pctModeL3}
            setPctModeL3={setPctModeL3}
          />
        </>
      )}
    </div>
  )
}

function CategorySection({
  summary,
  selectedL1,
  setSelectedL1,
  selectedL2,
  setSelectedL2,
  showAllL2,
  setShowAllL2,
  showAllL3,
  setShowAllL3,
  pctModeL2,
  setPctModeL2,
  pctModeL3,
  setPctModeL3,
}: {
  summary: Summary
  selectedL1: string | null
  setSelectedL1: (v: string | null) => void
  selectedL2: string | null
  setSelectedL2: (v: string | null) => void
  showAllL2: boolean
  setShowAllL2: (v: boolean) => void
  showAllL3: boolean
  setShowAllL3: (v: boolean) => void
  pctModeL2: 'total' | 'category'
  setPctModeL2: (v: 'total' | 'category') => void
  pctModeL3: 'total' | 'category'
  setPctModeL3: (v: 'total' | 'category') => void
}) {
  const l1Total =
    summary.by_category_l1.reduce((s, r) => s + r.amount_cents, 0) || summary.total_amount_cents

  const selectedL1Cents = selectedL1
    ? (summary.by_category_l1.find((r) => r.name === selectedL1)?.amount_cents ?? l1Total)
    : l1Total

  // L2: filter by L1, strip L1 prefix
  const filteredL2 = selectedL1
    ? summary.by_category_l2
        .filter((r) => r.name.startsWith(selectedL1 + '/'))
        .map((r) => ({ ...r, name: r.name.slice(selectedL1.length + 1) }))
    : summary.by_category_l2

  // selectedL2 display name → find its amount from filteredL2
  const selectedL2Cents = selectedL2
    ? (filteredL2.find((r) => r.name === selectedL2)?.amount_cents ?? selectedL1Cents)
    : selectedL1Cents

  // L3: filter by L1, then optionally by L2; strip both prefixes
  const l3AfterL1 = selectedL1
    ? summary.by_category_l3
        .filter((r) => r.name.startsWith(selectedL1 + '/'))
        .map((r) => ({ ...r, name: r.name.slice(selectedL1.length + 1) }))
    : summary.by_category_l3

  const filteredL3 = selectedL2
    ? l3AfterL1
        .filter((r) => r.name.startsWith(selectedL2 + '/'))
        .map((r) => ({ ...r, name: r.name.slice(selectedL2.length + 1) }))
    : l3AfterL1

  // L2 denominator: "% of selected L1" or "% of grand total"
  const l2TotalBase = selectedL1
    ? pctModeL2 === 'category' ? selectedL1Cents : l1Total
    : filteredL2.reduce((s, r) => s + r.amount_cents, 0) || summary.total_amount_cents

  // L3 denominator: "% of selected L2 (or L1)" or "% of grand total"
  const l3CatDenom = selectedL2 ? selectedL2Cents : selectedL1Cents
  const l3TotalBase = selectedL1
    ? pctModeL3 === 'category' ? l3CatDenom : l1Total
    : filteredL3.reduce((s, r) => s + r.amount_cents, 0) || summary.total_amount_cents

  const handleSelectL1 = (name: string) => {
    setSelectedL1(selectedL1 === name ? null : name)
    setSelectedL2(null)
    setShowAllL2(false)
    setShowAllL3(false)
  }

  const handleSelectL2 = (name: string) => {
    setSelectedL2(selectedL2 === name ? null : name)
    setShowAllL3(false)
  }

  const l2ContentKey = selectedL1 ?? 'none'
  const l3ContentKey = `${selectedL1 ?? 'none'}/${selectedL2 ?? 'none'}`

  // Breadcrumb: "— grocery" or "— grocery / paper products"
  const breadcrumb = selectedL1
    ? selectedL2
      ? `— ${selectedL1} / ${selectedL2}`
      : `— ${selectedL1}`
    : null

  // L3 pct toggle label: selectedL2 label (if set) or selectedL1 label
  const l3PctCatLabel = selectedL2 ?? selectedL1 ?? undefined

  return (
    <div className="mt-4">
      <div className="flex items-center gap-2 mb-3 pl-3 sm:pl-4">
        <h3 className="text-sm font-semibold text-theme-dark/90">By category</h3>
        {breadcrumb && (
          <span className="font-normal text-theme-orange text-xs">{breadcrumb}</span>
        )}
      </div>

      {/* Unclassified — prominent, between heading and three columns */}
      {(summary.unclassified_count ?? 0) > 0 && !unclassifiedBannerDismissed && (
        <div className="mb-4 flex items-stretch gap-0">
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

      {!selectedL1 && (
        <p className="text-xs text-theme-mid mb-2 pl-3 sm:pl-4">
          Click a Level I category to filter.
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 w-full max-w-full md:items-stretch">
        <div className="w-full min-w-0 md:flex md:flex-col">
          <CategoryLevelTable
            title="Level I"
            rows={summary.by_category_l1}
            totalCents={l1Total}
            selectedItem={selectedL1}
            onSelectItem={handleSelectL1}
            isClickable
          />
        </div>
        <div className="w-full min-w-0 md:flex md:flex-col">
          <CategoryLevelTable
          title="Level II"
          rows={filteredL2}
          totalCents={l2TotalBase}
          maxDefault={selectedL1 ? undefined : 10}
          showAll={showAllL2}
          onShowAll={() => setShowAllL2(true)}
          onCollapse={() => setShowAllL2(false)}
          contentKey={l2ContentKey}
          selectedItem={selectedL1 ? selectedL2 : undefined}
          onSelectItem={selectedL1 ? handleSelectL2 : undefined}
          isClickable={!!selectedL1}
          pctMode={selectedL1 ? pctModeL2 : undefined}
          onPctModeChange={selectedL1 ? setPctModeL2 : undefined}
          pctCatLabel={selectedL1 ?? undefined}
        />
        </div>
        <div className="w-full min-w-0 md:flex md:flex-col">
          <CategoryLevelTable
          title="Level III"
          rows={filteredL3}
          totalCents={l3TotalBase}
          maxDefault={selectedL1 ? undefined : 10}
          showAll={showAllL3}
          onShowAll={() => setShowAllL3(true)}
          onCollapse={() => setShowAllL3(false)}
          contentKey={l3ContentKey}
          pctMode={selectedL1 ? pctModeL3 : undefined}
          onPctModeChange={selectedL1 ? setPctModeL3 : undefined}
          pctCatLabel={l3PctCatLabel}
        />
        </div>
      </div>
    </div>
  )
}
