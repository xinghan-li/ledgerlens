'use client'

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { getFirebaseAuth, getAuthToken } from '@/lib/firebase'
import { onAuthStateChanged } from 'firebase/auth'
import DataAnalysisSection from './DataAnalysisSection'
import { CameraCaptureButton } from './camera'

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

export default function DashboardPage() {
  const [token, setToken] = useState<string | null>(null)
  const [userEmail, setUserEmail] = useState<string | null>(null)
  const [userName, setUserName] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadWorkingHard, setUploadWorkingHard] = useState(false)
  const [uploadBannerStep, setUploadBannerStep] = useState(0) // 0: writing, 1: escalated, 2: final check
  const [uploadResult, setUploadResult] = useState<any>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const workingHardTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const uploadAbortRef = useRef<AbortController | null>(null)
  const uploadCancelledByUserRef = useRef(false)
  const uploadCleanupRef = useRef<{ clearBanner: () => void; timeoutId: ReturnType<typeof setTimeout> | null } | null>(null)
  const cameraUploadTimersRef = useRef<ReturnType<typeof setTimeout>[]>([])
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
  const [smartCategorizeSelectedIds, setSmartCategorizeSelectedIds] = useState<Set<string>>(new Set())
  const [userClass, setUserClass] = useState<string | null>(null)
  const [processingRunsModalReceiptId, setProcessingRunsModalReceiptId] = useState<string | null>(null)
  const [processingRunsData, setProcessingRunsData] = useState<{ track: string; track_method: string | null; runs: Array<Record<string, unknown>>; workflow_steps: Array<Record<string, unknown>> } | null>(null)
  const [processingRunsLoading, setProcessingRunsLoading] = useState(false)
  const router = useRouter()

  useEffect(() => {
    setSmartCategorizeSelectedIds(new Set())
  }, [expandedReceiptId])

  useEffect(() => {
    if (!token) {
      setUserClass(null)
      setUserName(null)
      return
    }
    let cancelled = false
    fetch(`${apiUrl()}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) {
          setUserClass(data.user_class ?? null)
          setUserName(data.username ?? null)
        }
      })
      .catch(() => { if (!cancelled) setUserClass(null); if (!cancelled) setUserName(null) })
    return () => { cancelled = true }
  }, [token])

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

  /** 统一为 24 小时制 HH:mm；支持 "15:34"、"15:34:00" 或 "3:34 PM" 等输入 */
  function formatTimeToHHmm(t: string): string {
    if (!t || typeof t !== 'string') return ''
    const s = t.trim()
    const match24 = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?(\s|$|:)/)
    if (match24) {
      const h = parseInt(match24[1], 10)
      const m = match24[2]
      if (h >= 0 && h <= 23 && m.length === 2) return `${String(h).padStart(2, '0')}:${m}`
    }
    const match12 = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)/i)
    if (match12) {
      let h = parseInt(match12[1], 10)
      const m = match12[2]
      const pm = match12[3].toUpperCase() === 'PM'
      if (pm && h !== 12) h += 12
      if (!pm && h === 12) h = 0
      return `${String(h).padStart(2, '0')}:${m}`
    }
    return s.slice(0, 5)
  }

  /** 匹配 "City, ST ZIP" 或 "City, ST ZIP-4" 格式，避免把城市/州/邮编误填到 Address line 2 */
  function looksLikeCityStateZip(s: string): boolean {
    return /^[A-Za-z\s\-'.]+,\s*[A-Z]{2}\s+\d{5}(-\d{4})?$/i.test((s || '').trim())
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
      // Address line 2 仅用于门牌/单元号，若第二行是 "City, ST ZIP" 则不要填到 line2，避免与 City, State ZIP 重复
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

  /** 店名转首字母大写，与后端一致，避免编辑框和标题仍显示全大写 */
  function toTitleCaseStore(name: string): string {
    if (!name || typeof name !== 'string') return name
    return name.trim().split(/\s+/).map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ')
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
    const toDollarItem = (v: any) => {
      if (v == null || v === '') return ''
      const n = Number(v)
      if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
      return String(v)
    }
    setEditItems(
      items.length
        ? items.map((it: any) => ({
            id: it.id ?? undefined,
            product_name: it.product_name ?? '',
            quantity: it.quantity != null && it.quantity !== '' ? String(it.quantity) : '1',
            unit: it.unit ?? '',
            unit_price: it.unit_price != null ? (typeof it.unit_price === 'number' || !Number.isNaN(Number(it.unit_price)) ? toDollarItem(it.unit_price) : String(it.unit_price)) : '',
            line_total: it.line_total != null ? (typeof it.line_total === 'number' || !Number.isNaN(Number(it.line_total)) ? toDollarItem(it.line_total) : String(it.line_total)) : '',
            on_sale: it.on_sale ?? false,
            original_price: it.original_price != null ? String(it.original_price) : '',
            discount_amount: it.discount_amount != null ? String(it.discount_amount) : '',
          }))
        : [{ product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }]
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
        setUserName(null)
        setLoading(false)
        router.push('/login')
        return
      }
      setUserEmail(user.email ?? null)
      try {
        const t = await user.getIdToken()
        setToken(t)
      } catch (e) {
        console.error('getIdToken failed:', e)
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

  const clearCameraUploadTimers = useCallback(() => {
    cameraUploadTimersRef.current.forEach((id) => clearTimeout(id))
    cameraUploadTimersRef.current = []
  }, [])

  const handleCameraUploadStart = useCallback(() => {
    setUploading(true)
    setUploadError(null)
    setUploadResult(null)
    setUploadBannerStep(0)
    setUploadWorkingHard(false)
    clearCameraUploadTimers()
    cameraUploadTimersRef.current = [
      setTimeout(() => setUploadBannerStep(1), 25000),
      setTimeout(() => setUploadBannerStep(2), 55000),
      setTimeout(() => setUploadWorkingHard(true), 30000),
    ]
  }, [clearCameraUploadTimers])

  const handleCameraUploadSuccess = useCallback(() => {
    clearCameraUploadTimers()
    setUploading(false)
    setUploadWorkingHard(false)
    fetchReceiptList()
  }, [clearCameraUploadTimers, fetchReceiptList])

  const handleCameraUploadError = useCallback(
    (message: string) => {
      clearCameraUploadTimers()
      setUploading(false)
      setUploadWorkingHard(false)
      setUploadError(message)
    },
    [clearCameraUploadTimers]
  )

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
    if (!file) {
      e.target.value = ''
      return
    }
    // 每次上传时获取新 token，避免 Firebase ID token 过期（约 1 小时）导致 401
    const requestToken = await getAuthToken()
    if (!requestToken) {
      setUploadError('登录已过期，请刷新页面重新登录')
      e.target.value = ''
      return
    }

    // 重置状态
    uploadCancelledByUserRef.current = false
    setUploading(true)
    setUploadResult(null)
    setUploadError(null)
    setUploadBannerStep(0)
    const bannerTimeouts: ReturnType<typeof setTimeout>[] = []
    bannerTimeouts.push(setTimeout(() => setUploadBannerStep(1), 25000))
    bannerTimeouts.push(setTimeout(() => setUploadBannerStep(2), 55000))
    const clearBannerTimers = (): void => {
      bannerTimeouts.forEach((t) => clearTimeout(t))
    }

    const formData = new FormData()
    formData.append('file', file)

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      console.log('上传到:', `${apiUrl}/api/receipt/workflow`)
      console.log('文件:', file.name, file.type, file.size)
      
      // 3 分钟超时（多步 LLM 可能需 2–3 分钟）；30s 后仅显示 “working hard” 提示，不报错
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 180000) // 3 min
      workingHardTimerRef.current = setTimeout(() => setUploadWorkingHard(true), 30000) // 30s 后显示友好提示
      uploadAbortRef.current = controller
      uploadCleanupRef.current = { clearBanner: clearBannerTimers, timeoutId }

      try {
        const response = await fetch(`${apiUrl}/api/receipt/workflow`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${requestToken}` },
          body: formData,
          signal: controller.signal,
        })

        clearTimeout(timeoutId)
        clearBannerTimers()
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
        let errorMessage: string
        if (response.status === 401) {
          errorMessage = '登录已过期，请刷新页面或重新登录'
        } else {
          errorMessage = `HTTP ${response.status}: ${response.statusText}`
          try {
            const errorData = await response.json()
            if (typeof errorData.detail === 'string') errorMessage = errorData.detail
            else if (typeof errorData.detail === 'object') errorMessage = JSON.stringify(errorData.detail)
            else if (errorData.message) errorMessage = errorData.message
          } catch {
            try {
              const text = await response.text()
              if (text) errorMessage = text
            } catch {
              // 忽略
            }
          }
        }
        setUploadError(errorMessage)
      }
      } catch (fetchError) {
        clearTimeout(timeoutId)
        clearBannerTimers()
        if (workingHardTimerRef.current) {
          clearTimeout(workingHardTimerRef.current)
          workingHardTimerRef.current = null
        }
        throw fetchError
      }
    } catch (error) {
      console.error('❌ 上传错误:', error)
      clearBannerTimers()
      if (workingHardTimerRef.current) {
        clearTimeout(workingHardTimerRef.current)
        workingHardTimerRef.current = null
      }
      // 用户点击 Stop 取消：不显示错误，直接回到未上传状态
      if (error instanceof Error && error.name === 'AbortError' && uploadCancelledByUserRef.current) {
        setUploadError(null)
        setUploadResult(null)
        return
      }
      // 更详细的错误提示
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          setUploadError('Request timed out (3 min). Check:\n1. Backend is running\n2. Network is stable\n3. Image size is not too large')
        } else if (error.message.includes('Failed to fetch') || error.message === 'Load failed' || error.message === 'Load failed.') {
          const base = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
          setUploadError('Cannot reach the backend. If using ngrok on mobile: expose the backend via ngrok and set NEXT_PUBLIC_API_URL in frontend .env.local to that ngrok URL. Current API: ' + base)
        } else {
          setUploadError(error.message)
        }
      } else {
        setUploadError('Network error. Please retry.')
      }
    } finally {
      setUploading(false)
      setUploadWorkingHard(false)
      clearBannerTimers()
      if (workingHardTimerRef.current) {
        clearTimeout(workingHardTimerRef.current)
        workingHardTimerRef.current = null
      }
      uploadAbortRef.current = null
      uploadCleanupRef.current = null
      // 清空 input value，否则下次选同一文件时 onChange 不会触发（删除小票后未整页刷新时会出现）
      e.target.value = ''
    }
  }

  const handleCancelUpload = (): void => {
    uploadCancelledByUserRef.current = true
    uploadCleanupRef.current?.clearBanner()
    if (uploadCleanupRef.current?.timeoutId != null) clearTimeout(uploadCleanupRef.current.timeoutId)
    if (workingHardTimerRef.current) {
      clearTimeout(workingHardTimerRef.current)
      workingHardTimerRef.current = null
    }
    uploadAbortRef.current?.abort()
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-gray-600">Loading…</p>
        </div>
      </div>
    )
  }

  if (!token) {
    return null
  }

  return (
    <>
      <main className="max-w-7xl mx-auto px-4 py-6 sm:py-8 sm:px-6 lg:px-8">
        {/* Customer welcome: email only + upload & camera */}
        <div className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-8 flex flex-col sm:flex-row sm:flex-wrap sm:items-start sm:justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h2 className="text-lg sm:text-xl font-semibold mb-1 sm:mb-2">Welcome back, {userName || userEmail}</h2>
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
            {uploading ? (
              <div
                className="group inline-flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium text-white bg-green-500 cursor-wait select-none min-h-[44px] sm:min-h-0"
                title="Hover to show Stop"
              >
                <span className="inline-block animate-spin text-lg">⏳</span>
                <span>Processing…</span>
                <button
                  type="button"
                  onClick={(ev) => { ev.preventDefault(); ev.stopPropagation(); handleCancelUpload() }}
                  className="ml-2 px-2.5 py-1 rounded bg-red-500 hover:bg-red-600 text-white text-sm font-medium opacity-0 group-hover:opacity-100 transition-opacity focus:opacity-100 focus:outline-none"
                  aria-label="Stop and cancel upload"
                >
                  Stop
                </button>
              </div>
            ) : (
              <label
                htmlFor="receipt-upload"
                className="inline-flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium text-white bg-green-600 hover:bg-green-700 cursor-pointer transition select-none min-h-[44px] sm:min-h-0"
              >
                Upload receipt
              </label>
            )}
            <CameraCaptureButton
              token={token}
              disabled={uploading}
              showAsProcessing={uploading}
              onUploadStart={handleCameraUploadStart}
              onSuccess={handleCameraUploadSuccess}
              onError={handleCameraUploadError}
            />
          </div>
        </div>

        {/* 上传中：bookkeeper 状态横幅（随等待时间切换） */}
        {uploading && (
          <div className="mb-4 p-4 sm:p-5 bg-blue-50 border border-blue-200 rounded-lg text-center animate-pulse">
            {uploadBannerStep === 0 && (
              <>
                <p className="text-blue-900 font-medium text-base sm:text-lg mb-1">Your bookkeeper is writing busily…</p>
                <p className="text-blue-700 text-sm">Reading your receipt — this may take a minute.</p>
              </>
            )}
            {uploadBannerStep === 1 && (
              <>
                <p className="text-blue-900 font-medium text-base sm:text-lg mb-1">The bookkeeper has questions and is escalating.</p>
                <p className="text-blue-700 text-sm">You can close this page and come back later — we’ll have it ready when they’re done.</p>
              </>
            )}
            {uploadBannerStep === 2 && (
              <>
                <p className="text-blue-900 font-medium text-base sm:text-lg mb-1">Doing final check.</p>
                <p className="text-blue-700 text-sm">Almost there — thank you for your patience.</p>
              </>
            )}
          </div>
        )}
        {/* Upload success/error toasts */}
        {uploadResult?.success === true && (
          <div className="mb-4 p-3 sm:p-4 bg-green-50 border border-green-200 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <span className="text-green-800 text-sm sm:text-base min-w-0">
              ✅ Processed.
              {(uploadResult.status === 'passed_after_fallback' || uploadResult.status === 'passed_after_vision_retry')
                ? ' Final check complete.'
                : ` Status: ${uploadResult.status || 'passed'}`}
            </span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-green-700 hover:underline self-start sm:self-center min-h-[44px] sm:min-h-0"
            >
              Dismiss
            </button>
          </div>
        )}
        {/* 重复上传：明确提示 */}
        {uploadResult && uploadResult.success === false && uploadResult.error === 'duplicate_receipt' && (
          <div className="mb-4 p-3 sm:p-4 bg-red-50 border border-red-200 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <span className="text-red-800 text-sm sm:text-base min-w-0">
              This receipt was already uploaded. If something is wrong, delete the existing receipt and upload a new photo.
            </span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-red-700 hover:underline self-start sm:self-center min-h-[44px] sm:min-h-0"
            >
              Dismiss
            </button>
          </div>
        )}
        {/* 失败/需人工：bookkeeper 升级提示 */}
        {(uploadError || (uploadResult && uploadResult.success === false && uploadResult.error !== 'duplicate_receipt')) && (
          <div className="mb-4 p-3 sm:p-4 bg-amber-50 border border-amber-200 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <p className="text-amber-900 font-medium text-sm sm:text-base mb-1">The bookkeeper had questions and escalated.</p>
              <p className="text-amber-800 text-sm">You can close this page and come back later — we’ll have it ready when they’re done.</p>
            </div>
            <button
              type="button"
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-amber-800 hover:text-amber-900 font-medium text-sm px-3 py-1.5 rounded border border-amber-300 hover:bg-amber-100 shrink-0"
              aria-label="Dismiss"
            >
              Dismiss
            </button>
          </div>
        )}
        {uploadError && (
          <div className="mb-4 p-3 sm:p-4 bg-red-50 border border-red-200 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <span className="text-red-800 text-sm whitespace-pre-wrap min-w-0 break-words">{uploadError}</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-red-700 hover:underline self-start sm:self-center min-h-[44px] sm:min-h-0"
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
                                  {r.chain_name || (r.store_name ? toTitleCaseStore(r.store_name) : '') || r.store_name || 'Unknown store'}
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
                                <div className="relative bg-white border border-gray-200 rounded-lg overflow-hidden flex flex-col min-h-0">
                                  {(() => {
                                    const rec = expandedReceiptJson?.data?.receipt
                                    const items = expandedReceiptJson?.data?.items || []
                                    const chainName = expandedReceiptJson?.data?.chain_name
                                    const $ = (v: any) => (v == null || v === '' ? null : String(v))
                                    const money = (v: any) => {
                                      if (v == null || v === '') return null
                                      const n = Number(v)
                                      if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
                                      return Number.isFinite(n) ? n.toFixed(2) : String(v)
                                    }
                                    if (!rec && items.length === 0) return <span>(No data)</span>
                                    // 左侧店名与编辑框一致：统一用 toTitleCaseStore，避免 API 未 title case 时仍显示全大写
                                    const rawFromApi = rec?.merchant_name ?? ''
                                    const displayName = chainName || (rawFromApi ? toTitleCaseStore(rawFromApi) : '') || rawFromApi || ''
                                    const rawAddress = $(rec?.merchant_address)
                                    const addressLines = rawAddress ? rawAddress.split(/\r?\n/).map((l: string) => l.trim()).filter(Boolean) : []
                                    const lastLine = addressLines[addressLines.length - 1]
                                    const isCountryOnly = lastLine && /^[A-Z]{2}$/i.test(lastLine)
                                    const address = addressLines.length
                                      ? isCountryOnly && addressLines.length >= 2
                                        ? [...addressLines.slice(0, -2), addressLines[addressLines.length - 2] + ' ' + lastLine].join('\n')
                                        : addressLines.join('\n')
                                      : ''
                                    return (
                                      <>
                                      {/*
                                        视觉两栏，结构5块：
                                          [左上: 店铺信息] [右上: 分类头]
                                          [中间: 全宽8列表，第4-5列之间有空列做分隔线]
                                          [左下: 小计/支付] [右下: 消息/空]
                                        Edit 面板覆盖右半（absolute left-1/2 ... right-0）
                                      */}
                                      <div className="relative bg-white border border-gray-200 rounded-lg overflow-hidden font-mono text-sm text-gray-800">
                                        {/*
                                          统一 CSS Grid：10 列 = [product(2fr) | qty(3rem) | unit$(4rem) | $amt(5.5rem) | sep(8px) | lvlI(1fr) | lvlII(1fr) | lvlIII(1fr) | checkbox(2rem) | edit(2.5rem)]
                                          所有行（header/col-labels/items/footer）共用同一个 grid container，分隔线位置数学上完全一致。
                                          头行和尾行：左侧 col-span-4，sep 1列，右侧 col-span-5。
                                        */}
                                        <div
                                          className="grid overflow-x-auto"
                                          style={{ gridTemplateColumns: 'minmax(0,2fr) 3rem 4rem 5.5rem 8px minmax(0,1fr) minmax(0,1fr) minmax(0,1fr) 2rem 2.5rem' }}
                                        >
                                          {/* ① 左上：店铺信息 + Edit Fields | sep | 右上：Classification + Smart */}
                                          <div className="col-span-4 p-4 border-b border-gray-200 flex items-start justify-between gap-2">
                                            <div className="text-gray-800 whitespace-pre-line leading-5 min-w-0">
                                              {displayName && <span className="font-semibold">{displayName}</span>}
                                              {address && <>{'\n'}<span className="text-gray-600">{address}</span></>}
                                              {rec?.merchant_phone && <>{'\n'}<span className="text-gray-600">Tel: {rec.merchant_phone}</span></>}
                                            </div>
                                            <button
                                              type="button"
                                              className="shrink-0 text-sm text-gray-700 bg-gray-200 hover:bg-gray-300 px-2.5 py-1 rounded border border-gray-300 whitespace-nowrap ml-2"
                                              onClick={(e) => { e.stopPropagation(); setCorrectionOpen((o) => !o) }}
                                            >
                                              {correctionOpen ? 'Hide Edits' : 'Edit Fields'}
                                            </button>
                                          </div>
                                          <div className="border-b border-l border-r border-gray-200 bg-gray-100" />
                                          <div className="col-span-5 p-4 border-b border-gray-200 bg-gray-50/50 flex items-center">
                                            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Classification</p>
                                          </div>

                                          {/* ② 列标签行：大写加粗，无分割线 */}
                                          <div className="py-1.5 px-3 text-xs text-gray-700 font-semibold uppercase">Product</div>
                                          <div className="py-1.5 pl-3 pr-2 text-xs text-gray-700 font-semibold uppercase text-center">Qty</div>
                                          <div className="py-1.5 pl-3 pr-2 text-xs text-gray-700 font-semibold uppercase text-right">Unit $</div>
                                          <div className="py-1.5 pl-3 pr-2 text-xs text-gray-700 font-semibold uppercase text-right">$ Amount</div>
                                          <div className="bg-gray-100" />
                                          <div className="py-1.5 px-3 text-xs text-gray-700 font-semibold uppercase">Level I</div>
                                          <div className="py-1.5 px-2 text-xs text-gray-700 font-semibold uppercase">Level II</div>
                                          <div className="py-1.5 px-2 text-xs text-gray-700 font-semibold uppercase">Level III</div>
                                          <div className="py-1.5 px-1 flex items-center justify-center" title="Select for Smart Categorization" />
                                          <div />

                                          {/* ③ item 行：每个 React.Fragment 贡献 9 个 grid 子元素 */}
                                          {items.length === 0 && (
                                            <React.Fragment>
                                              <div className="col-span-4 px-3 py-3 text-gray-400 text-sm">No items</div>
                                              <div className="bg-gray-100" />
                                              <div className="col-span-5" />
                                            </React.Fragment>
                                          )}
                                          {items.map((it: any, i: number) => {
                                            const name = it.product_name ?? it.original_product_name ?? ''
                                            const qty = it.quantity != null ? (typeof it.quantity === 'number' ? it.quantity : Number(it.quantity)) : 1
                                            const u = it.unit_price != null ? (money(it.unit_price) ?? it.unit_price) : ''
                                            const p = it.line_total != null ? (money(it.line_total) ?? it.line_total) : ''
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
                                            const cancelEdit = () => { setEditingItemId(null); setCategoryUpdateMessage(null) }
                                            const confirmEdit = async () => {
                                              if (!expandedReceiptId || !token) return
                                              setCategoryUpdateMessage(null)
                                              const toSend = editCatL3 || editCatL2 || editCatL1 || null
                                              try {
                                                const res = await fetch(`${apiUrl()}/api/receipt/${expandedReceiptId}/item/${itemId}/category`, {
                                                  method: 'PATCH',
                                                  headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                  body: JSON.stringify({ category_id: toSend }),
                                                })
                                                if (res.ok) {
                                                  setCategoryUpdateMessage('Saved')
                                                  await refetchReceiptDetail()
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
                                              <React.Fragment key={itemId ?? i}>
                                                <div className="py-1.5 px-3 truncate min-w-0 text-gray-800" title={name}>{name}</div>
                                                <div className="py-1.5 pl-3 pr-2 text-center tabular-nums">{Number.isFinite(qty) ? qty : ''}</div>
                                                <div className="py-1.5 pl-3 pr-2 text-right tabular-nums">{u}</div>
                                                <div className="py-1.5 pl-3 pr-2 text-right tabular-nums">{p}</div>
                                                <div className="bg-gray-100" />
                                                <div className="py-1.5 px-3">
                                                  {isEditing ? (
                                                    <select className="border rounded px-1 py-0.5 text-xs w-full" value={editCatL1} onChange={(e) => { setEditCatL1(e.target.value); setEditCatL2(''); setEditCatL3('') }}><option value="">—</option>{L1List.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                                                  ) : (
                                                    <span className="truncate block text-gray-800" title={c1}>{c1}</span>
                                                  )}
                                                </div>
                                                <div className="py-1.5 px-2">
                                                  {isEditing ? (
                                                    <select className="border rounded px-1 py-0.5 text-xs w-full" value={editCatL2} onChange={(e) => { setEditCatL2(e.target.value); setEditCatL3('') }}><option value="">—</option>{L2List.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                                                  ) : (
                                                    <span className="truncate block text-gray-800" title={c2}>{c2}</span>
                                                  )}
                                                </div>
                                                <div className="py-1.5 px-2">
                                                  {isEditing ? (
                                                    <select className="border rounded px-1 py-0.5 text-xs w-full" value={editCatL3} onChange={(e) => setEditCatL3(e.target.value)}><option value="">—</option>{L3List.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                                                  ) : (
                                                    <span className="truncate block text-gray-800" title={c3}>{c3}</span>
                                                  )}
                                                </div>
                                                <div className="py-1.5 px-1 flex items-center justify-center">
                                                  <label className="relative cursor-pointer flex items-center justify-center w-5 h-5 rounded border border-gray-300 bg-white has-[:checked]:bg-green-600 has-[:checked]:border-green-600">
                                                    <input
                                                      type="checkbox"
                                                      checked={smartCategorizeSelectedIds.has(itemId)}
                                                      onChange={(e) => {
                                                        setSmartCategorizeSelectedIds((prev) => {
                                                          const next = new Set(prev)
                                                          if (e.target.checked) next.add(itemId)
                                                          else next.delete(itemId)
                                                          return next
                                                        })
                                                      }}
                                                      className="sr-only peer"
                                                    />
                                                    <span className="absolute inset-0 flex items-center justify-center pointer-events-none select-none text-white text-xs font-bold opacity-0 peer-checked:opacity-100">✓</span>
                                                  </label>
                                                </div>
                                                <div className="py-1.5 px-2 flex items-center">
                                                  {isEditing ? (
                                                    <div className="flex items-center gap-0.5">
                                                      <button type="button" className="p-1 bg-green-100 text-green-800 rounded hover:bg-green-200" onClick={confirmEdit} title="Confirm">✓</button>
                                                      <button type="button" className="p-1 bg-gray-200 text-gray-700 rounded hover:bg-gray-300" onClick={cancelEdit} title="Cancel">✕</button>
                                                    </div>
                                                  ) : (
                                                    <button type="button" className="p-1 text-gray-600 hover:text-gray-900 hover:bg-gray-200 rounded" onClick={startEdit} title="Edit">✏️</button>
                                                  )}
                                                </div>
                                              </React.Fragment>
                                            )
                                          })}

                                          {/* ④ 左下：小计/支付 | sep | ⑤ 右下：消息/空 */}
                                          <div className="col-span-4 p-4 border-t border-gray-200">
                                            {rec && (
                                              <>
                                                {/* 用与左侧4列相同的列宽做子网格，让数字对齐 $ Amount 列 */}
                                                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) 3rem 4rem 5.5rem' }}>
                                                  <div>Subtotal</div><div /><div />
                                                  <div className="text-right tabular-nums">{rec.subtotal != null ? `$${money(rec.subtotal) ?? rec.subtotal}` : ''}</div>
                                                  <div>Tax</div><div /><div />
                                                  <div className="text-right tabular-nums">{rec.tax != null ? `$${money(rec.tax) ?? rec.tax}` : ''}</div>
                                                  <div className="font-medium">Total</div><div /><div />
                                                  <div className="text-right tabular-nums font-medium">{rec.total != null ? `$${money(rec.total) ?? rec.total}` : ''}</div>
                                                </div>
                                                <div className="border-t border-dashed border-gray-300 my-2 pt-2" />
                                                {$(rec.payment_method) && <div>Payment: {rec.payment_method}</div>}
                                                {$(rec.card_last4) && <div>Payment Card: {rec.payment_method ? `${rec.payment_method} ` : ''}****{String(rec.card_last4).replace(/\D/g, '').slice(-4) || rec.card_last4}</div>}
                                                {$(rec.purchase_date) && <div>Date: {rec.purchase_date}</div>}
                                                {(editPurchaseTime?.trim() || $(rec.purchase_time)) && <div>Time: {formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '')}</div>}
                                              </>
                                            )}
                                          </div>
                                          <div className="border-t border-gray-200 bg-gray-100" />
                                          <div className="col-span-5 p-4 border-t border-gray-200 flex flex-col gap-2">
                                            <div className="flex items-start gap-3">
                                              <span className="text-sm text-gray-900 whitespace-nowrap font-medium pt-0.5">Run Smart Categorization on</span>
                                              <div className="flex flex-col gap-1 w-36 shrink-0 ml-auto">
                                                <button
                                                  type="button"
                                                  disabled={smartCategorizeLoading || smartCategorizeSelectedIds.size === 0}
                                                  onClick={async () => {
                                                    if (!expandedReceiptId || !token || smartCategorizeSelectedIds.size === 0) return
                                                    setSmartCategorizeLoading(true)
                                                    setSmartCategorizeMessage(null)
                                                    try {
                                                      const res = await fetch(`${apiUrl()}/api/receipt/${expandedReceiptId}/smart-categorize`, {
                                                        method: 'POST',
                                                        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                        body: JSON.stringify({ item_ids: Array.from(smartCategorizeSelectedIds) }),
                                                      })
                                                      const data = await res.json().catch(() => ({}))
                                                      if (res.ok) {
                                                        setSmartCategorizeMessage(data.updated_count != null ? `Updated ${data.updated_count} item(s)` : (data.message || 'Done'))
                                                        setSmartCategorizeSelectedIds(new Set())
                                                        await refetchReceiptDetail()
                                                      } else setSmartCategorizeMessage(data.detail || 'Failed')
                                                    } catch (e) { setSmartCategorizeMessage('Network error') }
                                                    finally { setSmartCategorizeLoading(false) }
                                                  }}
                                                  className="w-full text-sm text-gray-700 bg-gray-200 hover:bg-gray-300 px-3 py-1 rounded border border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed text-center"
                                                >
                                                  {smartCategorizeLoading ? 'Running…' : 'Selected Only'}
                                                </button>
                                                <button
                                                  type="button"
                                                  disabled={smartCategorizeLoading}
                                                  onClick={async () => {
                                                    if (!expandedReceiptId || !token) return
                                                    setSmartCategorizeLoading(true)
                                                    setSmartCategorizeMessage(null)
                                                    try {
                                                      const res = await fetch(`${apiUrl()}/api/receipt/${expandedReceiptId}/smart-categorize`, {
                                                        method: 'POST',
                                                        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                        body: JSON.stringify({}),
                                                      })
                                                      const data = await res.json().catch(() => ({}))
                                                      if (res.ok) {
                                                        setSmartCategorizeMessage(data.updated_count != null ? `Updated ${data.updated_count} item(s)` : (data.message || 'Done'))
                                                        await refetchReceiptDetail()
                                                      } else setSmartCategorizeMessage(data.detail || 'Failed')
                                                    } catch (e) { setSmartCategorizeMessage('Network error') }
                                                    finally { setSmartCategorizeLoading(false) }
                                                  }}
                                                  className="w-full text-sm text-gray-700 bg-gray-200 hover:bg-gray-300 px-3 py-1 rounded border border-gray-300 disabled:opacity-50 disabled:cursor-not-allowed text-center"
                                                >
                                                  {smartCategorizeLoading ? 'Running…' : 'All'}
                                                </button>
                                              </div>
                                            </div>
                                            {(categoryUpdateMessage || smartCategorizeMessage) && (
                                              <div className={`text-xs ${(categoryUpdateMessage || smartCategorizeMessage) === 'Saved' || (smartCategorizeMessage && smartCategorizeMessage.startsWith('Updated')) ? 'text-green-600' : 'text-red-600'}`}>
                                                {categoryUpdateMessage || smartCategorizeMessage}
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                        {/* Edit panel: 覆盖右侧半块 */}
                                        <div
                                          className={`absolute left-1/2 top-0 right-0 bottom-0 z-10 flex flex-col bg-white border-l border-gray-200 shadow-lg transition-transform duration-200 ease-out ${correctionOpen ? 'translate-x-0' : 'translate-x-full'}`}
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
                                            <span className="text-xs text-gray-500">Purchase time (optional, 24-hour only, e.g. 15:34)</span>
                                            <input type="text" className="border rounded px-2 py-1 text-sm font-mono" placeholder="15:34" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} maxLength={5} />
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
                                          <div className="max-h-48 overflow-auto border border-gray-200 rounded">
                                            <table className="w-full border-collapse text-sm">
                                              <thead>
                                                <tr className="text-xs text-gray-500 font-medium bg-gray-50 border-b border-gray-200">
                                                  <th className="text-left py-1.5 px-2 font-normal">Product name</th>
                                                  <th className="text-left py-1.5 px-2 w-16">Qty</th>
                                                  <th className="text-left py-1.5 px-2 w-20">Unit pr</th>
                                                  <th className="text-left py-1.5 px-2 w-20">$ Amount</th>
                                                </tr>
                                              </thead>
                                              <tbody>
                                                {editItems.map((row, idx) => (
                                                  <tr key={idx} className="border-b border-gray-100 last:border-0">
                                                    <td className="py-1 px-2"><input className="w-full min-w-[120px] border rounded px-1.5 py-0.5" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input type="text" inputMode="numeric" className="w-full border rounded px-1.5 py-0.5" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input className="w-full border rounded px-1.5 py-0.5" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input className="w-full border rounded px-1.5 py-0.5" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} /></td>
                                                  </tr>
                                                ))}
                                              </tbody>
                                            </table>
                                          </div>
                                          <button type="button" className="mt-2 text-sm text-blue-600 hover:underline" onClick={() => setEditItems((prev) => [...prev, { product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])}>
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
                                              setUploadResult(null)
                                              setUploadError(null)
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
                                </>
                                );
                                  })()}
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
                                          const res = await fetch(`${apiUrl()}/api/receipt/${r.id}/processing-runs`, {
                                            headers: { Authorization: `Bearer ${token}` },
                                          })
                                          if (res.ok) {
                                            const data = await res.json()
                                            setProcessingRunsData({ track: data.track ?? 'unknown', track_method: data.track_method ?? null, runs: data.runs ?? [], workflow_steps: data.workflow_steps ?? [] })
                                          } else {
                                            setProcessingRunsData({ track: 'unknown', track_method: null, runs: [], workflow_steps: [] })
                                          }
                                        } catch {
                                          setProcessingRunsData({ track: 'unknown', track_method: null, runs: [], workflow_steps: [] })
                                        } finally {
                                          setProcessingRunsLoading(false)
                                        }
                                      }}
                                      className="text-sm text-blue-600 hover:text-blue-800 underline"
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
                <h3 className="font-semibold text-gray-900">Processing workflow — Receipt {processingRunsModalReceiptId.slice(0, 8)}…</h3>
                <button type="button" onClick={() => { setProcessingRunsModalReceiptId(null); setProcessingRunsData(null) }} className="text-gray-500 hover:text-gray-700 text-lg leading-none">×</button>
              </div>
              <div className="p-4 overflow-auto flex-1 min-h-0">
                {processingRunsLoading ? (
                  <p className="text-gray-500">Loading…</p>
                ) : processingRunsData ? (
                  <>
                    <div className="mb-4 p-3 bg-gray-100 rounded">
                      <p className="text-sm font-medium text-gray-700">Track</p>
                      <p className="text-sm text-gray-900">
                        {processingRunsData.track === 'specific_rule' ? (
                          <>Specific rule (method: <code className="bg-white px-1 rounded">{processingRunsData.track_method ?? '—'}</code>)</>
                        ) : processingRunsData.track === 'general' ? (
                          <>General track (no store-specific rule matched)</>
                        ) : (
                          <>Unknown (no rule_based_cleaning run or failed)</>
                        )}
                      </p>
                    </div>
                    {Array.isArray(processingRunsData.workflow_steps) && processingRunsData.workflow_steps.length > 0 && (
                      <div className="mb-4">
                        <p className="text-sm font-medium text-gray-700 mb-2">Workflow path ({processingRunsData.workflow_steps.length} steps)</p>
                        <div className="rounded border border-gray-200 bg-gray-50 p-2 flex flex-wrap gap-2">
                          {(processingRunsData.workflow_steps as Array<Record<string, unknown>>).map((s: Record<string, unknown>, i: number) => {
                            const r = String(s.result ?? '')
                            const resultClass = r === 'pass' || r === 'ok' || r === 'yes' ? 'text-green-600' : r === 'fail' || r === 'no' ? 'text-red-600' : 'text-gray-600'
                            return (
                              <span key={String(s.id ?? i)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-mono bg-white border border-gray-200" title={s.details ? JSON.stringify(s.details) : undefined}>
                                <span className="text-gray-500">{Number(s.sequence) + 1}.</span>
                                <span className="font-medium">{String(s.step_name ?? '')}</span>
                                <span className={resultClass}>{r}</span>
                              </span>
                            )
                          })}
                        </div>
                      </div>
                    )}
                    <p className="text-sm font-medium text-gray-700 mb-2">Runs ({processingRunsData.runs.length})</p>
                    <div className="space-y-3">
                      {processingRunsData.runs.map((run: Record<string, unknown>, idx: number) => (
                        <ProcessingRunCard key={String(run.id ?? idx)} run={run} />
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-gray-500">No data</p>
                )}
              </div>
            </div>
          </div>
        )}
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
    <div className="border rounded p-3 bg-gray-50">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{stage}</span>
        <span className={status === 'pass' ? 'text-green-600' : 'text-red-600'}>{status}</span>
        {validation && <span className="text-gray-500">validation: {validation}</span>}
        {provider && <span className="text-gray-500">{provider}{model ? ` / ${model}` : ''}</span>}
        <span className="text-gray-400" suppressHydrationWarning>{created}</span>
      </div>
      {err && <p className="text-xs text-red-600 mt-1">{err}</p>}
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={() => setShowInput((v) => !v)} className="text-xs text-blue-600 hover:underline">
          {showInput ? 'Hide' : 'Show'} input_payload
        </button>
        <button type="button" onClick={() => setShowOutput((v) => !v)} className="text-xs text-blue-600 hover:underline">
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
