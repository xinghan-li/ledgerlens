'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { getFirebaseAuth } from '@/lib/firebase'
import { formatTimeToHHmm, toTitleCaseStore } from '@/lib/utils'
import { onAuthStateChanged } from 'firebase/auth'
import DataAnalysisSection from '../DataAnalysisSection'
import { CameraCaptureButton } from '../camera'
import { useApiUrl } from '@/lib/api-url-context'

const MAX_PROCESSING = 5

async function sha256Hex(blob: Blob): Promise<string> {
  const buf = await blob.arrayBuffer()
  const hash = await crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

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
  const apiBaseUrl = useApiUrl()
  const [token, setToken] = useState<string | null>(null)
  const [userEmail, setUserEmail] = useState<string | null>(null)
  const [userUid, setUserUid] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [developerAllowed, setDeveloperAllowed] = useState<boolean | null>(null)
  const [processingCount, setProcessingCount] = useState(0)
  const [uploadWorkingHard, setUploadWorkingHard] = useState(false)
  const [uploadResult, setUploadResult] = useState<any>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const workingHardTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inFlightKeysRef = useRef<Set<string>>(new Set())
  const uploadControllersRef = useRef<Map<string, AbortController>>(new Map())
  const processingCountRef = useRef(0)
  const cancelledKeysRef = useRef<Set<string>>(new Set())
  const cameraUploadTimersRef = useRef<ReturnType<typeof setTimeout>[]>([])
  const [receiptList, setReceiptList] = useState<ReceiptListItem[]>([])
  const [receiptListLoading, setReceiptListLoading] = useState(false)
  const [expandedReceiptIds, setExpandedReceiptIds] = useState<Set<string>>(new Set())
  const [expandedReceiptData, setExpandedReceiptData] = useState<Record<string, any>>({})
  const [showRawJson, setShowRawJson] = useState(false)
  const [correctionOpenReceiptId, setCorrectionOpenReceiptId] = useState<string | null>(null)
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
  const [editMerchantPhone, setEditMerchantPhone] = useState('')
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
  const [userClass, setUserClass] = useState<string | null>(null)
  const [processingRunsModalReceiptId, setProcessingRunsModalReceiptId] = useState<string | null>(null)
  const [processingRunsData, setProcessingRunsData] = useState<{ track: string; track_method: string | null; runs: Array<Record<string, unknown>>; workflow_steps: Array<Record<string, unknown>>; pipeline_version?: string | null } | null>(null)
  const [processingRunsLoading, setProcessingRunsLoading] = useState(false)
  const [mobileReceiptViewMode, setMobileReceiptViewMode] = useState<'receipt' | 'classification'>('receipt')
  const router = useRouter()

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

  /** 匹配 "City, ST ZIP" 或 "City, ST ZIP-4" 格式，避免把城市/州/邮编误填到 Address line 2 */
  function looksLikeCityStateZip(s: string): boolean {
    return /^[A-Za-z\s\-'.]+,\s*[A-Z]{2}\s+\d{5}(-\d{4})?$/i.test((s || '').trim())
  }

  /** 根据邮编推断国家：加拿大 N0N 0N0 格式 / 美国 5 位或 9 位邮编 */
  function inferCountryFromPostal(cityStateZip: string): string {
    if (!(cityStateZip || '').trim()) return ''
    const s = cityStateZip.trim()
    if (/\b[A-Za-z][0-9][A-Za-z]\s*[0-9][A-Za-z][0-9]\b/i.test(s)) return 'Canada'
    if (/\b\d{5}(-\d{4})?\b/.test(s)) return 'US'
    return ''
  }

  /** 展示用地址：永远为 "address2 - address1"（门牌/单元 - 街道），再 cityStateZip，再 country；无 country 时按邮编推断 */
  function formatAddressForDisplay(addr: string): string {
    const fields = parseAddressToFields(addr || '')
    let country = (fields.country || '').trim()
    if (!country && fields.cityStateZip) country = inferCountryFromPostal(fields.cityStateZip)
    const parts: string[] = []
    if (fields.line2 && fields.line1) parts.push(`${fields.line2} - ${fields.line1}`)
    else if (fields.line1) parts.push(fields.line1)
    else if (fields.line2) parts.push(fields.line2)
    if (fields.cityStateZip) parts.push(fields.cityStateZip)
    if (country) parts.push(country)
    return parts.join('\n')
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
      const possibleLine2 = lines.length >= 3 ? lines[1] : ''
      const line2 = lines.length >= 3 && !looksLikeCityStateZip(possibleLine2) ? possibleLine2 : ''
      return {
        line1: lines[0],
        line2,
        cityStateZip,
        country: last,
      }
    }
    // 两行时：若第二行是 "City, ST ZIP" 格式，应填到 cityStateZip，不要填到 line2
    if (lines.length === 2 && looksLikeCityStateZip(lines[1])) {
      return {
        line1: lines[0],
        line2: '',
        cityStateZip: lines[1],
        country: '',
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
    const rawStore = data.chain_name ?? receipt.merchant_name ?? ''
    setEditStoreName(rawStore ? toTitleCaseStore(rawStore) : '')
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
    setEditMerchantPhone(receipt.merchant_phone ?? '')
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
    setShowRawJson(false)
    setCorrectMessage(null)
  }

  const fetchReceiptList = useCallback(async () => {
    if (!token) return
    setReceiptListLoading(true)
    try {
      const res = await fetch(`${apiBaseUrl}/api/receipt/list?limit=50&offset=0`, {
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
    processingCountRef.current = processingCount
  }, [processingCount])

  const clearCameraUploadTimers = useCallback(() => {
    cameraUploadTimersRef.current.forEach((id) => clearTimeout(id))
    cameraUploadTimersRef.current = []
  }, [])

  const addToQueue = useCallback((key: string): boolean => {
    if (processingCountRef.current >= MAX_PROCESSING) return false
    if (inFlightKeysRef.current.has(key)) return false
    inFlightKeysRef.current.add(key)
    setProcessingCount((prev) => {
      const next = prev + 1
      if (next === 1)
        workingHardTimerRef.current = setTimeout(() => setUploadWorkingHard(true), 30000)
      return next
    })
    return true
  }, [])

  const removeFromQueue = useCallback((key: string) => {
    inFlightKeysRef.current.delete(key)
    uploadControllersRef.current.delete(key)
    cancelledKeysRef.current.delete(key)
    setProcessingCount((prev) => {
      const next = prev - 1
      if (next <= 0) {
        if (workingHardTimerRef.current) {
          clearTimeout(workingHardTimerRef.current)
          workingHardTimerRef.current = null
        }
        setUploadWorkingHard(false)
      }
      return Math.max(0, next)
    })
  }, [])

  const checkAndStartUpload = useCallback(
    async (blob: Blob): Promise<{ allowed: boolean; key?: string }> => {
      if (processingCountRef.current >= MAX_PROCESSING)
        return { allowed: false }
      const key = await sha256Hex(blob)
      if (!addToQueue(key)) return { allowed: false }
      return { allowed: true, key }
    },
    [addToQueue]
  )

  const handleCameraUploadSuccess = useCallback(() => {
    clearCameraUploadTimers()
    fetchReceiptList()
  }, [clearCameraUploadTimers, fetchReceiptList])

  const handleCameraUploadError = useCallback((message: string) => {
    clearCameraUploadTimers()
    setUploadError(message)
  }, [clearCameraUploadTimers])

  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetch(`${apiBaseUrl}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (cancelled) return
        setUserClass(data?.user_class ?? null)
        const uc = data?.user_class
        setDeveloperAllowed(uc === 9 || uc === 'super_admin')
      })
      .catch(() => {
        if (!cancelled) setDeveloperAllowed(false)
      })
    return () => { cancelled = true }
  }, [token])

  const fetchCategories = useCallback(async () => {
    if (!token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/categories`, { headers: { Authorization: `Bearer ${token}` } })
      if (res.ok) {
        const json = await res.json()
        setCategoriesList(json?.data ?? [])
      }
    } catch (_) {}
  }, [token])

  useEffect(() => {
    fetchCategories()
  }, [fetchCategories])

  const refetchReceiptDetail = useCallback(async (receiptId: string) => {
    if (!receiptId || !token) return
    try {
      const res = await fetch(`${apiBaseUrl}/api/receipt/${receiptId}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const json = await res.json()
        setExpandedReceiptData((prev) => ({ ...prev, [receiptId]: json }))
      }
    } catch (_) {}
  }, [token])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !token) {
      e.target.value = ''
      return
    }
    if (processingCountRef.current >= MAX_PROCESSING) {
      setUploadError(`Up to ${MAX_PROCESSING} receipts can be processing at once. Please wait.`)
      e.target.value = ''
      return
    }
    let key: string
    try {
      key = await sha256Hex(file)
    } catch {
      setUploadError('Could not read file. Please try again.')
      e.target.value = ''
      return
    }
    if (!addToQueue(key)) {
      setUploadError(inFlightKeysRef.current.has(key) ? 'This image is already being uploaded.' : `Up to ${MAX_PROCESSING} receipts can be processing at once. Please wait.`)
      e.target.value = ''
      return
    }
    const formData = new FormData()
    formData.append('file', file)
    const controller = new AbortController()
    uploadControllersRef.current.set(key, controller)
    const timeoutId = setTimeout(() => controller.abort(), 180000)
    try {
      const response = await fetch(`${apiBaseUrl}/api/receipt/workflow-vision`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
        signal: controller.signal,
      })
      clearTimeout(timeoutId)
      if (response.ok) {
        const data = await response.json()
        setUploadResult(data)
        setUploadError(null)
        fetchReceiptList()
      } else {
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`
        try {
          const errorData = await response.json()
          if (typeof errorData.detail === 'string') errorMessage = errorData.detail
          else if (typeof errorData.detail === 'object') errorMessage = JSON.stringify(errorData.detail)
          else if (errorData.message) errorMessage = errorData.message
        } catch {
          const text = await response.text()
          if (text) errorMessage = text
        }
        setUploadError(errorMessage)
      }
    } catch (error) {
      clearTimeout(timeoutId)
      if (!(error instanceof Error && error.name === 'AbortError' && cancelledKeysRef.current.has(key))) {
        if (error instanceof Error) {
          if (error.name === 'AbortError') {
            setUploadError('Request timed out (3 min). Check:\n1. Backend is running\n2. Network is stable\n3. Image size is not too large')
          } else if (error.message.includes('Failed to fetch')) {
            setUploadError('Cannot connect to backend. Check:\n1. Backend is running at ' + apiBaseUrl + '\n2. Firewall\n3. CORS')
          } else {
            setUploadError(error.message)
          }
        } else {
          setUploadError('Network error. Please retry.')
        }
      }
    } finally {
      removeFromQueue(key)
      e.target.value = ''
    }
  }

  const handleCancelAllUploads = useCallback(() => {
    const keys = Array.from(uploadControllersRef.current.keys())
    keys.forEach((k) => cancelledKeysRef.current.add(k))
    uploadControllersRef.current.forEach((c) => c.abort())
    uploadControllersRef.current.clear()
    inFlightKeysRef.current.clear()
    if (workingHardTimerRef.current) {
      clearTimeout(workingHardTimerRef.current)
      workingHardTimerRef.current = null
    }
    setUploadWorkingHard(false)
    setProcessingCount(0)
  }, [])

  useEffect(() => {
    if (developerAllowed === false) {
      router.push('/dashboard')
    }
  }, [developerAllowed, router])

  if (loading || developerAllowed === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-ivory">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-theme-gray-666">Loading…</p>
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
                <span className="text-theme-gray-666">Email: </span>
                <span className="font-medium break-all">{userEmail}</span>
              </p>
              <p>
                <span className="text-theme-gray-666">User ID: </span>
                <span className="font-mono text-xs break-all">{userUid}</span>
              </p>
              <details className="pt-2">
                <summary className="cursor-pointer text-theme-blue hover:opacity-90 min-h-[44px] flex items-center sm:min-h-0">View JWT Token (for testing)</summary>
                <div className="mt-2 p-3 bg-theme-ivory rounded text-xs font-mono break-all">
                  {token}
                </div>
              </details>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 items-stretch w-full sm:w-auto">
            <div className="min-w-0">
              <input
                type="file"
                accept="image/*,.pdf"
                onChange={handleUpload}
                className="hidden"
                id="receipt-upload"
                disabled={processingCount >= MAX_PROCESSING}
              />
              <label
                htmlFor="receipt-upload"
                className={`flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium text-white bg-green-600 hover:bg-green-700 transition select-none min-h-[44px] sm:min-h-0 ${processingCount >= MAX_PROCESSING ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}
              >
                <span aria-hidden>🧾</span>
                <span>Upload Receipt</span>
              </label>
            </div>
            <CameraCaptureButton
              token={token}
              disabled={processingCount >= MAX_PROCESSING}
              showAsProcessing={false}
              onCheckQueue={checkAndStartUpload}
              onRemoveFromQueue={removeFromQueue}
              onSuccess={handleCameraUploadSuccess}
              onError={handleCameraUploadError}
            />
          </div>
        </div>

        {processingCount > 0 && (
          <div className="mb-4 p-4 sm:p-5 bg-theme-blue/10 border border-theme-blue/30 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 animate-processing-pulse">
            <div className="flex items-center gap-2 sm:gap-3">
              <span className="inline-block text-xl sm:text-2xl animate-sandglass-tilt select-none" aria-hidden>
                ⏳
              </span>
              <div>
                <p className="text-theme-blue font-medium text-base sm:text-lg mb-0.5">
                  {processingCount} receipt{processingCount !== 1 ? 's' : ''} still processing.
                </p>
                <p className="text-theme-blue text-sm">
                  You can upload more (up to {MAX_PROCESSING} at a time).
                  {uploadWorkingHard && ' This may take a minute.'}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleCancelAllUploads}
              className="px-3 py-1.5 rounded bg-theme-red/90 hover:bg-theme-red text-white text-sm font-medium shrink-0"
              aria-label="Cancel all uploads"
            >
              Cancel all
            </button>
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
          <div className="mb-4 p-4 bg-theme-red/10 border border-theme-red/30 rounded-lg flex items-center justify-between">
            <span className="text-theme-red text-sm">This receipt was already uploaded. If something is wrong, delete the existing receipt and upload a new photo.</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-theme-red hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}
        {uploadError && (
          <div className="mb-4 p-4 bg-theme-red/10 border border-theme-red/30 rounded-lg flex items-center justify-between">
            <span className="text-theme-red text-sm whitespace-pre-wrap">{uploadError}</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-theme-red hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Receipt history — 与 dashboard 一致 */}
        <div id="receipt-history-section" className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-8 overflow-hidden scroll-mt-4">
          <h2 className="font-heading text-lg sm:text-xl font-semibold mb-4 text-theme-dark">My Receipts</h2>
          {receiptListLoading ? (
            <div className="py-8 text-center text-theme-mid">
              <span className="inline-block animate-spin text-2xl mr-2">⏳</span>
              Loading…
            </div>
          ) : receiptList.length === 0 ? (
            <p className="py-6 text-theme-mid text-center">No receipts yet. Upload one using the button above.</p>
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
                return date.toLocaleDateString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit' })
              }
              const monthLabels: Record<string, string> = {}
              const byMonth = receiptList.reduce<Record<string, ReceiptListItem[]>>((acc, r) => {
                const key = getDateKey(r)
                if (!monthLabels[key] && key !== 'Unknown') {
                  const date = new Date(r.receipt_date || r.uploaded_at || '')
                  monthLabels[key] = date.toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
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
                        <span className="text-sm font-semibold text-theme-dark/90">{monthLabels[monthKey]}</span>
                        <div className="flex-1 h-px bg-theme-light-gray" />
                      </div>
                      <div className="space-y-3">
                        {byMonth[monthKey].map((r) => (
                          <div
                            key={r.id}
                            className="border border-theme-ivory-dark rounded-lg overflow-hidden"
                          >
                            <button
                              type="button"
                              className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-theme-ivory transition"
                              onClick={async () => {
                                if (expandedReceiptIds.has(r.id)) {
                                  setExpandedReceiptIds((prev) => { const next = new Set(prev); next.delete(r.id); return next })
                                  setExpandedReceiptData((prev) => { const next = { ...prev }; delete next[r.id]; return next })
                                  if (correctionOpenReceiptId === r.id) setCorrectionOpenReceiptId(null)
                                  return
                                }
                                setExpandedReceiptIds((prev) => new Set(prev).add(r.id))
                                if (!token) return
                                try {
                                  const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}`, {
                                    headers: { Authorization: `Bearer ${token}` },
                                  })
                                  if (res.ok) {
                                    const json = await res.json()
                                    setExpandedReceiptData((prev) => ({ ...prev, [r.id]: json }))
                                  } else {
                                    setExpandedReceiptData((prev) => ({ ...prev, [r.id]: { error: 'Failed to load' } }))
                                  }
                                } catch (e) {
                                  setExpandedReceiptData((prev) => ({ ...prev, [r.id]: { error: String(e) } }))
                                }
                              }}
                            >
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-medium text-theme-dark-404">
                                  {(() => { const raw = (r.chain_name || r.store_name || '').trim(); return raw ? toTitleCaseStore(raw) : 'Unknown store'; })()}
                                </span>
                                <span className="text-xs text-theme-gray-666">
                                  {formatDisplayDate(r)}
                                </span>
                                <span className={`text-xs px-2 py-0.5 rounded ${
                                  r.current_status === 'success' ? 'bg-green-100 text-green-800' :
                                  r.current_status === 'failed' || r.current_status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-theme-cream-f0 text-theme-gray-666'
                                }`}>
                                  {r.current_status}
                                </span>
                              </div>
                              <span className="text-theme-gray-919">{expandedReceiptIds.has(r.id) ? '▼' : '▶'}</span>
                            </button>
                            {expandedReceiptIds.has(r.id) && expandedReceiptData[r.id] && expandedReceiptData[r.id].error && (
                              <div className="border-t border-theme-ivory-dark bg-theme-red/10 p-4 text-sm text-theme-red">
                                {String(expandedReceiptData[r.id].error)}
                              </div>
                            )}
                            {expandedReceiptIds.has(r.id) && expandedReceiptData[r.id] && !expandedReceiptData[r.id].error && (
                              <div className="relative">
                                {(() => {
                                  const json = expandedReceiptData[r.id]
                                  const rec = json?.data?.receipt
                                  const items = json?.data?.items || []
                                  const chainName = json?.data?.chain_name
                                  const $ = (v: any) => (v == null || v === '' ? null : String(v))
                                  const money = (v: any) => {
                                    if (v == null || v === '') return null
                                    const n = Number(v)
                                    if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
                                    return String(v)
                                  }
                                  const rawName = rec?.merchant_name ?? ''
                                  const displayName = chainName || (rawName ? toTitleCaseStore(rawName) : '') || rawName || ''
                                  const rawAddress = $(rec?.merchant_address)
                                  const address = formatAddressForDisplay(rawAddress || '')
                                  return (
                                    <>
                                    {/* 手机端：无灰色层，外层之后直接白底 */}
                                    <div className="block lg:hidden p-4">
                                      <div className="bg-white rounded-lg text-sm text-theme-dark-404 p-4 space-y-4" style={{ fontFamily: "'Space Mono', 'Courier New', monospace" }}>
                                      <div className="flex items-start gap-2">
                                        <div className="flex-1 min-w-0 text-theme-gray-666 text-sm whitespace-pre-line leading-5">
                                          {address && <span>{address}</span>}{(address && rec?.merchant_phone) && '\n'}{rec?.merchant_phone && <span>Tel: {rec.merchant_phone}</span>}
                                          {!address && !rec?.merchant_phone && <span className="text-theme-gray-919">No address or phone</span>}
                                        </div>
                                        <button type="button" className="shrink-0 p-1.5 text-theme-gray-666 hover:bg-theme-ivory-dark rounded" onClick={(e) => { e.stopPropagation(); if (correctionOpenReceiptId === r.id) setCorrectionOpenReceiptId(null); else { setCorrectionOpenReceiptId(r.id); initEditFormFromJson(expandedReceiptData[r.id]) } }} aria-label={mobileReceiptViewMode === 'classification' ? 'Edit I/II/III category' : 'Edit fields'} title={mobileReceiptViewMode === 'classification' ? 'Edit category (I/II/III)' : 'Edit receipt fields'}>✏️</button>
                                      </div>
                                      <div className="flex flex-col gap-1">
                                        <div className="flex rounded-lg border border-theme-cloud p-0.5 bg-theme-cream-f0">
                                          <button type="button" className={`flex-1 py-1.5 text-sm font-medium rounded-md transition ${mobileReceiptViewMode === 'receipt' ? 'bg-white shadow text-theme-dark-404' : 'text-theme-gray-666'}`} onClick={() => setMobileReceiptViewMode('receipt')}>Receipt</button>
                                          <button type="button" className={`flex-1 py-1.5 text-sm font-medium rounded-md transition ${mobileReceiptViewMode === 'classification' ? 'bg-white shadow text-theme-dark-404' : 'text-theme-gray-666'}`} onClick={() => setMobileReceiptViewMode('classification')}>Classification</button>
                                        </div>
                                      </div>
                                      <div className="space-y-2">
                                        {items.length === 0 && <p className="text-theme-gray-919 text-sm">No items</p>}
                                        {items.map((it: any, i: number) => {
                                          const name = it.product_name ?? it.original_product_name ?? ''
                                          const qty = it.quantity != null ? (typeof it.quantity === 'number' ? it.quantity : Number(it.quantity)) : 1
                                          const u = it.unit_price != null ? (money(it.unit_price) ?? it.unit_price) : ''
                                          const unit = (it.unit ?? '').trim() || 'each'
                                          const p = it.line_total != null ? (money(it.line_total) ?? it.line_total) : ''
                                          const path = (it.category_path ?? '').trim()
                                          const parts = path ? path.split(/\s*[\/>]\s*/).map((s: string) => s.trim()).filter(Boolean) : []
                                          const catL1L2 = parts.length >= 2 ? parts.slice(0, 2).join(' / ') : (parts.join(' / ') || '—')
                                          const catL3 = parts.length >= 3 ? parts[2] : ''
                                          const showQtyUnit = Number.isFinite(qty) && qty > 1 && (u && u !== '')
                                          return (
                                            <div key={it.id ?? i} className="border-b border-theme-cream-f0 pb-2 last:border-0">
                                              {mobileReceiptViewMode === 'receipt' ? (
                                                <>
                                                  <div className="flex justify-between items-baseline gap-2">
                                                    <span className="min-w-0 truncate text-theme-dark-404">{name || '—'}</span>
                                                    {!showQtyUnit && <span className="shrink-0 tabular-nums">{p ? `$${p}` : ''}</span>}
                                                  </div>
                                                  {showQtyUnit && (
                                                    <div className="flex justify-between items-baseline gap-2 mt-0.5 text-sm text-theme-gray-666">
                                                      <span>{qty} @ ${u} / {unit}</span>
                                                      <span className="shrink-0 tabular-nums">{p ? `$${p}` : ''}</span>
                                                    </div>
                                                  )}
                                                </>
                                              ) : (
                                                <>
                                                  <div className="flex justify-between items-baseline gap-2">
                                                    <span className="min-w-0 truncate text-theme-dark-404">{name || '—'}</span>
                                                    <span className="shrink-0 tabular-nums">{p ? `$${p}` : ''}</span>
                                                  </div>
                                                  <div className="mt-0.5 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-0.5 text-xs text-theme-gray-666">
                                                    <span className="sm:flex-1">{catL1L2}</span>
                                                    <span className="sm:shrink-0">{catL3}</span>
                                                  </div>
                                                </>
                                              )}
                                            </div>
                                          )
                                        })}
                                      </div>
                                      {rec && (
                                        <div className="border-t border-dashed border-theme-cloud pt-2 space-y-0.5">
                                          <div className="flex justify-between"><span>Subtotal</span><span className="tabular-nums">{rec.subtotal != null ? `$${money(rec.subtotal)}` : ''}</span></div>
                                          <div className="flex justify-between"><span>Tax</span><span className="tabular-nums">{rec.tax != null ? `$${money(rec.tax)}` : ''}</span></div>
                                          <div className="flex justify-between font-medium"><span>Total</span><span className="tabular-nums">{rec.total != null ? `$${money(rec.total)}` : ''}</span></div>
                                        </div>
                                      )}
                                      <div className="border-t border-theme-ivory-dark pt-3 flex flex-col gap-2">
                                        <p className="text-xs font-medium text-theme-gray-666 uppercase tracking-wide">Smart Categorization</p>
                                        <button
                                          type="button"
                                          disabled={smartCategorizeLoading}
                                          onClick={async () => {
                                            if (!r.id || !token) return
                                            setSmartCategorizeLoading(true); setSmartCategorizeMessage(null)
                                            try {
                                              const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/smart-categorize`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
                                              const data = await res.json().catch(() => ({}))
                                              if (res.ok) { setSmartCategorizeMessage(data.updated_count ? `Updated ${data.updated_count} item(s)` : 'Done'); await refetchReceiptDetail(r.id) }
                                              else setSmartCategorizeMessage(data.detail || 'Failed')
                                            } catch { setSmartCategorizeMessage('Network error') }
                                            finally { setSmartCategorizeLoading(false) }
                                          }}
                                          className="w-full text-sm text-theme-gray-666 bg-theme-ivory-dark hover:bg-theme-cloud py-2 rounded border border-theme-cloud disabled:opacity-50 disabled:cursor-not-allowed"
                                        >
                                          {smartCategorizeLoading ? '…' : 'Smart categorization'}
                                        </button>
                                        {smartCategorizeMessage && <p className={`text-xs ${smartCategorizeMessage.startsWith('Updated') ? 'text-green-600' : 'text-theme-red'}`}>{smartCategorizeMessage}</p>}
                                      </div>
                                      </div>
                                    </div>
                                    </>
                                  )
                                })()}
                                {/* 桌面端：与 dashboard 一致 — 灰色层 + 双栏 */}
                                <div className="hidden lg:block border-t border-theme-light-gray/50 bg-theme-cream p-4">
                                <div className="hidden lg:grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
                                  <div className="relative bg-white border border-theme-light-gray rounded-lg p-4 text-sm text-theme-dark flex flex-col min-h-0">
                                    <button
                                      type="button"
                                      className="absolute top-2 right-2 text-sm text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 px-2.5 py-1 rounded border border-theme-mid min-w-26"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        if (correctionOpenReceiptId === r.id) {
                                          setCorrectionOpenReceiptId(null)
                                        } else {
                                          setCorrectionOpenReceiptId(r.id)
                                          initEditFormFromJson(expandedReceiptData[r.id])
                                        }
                                      }}
                                    >
                                      {correctionOpenReceiptId === r.id ? 'Hide Edits' : 'Edit Fields'}
                                    </button>
                                    {(() => {
                                      const json = expandedReceiptData[r.id]
                                      const rec = json?.data?.receipt
                                      const items = json?.data?.items || []
                                      const chainName = json?.data?.chain_name
                                      const $ = (v: any) => (v == null || v === '' ? null : String(v))
                                      const money = (v: any) => {
                                        if (v == null || v === '') return null
                                        const n = Number(v)
                                        if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
                                        return String(v)
                                      }
                                      if (!rec && items.length === 0) return <span>(No data)</span>
                                      const rawName = rec?.merchant_name ?? ''
                                      const displayName = chainName || (rawName ? toTitleCaseStore(rawName) : '') || rawName || ''
                                      const rawAddress = $(rec?.merchant_address)
                                      const address = formatAddressForDisplay(rawAddress || '')
                                      const addressLineCount = (address || '').split(/\r?\n/).filter(Boolean).length
                                      const lineCount = 1 + addressLineCount + (rec?.merchant_phone ? 1 : 0)
                                      return (
                                        <div className="space-y-0">
                                          {/* Section1: 店名+地址+Tel，与 dashboard/图2 一致 */}
                                          <div className="min-h-22">
                                            {(displayName || address || rec?.merchant_phone) ? (
                                              <div className="text-theme-dark whitespace-pre-line leading-5 text-sm">
                                                {displayName && <span className="font-semibold">{displayName}</span>}
                                                {address && <>{'\n'}<span className="text-theme-dark/90">{address}</span></>}
                                                {rec?.merchant_phone && <>{'\n'}<span className="text-theme-dark/90">Tel: {rec.merchant_phone}</span></>}
                                              </div>
                                            ) : null}
                                            {(displayName || address) && (
                                              <div className="border-t border-dashed border-theme-light-gray my-2 pt-2" />
                                            )}
                                          </div>
                                          {/* Section2: items table — each row min-h-7 to align with classification */}
                                          {items.length > 0 && (
                                            <>
                                              {/* 与 dashboard 一致：Product, Qty, Unit $, $ Amount；图2 排版 */}
                                              <div className="grid grid-cols-[1fr_3.5rem_5.5rem_5.5rem] gap-x-3 gap-y-0 text-left mb-0.5 min-h-7 items-center">
                                                <div className="py-1.5 px-3 text-xs text-theme-dark/90 font-semibold uppercase">Product</div>
                                                <div className="py-1.5 pl-3 pr-2 text-xs text-theme-dark/90 font-semibold uppercase text-center">Qty</div>
                                                <div className="py-1.5 pl-3 pr-2 text-xs text-theme-dark/90 font-semibold uppercase text-right">Unit $</div>
                                                <div className="py-1.5 pl-3 pr-2 text-xs text-theme-dark/90 font-semibold uppercase text-right">$ Amount</div>
                                              </div>
                                              {items.map((it: any, i: number) => {
                                                const name = it.product_name ?? it.original_product_name ?? ''
                                                const qty = it.quantity != null ? (typeof it.quantity === 'number' ? it.quantity : Number(it.quantity)) : 1
                                                const u = it.unit_price != null ? (money(it.unit_price) ?? it.unit_price) : ''
                                                const p = it.line_total != null ? (money(it.line_total) ?? it.line_total) : ''
                                                return (
                                                  <div key={i} className="grid grid-cols-[1fr_3.5rem_5.5rem_5.5rem] gap-x-3 gap-y-0 min-h-7 items-center">
                                                    <div className="py-1.5 px-3 truncate min-w-0 text-theme-dark" title={name}>{name}</div>
                                                    <div className="py-1.5 pl-3 pr-2 text-center tabular-nums text-theme-dark">{Number.isFinite(qty) ? qty : ''}</div>
                                                    <div className="py-1.5 pl-3 pr-2 text-right tabular-nums text-theme-dark">{u}</div>
                                                    <div className="py-1.5 pl-3 pr-2 text-right tabular-nums text-theme-dark">{p}</div>
                                                  </div>
                                                )
                                              })}
                                              <div className="border-t border-dashed border-theme-light-gray my-2 pt-2" />
                                            </>
                                          )}
                                          {/* Subtotal / Tax / Total 与第四栏 price 对齐，与 dashboard/图2 一致 */}
                                          {rec && (
                                            <>
                                              <div className="grid grid-cols-[1fr_3.5rem_5.5rem_5.5rem] gap-x-3 text-theme-dark">
                                                <div>Subtotal</div>
                                                <div />
                                                <div />
                                                <div className="text-right tabular-nums py-1.5 pl-3 pr-2">{rec.subtotal != null ? (money(rec.subtotal) ?? rec.subtotal) : ''}</div>
                                              </div>
                                              <div className="grid grid-cols-[1fr_3.5rem_5.5rem_5.5rem] gap-x-3 text-theme-dark">
                                                <div>Tax</div>
                                                <div />
                                                <div />
                                                <div className="text-right tabular-nums py-1.5 pl-3 pr-2">{rec.tax != null ? (money(rec.tax) ?? rec.tax) : ''}</div>
                                              </div>
                                              <div className="grid grid-cols-[1fr_3.5rem_5.5rem_5.5rem] gap-x-3 font-medium text-theme-dark">
                                                <div>Total</div>
                                                <div />
                                                <div />
                                                <div className="text-right tabular-nums py-1.5 pl-3 pr-2">{rec.total != null ? (money(rec.total) ?? rec.total) : ''}</div>
                                              </div>
                                              <div className="border-t border-dashed border-theme-light-gray my-2 pt-2" />
                                              {$(rec.payment_method) && <div className="text-theme-dark">Payment: {rec.payment_method}</div>}
                                              {$(rec.card_last4) && <div className="text-theme-dark">Payment Card: {rec.payment_method ? `${rec.payment_method} ` : ''}****{String(rec.card_last4).replace(/\D/g, '').slice(-4) || rec.card_last4}</div>}
                                              {$(rec.purchase_date) && <div className="text-theme-dark">Date: {rec.purchase_date}</div>}
                                              {(editPurchaseTime?.trim() || $(rec.purchase_time)) && (
                                                <div className="text-theme-dark">Time: {formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '')}</div>
                                              )}
                                            </>
                                          )}
                                        </div>
                                      )
                                    })()}
                                  </div>
                                  <div className="relative border border-theme-light-gray rounded-lg overflow-hidden bg-white min-h-[200px] flex flex-col">
                                    {/* Row 1: CLASSIFICATION title + Smart categorization button */}
                                    <div className="px-3 py-2 border-b border-theme-light-gray bg-theme-light-gray/50 flex items-center justify-between gap-2 shrink-0">
                                      <p className="text-xs font-medium text-theme-mid uppercase tracking-wide">Classification</p>
                                      <button
                                        type="button"
                                        className="text-xs font-medium text-theme-blue hover:text-theme-blue hover:bg-theme-blue/10 px-2 py-1.5 rounded border border-theme-blue/30"
                                        onClick={async () => {
                                          if (!r.id || !token) return
                                          setSmartCategorizeLoading(true)
                                          setSmartCategorizeMessage(null)
                                          try {
                                            const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/smart-categorize`, {
                                              method: 'POST',
                                              headers: { Authorization: `Bearer ${token}` },
                                            })
                                            const data = await res.json().catch(() => ({}))
                                            if (res.ok) {
                                              setSmartCategorizeMessage(data.updated_count ? `Updated ${data.updated_count} item(s)` : 'No uncategorized items')
                                              await refetchReceiptDetail(r.id)
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
                                      <span className="text-xs text-theme-gray-666">Category</span>
                                    </div>
                                    {/* Row 3: level I / II / III + 修改 — aligns with left "Qty Unit $ $ Amount" row */}
                                    <div className="px-3 overflow-auto">
                                      {((expandedReceiptData[r.id]?.data?.items) || []).length > 0 ? (
                                        <>
                                          <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-x-2 gap-y-0 text-left mb-0.5 min-h-7 items-center text-xs text-theme-gray-666 font-medium">
                                            <div>level I</div>
                                            <div>level II</div>
                                            <div>level III</div>
                                            <div className="w-14" />
                                          </div>
                                          {((expandedReceiptData[r.id]?.data?.items) || []).map((it: any, i: number) => {
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
                                              if (!r.id || !token) return
                                              setCategoryUpdateMessage(null)
                                              const toSend = editCatL3 || editCatL2 || editCatL1 || null
                                              try {
                                                const res = await fetch(
                                                  `${apiBaseUrl}/api/receipt/${r.id}/item/${itemId}/category`,
                                                  {
                                                    method: 'PATCH',
                                                    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                    body: JSON.stringify({ category_id: toSend }),
                                                  }
                                                )
                                                if (res.ok) {
                                                  setCategoryUpdateMessage('Saved')
                                                  await refetchReceiptDetail(r.id)
                                                  setEditingItemId(null)
                                                } else {
                                                  const err = await res.json().catch(() => ({}))
                                                  setCategoryUpdateMessage(err?.detail ?? 'Save failed')
                                                }
                                              } catch (e) {
                                                setCategoryUpdateMessage('Network error')
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
                                                      <button type="button" className="p-1 bg-green-100 text-green-800 rounded hover:bg-green-200 w-5 h-5 flex items-center justify-center" onClick={confirmEdit} title="Confirm">✓</button>
                                                      <button type="button" className="p-1 bg-theme-ivory-dark text-theme-gray-666 rounded hover:bg-theme-cloud w-5 h-5 flex items-center justify-center" onClick={cancelEdit} title="Cancel">✕</button>
                                                    </div>
                                                  </>
                                                ) : (
                                                  <>
                                                    <div className="truncate text-theme-dark-404" title={c1}>{c1}</div>
                                                    <div className="truncate text-theme-dark-404" title={c2}>{c2}</div>
                                                    <div className="truncate text-theme-dark-404" title={c3}>{c3}</div>
                                                    <button type="button" className="p-1 text-theme-gray-666 hover:text-theme-dark-404 hover:bg-theme-ivory-dark rounded w-5 h-5 flex items-center justify-center" onClick={startEdit} title="Edit">✏️</button>
                                                  </>
                                                )}
                                              </div>
                                            )
                                          })}
                                          {(categoryUpdateMessage || smartCategorizeMessage) && (
                                            <div className={`mt-1 text-xs ${(categoryUpdateMessage || smartCategorizeMessage) === 'Saved' || (smartCategorizeMessage && smartCategorizeMessage.startsWith('Updated')) ? 'text-green-600' : 'text-theme-red'}`}>
                                              {categoryUpdateMessage || smartCategorizeMessage}
                                            </div>
                                          )}
                                        </>
                                      ) : (
                                        <p className="text-theme-gray-919 text-sm">No items</p>
                                      )}
                                    </div>
                                    {/* Edit panel: overlays only this CLASSIFICATION column; scrollable inside */}
                                    <div
                                      className={`absolute inset-0 z-10 flex flex-col bg-white border border-theme-ivory-dark rounded-lg shadow-lg transition-transform duration-200 ease-out ${correctionOpenReceiptId === r.id ? 'translate-x-0' : 'translate-x-full'}`}
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <div className="flex items-center justify-between px-3 py-2 border-b border-theme-ivory-dark bg-theme-ivory shrink-0">
                                        <span className="text-sm font-medium text-theme-gray-666">Edit receipt</span>
                                        <button
                                          type="button"
                                          className="p-1.5 text-theme-gray-666 hover:text-theme-dark-404 hover:bg-theme-ivory-dark rounded"
                                          onClick={(e) => { e.stopPropagation(); setCorrectionOpenReceiptId(null) }}
                                          title="Close"
                                        >
                                          ▶
                                        </button>
                                      </div>
                                      <div className="p-4 space-y-4 overflow-y-auto flex-1 min-h-0">
                                        {correctMessage && (
                                          <div className={`p-2 rounded text-sm ${correctMessage.startsWith('Saved') ? 'bg-green-100 text-green-800' : 'bg-theme-red/15 text-theme-red'}`}>
                                            {correctMessage}
                                          </div>
                                        )}
                                        <div className="grid grid-cols-1 gap-2">
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Store name</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editStoreName} onChange={(e) => setEditStoreName(e.target.value)} placeholder="Store name" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Address line 1</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressLine1} onChange={(e) => setEditAddressLine1(e.target.value)} placeholder="Street address" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Address line 2</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressLine2} onChange={(e) => setEditAddressLine2(e.target.value)} placeholder="Unit / Suite" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">City, State ZIP</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressCityStateZip} onChange={(e) => setEditAddressCityStateZip(e.target.value)} placeholder="Lynnwood, WA 98036" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Country</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressCountry} onChange={(e) => setEditAddressCountry(e.target.value)} placeholder="US" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Phone</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="425-640-2648" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Purchase date</span>
                                            <input type="date" className="border rounded px-2 py-1 text-sm" value={editReceiptDate} onChange={(e) => setEditReceiptDate(e.target.value)} />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-gray-666">Purchase time (optional, 24-hour only, e.g. 15:34)</span>
                                            <input type="text" className="border rounded px-2 py-1 text-sm font-mono" placeholder="15:34" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} maxLength={5} pattern="([01]?[0-9]|2[0-3]):[0-5][0-9]" title="Please enter time in 24-hour HH:MM format" />
                                          </label>
                                          <div className="grid grid-cols-3 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-gray-666">Subtotal</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editSubtotal} onChange={(e) => setEditSubtotal(e.target.value)} placeholder="0.00" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-gray-666">Tax</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editTax} onChange={(e) => setEditTax(e.target.value)} placeholder="0.00" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-gray-666">Total *</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editTotal} onChange={(e) => setEditTotal(e.target.value)} placeholder="0.00" />
                                            </label>
                                          </div>
                                          <div className="grid grid-cols-2 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-gray-666">Currency</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editCurrency} onChange={(e) => setEditCurrency(e.target.value)} placeholder="USD" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-gray-666">Payment method</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editPaymentMethod} onChange={(e) => setEditPaymentMethod(e.target.value)} placeholder="AMEX Credit" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-gray-666">Card last 4</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editPaymentLast4} onChange={(e) => setEditPaymentLast4(e.target.value)} placeholder="5030" maxLength={4} />
                                            </label>
                                          </div>
                                        </div>
                                        <div>
                                          <p className="text-xs text-theme-gray-666 mb-2">Item lines</p>
                                          {/* 手机：每条两行（name 一行，Qty/Unit pr/Amount 一行），无 table */}
                                          <div className="md:hidden max-h-48 overflow-auto border border-theme-ivory-dark rounded divide-y divide-theme-cream-f0">
                                            {editItems.map((row, idx) => (
                                              <div key={idx} className="p-2 space-y-2">
                                                <div>
                                                  <label className="text-xs text-theme-gray-666 block mb-0.5">Product name</label>
                                                  <input className="w-full border rounded px-2 py-1.5 text-sm" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} />
                                                </div>
                                                <div className="grid grid-cols-3 gap-2">
                                                  <div>
                                                    <label className="text-xs text-theme-gray-666 block mb-0.5">Qty</label>
                                                    <input type="text" inputMode="numeric" className="w-full border rounded px-2 py-1.5 text-sm" placeholder="Qty" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} />
                                                  </div>
                                                  <div>
                                                    <label className="text-xs text-theme-gray-666 block mb-0.5">Unit pr</label>
                                                    <input className="w-full border rounded px-2 py-1.5 text-sm" placeholder="Unit price" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} />
                                                  </div>
                                                  <div>
                                                    <label className="text-xs text-theme-gray-666 block mb-0.5">$ Amount</label>
                                                    <input className="w-full border rounded px-2 py-1.5 text-sm" placeholder="Line total" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} />
                                                  </div>
                                                </div>
                                              </div>
                                            ))}
                                          </div>
                                          {/* 桌面：表格 */}
                                          <div className="hidden md:block max-h-48 overflow-auto border border-theme-ivory-dark rounded">
                                            <table className="w-full border-collapse text-sm">
                                              <thead>
                                                <tr className="text-xs text-theme-gray-666 font-medium bg-theme-ivory border-b border-theme-ivory-dark">
                                                  <th className="text-left py-1.5 px-2 font-normal">Product name</th>
                                                  <th className="text-left py-1.5 px-2 w-16">Qty</th>
                                                  <th className="text-left py-1.5 px-2 w-20">Unit pr</th>
                                                  <th className="text-left py-1.5 px-2 w-20">$ Amount</th>
                                                </tr>
                                              </thead>
                                              <tbody>
                                                {editItems.map((row, idx) => (
                                                  <tr key={idx} className="border-b border-theme-cream-f0 last:border-0">
                                                    <td className="py-1 px-2"><input className="w-full min-w-[120px] border rounded px-1.5 py-0.5" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input type="text" inputMode="numeric" className="w-full border rounded px-1.5 py-0.5" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input className="w-full border rounded px-1.5 py-0.5" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input className="w-full border rounded px-1.5 py-0.5" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} /></td>
                                                  </tr>
                                                ))}
                                              </tbody>
                                            </table>
                                          </div>
                                          <button type="button" className="mt-2 text-sm text-theme-blue hover:underline" onClick={() => setEditItems((prev) => [...prev, { product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])}>
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
                                                merchant_phone: editMerchantPhone.trim() || undefined,
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
                                              const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/correct`, {
                                                method: 'POST',
                                                headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                body: JSON.stringify({ summary, items: itemsPayload }),
                                              })
                                              const data = res.ok ? await res.json().catch(() => ({})) : await res.json().catch(() => ({}))
                                              if (!res.ok) throw new Error(data.detail || data.detail?.detail || 'Submit failed')
                                              setCorrectMessage('Saved. Receipt updated.')
                                              fetchReceiptList()
                                              const detailRes = await fetch(`${apiBaseUrl}/api/receipt/${r.id}`, {
                                                headers: { Authorization: `Bearer ${token}` },
                                              })
                                              if (detailRes.ok) {
                                                const detailJson = await detailRes.json()
                                                setExpandedReceiptData((prev) => ({ ...prev, [r.id]: detailJson }))
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
                                </div>
                                <div className="mt-4 flex flex-wrap items-center gap-2">
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); setShowRawJson((v) => !v) }}
                                    className="text-sm text-theme-gray-666 hover:text-theme-dark-404 underline"
                                  >
                                    {showRawJson ? 'Hide' : 'Show'} raw JSON
                                  </button>
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        if (expandedReceiptData[r.id]) navigator.clipboard.writeText(JSON.stringify(expandedReceiptData[r.id], null, 2))
                                        alert('Copied to clipboard')
                                      }}
                                      className="text-sm text-theme-gray-666 hover:text-theme-dark-404 underline"
                                    >
                                      Copy
                                    </button>
                                  {(userClass === 'admin' || userClass === 'super_admin') && (
                                    <button
                                      type="button"
                                      onClick={async (e) => {
                                        e.stopPropagation()
                                        if (!token || !r.id) return
                                        setProcessingRunsModalReceiptId(r.id)
                                        setProcessingRunsData(null)
                                        setProcessingRunsLoading(true)
                                        try {
                                          const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/processing-runs`, {
                                            headers: { Authorization: `Bearer ${token}` },
                                          })
                                          if (res.ok) {
                                            const data = await res.json()
                                            setProcessingRunsData({ track: data.track ?? 'unknown', track_method: data.track_method ?? null, runs: data.runs ?? [], workflow_steps: data.workflow_steps ?? [], pipeline_version: data.pipeline_version ?? null })
                                          } else {
                                            setProcessingRunsData({ track: 'unknown', track_method: null, runs: [], workflow_steps: [], pipeline_version: null })
                                          }
                                        } catch {
                                          setProcessingRunsData({ track: 'unknown', track_method: null, runs: [], workflow_steps: [], pipeline_version: null })
                                        } finally {
                                          setProcessingRunsLoading(false)
                                        }
                                      }}
                                      className="text-sm text-theme-blue hover:text-theme-blue underline"
                                    >
                                      View workflow
                                    </button>
                                  )}
                                  <button
                                    type="button"
                                    onClick={async (e) => {
                                      e.stopPropagation()
                                      if (!token || !r.id) return
                                      const msg = 'This will permanently remove this receipt. This cannot be undone. Delete anyway?'
                                      if (!confirm(msg)) return
                                      try {
                                        const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}`, {
                                          method: 'DELETE',
                                          headers: { Authorization: `Bearer ${token}` },
                                        })
                                        if (!res.ok) {
                                          const data = await res.json().catch(() => ({}))
                                          throw new Error(data.detail || 'Delete failed')
                                        }
                                        if (expandedReceiptIds.has(r.id)) {
                                          setExpandedReceiptIds((prev) => { const next = new Set(prev); next.delete(r.id); return next })
                                          setExpandedReceiptData((prev) => { const next = { ...prev }; delete next[r.id]; return next })
                                          if (correctionOpenReceiptId === r.id) setCorrectionOpenReceiptId(null)
                                        }
                                        fetchReceiptList()
                                      } catch (err) {
                                        alert(err instanceof Error ? err.message : 'Delete failed')
                                      }
                                    }}
                                    className="text-sm text-theme-red hover:text-theme-red hover:underline"
                                  >
                                    Delete this receipt
                                  </button>
                                </div>
                                {showRawJson && expandedReceiptData[r.id] && (
                                  <div className="mt-2 rounded overflow-hidden border border-theme-ivory-dark">
                                    <div className="bg-theme-slate px-3 py-1.5 text-xs text-theme-gray-919">Processing result JSON</div>
                                    <div className="bg-theme-black p-3 max-h-64 overflow-auto">
                                      <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap">
                                        {JSON.stringify(expandedReceiptData[r.id], null, 2)}
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

        {/* Processing runs modal (admin only) */}
        {processingRunsModalReceiptId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => { setProcessingRunsModalReceiptId(null); setProcessingRunsData(null) }}>
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
              <div className="px-4 py-3 border-b flex justify-between items-center">
                <h3 className="font-semibold text-theme-dark-404">Processing workflow — Receipt {processingRunsModalReceiptId.slice(0, 8)}…</h3>
                <button type="button" onClick={() => { setProcessingRunsModalReceiptId(null); setProcessingRunsData(null) }} className="text-theme-gray-666 hover:text-theme-gray-666 text-lg leading-none">×</button>
              </div>
              <div className="p-4 overflow-auto flex-1 min-h-0">
                {processingRunsLoading ? (
                  <p className="text-theme-gray-666">Loading…</p>
                ) : processingRunsData ? (
                  <>
                    <div className="mb-4 p-3 bg-theme-cream-f0 rounded">
                      <p className="text-sm font-medium text-theme-gray-666">Track</p>
                      <p className="text-sm text-theme-dark-404">
                        {processingRunsData.track === 'specific_rule' ? (
                          <>Specific rule (method: <code className="bg-white px-1 rounded">{processingRunsData.track_method ?? '—'}</code>)</>
                        ) : processingRunsData.track === 'general' ? (
                          <>General track (no store-specific rule matched)</>
                        ) : processingRunsData.track === 'vision_primary' ? (
                          <>Vision primary (pipeline: <code className="bg-white px-1 rounded">{(processingRunsData as { pipeline_version?: string }).pipeline_version ?? 'vision_b'}</code>)</>
                        ) : (
                          <>
                            Unknown (no rule_based_cleaning or vision run recorded).
                            {(processingRunsData as { pipeline_version?: string | null }).pipeline_version && (
                              <span className="block mt-1 text-theme-gray-666">
                                Pipeline: <code className="bg-white px-1 rounded">{(processingRunsData as { pipeline_version?: string }).pipeline_version}</code>
                              </span>
                            )}
                          </>
                        )}
                      </p>
                    </div>
                    {Array.isArray(processingRunsData.workflow_steps) && processingRunsData.workflow_steps.length > 0 && (
                      <div className="mb-4">
                        <p className="text-sm font-medium text-theme-gray-666 mb-2">Workflow path ({processingRunsData.workflow_steps.length} steps)</p>
                        <div className="rounded border border-theme-ivory-dark bg-theme-ivory p-2 flex flex-wrap gap-2">
                          {(processingRunsData.workflow_steps as Array<Record<string, unknown>>).map((s: Record<string, unknown>, i: number) => {
                            const r = String(s.result ?? '')
                            const resultClass = r === 'pass' || r === 'ok' || r === 'yes' ? 'text-green-600' : r === 'fail' || r === 'no' ? 'text-theme-red' : 'text-theme-gray-666'
                            return (
                              <span key={String(s.id ?? i)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-mono bg-white border border-theme-ivory-dark" title={s.details ? JSON.stringify(s.details) : undefined}>
                                <span className="text-theme-gray-666">{Number(s.sequence) + 1}.</span>
                                <span className="font-medium">{String(s.step_name ?? '')}</span>
                                <span className={resultClass}>{r}</span>
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    {processingRunsData.runs.length === 0 ? (
                      <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                        <p className="font-medium mb-1">No run records (Runs = 0)</p>
                        <p className="text-amber-700">
                          Debug cards (input_payload / output_payload) come from <code className="bg-white/80 px-1 rounded">receipt_processing_runs</code>.
                          This receipt has no rows there: only workflow steps (e.g. create_db) were written.
                          Common causes: pipeline failed before the first <code className="bg-white/80 px-1 rounded">save_processing_run</code>, or DB constraint rejected the stage (e.g. Vision pipeline needs migration 049 for <code>vision_primary</code>).
                        </p>
                      </div>
                    ) : null}
                    <p className="text-sm font-medium text-theme-gray-666 mb-2 mt-2">Runs ({processingRunsData.runs.length})</p>
                    <div className="space-y-3">
                      {processingRunsData.runs.map((run: Record<string, unknown>, idx: number) => (
                        <ProcessingRunCard key={String(run.id ?? idx)} run={run} />
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-theme-gray-666">No data</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* API Test Section — developer only */}
        <div className="mt-8 bg-theme-blue/10 rounded-xl p-6">
          <h3 className="text-lg font-semibold text-theme-blue mb-3">
            🧪 API test info
          </h3>
          <div className="space-y-2 text-sm text-theme-blue">
            <p>
              <span className="font-semibold">Backend API: </span>
              {apiBaseUrl}
            </p>
            <p>
              <span className="font-semibold">Auth: </span>
              <span className="text-green-600 font-semibold">✓ Authenticated</span>
            </p>
            <p>
              <a href={`${apiBaseUrl}/docs`} target="_blank" rel="noopener noreferrer" className="text-theme-blue hover:underline font-medium">
                → Open API docs (/doc)
              </a>
            </p>
            <p className="pt-2 text-xs text-theme-blue">
              Open browser console (F12) for API response details
            </p>
          </div>
        </div>
      </main>
    </>
  )
}

function ProcessingRunCard({ run }: { run: Record<string, unknown> }) {
  const [showInput, setShowInput] = useState(false)
  const [showOutput, setShowOutput] = useState(false)
  const stage = String(run.stage ?? '')
  const status = String(run.status ?? '')
  const created = run.created_at ? new Date(String(run.created_at)).toLocaleString('en-US') : '—'
  const provider = run.model_provider ? String(run.model_provider) : ''
  const model = run.model_name ? String(run.model_name) : ''
  const validation = run.validation_status ? String(run.validation_status) : ''
  const err = run.error_message ? String(run.error_message) : ''
  return (
    <div className="border rounded p-3 bg-theme-ivory">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{stage}</span>
        <span className={status === 'pass' ? 'text-green-600' : 'text-theme-red'}>{status}</span>
        {validation && <span className="text-theme-gray-666">validation: {validation}</span>}
        {provider && <span className="text-theme-gray-666">{provider}{model ? ` / ${model}` : ''}</span>}
        <span className="text-theme-gray-919" suppressHydrationWarning>{created}</span>
      </div>
      {err && <p className="text-xs text-theme-red mt-1">{err}</p>}
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={() => setShowInput((v) => !v)} className="text-xs text-theme-blue hover:underline">
          {showInput ? 'Hide' : 'Show'} input_payload
        </button>
        <button type="button" onClick={() => setShowOutput((v) => !v)} className="text-xs text-theme-blue hover:underline">
          {showOutput ? 'Hide' : 'Show'} output_payload
        </button>
      </div>
      {showInput && run.input_payload != null && (
        <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 overflow-hidden">
          <p className="px-3 py-1.5 text-xs font-semibold text-slate-600 bg-slate-100 border-b border-slate-200">Input</p>
          <pre className="p-3 text-sm font-mono text-slate-800 whitespace-pre-wrap break-words overflow-auto max-h-72 leading-relaxed">{JSON.stringify(run.input_payload, null, 2).replace(/\\n/g, '\n')}</pre>
        </div>
      )}
      {showOutput && run.output_payload != null && (
        <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 overflow-hidden">
          <p className="px-3 py-1.5 text-xs font-semibold text-slate-600 bg-slate-100 border-b border-slate-200">Output</p>
          <pre className="p-3 text-sm font-mono text-slate-800 whitespace-pre-wrap break-words overflow-auto max-h-72 leading-relaxed">{JSON.stringify(run.output_payload, null, 2).replace(/\\n/g, '\n')}</pre>
        </div>
      )}
    </div>
  )
}
