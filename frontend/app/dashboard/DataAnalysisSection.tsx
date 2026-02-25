'use client'

import { useEffect, useState } from 'react'

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

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
    if (qq < 1) {
      qq += 4
      y -= 1
    }
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
}

function formatDollars(cents: number): string {
  return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
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
  if (rows.length === 0) return null
  const total = totalCents || 1
  return (
    <div className="bg-white rounded-xl shadow p-3 sm:p-4 mb-4 overflow-hidden">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-gray-500">
              <th className="py-2 pr-4">Name</th>
              {showCount && <th className="py-2 pr-4 text-right">Count</th>}
              <th className="py-2 pr-4 text-right">Amount</th>
              <th className="py-2 text-right">%</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2 pr-4 font-medium text-gray-900">{r.name}</td>
                {showCount && (
                  <td className="py-2 pr-4 text-right tabular-nums text-gray-600">
                    {(r as { count?: number }).count ?? '—'}
                  </td>
                )}
                <td className="py-2 pr-4 text-right tabular-nums">{formatDollars(r.amount_cents)}</td>
                <td className="py-2 text-right tabular-nums text-gray-600">
                  {((r.amount_cents / total) * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

type PeriodOption = { value: string; label: string }

export default function DataAnalysisSection({ token }: { token: string | null }) {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [periodType, setPeriodType] = useState<PeriodType>('')
  const [periodValue, setPeriodValue] = useState<string>('')
  // 仅在客户端挂载后生成，避免服务端/客户端时区不同导致水合不一致
  const [monthOptions, setMonthOptions] = useState<PeriodOption[]>([])
  const [quarterOptions, setQuarterOptions] = useState<PeriodOption[]>([])
  const [yearOptions, setYearOptions] = useState<PeriodOption[]>([])

  useEffect(() => {
    setMonthOptions(buildMonthOptions())
    setQuarterOptions(buildQuarterOptions())
    setYearOptions(buildYearOptions())
  }, [])

  useEffect(() => {
    if (!token) {
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    const params = new URLSearchParams()
    if (periodType && periodValue) {
      params.set('period', periodType)
      params.set('value', periodValue)
    }
    const url = `${apiUrl()}/api/analytics/summary` + (params.toString() ? `?${params}` : '')
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error(res.statusText)
        return res.json()
      })
      .then((data) => {
        if (!cancelled) setSummary(data)
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || 'Failed to load')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [token, periodType, periodValue])

  const periodOptions: { value: PeriodType; label: string }[] = [
    { value: '', label: 'All time' },
    { value: 'month', label: 'By month' },
    { value: 'quarter', label: 'By quarter' },
    { value: 'year', label: 'By year' },
  ]
  const valueOptions =
    periodType === 'month'
      ? monthOptions
      : periodType === 'quarter'
        ? quarterOptions
        : periodType === 'year'
          ? yearOptions
          : []

  return (
    <div className="mb-6 sm:mb-8">
      <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-4">
        <h2 className="text-xl font-semibold mb-4">Data Analysis</h2>
        <p className="text-sm text-gray-600 mb-4">
          Spending summary from your receipts: by store, payment card, and category (Level I / II / III).
        </p>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <label className="flex items-center gap-2 text-sm text-gray-600">
            <span>Filter:</span>
            <select
              className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
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
                <option key={o.value || 'all'} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          {periodType && valueOptions.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <span>Period:</span>
              <select
                className="border border-gray-300 rounded px-2 py-1.5 text-sm bg-white"
                value={periodValue}
                onChange={(e) => setPeriodValue(e.target.value)}
              >
                {valueOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        {loading && (
          <div className="py-8 text-center text-gray-500">
            <span className="inline-block animate-spin text-2xl mr-2">⏳</span>
            Loading…
          </div>
        )}
        {error && !loading && <p className="text-red-600 text-sm">{error}</p>}
        {!loading && !error && (!summary || (summary.total_receipts === 0 && summary.by_store.length === 0)) && (
          <p className="text-gray-500 text-sm">No receipt data for this period. Upload receipts or choose another period.</p>
        )}
        {!loading && !error && summary && (summary.total_receipts > 0 || summary.by_store.length > 0) && (
          <>
            <div className="flex flex-wrap gap-6 text-sm">
              <div>
                <span className="text-gray-500">Total receipts</span>
                <p className="font-semibold text-gray-900">{summary.total_receipts}</p>
              </div>
              <div>
                <span className="text-gray-500">Total amount (receipts)</span>
                <p className="font-semibold text-gray-900">{formatDollars(summary.total_amount_cents)}</p>
              </div>
            </div>
          </>
        )}
      </div>

      {!loading && !error && summary && (summary.total_receipts > 0 || summary.by_store.length > 0) && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <TableWithPct
              title="By store"
              rows={summary.by_store}
              totalCents={summary.total_amount_cents}
              showCount
            />
            <TableWithPct
              title="By payment card"
              rows={summary.by_payment}
              totalCents={summary.total_amount_cents}
              showCount
            />
          </div>

          <div className="mt-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-2">By category</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <TableWithPct
                title="Level I"
                rows={summary.by_category_l1}
                totalCents={
                  summary.by_category_l1.reduce((s, r) => s + r.amount_cents, 0) || summary.total_amount_cents
                }
              />
              <TableWithPct
                title="Level II"
                rows={summary.by_category_l2}
                totalCents={
                  summary.by_category_l2.reduce((s, r) => s + r.amount_cents, 0) || summary.total_amount_cents
                }
              />
              <TableWithPct
                title="Level III"
                rows={summary.by_category_l3}
                totalCents={
                  summary.by_category_l3.reduce((s, r) => s + r.amount_cents, 0) || summary.total_amount_cents
                }
              />
            </div>
          </div>
        </>
      )}
    </div>
  )
}
