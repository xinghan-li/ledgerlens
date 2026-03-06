'use client'

import { useEffect, useState, useCallback } from 'react'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import { useRouter, useParams } from 'next/navigation'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'

type PrefillItem = {
  product_name: string
  quantity: number | null
  unit: string | null
  unit_price: number | null
  line_total: number | null
  on_sale: boolean
  original_price: number | null
  discount_amount: number | null
}

type Prefill = {
  store_name: string | null
  store_address: string | null
  receipt_date: string | null
  subtotal: number | null
  tax: number | null
  total: number | null
  currency: string | null
  payment_method: string | null
  payment_last4: string | null
  cashier: string | null
}

type ReceiptDetail = {
  id: string
  user_id: string
  uploaded_at: string
  current_status: string
  current_stage: string | null
  raw_file_url: string | null
  failure_reason: string | null
  run_stage?: string | null
  prefill: Prefill
  prefill_items: PrefillItem[]
}

function toInputDate(d: string | null | undefined): string {
  if (!d) return ''
  try {
    const dt = new Date(d)
    return dt.toISOString().slice(0, 10)
  } catch {
    return ''
  }
}

function numToStr(v: number | null | undefined): string {
  if (v == null) return ''
  return String(v)
}

export default function FailedReceiptEditPage() {
  const params = useParams()
  const router = useRouter()
  const apiBaseUrl = useApiUrl()
  const id = params?.id as string
  const [detail, setDetail] = useState<ReceiptDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [imageObjectUrl, setImageObjectUrl] = useState<string | null>(null)

  // Form state: summary
  const [storeName, setStoreName] = useState('')
  const [storeAddress, setStoreAddress] = useState('')
  const [cashier, setCashier] = useState('')
  const [receiptDate, setReceiptDate] = useState('')
  const [subtotal, setSubtotal] = useState('')
  const [tax, setTax] = useState('')
  const [total, setTotal] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [paymentMethod, setPaymentMethod] = useState('')
  const [paymentLast4, setPaymentLast4] = useState('')

  // Form state: items (array of editable rows)
  const [items, setItems] = useState<Array<{
    product_name: string
    quantity: string
    unit: string
    unit_price: string
    line_total: string
    on_sale: boolean
    original_price: string
    discount_amount: string
  }>>([])

  const fetchDetail = useCallback(async () => {
    if (!id || !token) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${apiBaseUrl}/api/admin/failed-receipts/${id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(res.status === 404 ? 'Receipt not found' : await res.text())
      const data: ReceiptDetail = await res.json()
      setDetail(data)
      const p = data.prefill || {}
      setStoreName(p.store_name ?? '')
      setStoreAddress(p.store_address ?? '')
      setCashier(p.cashier ?? '')
      setReceiptDate(toInputDate(p.receipt_date))
      setSubtotal(numToStr(p.subtotal))
      setTax(numToStr(p.tax))
      setTotal(numToStr(p.total))
      setCurrency(p.currency ?? 'USD')
      setPaymentMethod(p.payment_method ?? '')
      setPaymentLast4(p.payment_last4 ?? '')
      const list = (data.prefill_items || []).map((it) => ({
        product_name: it.product_name ?? '',
        quantity: numToStr(it.quantity),
        unit: it.unit ?? '',
        unit_price: numToStr(it.unit_price),
        line_total: numToStr(it.line_total),
        on_sale: it.on_sale ?? false,
        original_price: numToStr(it.original_price),
        discount_amount: numToStr(it.discount_amount),
      }))
      if (list.length === 0) list.push({ product_name: '', quantity: '', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' })
      setItems(list)
      // Fetch image via API (raw_file_url may be local path; API serves or redirects)
      if (data.raw_file_url && token) {
        try {
          const imgRes = await fetch(`${apiBaseUrl}/api/admin/receipt-image/${id}`, {
            headers: { Authorization: `Bearer ${token}` },
          })
          if (imgRes.ok) {
            const blob = await imgRes.blob()
            const url = URL.createObjectURL(blob)
            setImageObjectUrl(url)
          }
        } catch {
          // Ignore image load failure
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load')
    } finally {
      setLoading(false)
    }
  }, [id, token])

  useEffect(() => {
    return () => {
      if (imageObjectUrl) URL.revokeObjectURL(imageObjectUrl)
    }
  }, [imageObjectUrl])

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      setToken(user ? await user.getIdToken() : null)
    })
    return () => unsubscribe()
  }, [])

  useEffect(() => {
    if (token && id) fetchDetail()
  }, [token, id, fetchDetail])

  const addRow = () => {
    setItems((prev) => [...prev, { product_name: '', quantity: '', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])
  }

  const removeRow = (index: number) => {
    setItems((prev) => prev.filter((_, i) => i !== index))
  }

  const updateItem = (index: number, field: string, value: string | boolean) => {
    setItems((prev) => {
      const next = [...prev]
      if (!next[index]) return next
      ;(next[index] as Record<string, unknown>)[field] = value
      return next
    })
  }

  // 每行容差：至少 0.10 美元，或 line_total 的 1%（按重量/小数数量时 1.27×10.99 的真实值可在一定区间内，固定 2 美分不够）
  const toleranceForLine = (lineTotal: number) => Math.max(0.10, lineTotal * 0.01)
  const invalidRows = items.filter((it) => {
    const qty = it.quantity.trim() ? parseFloat(it.quantity) : NaN
    const price = it.unit_price.trim() ? parseFloat(it.unit_price) : NaN
    const lt = it.line_total.trim() ? parseFloat(it.line_total) : NaN
    if (isNaN(qty) || isNaN(price) || isNaN(lt)) return false
    const diff = Math.abs(qty * price - lt)
    return diff > toleranceForLine(lt)
  })

  const handleSubmit = async () => {
    if (!token || !id) return
    if (invalidRows.length > 0) {
      setError('Some rows have quantity × unit price ≠ line total. Please fix the highlighted red rows.')
      return
    }
    const totalNum = total.trim() ? parseFloat(total) : NaN
    if (isNaN(totalNum)) {
      setError('Please fill Total')
      return
    }
    setSubmitting(true)
    setError(null)
    setSuccessMessage(null)
    try {
      const summary = {
        store_name: storeName.trim() || undefined,
        store_address: storeAddress.trim() || undefined,
        receipt_date: receiptDate.trim() || undefined,
        subtotal: subtotal.trim() ? parseFloat(subtotal) : undefined,
        tax: tax.trim() ? parseFloat(tax) : undefined,
        total: totalNum,
        currency: currency.trim() || 'USD',
        payment_method: paymentMethod.trim() || undefined,
        payment_last4: paymentLast4.trim() || undefined,
      }
      const itemsPayload = items
        .filter((it) => (it.product_name || '').trim())
        .map((it) => ({
          product_name: it.product_name.trim(),
          quantity: it.quantity.trim() ? parseFloat(it.quantity) : undefined,
          unit: it.unit.trim() || undefined,
          unit_price: it.unit_price.trim() ? parseFloat(it.unit_price) : undefined,
          line_total: it.line_total.trim() ? parseFloat(it.line_total) : undefined,
          on_sale: it.on_sale,
          original_price: it.original_price.trim() ? parseFloat(it.original_price) : undefined,
          discount_amount: it.discount_amount.trim() ? parseFloat(it.discount_amount) : undefined,
        }))
      const res = await fetch(`${apiBaseUrl}/api/admin/failed-receipts/${id}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ summary, items: itemsPayload }),
      })
      const data = res.ok ? await res.json().catch(() => ({})) : await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(data.detail || 'Submit failed')
      setSuccessMessage('Saved. Receipt status updated to success.')
      setTimeout(() => router.push('/admin/failed-receipts'), 1500)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Submit failed')
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancel = () => {
    router.push('/admin/failed-receipts')
  }

  if (!token) {
    return <div className="text-center py-8 text-theme-mid">Please sign in first.</div>
  }

  if (loading) {
    return <p className="text-theme-mid">Loading…</p>
  }

  if (error && !detail) {
    return (
      <div>
        <p className="text-theme-red">{error}</p>
        <Link href="/admin/failed-receipts" className="mt-4 inline-block text-theme-orange hover:underline">Back to list</Link>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Manual receipt correction</h2>
        <Link href="/admin/failed-receipts" className="text-sm text-theme-orange hover:underline">← Back to list</Link>
      </div>
      {detail?.failure_reason && (
        <div className="p-2 bg-amber-50 text-amber-800 rounded text-sm">
          Failure reason: {detail.failure_reason}
        </div>
      )}
      {error && (
        <div className="p-2 bg-theme-red/15 text-theme-red rounded text-sm flex items-center justify-between gap-2">
          <span>{error}</span>
          <button type="button" className="shrink-0 text-theme-red hover:opacity-90" onClick={() => setError(null)} aria-label="Close">×</button>
        </div>
      )}
      {successMessage && (
        <div className="p-2 bg-green-100 text-green-800 rounded text-sm flex items-center justify-between gap-2">
          <span>{successMessage}</span>
          <button type="button" className="shrink-0 text-green-800 hover:text-green-900" onClick={() => setSuccessMessage(null)} aria-label="Close">×</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: receipt image */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg shadow p-4 sticky top-4">
            <p className="text-sm font-medium text-theme-dark/90 mb-2">Receipt image</p>
            {(detail?.raw_file_url && imageObjectUrl) ? (
              <img src={imageObjectUrl} alt="Receipt" className="w-full border rounded object-contain max-h-[70vh]" />
            ) : detail?.raw_file_url ? (
              <div className="w-full aspect-[3/4] border rounded bg-theme-light-gray/50 flex items-center justify-center text-theme-mid text-sm">
                Loading…
              </div>
            ) : (
              <div className="w-full aspect-[3/4] border rounded bg-theme-light-gray/50 flex items-center justify-center text-theme-mid text-sm">
                No image
              </div>
            )}
          </div>
        </div>

        {/* Right: form */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm font-medium text-theme-dark/90 mb-3">Store / Address / Cashier</p>
            <div className="grid grid-cols-1 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Store name</span>
                <input className="border rounded px-2 py-1" value={storeName} onChange={(e) => setStoreName(e.target.value)} placeholder="Store name" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Address</span>
                <input className="border rounded px-2 py-1" value={storeAddress} onChange={(e) => setStoreAddress(e.target.value)} placeholder="Address" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Cashier</span>
                <input className="border rounded px-2 py-1" value={cashier} onChange={(e) => setCashier(e.target.value)} placeholder="Cashier (optional)" />
              </label>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm font-medium text-theme-dark/90 mb-3">Item lines (add/remove)</p>
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-theme-light-gray">
                    <th className="text-left py-2 pr-4 font-medium text-theme-dark/90" style={{ minWidth: 200 }}>Product name</th>
                    <th className="text-left py-2 pr-2 font-medium text-theme-dark/90 w-20">Quantity</th>
                    <th className="text-left py-2 pr-2 font-medium text-theme-dark/90 w-16">Unit</th>
                    <th className="text-left py-2 pr-2 font-medium text-theme-dark/90 w-20">Unit price</th>
                    <th className="text-left py-2 pr-2 font-medium text-theme-dark/90 w-20">Line total</th>
                    <th className="text-left py-2 pr-2 font-medium text-theme-dark/90 w-14">On sale</th>
                    <th className="text-left py-2 w-12" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((row, index) => {
                    const qty = row.quantity.trim() ? parseFloat(row.quantity) : NaN
                    const price = row.unit_price.trim() ? parseFloat(row.unit_price) : NaN
                    const lt = row.line_total.trim() ? parseFloat(row.line_total) : NaN
                    const hasQtyAndPrice = !isNaN(qty) && !isNaN(price)
                    const expectedLineTotal = hasQtyAndPrice ? qty * price : NaN
                    const lineTotalMismatch = hasQtyAndPrice && !isNaN(lt) && Math.abs(expectedLineTotal - lt) > toleranceForLine(lt)
                    return (
                      <tr key={index} className={`border-b border-theme-light-gray/50 ${lineTotalMismatch ? 'bg-theme-red/15' : ''}`}>
                        <td className="py-1.5 pr-4">
                          <input className="w-full min-w-[180px] border border-theme-light-gray rounded px-1.5 py-0.5 text-sm" placeholder="product name" value={row.product_name} onChange={(e) => updateItem(index, 'product_name', e.target.value)} />
                        </td>
                        <td className="py-1.5 pr-2">
                          <input className="w-full max-w-16 border border-theme-light-gray rounded px-1 py-0.5 text-sm" placeholder="quantity" value={row.quantity} onChange={(e) => updateItem(index, 'quantity', e.target.value)} />
                        </td>
                        <td className="py-1.5 pr-2">
                          <input className="w-full max-w-12 border border-theme-light-gray rounded px-1 py-0.5 text-sm" placeholder="unit" value={row.unit} onChange={(e) => updateItem(index, 'unit', e.target.value)} />
                        </td>
                        <td className="py-1.5 pr-2">
                          <input className="w-full max-w-20 border border-theme-light-gray rounded px-1 py-0.5 text-sm" placeholder="unit price" value={row.unit_price} onChange={(e) => updateItem(index, 'unit_price', e.target.value)} />
                        </td>
                        <td className="py-1.5 pr-2">
                          <input className="w-full max-w-20 border border-theme-light-gray rounded px-1 py-0.5 text-sm" placeholder="line total" value={row.line_total} onChange={(e) => updateItem(index, 'line_total', e.target.value)} />
                        </td>
                        <td className="py-1.5 pr-2">
                          <label className="flex items-center gap-1">
                            <input type="checkbox" checked={row.on_sale} onChange={(e) => updateItem(index, 'on_sale', e.target.checked)} />
                          </label>
                        </td>
                        <td className="py-1.5">
                          <button type="button" className="text-theme-red hover:underline" onClick={() => removeRow(index)}>Delete</button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot>
                  {(() => {
                    const itemsSum = items.reduce((acc, it) => {
                      const v = it.line_total.trim() ? parseFloat(it.line_total) : NaN
                      return acc + (isNaN(v) ? 0 : v)
                    }, 0)
                    const capturedSubtotal = subtotal.trim() ? parseFloat(subtotal) : NaN
                    const sumMatchesSubtotal = !isNaN(capturedSubtotal) && !Number.isNaN(itemsSum) && Math.abs(itemsSum - capturedSubtotal) < 0.02
                    return (
                      <tr className="bg-white border-t-2 border-theme-light-gray">
                        <td colSpan={4} className="py-2 pr-4 text-right font-medium text-theme-dark/90">Items total:</td>
                        <td className="py-2 pr-2">
                          <span className={`font-semibold ${sumMatchesSubtotal ? 'text-green-600' : 'text-theme-dark'}`}>
                            ${itemsSum.toFixed(2)}
                          </span>
                        </td>
                        <td colSpan={2} />
                      </tr>
                    )
                  })()}
                </tfoot>
              </table>
            </div>
            <p className="text-xs text-theme-mid mt-1">Compare Items total above with Subtotal below. Green = match.</p>
            <button type="button" className="mt-2 px-3 py-1 border rounded text-sm bg-theme-light-gray/50 hover:bg-theme-light-gray" onClick={addRow}>+ Add row</button>
          </div>

          <div className="bg-white rounded-lg shadow p-4">
            <p className="text-sm font-medium text-theme-dark/90 mb-3">Total & payment</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Date</span>
                <input type="date" className="border rounded px-2 py-1" value={receiptDate} onChange={(e) => setReceiptDate(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Subtotal</span>
                <input className="border rounded px-2 py-1" value={subtotal} onChange={(e) => setSubtotal(e.target.value)} placeholder="0.00" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Tax</span>
                <input className="border rounded px-2 py-1" value={tax} onChange={(e) => setTax(e.target.value)} placeholder="0.00" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Total *</span>
                <input className="border rounded px-2 py-1" value={total} onChange={(e) => setTotal(e.target.value)} placeholder="0.00" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Currency</span>
                <input className="border rounded px-2 py-1" value={currency} onChange={(e) => setCurrency(e.target.value)} placeholder="USD" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Payment method</span>
                <input className="border rounded px-2 py-1" value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)} placeholder="credit_card / cash" />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-theme-mid">Card last 4</span>
                <input className="border rounded px-2 py-1" value={paymentLast4} onChange={(e) => setPaymentLast4(e.target.value)} placeholder="1234" maxLength={4} />
              </label>
            </div>
          </div>

          <div className="flex gap-3">
            <button type="button" className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50" disabled={submitting || invalidRows.length > 0} onClick={handleSubmit}>
              {submitting ? 'Submitting...' : 'Submit'}
            </button>
            <button type="button" className="px-4 py-2 border rounded hover:bg-theme-light-gray/50" onClick={handleCancel}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
