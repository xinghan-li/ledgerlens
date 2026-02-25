'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { getFirebaseAuth } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import DataAnalysisSection from '../DataAnalysisSection'
import { CameraCaptureButton } from '../camera'

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type ReceiptListItem = {
  id: string
  uploaded_at: string
  current_status: string
  current_stage?: string
  store_name?: string | null
  chain_name?: string | null
  receipt_date?: string | null
}

export default function DeveloperDashboardPage() {
  const [token, setToken] = useState<string | null>(null)
  const [userEmail, setUserEmail] = useState<string | null>(null)
  const [userUid, setUserUid] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [developerAllowed, setDeveloperAllowed] = useState<boolean | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadWorkingHard, setUploadWorkingHard] = useState(false)
  const [uploadResult, setUploadResult] = useState<any>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const workingHardTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [receiptList, setReceiptList] = useState<ReceiptListItem[]>([])
  const [receiptListLoading, setReceiptListLoading] = useState(false)
  const [expandedReceiptId, setExpandedReceiptId] = useState<string | null>(null)
  const [expandedReceiptJson, setExpandedReceiptJson] = useState<any>(null)
  const [showRawJson, setShowRawJson] = useState(false)
  const [correctionOpen, setCorrectionOpen] = useState(false)
  const [editStoreName, setEditStoreName] = useState('')
  const [editAddressLine1, setEditAddressLine1] = useState('')
  const [editAddressLine2, setEditAddressLine2] = useState('')
  const [editAddressCityStateZip, setEditAddressCityStateZip] = useState('')
  const [editAddressCountry, setEditAddressCountry] = useState('')
  const [editReceiptDate, setEditReceiptDate] = useState('')
  const [editPurchaseTime, setEditPurchaseTime] = useState('')
  const [editSubtotal, setEditSubtotal] = useState('')
  const [editTax, setEditTax] = useState('')
  const [editTotal, setEditTotal] = useState('')
  const [editCurrency, setEditCurrency] = useState('USD')
  const [editPaymentMethod, setEditPaymentMethod] = useState('')
  const [editPaymentLast4, setEditPaymentLast4] = useState('')
  const [editItems, setEditItems] = useState<Array<{ id?: string; product_name: string; quantity: string; unit: string; unit_price: string; line_total: string; on_sale: boolean; original_price: string; discount_amount: string }>>([])
  const [correctSubmitting, setCorrectSubmitting] = useState(false)
  const [correctMessage, setCorrectMessage] = useState<string | null>(null)
  const [categoriesList, setCategoriesList] = useState<Array<{ id: string; parent_id: string | null; name: string; path: string; level: number }>>([])
  const [editingItemId, setEditingItemId] = useState<string | null>(null)
  const [editCatL1, setEditCatL1] = useState<string>('')
  const [editCatL2, setEditCatL2] = useState<string>('')
  const [editCatL3, setEditCatL3] = useState<string>('')
  const [categoryUpdateMessage, setCategoryUpdateMessage] = useState<string | null>(null)
  const [smartCategorizeLoading, setSmartCategorizeLoading] = useState(false)
  const [smartCategorizeMessage, setSmartCategorizeMessage] = useState<string | null>(null)
  const router = useRouter()
  const supabase = createClient()

  function formatAddressMultiLine(addr: string): string {
    if (!addr || addr.includes('\n')) return addr || ''
    let s = addr.trim()
    s = s.replace(/(\d{5})([A-Z]{2})\b/gi, '$1 $2')
    s = s.replace(/\s*Unit\s+/gi, '\nUnit ')
    s = s.replace(/\s*Suite\s+/gi, '\nSuite ')
    s = s.replace(/(\d+)([A-Z][a-z]+,\s*[A-Z]{2}\s*)/g, '$1\n$2')
    s = s.replace(/\s+([A-Z][a-z]+,\s*[A-Z]{2}\s*\d{5}(?:\s+[A-Z]{2})?)/g, '\n$1')
    return s.trim()
  }

  function formatTimeToHHmm(t: string): string {
    if (!t || typeof t !== 'string') return ''
    const s = t.trim()
    const match = s.match(/^(\d{1,2}):(\d{2})/)
    if (match) return `${match[1].padStart(2, '0')}:${match[2]}`
    return s.slice(0, 5)
  }

  function parseAddressToFields(addr: string): { line1: string; line2: string; cityStateZip: string; country: string } {
    const formatted = formatAddressMultiLine(addr || '')
    const lines = formatted.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
    const last = lines[lines.length - 1]
    const isCountryOnly = last && /^[A-Z]{2}$/i.test(last)
    if (lines.length === 0) return { line1: '', line2: '', cityStateZip: '', country: '' }
    if (lines.length === 1) return { line1: lines[0], line2: '', cityStateZip: '', country: '' }
    if (isCountryOnly && lines.length >= 2) {
      const cityStateZip = lines[lines.length - 2]
      return {
        line1: lines[0],
        line2: lines.length >= 3 ? lines[1] : '',
        cityStateZip,
        country: last,
      }
    }
    return {
      line1: lines[0],
      line2: lines.length >= 2 ? lines[1] : '',
      cityStateZip: lines.length >= 3 ? lines[2] : '',
      country: lines.length >= 4 ? lines[3] : '',
    }
  }

  function initEditFormFromJson(json: any) {
    const data = json?.data || {}
    const receipt = data.receipt || {}
    const items = data.items || []
    const toDollar = (v: any) => {
      if (v == null || v === '') return ''
      const n = Number(v)
      if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
      return String(v)
    }
    setEditStoreName(data.chain_name ?? receipt.merchant_name ?? '')
    const addrFields = parseAddressToFields(receipt.merchant_address ?? '')
    setEditAddressLine1(addrFields.line1)
    setEditAddressLine2(addrFields.line2)
    setEditAddressCityStateZip(addrFields.cityStateZip)
    setEditAddressCountry(addrFields.country)
    setEditReceiptDate(receipt.purchase_date ? receipt.purchase_date.slice(0, 10) : '')
    setEditPurchaseTime(formatTimeToHHmm(receipt.purchase_time ?? ''))
    setEditSubtotal(toDollar(receipt.subtotal))
    setEditTax(toDollar(receipt.tax))
    setEditTotal(toDollar(receipt.total))
    setEditCurrency(receipt.currency ?? 'USD')
    setEditPaymentMethod(receipt.payment_method ?? '')
    setEditPaymentLast4(receipt.card_last4 ?? '')
    setEditItems(
      items.length
        ? items.map((it: any) => ({
            id: it.id ?? undefined,
            product_name: it.product_name ?? '',
            quantity: it.quantity != null ? String(it.quantity) : '',
            unit: it.unit ?? '',
            unit_price: it.unit_price != null ? String(it.unit_price) : '',
            line_total: it.line_total != null ? String(it.line_total) : '',
            on_sale: it.on_sale ?? false,
            original_price: it.original_price != null ? String(it.original_price) : '',
            discount_amount: it.discount_amount != null ? String(it.discount_amount) : '',
          }))
        : [{ product_name: '', quantity: '', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }]
    )
    setCorrectionOpen(false)
    setShowRawJson(false)
    setCorrectMessage(null)
  }

  const fetchReceiptList = useCallback(async () => {
    if (!token) return
    setReceiptListLoading(true)
    try {
      const res = await fetch(`${apiUrl()}/api/receipt/list?limit=50&offset=0`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        setReceiptList(data.data || [])
      }
    } catch (e) {
      console.error('Failed to fetch receipt list:', e)
    } finally {
      setReceiptListLoading(false)
    }
  }, [token])

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (!user) {
        setToken(null)
        setUserEmail(null)
        setUserUid(null)
        setLoading(false)
        router.push('/login')
        return
      }
      setUserEmail(user.email ?? null)
      setUserUid(user.uid)
      try {
        setToken(await user.getIdToken())
      } catch (e) {
        setToken(null)
      } finally {
        setLoading(false)
      }
    })
    return () => unsubscribe()
  }, [router])

  useEffect(() => {
    if (token) fetchReceiptList()
  }, [token, fetchReceiptList])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetch(`${apiUrl()}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (cancelled) return
        if (data?.user_class === 'super_admin') {
          setDeveloperAllowed(true)
        } else {
          setDeveloperAllowed(false)
        }
      })
      .catch(() => {
        if (!cancelled) setDeveloperAllowed(false)
      })
    return () => { cancelled = true }
  }, [token])

  const fetchCategories = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${apiUrl()}/api/categories`, { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) {
        const json = await res.json()
        setCategoriesList(json?.data ?? [])
      }
    } catch (_) {}
  }, [token])

  useEffect(() => {
    fetchCategories()
  }, [fetchCategories])

  const refetchReceiptDetail = useCallback(async () => {
    if (!expandedReceiptId || !token) return
    try {
      const res = await fetch(`${apiUrl()}/api/receipt/${expandedReceiptId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const json = await res.json()
        setExpandedReceiptJson(json)
      }
    } catch (_) {}
  }, [expandedReceiptId, token])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !token) {
      e.target.value = ''
      return
    }

    // 重置状态
    setUploading(true)
    setUploadResult(null)
    setUploadError(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      console.log('上传到:', `${apiUrl}/api/receipt/workflow`)
      console.log('Token:', token?.substring(0, 50) + '...')
      console.log('文件:', file.name, file.type, file.size)
      
      // 3 分钟超时；30s 后显示 “working hard” 提示
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 180000)
      workingHardTimerRef.current = setTimeout(() => setUploadWorkingHard(true), 30000)

      try {
        const response = await fetch(`${apiUrl}/api/receipt/workflow`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
          body: formData,
          signal: controller.signal,
        })

        clearTimeout(timeoutId)
        if (workingHardTimerRef.current) {
          clearTimeout(workingHardTimerRef.current)
          workingHardTimerRef.current = null
        }
        console.log('响应状态:', response.status, response.statusText)

      if (response.ok) {
        const data = await response.json()
        console.log('✅ 上传成功:', data)
        setUploadResult(data)
        setUploadError(null)
        fetchReceiptList()
      } else {
        // 尝试解析错误响应
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`
        try {
          const errorData = await response.json()
          console.error('❌ 错误响应:', errorData)
          
          // 提取错误信息
          if (typeof errorData.detail === 'string') {
            errorMessage = errorData.detail
          } else if (typeof errorData.detail === 'object') {
            errorMessage = JSON.stringify(errorData.detail)
          } else if (errorData.message) {
            errorMessage = errorData.message
          }
        } catch (parseError) {
          const text = await response.text()
          console.error('原始错误响应:', text)
          errorMessage = text || errorMessage
        }
        
        setUploadError(errorMessage)
        }
      } catch (fetchError) {
        clearTimeout(timeoutId)
        if (workingHardTimerRef.current) {
          clearTimeout(workingHardTimerRef.current)
          workingHardTimerRef.current = null
        }
        throw fetchError
      }
    } catch (error) {
      console.error('❌ 上传错误:', error)
      if (workingHardTimerRef.current) {
        clearTimeout(workingHardTimerRef.current)
        workingHardTimerRef.current = null
      }
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          setUploadError('Request timed out (3 min). Check:\n1. Backend is running\n2. Network is stable\n3. Image size is not too large')
        } else if (error.message.includes('Failed to fetch')) {
          setUploadError('Cannot connect to backend. Check:\n1. Backend is running at ' + (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + '\n2. Firewall\n3. CORS')
        } else {
          setUploadError(error.message)
        }
      } else {
        setUploadError('Network error. Please retry.')
      }
    } finally {
      setUploading(false)
      setUploadWorkingHard(false)
      if (workingHardTimerRef.current) {
        clearTimeout(workingHardTimerRef.current)
        workingHardTimerRef.current = null
      }
      e.target.value = ''
    }
  }

  useEffect(() => {
    if (developerAllowed === false) {
      router.push('/dashboard')
    }
  }, [developerAllowed, router])

  if (loading || developerAllowed === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-gray-600">Loading…</p>
        </div>
      </div>
    )
  }

  if (!token || !developerAllowed) {
    return null
  }

  return (
    <>
      <main className="max-w-7xl mx-auto px-4 py-6 sm:py-8 sm:px-6 lg:px-8">
        {/* Developer welcome: email, User ID, JWT + upload & camera */}
        <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-8 flex flex-col sm:flex-row sm:flex-wrap sm:items-start sm:justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h2 className="text-lg sm:text-xl font-semibold mb-3 sm:mb-4">Welcome back</h2>
            <div className="space-y-2 text-sm">
              <p>
                <span className="text-gray-600">Email: </span>
                <span className="font-medium break-all">{userEmail}</span>
              </p>
              <p>
                <span className="text-gray-600">User ID: </span>
                <span className="font-mono text-xs break-all">{userUid}</span>
              </p>
              <details className="pt-2">
                <summary className="cursor-pointer text-blue-600 hover:text-blue-700 min-h-[44px] flex items-center sm:min-h-0">View JWT Token (for testing)</summary>
                <div className="mt-2 p-3 bg-gray-50 rounded text-xs font-mono break-all">
                  {token}
                </div>
              </details>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <input
              type="file"
              accept="image/*,.pdf"
              onChange={handleUpload}
              className="hidden"
              id="receipt-upload"
              disabled={uploading}
            />
            <label
              htmlFor="receipt-upload"
              className={`inline-flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium text-white cursor-pointer transition select-none min-h-[44px] sm:min-h-0 ${
                uploading
                  ? 'bg-green-500 cursor-wait'
                  : 'bg-green-600 hover:bg-green-700'
              }`}
            >
              {uploading ? (
                <>
                  <span className="inline-block animate-spin text-lg">⏳</span>
                  <span>Processing…</span>
                </>
              ) : (
                'Upload receipt'
              )}
            </label>
            <CameraCaptureButton
              token={token}
              disabled={uploading}
              onSuccess={fetchReceiptList}
              onError={setUploadError}
            />
          </div>
        </div>

        {uploading && uploadWorkingHard && (
          <div className="mb-4 p-4 sm:p-5 bg-blue-50 border border-blue-200 rounded-lg text-center animate-pulse">
            <p className="text-blue-900 font-medium text-base sm:text-lg mb-1">Your Smart AI Accountant is Working Hard.</p>
            <p className="text-blue-700 text-sm">Feel free to come back later — this may take 2–3 minutes.</p>
          </div>
        )}
        {/* Upload success/error toasts */}
        {uploadResult?.success === true && (
          <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg flex items-center justify-between">
            <span className="text-green-800">✅ Processed. Status: {uploadResult.status || 'passed'}</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-green-700 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}
        {uploadResult && uploadResult.success === false && uploadResult.error === 'duplicate_receipt' && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between">
            <span className="text-red-800 text-sm">这张单子已经上传过。如果有错误，请删掉现有的小票并重新拍摄上传。</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-red-700 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}
        {uploadError && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between">
            <span className="text-red-800 text-sm whitespace-pre-wrap">{uploadError}</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-red-700 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Receipt history */}
        <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-8 overflow-hidden">
          <h2 className="text-lg sm:text-xl font-semibold mb-4">My Receipts</h2>
          {receiptListLoading ? (
            <div className="py-8 text-center text-gray-500">
              <span className="inline-block animate-spin text-2xl mr-2">⏳</span>
              Loading…
            </div>
          ) : receiptList.length === 0 ? (
            <p className="py-6 text-gray-500 text-center">No receipts yet. Upload one using the button above.</p>
          ) : (
            (() => {
              const getDateKey = (r: ReceiptListItem) => {
                const d = r.receipt_date || r.uploaded_at
                if (!d) return 'Unknown'
                const date = new Date(d)
                return isNaN(date.getTime()) ? 'Unknown' : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
              }
              const formatDisplayDate = (r: ReceiptListItem) => {
                const d = r.receipt_date || r.uploaded_at
                if (!d) return r.id.slice(0, 8)
                const date = new Date(d)
                if (isNaN(date.getTime())) return r.id.slice(0, 8)
                return date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
              }
              const monthLabels: Record<string, string> = {}
              const byMonth = receiptList.reduce<Record<string, ReceiptListItem[]>>((acc, r) => {
                const key = getDateKey(r)
                if (!monthLabels[key] && key !== 'Unknown') {
                  const date = new Date(r.receipt_date || r.uploaded_at || '')
                  monthLabels[key] = date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' })
                } else if (key === 'Unknown') monthLabels[key] = 'Unknown'
                if (!acc[key]) acc[key] = []
                acc[key].push(r)
                return acc
              }, {})
              const orderedMonths = Object.keys(byMonth).sort((a, b) => (a === 'Unknown' ? 1 : b === 'Unknown' ? -1 : b.localeCompare(a)))
              return (
                <div className="space-y-6">
                  {orderedMonths.map((monthKey) => (
                    <div key={monthKey}>
                      <div className="flex items-center gap-3 mb-3">
                        <span className="text-sm font-semibold text-gray-600">{monthLabels[monthKey]}</span>
                        <div className="flex-1 h-px bg-gray-200" />
                      </div>
                      <div className="space-y-3">
                        {byMonth[monthKey].map((r) => (
                          <div
                            key={r.id}
                            className="border border-gray-200 rounded-lg overflow-hidden"
                          >
                            <button
                              type="button"
                              className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50 transition"
                              onClick={async () => {
                                if (expandedReceiptId === r.id) {
                                  setExpandedReceiptId(null)
                                  setExpandedReceiptJson(null)
                                  return
                                }
                                setExpandedReceiptId(r.id)
                                if (!token) return
                                try {
                                  const res = await fetch(`${apiUrl()}/api/receipt/${r.id}`, {
                                    headers: { Authorization: `Bearer ${token}` },
                                  })
                                  if (res.ok) {
                                    const json = await res.json()
                                    setExpandedReceiptJson(json)
                                    initEditFormFromJson(json)
                                  } else {
                                    setExpandedReceiptJson({ error: 'Failed to load' })
                                  }
                                } catch (e) {
                                  setExpandedReceiptJson({ error: String(e) })
                                }
                              }}
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-medium text-gray-900">
                                  {r.chain_name || r.store_name || 'Unknown store'}
                                </span>
                                <span className="text-xs text-gray-500">
                                  {formatDisplayDate(r)}
                                </span>
                                <span className={`text-xs px-2 py-0.5 rounded ${
                                  r.current_status === 'success' ? 'bg-green-100 text-green-800' :
                                  r.current_status === 'failed' || r.current_status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-600'
                                }`}>
                                  {r.current_status}
                                </span>
                              </div>
                              <span className="text-gray-400">{expandedReceiptId === r.id ? '▼' : '▶'}</span>
                            </button>
                            {expandedReceiptId === r.id && expandedReceiptJson && expandedReceiptJson.error && (
                              <div className="border-t border-gray-200 bg-red-50 p-4 text-sm text-red-700">
                                {expandedReceiptJson.error}
                              </div>
                            )}
                            {expandedReceiptId === r.id && expandedReceiptJson && !expandedReceiptJson.error && (
                              <div className="border-t border-gray-200 bg-gray-50 p-4">
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
                                  <div className="relative bg-white border border-gray-200 rounded-lg p-4 font-mono text-sm text-gray-800 flex flex-col min-h-0">
                                    <button
                                      type="button"
                                      className="absolute top-2 right-2 text-sm text-gray-700 bg-gray-200 hover:bg-gray-300 px-2.5 py-1 rounded border border-gray-300 min-w-26"
                                      onClick={(e) => { e.stopPropagation(); setCorrectionOpen((o) => !o) }}
                                    >
                                      {correctionOpen ? 'Hide Edits' : 'Edit Fields'}
                                    </button>
                                    {(() => {
                                      const rec = expandedReceiptJson?.data?.receipt
                                      const items = expandedReceiptJson?.data?.items || []
                                      const chainName = expandedReceiptJson?.data?.chain_name
                                      const $ = (v: any) => (v == null || v === '' ? null : String(v))
                                      const money = (v: any) => {
                                        if (v == null || v === '') return null
                                        const n = Number(v)
                                        if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
                                        return String(v)
                                      }
                                      const titleCase = (s: string) =>
                                        s ? s.replace(/\w\S*/g, (w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()) : ''
                                      if (!rec && items.length === 0) return <span>(No data)</span>
                                      const displayName = chainName || titleCase(rec?.merchant_name || '') || rec?.merchant_name || ''
                                      const rawAddress = $(rec?.merchant_address)
                                      const addressLines = rawAddress ? rawAddress.split(/\r?\n/).map((l: string) => l.trim()).filter(Boolean) : []
                                      const lastLine = addressLines[addressLines.length - 1]
                                      const isCountryOnly = lastLine && /^[A-Z]{2}$/i.test(lastLine)
                                      const address = addressLines.length
                                        ? isCountryOnly && addressLines.length >= 2
                                          ? [...addressLines.slice(0, -2), addressLines[addressLines.length - 2] + ' ' + lastLine].join('\n')
                                          : addressLines.join('\n')
                                        : ''
                                      const lineCount = 1 + addressLines.length + (rec?.merchant_phone ? 1 : 0)
                                      return (
                                        <div className="space-y-0">
                                          {/* Section1: 店名+地址+Tel 在一个 div 里，5 行 box 高 100px；分割线保留 my-2 pt-2 */}
                                          <div className="min-h-22">
                                            {(displayName || address || rec?.merchant_phone) ? (
                                              <div className="text-gray-800 whitespace-pre-line leading-5 font-mono text-sm">
                                                {displayName && <span className="font-semibold">{displayName}</span>}
                                                {address && <>{'\n'}<span className="text-gray-600">{address}</span></>}
                                                {rec?.merchant_phone && <>{'\n'}<span className="text-gray-600">Tel: {rec.merchant_phone}</span></>}
                                              </div>
                                            ) : null}
                                            {(displayName || address) && (
                                              <div className="border-t border-dashed border-gray-300 my-2 pt-2" />
                                            )}
                                          </div>
                                          {/* Section2: items table — each row min-h-7 to align with classification */}
                                          {items.length > 0 && (
                                            <>
                                              <div className="grid grid-cols-[1fr_3rem_5rem_5rem] gap-x-3 gap-y-0 text-left mb-0.5 min-h-7 items-center">
                                                <div className="text-gray-500 text-xs" />
                                                <div className="text-gray-500 text-xs text-center">Qty</div>
                                                <div className="text-gray-500 text-xs text-right">Unit $</div>
                                                <div className="text-gray-500 text-xs text-right">$ Amount</div>
                                              </div>
                                              {items.map((it: any, i: number) => {
                                                const name = it.product_name ?? it.original_product_name ?? ''
                                                const qty = it.quantity != null ? (typeof it.quantity === 'number' ? it.quantity : Number(it.quantity)) : 1
                                                const u = it.unit_price != null ? (money(it.unit_price) ?? it.unit_price) : ''
                                                const p = it.line_total != null ? (money(it.line_total) ?? it.line_total) : ''
                                                return (
                                                  <div key={i} className="grid grid-cols-[1fr_3rem_5rem_5rem] gap-x-3 gap-y-0 min-h-7 items-center">
                                                    <div className="truncate" title={name}>{name}</div>
                                                    <div className="text-center tabular-nums">{Number.isFinite(qty) ? qty : ''}</div>
                                                    <div className="text-right tabular-nums">{u}</div>
                                                    <div className="text-right tabular-nums">{p}</div>
                                                  </div>
                                                )
                                              })}
                                              <div className="border-t border-dashed border-gray-300 my-2 pt-2" />
                                            </>
                                          )}
                                          {/* Subtotal / Tax / Total 与第四栏 price 对齐 */}
                                          {rec && (
                                            <>
                                              <div className="grid grid-cols-[1fr_3rem_5rem_5rem] gap-x-3">
                                                <div>Subtotal</div>
                                                <div />
                                                <div />
                                                <div className="text-right tabular-nums">{rec.subtotal != null ? (money(rec.subtotal) ?? rec.subtotal) : ''}</div>
                                              </div>
                                              <div className="grid grid-cols-[1fr_3rem_5rem_5rem] gap-x-3">
                                                <div>Tax</div>
                                                <div />
                                                <div />
                                                <div className="text-right tabular-nums">{rec.tax != null ? (money(rec.tax) ?? rec.tax) : ''}</div>
                                              </div>
                                              <div className="grid grid-cols-[1fr_3rem_5rem_5rem] gap-x-3 font-medium">
                                                <div>Total</div>
                                                <div />
                                                <div />
                                                <div className="text-right tabular-nums">{rec.total != null ? (money(rec.total) ?? rec.total) : ''}</div>
                                              </div>
                                              <div className="border-t border-dashed border-gray-300 my-2 pt-2" />
                                              {$(rec.payment_method) && <div>Payment: {rec.payment_method}</div>}
                                              {$(rec.card_last4) && <div>Card: ****{String(rec.card_last4).replace(/\D/g, '').slice(-4) || rec.card_last4}</div>}
                                              {$(rec.purchase_date) && <div>Date: {rec.purchase_date}</div>}
                                              {(editPurchaseTime?.trim() || $(rec.purchase_time)) && (
                                                <div>Time: {formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '')}</div>
                                              )}
                                            </>
                                          )}
                                        </div>
                                      )
                                    })()}
                                  </div>
                                  <div className="relative border border-gray-200 rounded-lg overflow-hidden bg-white min-h-[200px] flex flex-col">
                                    {/* Row 1: CLASSIFICATION title + Smart categorization button */}
                                    <div className="px-3 py-2 border-b border-gray-200 bg-gray-50 flex items-center justify-between gap-2 shrink-0">
                                      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Classification</p>
                                      <button
                                        type="button"
                                        className="text-xs font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-50 px-2 py-1.5 rounded border border-blue-200"
                                        onClick={async () => {
                                          if (!expandedReceiptId || !token) return
                                          setSmartCategorizeLoading(true)
                                          setSmartCategorizeMessage(null)
                                          try {
                                            const res = await fetch(`${apiUrl()}/api/receipt/${expandedReceiptId}/smart-categorize`, {
                                              method: 'POST',
                                              headers: { Authorization: `Bearer ${token}` },
                                            })
                                            const data = await res.json().catch(() => ({}))
                                            if (res.ok) {
                                              setSmartCategorizeMessage(data.updated_count ? `Updated ${data.updated_count} item(s)` : 'No uncategorized items')
                                              await refetchReceiptDetail()
                                            } else {
                                              setSmartCategorizeMessage(data.detail || 'Failed')
                                            }
                                          } catch (e) {
                                            setSmartCategorizeMessage('Network error')
                                          } finally {
                                            setSmartCategorizeLoading(false)
                                          }
                                        }}
                                        disabled={smartCategorizeLoading}
                                      >
                                        {smartCategorizeLoading ? '…' : 'Smart categorization'}
                                      </button>
                                    </div>
                                    {/* 右边留白高度 63px（由左边/右侧其他 box 计算得出，此处先固定） */}
                                    <div aria-hidden="true" className="shrink-0" style={{ minHeight: '63px' }} />
                                    {/* "Category" row — no top margin so it sits flush under whitespace */}
                                    <div className="px-3 pt-2 min-h-7 flex items-end">
                                      <span className="text-xs text-gray-500">Category</span>
                                    </div>
                                    {/* Row 3: level I / II / III + 修改 — aligns with left "Qty Unit $ $ Amount" row */}
                                    <div className="px-3 overflow-auto">
                                      {(expandedReceiptJson?.data?.items || []).length > 0 ? (
                                        <>
                                          <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-x-2 gap-y-0 text-left mb-0.5 min-h-7 items-center text-xs text-gray-500 font-medium">
                                            <div>level I</div>
                                            <div>level II</div>
                                            <div>level III</div>
                                            <div className="w-14" />
                                          </div>
                                          {(expandedReceiptJson?.data?.items || []).map((it: any, i: number) => {
                                            const path = (it.category_path ?? '').trim()
                                            const parts = path ? path.split(/\s*[\/>]\s*/).map((s: string) => s.trim()).filter(Boolean) : []
                                            const [c1, c2, c3] = [parts[0] ?? '—', parts[1] ?? '—', parts[2] ?? '—']
                                            const itemId = it.id
                                            const isEditing = editingItemId === itemId
                                            const L1List = categoriesList.filter((c) => c.parent_id == null)
                                            const L2List = categoriesList.filter((c) => c.parent_id === editCatL1)
                                            const L3List = categoriesList.filter((c) => c.parent_id === editCatL2)
                                            const startEdit = () => {
                                              setEditingItemId(itemId)
                                              const catId = it.category_id
                                              if (catId && categoriesList.length) {
                                                const byId = Object.fromEntries(categoriesList.map((c) => [c.id, c]))
                                                const leaf = byId[catId]
                                                if (leaf) {
                                                  const p2 = leaf.parent_id ? byId[leaf.parent_id] : null
                                                  const p1 = p2?.parent_id ? byId[p2.parent_id] : null
                                                  setEditCatL1(p1?.id ?? '')
                                                  setEditCatL2(p2?.id ?? '')
                                                  setEditCatL3(leaf.id)
                                                  return
                                                }
                                              }
                                              setEditCatL1('')
                                              setEditCatL2('')
                                              setEditCatL3('')
                                            }
                                            const cancelEdit = () => {
                                              setEditingItemId(null)
                                              setCategoryUpdateMessage(null)
                                            }
                                            const confirmEdit = async () => {
                                              if (!expandedReceiptId || !token) return
                                              setCategoryUpdateMessage(null)
                                              const toSend = editCatL3 || editCatL2 || editCatL1 || null
                                              try {
                                                const res = await fetch(
                                                  `${apiUrl()}/api/receipt/${expandedReceiptId}/item/${itemId}/category`,
                                                  {
                                                    method: 'PATCH',
                                                    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                    body: JSON.stringify({ category_id: toSend }),
                                                  }
                                                )
                                                if (res.ok) {
                                                  setCategoryUpdateMessage('已保存')
                                                  await refetchReceiptDetail()
                                                  setEditingItemId(null)
                                                } else {
                                                  const err = await res.json().catch(() => ({}))
                                                  setCategoryUpdateMessage(err?.detail ?? '保存失败')
                                                }
                                              } catch (e) {
                                                setCategoryUpdateMessage('网络错误')
                                              }
                                            }
                                            return (
                                              <div key={itemId ?? i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-x-2 gap-y-0 min-h-7 items-center text-sm">
                                                {isEditing ? (
                                                  <>
                                                    <select
                                                      className="border rounded px-1 py-0.5 text-xs w-full max-w-[120px]"
                                                      value={editCatL1}
                                                      onChange={(e) => {
                                                        setEditCatL1(e.target.value)
                                                        setEditCatL2('')
                                                        setEditCatL3('')
                                                      }}
                                                    >
                                                      <option value="">—</option>
                                                      {L1List.map((c) => (
                                                        <option key={c.id} value={c.id}>{c.name}</option>
                                                      ))}
                                                    </select>
                                                    <select
                                                      className="border rounded px-1 py-0.5 text-xs w-full max-w-[120px]"
                                                      value={editCatL2}
                                                      onChange={(e) => {
                                                        setEditCatL2(e.target.value)
                                                        setEditCatL3('')
                                                      }}
                                                    >
                                                      <option value="">—</option>
                                                      {L2List.map((c) => (
                                                        <option key={c.id} value={c.id}>{c.name}</option>
                                                      ))}
                                                    </select>
                                                    <select
                                                      className="border rounded px-1 py-0.5 text-xs w-full max-w-[120px]"
                                                      value={editCatL3}
                                                      onChange={(e) => setEditCatL3(e.target.value)}
                                                    >
                                                      <option value="">—</option>
                                                      {L3List.map((c) => (
                                                        <option key={c.id} value={c.id}>{c.name}</option>
                                                      ))}
                                                    </select>
                                                    <div className="flex items-center gap-0.5 w-14">
                                                      <button type="button" className="p-1 bg-green-100 text-green-800 rounded hover:bg-green-200" onClick={confirmEdit} title="确认">✓</button>
                                                      <button type="button" className="p-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300" onClick={cancelEdit} title="取消">✕</button>
                                                    </div>
                                                  </>
                                                ) : (
                                                  <>
                                                    <div className="truncate text-gray-800" title={c1}>{c1}</div>
                                                    <div className="truncate text-gray-800" title={c2}>{c2}</div>
                                                    <div className="truncate text-gray-800" title={c3}>{c3}</div>
                                                    <button type="button" className="p-1 text-gray-600 hover:text-gray-900 hover:bg-gray-200 rounded" onClick={startEdit} title="修改">✏️</button>
                                                  </>
                                                )}
                                              </div>
                                            )
                                          })}
                                          {(categoryUpdateMessage || smartCategorizeMessage) && (
                                            <div className={`mt-1 text-xs ${(categoryUpdateMessage || smartCategorizeMessage) === '已保存' || (smartCategorizeMessage && smartCategorizeMessage.startsWith('Updated')) ? 'text-green-600' : 'text-red-600'}`}>
                                              {categoryUpdateMessage || smartCategorizeMessage}
                                            </div>
                                          )}
                                        </>
                                      ) : (
                                        <p className="text-gray-400 text-sm">No items</p>
                                      )}
                                    </div>
                                    {/* Edit panel: overlays only this CLASSIFICATION column; scrollable inside */}
                                    <div
                                      className={`absolute inset-0 z-10 flex flex-col bg-white border border-gray-200 rounded-lg shadow-lg transition-transform duration-200 ease-out ${correctionOpen ? 'translate-x-0' : 'translate-x-full'}`}
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 bg-gray-50 shrink-0">
                                        <span className="text-sm font-medium text-gray-700">Edit receipt</span>
                                        <button
                                          type="button"
                                          className="p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-200 rounded"
                                          onClick={(e) => { e.stopPropagation(); setCorrectionOpen(false) }}
                                          title="Close"
                                        >
                                          ▶
                                        </button>
                                      </div>
                                      <div className="p-4 space-y-4 overflow-y-auto flex-1 min-h-0">
                                        {correctMessage && (
                                          <div className={`p-2 rounded text-sm ${correctMessage.startsWith('Saved') ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`}>
                                            {correctMessage}
                                          </div>
                                        )}
                                        <div className="grid grid-cols-1 gap-2">
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">Store name</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editStoreName} onChange={(e) => setEditStoreName(e.target.value)} placeholder="Store name" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">Address line 1</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressLine1} onChange={(e) => setEditAddressLine1(e.target.value)} placeholder="Street address" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">Address line 2</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressLine2} onChange={(e) => setEditAddressLine2(e.target.value)} placeholder="Unit / Suite" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">City, State ZIP</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressCityStateZip} onChange={(e) => setEditAddressCityStateZip(e.target.value)} placeholder="Lynnwood, WA 98036" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">Country</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressCountry} onChange={(e) => setEditAddressCountry(e.target.value)} placeholder="US" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">Purchase date</span>
                                            <input type="date" className="border rounded px-2 py-1 text-sm" value={editReceiptDate} onChange={(e) => setEditReceiptDate(e.target.value)} />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-gray-500">Purchase time (optional, 时:分)</span>
                                            <input type="time" className="border rounded px-2 py-1 text-sm" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} />
                                          </label>
                                          <div className="grid grid-cols-3 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-gray-500">Subtotal</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editSubtotal} onChange={(e) => setEditSubtotal(e.target.value)} placeholder="0.00" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-gray-500">Tax</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editTax} onChange={(e) => setEditTax(e.target.value)} placeholder="0.00" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-gray-500">Total *</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editTotal} onChange={(e) => setEditTotal(e.target.value)} placeholder="0.00" />
                                            </label>
                                          </div>
                                          <div className="grid grid-cols-2 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-gray-500">Currency</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editCurrency} onChange={(e) => setEditCurrency(e.target.value)} placeholder="USD" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-gray-500">Payment method</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editPaymentMethod} onChange={(e) => setEditPaymentMethod(e.target.value)} placeholder="AMEX Credit" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-gray-500">Card last 4</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editPaymentLast4} onChange={(e) => setEditPaymentLast4(e.target.value)} placeholder="5030" maxLength={4} />
                                            </label>
                                          </div>
                                        </div>
                                        <div>
                                          <p className="text-xs text-gray-600 mb-2">Item lines</p>
                                          <div className="space-y-2 max-h-48 overflow-auto">
                                            {editItems.map((row, idx) => (
                                              <div key={idx} className="flex flex-wrap gap-2 items-center text-sm border-b border-gray-100 pb-2">
                                                <input className="min-w-[120px] border rounded px-1.5 py-0.5" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} />
                                                <input className="w-14 border rounded px-1.5 py-0.5" placeholder="Qty" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} />
                                                <input className="w-14 border rounded px-1.5 py-0.5" placeholder="Unit price" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} />
                                                <input className="w-16 border rounded px-1.5 py-0.5" placeholder="Line total" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} />
                                              </div>
                                            ))}
                                          </div>
                                          <button type="button" className="mt-2 text-sm text-blue-600 hover:underline" onClick={() => setEditItems((prev) => [...prev, { product_name: '', quantity: '', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])}>
                                            + Add row
                                          </button>
                                        </div>
                                        <button
                                          type="button"
                                          className="w-full px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm"
                                          disabled={correctSubmitting || !editTotal.trim()}
                                          onClick={async (e) => {
                                            e.stopPropagation()
                                            if (!token || !r.id) return
                                            setCorrectSubmitting(true)
                                            setCorrectMessage(null)
                                            try {
                                              const totalNum = editTotal.trim() ? parseFloat(editTotal) : NaN
                                              if (isNaN(totalNum)) { setCorrectMessage('Please enter Total'); return }
                                              const summary = {
                                                store_name: editStoreName.trim() || undefined,
                                                store_address: [editAddressLine1, editAddressLine2, editAddressCityStateZip, editAddressCountry].filter(Boolean).join('\n').trim() || undefined,
                                                receipt_date: editReceiptDate.trim() || undefined,
                                                purchase_time: formatTimeToHHmm(editPurchaseTime).trim() || undefined,
                                                subtotal: editSubtotal.trim() ? parseFloat(editSubtotal) : undefined,
                                                tax: editTax.trim() ? parseFloat(editTax) : undefined,
                                                total: totalNum,
                                                currency: editCurrency.trim() || 'USD',
                                                payment_method: editPaymentMethod.trim() || undefined,
                                                payment_last4: editPaymentLast4.trim() || undefined,
                                              }
                                              const itemsPayload = editItems
                                                .filter((it) => (it.product_name || '').trim())
                                                .map((it) => ({
                                                  id: it.id || undefined,
                                                  product_name: it.product_name.trim(),
                                                  quantity: it.quantity.trim() ? parseFloat(it.quantity) : undefined,
                                                  unit: it.unit.trim() || undefined,
                                                  unit_price: it.unit_price.trim() ? parseFloat(it.unit_price) : undefined,
                                                  line_total: it.line_total.trim() ? parseFloat(it.line_total) : undefined,
                                                  on_sale: it.on_sale,
                                                  original_price: it.original_price.trim() ? parseFloat(it.original_price) : undefined,
                                                  discount_amount: it.discount_amount.trim() ? parseFloat(it.discount_amount) : undefined,
                                                }))
                                              const res = await fetch(`${apiUrl()}/api/receipt/${r.id}/correct`, {
                                                method: 'POST',
                                                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                body: JSON.stringify({ summary, items: itemsPayload }),
                                              })
                                              const data = res.ok ? await res.json().catch(() => ({})) : await res.json().catch(() => ({}))
                                              if (!res.ok) throw new Error(data.detail || data.detail?.detail || 'Submit failed')
                                              setCorrectMessage('Saved. Receipt updated.')
                                              fetchReceiptList()
                                              const detailRes = await fetch(`${apiUrl()}/api/receipt/${r.id}`, {
                                                headers: { Authorization: `Bearer ${token}` },
                                              })
                                              if (detailRes.ok) {
                                                const detailJson = await detailRes.json()
                                                setExpandedReceiptJson(detailJson)
                                              }
                                            } catch (err) {
                                              setCorrectMessage(err instanceof Error ? err.message : 'Submit failed')
                                            } finally {
                                              setCorrectSubmitting(false)
                                            }
                                          }}
                                        >
                                          {correctSubmitting ? 'Saving…' : 'Save correction'}
                                        </button>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                                <div className="mt-4 flex flex-wrap items-center gap-2">
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); setShowRawJson((v) => !v) }}
                                    className="text-sm text-gray-600 hover:text-gray-900 underline"
                                  >
                                    {showRawJson ? 'Hide' : 'Show'} raw JSON
                                  </button>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      navigator.clipboard.writeText(JSON.stringify(expandedReceiptJson, null, 2))
                                      alert('Copied to clipboard')
                                    }}
                                    className="text-sm text-gray-600 hover:text-gray-900 underline"
                                  >
                                    Copy
                                  </button>
                                  <button
                                    type="button"
                                    onClick={async (e) => {
                                      e.stopPropagation()
                                      if (!token || !r.id) return
                                      const msg = '删除后无法恢复，确定要删除这张小票吗？\n\nThis will permanently remove this receipt. This cannot be undone.'
                                      if (!confirm(msg)) return
                                      try {
                                        const res = await fetch(`${apiUrl()}/api/receipt/${r.id}`, {
                                          method: 'DELETE',
                                          headers: { Authorization: `Bearer ${token}` },
                                        })
                                        if (!res.ok) {
                                          const data = await res.json().catch(() => ({}))
                                          throw new Error(data.detail || 'Delete failed')
                                        }
                                        if (expandedReceiptId === r.id) {
                                          setExpandedReceiptId(null)
                                          setExpandedReceiptJson(null)
                                        }
                                        fetchReceiptList()
                                      } catch (err) {
                                        alert(err instanceof Error ? err.message : 'Delete failed')
                                      }
                                    }}
                                    className="text-sm text-red-600 hover:text-red-800 hover:underline"
                                  >
                                    Delete this receipt
                                  </button>
                                </div>
                                {showRawJson && (
                                  <div className="mt-2 rounded overflow-hidden border border-gray-200">
                                    <div className="bg-gray-800 px-3 py-1.5 text-xs text-gray-300">Processing result JSON</div>
                                    <div className="bg-gray-900 p-3 max-h-64 overflow-auto">
                                      <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap">
                                        {JSON.stringify(expandedReceiptJson, null, 2)}
                                      </pre>
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )
            })()
          )}
        </div>

        {/* Data Analysis */}
        <DataAnalysisSection token={token} />

        {/* API Test Section — developer only */}
        <div className="mt-8 bg-blue-50 rounded-xl p-6">
          <h3 className="text-lg font-semibold text-blue-900 mb-3">
            🧪 API test info
          </h3>
          <div className="space-y-2 text-sm text-blue-800">
            <p>
              <span className="font-semibold">Backend API: </span>
              {apiUrl()}
            </p>
            <p>
              <span className="font-semibold">Auth: </span>
              <span className="text-green-600 font-semibold">✓ Authenticated</span>
            </p>
            <p>
              <a href={`${apiUrl()}/docs`} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline font-medium">
                → Open API docs (/doc)
              </a>
            </p>
            <p className="pt-2 text-xs text-blue-600">
              Open browser console (F12) for API response details
            </p>
          </div>
        </div>
      </main>
    </>
  )
}
