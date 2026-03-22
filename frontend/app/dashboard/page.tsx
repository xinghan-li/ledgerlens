'use client'

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { getFirebaseAuth, getAuthToken } from '@/lib/firebase'
import { formatTimeToHHmm, toTitleCaseStore } from '@/lib/utils'
import { onAuthStateChanged } from 'firebase/auth'
import dynamic from 'next/dynamic'
const DataAnalysisSection = dynamic(() => import('./DataAnalysisSection'), {
  loading: () => <div className="bg-white rounded-xl shadow p-6 mb-6 animate-pulse h-64" />,
  ssr: false,
})
import { CameraCaptureButton } from './camera'
import { useApiUrl } from '@/lib/api-url-context'
import { useAuth, authFetch } from '@/lib/auth-context'
import { useDashboardActions } from './dashboard-actions-context'
import CategoryTreeSelector from './CategoryTreeSelector'
import SystemCategorySubSelector from './SystemCategorySubSelector'

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

/** Item as returned by the receipt detail API. */
type ReceiptItem = {
  id?: string
  product_name?: string | null
  original_product_name?: string | null
  quantity?: number | string | null
  unit?: string | null
  unit_price?: number | string | null
  line_total?: number | string | null
  on_sale?: boolean
  original_price?: number | string | null
  discount_amount?: number | string | null
  user_category_path?: string | null
  category_path?: string | null
  category_id?: string | null
  user_category_id?: string | null
  categorization_source?: string | null
}

/** Item in the local edit form state (all monetary values as dollar strings for inputs). */
type EditableReceiptItem = {
  _key: string
  id?: string
  product_name: string
  quantity: string
  unit: string
  unit_price: string
  line_total: string
  on_sale: boolean
  original_price: string
  discount_amount: string
}

export default function DashboardPage() {
  const apiBaseUrl = useApiUrl()
  const auth = useAuth()
  const token = auth?.token ?? null
  const [userEmail, setUserEmail] = useState<string | null>(null)
  const [userName, setUserName] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [sessionRefreshedHint, setSessionRefreshedHint] = useState(false)
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
  /** Edit mode: when set, user can click sections to edit inline. Toggle replaces former Edit Fields / Hide Edits. */
  const [editModeReceiptId, setEditModeReceiptId] = useState<string | null>(null)
  /** Which section is currently in "editing" state (showing inputs). */
  const [editingSection, setEditingSection] = useState<{ receiptId: string; section: 'store' | 'address' | 'item' | 'classification' | 'payment_date'; index?: number } | null>(null)
  const [editStoreName, setEditStoreName] = useState('')
  const [editAddressLine1, setEditAddressLine1] = useState('')
  const [editAddressLine2, setEditAddressLine2] = useState('')
  const [editAddressCity, setEditAddressCity] = useState('')
  const [editAddressState, setEditAddressState] = useState('')
  const [editAddressZip, setEditAddressZip] = useState('')
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
  const [editItems, setEditItems] = useState<EditableReceiptItem[]>([])
  const [correctSubmitting, setCorrectSubmitting] = useState(false)
  const [correctMessage, setCorrectMessage] = useState<string | null>(null)
  const [categoriesList, setCategoriesList] = useState<Array<{ id: string; parent_id: string | null; name: string; path: string | null; level: number; is_locked?: boolean; sort_order?: number }>>([])
  const [editingItemId, setEditingItemId] = useState<string | null>(null)
  const [editCatId, setEditCatId] = useState<string | null>(null)
  /** Item ids currently in "classification edit" (multi-select); user can change category on several rows then Confirm once at bottom. */
  const [classificationEditingItemIds, setClassificationEditingItemIds] = useState<Set<string>>(new Set())
  /** Pending category id per item id (for batch confirm). */
  const [pendingCategoryByItemId, setPendingCategoryByItemId] = useState<Record<string, string | null>>({})
  /** Per-receipt: indices of item rows currently in "item edit" (quantity/price inputs). Multiple rows stay active until Confirm. */
  const [editingItemIndicesByReceipt, setEditingItemIndicesByReceipt] = useState<Record<string, number[]>>({})
  const [categoryUpdateMessage, setCategoryUpdateMessage] = useState<string | null>(null)
  const [smartCategorizeLoading, setSmartCategorizeLoading] = useState(false)
  const [smartCategorizeMessage, setSmartCategorizeMessage] = useState<string | null>(null)
  const [smartCategorizeSelectedIds, setSmartCategorizeSelectedIds] = useState<Record<string, Set<string>>>({})
  const [userClass, setUserClass] = useState<number | null>(null)
  const [processingRunsModalReceiptId, setProcessingRunsModalReceiptId] = useState<string | null>(null)
  const [processingRunsData, setProcessingRunsData] = useState<{ track: string; track_method: string | null; runs: Array<Record<string, unknown>>; workflow_steps: Array<Record<string, unknown>>; pipeline_version?: string | null } | null>(null)
  const [processingRunsLoading, setProcessingRunsLoading] = useState(false)
  const [deleteConfirmReceiptId, setDeleteConfirmReceiptId] = useState<string | null>(null)
  const [deleteConfirmLoading, setDeleteConfirmLoading] = useState(false)
  /** needs_review 小票的 LLM reasoning 是否折叠（可再展开），不隐藏 */
  const [collapsedReviewReasoningReceiptIds, setCollapsedReviewReasoningReceiptIds] = useState<Set<string>>(new Set())
  const [reviewCompleteLoading, setReviewCompleteLoading] = useState<string | null>(null)
  const [escalationReceiptId, setEscalationReceiptId] = useState<string | null>(null)
  const [escalationNotes, setEscalationNotes] = useState('')
  const [escalationSubmitting, setEscalationSubmitting] = useState(false)
  /** Index of item pending delete confirmation in edit mode */
  const [deleteConfirmItemIndex, setDeleteConfirmItemIndex] = useState<number | null>(null)

  const toggleReviewReasoningCollapsed = useCallback((receiptId: string) => {
    setCollapsedReviewReasoningReceiptIds((prev) => {
      const s = new Set(prev)
      if (s.has(receiptId)) s.delete(receiptId)
      else s.add(receiptId)
      return s
    })
  }, [])
  const [mobileReceiptViewMode, setMobileReceiptViewMode] = useState<'receipt' | 'classification'>('receipt')
  const [mobileReceiptVisibleCount, setMobileReceiptVisibleCount] = useState(5)
  const [desktopReceiptVisibleCount, setDesktopReceiptVisibleCount] = useState(10)
  const router = useRouter()
  const { setActions, setBannerInView } = useDashboardActions()
  const cameraTriggerRef = useRef<HTMLButtonElement>(null)
  // Use state-based ref so the IntersectionObserver effect re-runs when the element actually mounts
  const [welcomeBannerEl, setWelcomeBannerEl] = useState<HTMLDivElement | null>(null)

  const selectedIdsForReceipt = (receiptId: string) => smartCategorizeSelectedIds[receiptId] ?? new Set<string>()
  const setSelectedIdsForReceipt = useCallback((receiptId: string, setter: (prev: Set<string>) => Set<string>) => {
    setSmartCategorizeSelectedIds((prev) => ({ ...prev, [receiptId]: setter(prev[receiptId] ?? new Set()) }))
  }, [])

  useEffect(() => {
    processingCountRef.current = processingCount
  }, [processingCount])

  // Parallel data fetch: auth/me + receipt list + categories all fire at once
  useEffect(() => {
    if (!token) {
      setUserClass(null)
      setUserName(null)
      return
    }
    let cancelled = false
    // 1) auth/me
    fetch(`${apiBaseUrl}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) {
          setUserClass(data.user_class ?? null)
          setUserName(data.username ?? null)
        }
      })
      .catch(() => { if (!cancelled) setUserClass(null); if (!cancelled) setUserName(null) })
    // 2) receipt list (in parallel)
    fetchReceiptList()
    // 3) categories (in parallel)
    fetchCategories()
    return () => { cancelled = true }
  }, [token]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setActions({
      onReceiptHistory: () => document.getElementById('receipt-history-section')?.scrollIntoView({ behavior: 'smooth' }),
      onUpload: () => document.getElementById('receipt-upload')?.click() ?? undefined,
      onCamera: () => cameraTriggerRef.current?.click(),
    })
    return () => setActions(null)
  }, [setActions])

  useEffect(() => {
    if (!welcomeBannerEl) return
    const io = new IntersectionObserver(
      (entries) => {
        const e = entries[0]
        if (e) setBannerInView(e.isIntersecting)
      },
      { threshold: 0, rootMargin: '0px' }
    )
    io.observe(welcomeBannerEl)
    return () => io.disconnect()
  }, [welcomeBannerEl, setBannerInView])

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

  /** 拆解 "City, ST ZIP" 格式为三个独立字段 */
  function parseCityStateZip(s: string): { city: string; state: string; zip: string } {
    const m = (s || '').trim().match(/^(.+?),?\s+([A-Za-z]{1,3})\s+(\S+)$/)
    if (m) return { city: m[1].trim(), state: m[2].trim(), zip: m[3].trim() }
    return { city: (s || '').trim(), state: '', zip: '' }
  }

  /** 根据邮编推断国家：加拿大 N0N 0N0 格式 / 美国 5 位或 9 位邮编 */
  function inferCountryFromPostal(cityStateZip: string): string {
    if (!(cityStateZip || '').trim()) return ''
    const s = cityStateZip.trim()
    if (/\b[A-Za-z][0-9][A-Za-z]\s*[0-9][A-Za-z][0-9]\b/i.test(s)) return 'Canada'
    if (/\b\d{5}(-\d{4})?\b/.test(s)) return 'US'
    return ''
  }

  /** 将 reasoning 文本按 Date/time、Item Count、Sum Check 等分段，拆成可读的 bullet 行 */
  function parseReasoningBullets(raw: string): { title: string; bullets: string[] } {
    const text = (raw || '').replace(/\r\n/g, '\n').trim()
    const withoutReasoning = text.replace(/^Reasoning\s*[:：]\s*/i, '').trim()
    const sectionPattern = /(?=Date\/time\s*[:：]|Item\s+count\s*[:：]|Sum\s+check\s*[:：])/gi
    const parts = withoutReasoning.split(sectionPattern).map((s) => s.trim().replace(/^\s*[•]\s*/, '')).filter(Boolean)
    if (parts.length > 1) return { title: 'Reasoning:', bullets: parts }
    const lines = withoutReasoning.split(/\r?\n/).map((s) => s.trim().replace(/^\s*[•]\s*/, '')).filter(Boolean)
    return { title: 'Reasoning:', bullets: lines }
  }

  /** 展示用地址：line1, line2, cityStateZip + 空格 + country（US/CA 在邮编右侧空一格）；不单独一行 country */
  function formatAddressForDisplay(addr: string): string {
    const fields = parseAddressToFields(addr || '')
    let country = (fields.country || '').trim()
    if (!country && fields.cityStateZip) country = inferCountryFromPostal(fields.cityStateZip)
    const parts: string[] = []
    if (fields.line2 && fields.line1) parts.push(`${fields.line2} - ${fields.line1}`)
    else if (fields.line1) parts.push(fields.line1)
    else if (fields.line2) parts.push(fields.line2)
    if (fields.cityStateZip) parts.push(country ? `${fields.cityStateZip} ${country}` : fields.cityStateZip)
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
    const csz = parseCityStateZip(addrFields.cityStateZip)
    setEditAddressCity(csz.city)
    setEditAddressState(csz.state)
    setEditAddressZip(csz.zip)
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
    const toDollarItem = (v: any) => {
      if (v == null || v === '') return ''
      const n = Number(v)
      if (Number.isInteger(n) && n >= 100) return (n / 100).toFixed(2)
      return String(v)
    }
    setEditItems(
      items.length
        ? items.map((it: ReceiptItem, idx: number) => ({
            _key: it.id ?? `item_${idx}`,
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
        : [{ _key: 'item_0', product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }]
    )
    setShowRawJson(false)
    setCorrectMessage(null)
  }

  const fetchReceiptList = useCallback(async () => {
    if (!auth?.token) return
    setReceiptListLoading(true)
    try {
      const res = await authFetch(
        apiBaseUrl,
        '/api/receipt/list?limit=50&offset=0',
        { headers: {} },
        auth
      )
      if (res.ok) {
        const data = await res.json()
        setReceiptList(data.data || [])
      } else if (res.status === 401) {
        setSessionRefreshedHint(true)
        setTimeout(() => setSessionRefreshedHint(false), 5000)
      }
    } catch (e) {
      console.error('Failed to fetch receipt list:', e)
    } finally {
      setReceiptListLoading(false)
    }
  }, [apiBaseUrl, auth])

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (!user) {
        setUserEmail(null)
        setUserName(null)
        setLoading(false)
        router.push('/login')
        return
      }
      setUserEmail(user.email ?? null)
      setLoading(false)
    })
    return () => unsubscribe()
  }, [router])

  // Receipt list fetch is now in the parallel data fetch effect above

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
    if (message.includes('Session updated')) {
      setSessionRefreshedHint(true)
      setTimeout(() => setSessionRefreshedHint(false), 5000)
    }
  }, [clearCameraUploadTimers])

  const fetchCategories = useCallback(async () => {
    if (!auth?.token) return
    try {
      const res = await authFetch(apiBaseUrl, '/api/categories', { headers: {} }, auth)
      if (res.ok) {
        const json = await res.json()
        setCategoriesList(json?.data ?? [])
      }
    } catch (_) {}
  }, [apiBaseUrl, auth])

  // Categories initial fetch is now in the parallel data fetch effect above
  // Refetch categories when opening classification editor so user-created sub-categories from /dashboard/categories are visible
  useEffect(() => {
    if (editingSection?.section === 'classification') fetchCategories()
  }, [editingSection?.section, editingSection?.receiptId, editingSection?.index, fetchCategories])

  const createCategory = useCallback(
    async (parentId: string, name: string) => {
      if (!auth?.token) return null
      try {
        const res = await authFetch(
          apiBaseUrl,
          '/api/me/categories',
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parent_id: parentId, name: name.trim() }) },
          auth
        )
        if (!res.ok) return null
        const row = await res.json()
        if (!row?.id) return null
        return {
          id: row.id,
          parent_id: row.parent_id ?? null,
          name: row.name ?? '',
          path: row.path ?? null,
          level: row.level ?? 2,
          is_locked: row.is_locked,
          sort_order: row.sort_order,
        }
      } catch {
        return null
      }
    },
    [apiBaseUrl, auth]
  )

  const refetchReceiptDetail = useCallback(
    async (receiptId: string) => {
      if (!receiptId || !auth?.token) return
      try {
        const res = await authFetch(apiBaseUrl, `/api/receipt/${receiptId}`, { headers: {} }, auth)
        if (res.ok) {
          const json = await res.json()
          setExpandedReceiptData((prev) => ({ ...prev, [receiptId]: json }))
        } else if (res.status === 401) {
          setSessionRefreshedHint(true)
          setTimeout(() => setSessionRefreshedHint(false), 5000)
        }
      } catch (_) {}
    },
    [apiBaseUrl, auth]
  )

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) {
      e.target.value = ''
      return
    }
    const requestToken = auth ? (await getAuthToken(true)) ?? auth.token : await getAuthToken()
    if (!requestToken) {
      setUploadError('Session expired. Please refresh the page and sign in again.')
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
      if (inFlightKeysRef.current.has(key)) {
        setUploadError('This image is already being uploaded.')
      } else {
        setUploadError(`Up to ${MAX_PROCESSING} receipts can be processing at once. Please wait.`)
      }
      e.target.value = ''
      return
    }

    const formData = new FormData()
    formData.append('file', file)
    const controller = new AbortController()
    uploadControllersRef.current.set(key, controller)
    const timeoutId = setTimeout(() => controller.abort(), 180000)

    try {
      let response: Response
      if (auth) {
        response = await authFetch(
          apiBaseUrl,
          '/api/receipt/workflow-vision',
          {
            method: 'POST',
            headers: {},
            body: formData,
            signal: controller.signal,
          },
          auth
        )
      } else {
        response = await fetch(`${apiBaseUrl}/api/receipt/workflow-vision`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${requestToken}` },
          body: formData,
          signal: controller.signal,
        })
      }
      clearTimeout(timeoutId)

      if (response.ok) {
        const data = await response.json()
        setUploadResult(data)
        setUploadError(null)
        fetchReceiptList()
      } else {
        let errorMessage: string
        if (response.status === 401) {
          errorMessage = 'Session expired. Please try again or refresh and sign in again.'
          setSessionRefreshedHint(true)
          setTimeout(() => setSessionRefreshedHint(false), 5000)
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
              // ignore
            }
          }
        }
        setUploadError(errorMessage)
      }
    } catch (error) {
      clearTimeout(timeoutId)
      if (!(error instanceof Error && error.name === 'AbortError' && cancelledKeysRef.current.has(key))) {
        if (error instanceof Error) {
          if (error.name === 'AbortError') {
            setUploadError('Request timed out (3 min). Check:\n1. Backend is running\n2. Network is stable\n3. Image size is not too large')
          } else if (error.message.includes('Failed to fetch') || error.message === 'Load failed' || error.message === 'Load failed.') {
            const isLocal = typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
            const tip = isLocal
              ? '请确认：(1) 后端在 ' + apiBaseUrl + ' 运行 (2) 在新标签页打开 ' + apiBaseUrl + '/health 应看到 {"status":"ok"} (3) 若后端因端口占用改到 8081，前端会自动读 backend-port.json 使用正确端口。当前 API: ' + apiBaseUrl
              : '后端暂时不可用，请稍后再试。如果持续出现，请联系管理员。当前 API: ' + apiBaseUrl
            setUploadError('无法连接后端。' + tip)
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

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-cream">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-theme-dark/90">Loading…</p>
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
        <div
          ref={setWelcomeBannerEl}
          className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-8 flex flex-col sm:flex-row sm:flex-wrap sm:items-start sm:justify-between gap-4"
        >
          <div className="flex-1 min-w-0">
            <h2 className="font-heading text-lg sm:text-xl font-semibold mb-1 sm:mb-2 text-theme-dark">Welcome back, {userName || userEmail}</h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-3 items-stretch w-full sm:w-auto">
            <div className="min-w-0 order-1 sm:order-2">
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
                className={`flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium select-none min-h-[44px] sm:min-h-0 ${processingCount >= MAX_PROCESSING ? 'cursor-not-allowed opacity-60' : 'cursor-pointer transition-opacity hover:opacity-90'}`}
                style={{ backgroundColor: '#CC785C', color: '#FAFAF7' }}
              >
                <span aria-hidden>🧾</span>
                <span>Upload Receipt</span>
              </label>
            </div>
            <div className="min-w-0 order-2 sm:order-3">
              <CameraCaptureButton
                token={token}
                auth={auth ?? undefined}
                disabled={processingCount >= MAX_PROCESSING}
                showAsProcessing={false}
                onCheckQueue={checkAndStartUpload}
                onRemoveFromQueue={removeFromQueue}
                onSuccess={handleCameraUploadSuccess}
                onError={handleCameraUploadError}
                triggerRef={cameraTriggerRef}
              />
            </div>
            <div className="min-w-0 order-3 sm:order-1">
              <button
                type="button"
                onClick={() => document.getElementById('receipt-history-section')?.scrollIntoView({ behavior: 'smooth' })}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium cursor-pointer transition-opacity hover:opacity-90 select-none min-h-[44px] sm:min-h-0 border-2 border-theme-mid/40 bg-white text-theme-dark hover:bg-theme-light-gray/50"
              >
                <span aria-hidden>🔍</span>
                <span>Receipt History</span>
              </button>
            </div>
          </div>
        </div>

        {/* Processing: phase 1 = bookkeeper working; phase 2 = when store is detected we run extra check (no hardcoded store name) */}
        {processingCount > 0 && (
          <div className="mb-4 p-4 sm:p-5 bg-theme-light-gray/50 border border-theme-orange/30 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 animate-processing-pulse">
            <div className="flex items-center gap-2 sm:gap-3">
              <span className="inline-block text-xl sm:text-2xl animate-spin select-none" aria-hidden>
                ⏳
              </span>
              <div>
                <p className="text-theme-dark font-medium text-base sm:text-lg mb-0.5">
                  {processingCount === 1
                    ? 'Bookkeeper is working hard on reviewing your receipt.'
                    : `Bookkeeper is working hard on reviewing your ${processingCount} receipts.`}
                </p>
                <p className="text-theme-orange text-sm">
                  You can upload more (up to {MAX_PROCESSING} at a time).
                  For some stores we run an extra check or may escalate to a senior processor — sit tight, this may take a minute.
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
        {/* Upload success toast: Success / Success after secondary check / Success after escalation */}
        {uploadResult?.success === true && (
          <div className="mb-4 p-3 sm:p-4 bg-green-50 border border-green-200 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <span className="text-green-800 text-sm sm:text-base min-w-0">
              ✅ {uploadResult.current_stage === 'vision_store_specific'
                ? (() => {
                    const storeLabel = (uploadResult.store_name ?? uploadResult.data?.receipt?.merchant_name ?? '').trim()
                    return storeLabel
                      ? `Success after secondary check (${storeLabel}).`
                      : 'Success after secondary check.'
                  })()
                : uploadResult.current_stage === 'vision_escalation' || uploadResult.status === 'escalation_success'
                  ? 'Success after escalation.'
                  : 'Success.'}
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
          <div className="mb-4 p-3 sm:p-4 bg-theme-red/10 border border-theme-red/30 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <span className="text-theme-red text-sm sm:text-base min-w-0">
              This receipt was already uploaded. If something is wrong, delete the existing receipt and upload a new photo.
            </span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-theme-red hover:underline self-start sm:self-center min-h-[44px] sm:min-h-0"
            >
              Dismiss
            </button>
          </div>
        )}
        {/* 失败/需人工：bookkeeper 升级提示 */}
        {(uploadError || (uploadResult && uploadResult.success === false && uploadResult.error !== 'duplicate_receipt')) && (
          <div className="mb-4 p-3 sm:p-4 bg-amber-50 border border-amber-200 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <p className="text-amber-900 font-medium text-sm sm:text-base mb-1">
                {uploadResult?.status === 'needs_review'
                  ? "Unfortunately, the senior processor couldn't resolve all questions. Please review the result and make any adjustments. Thank you."
                  : 'The bookkeeper had questions.'}
              </p>
              {uploadResult?.status !== 'needs_review' && (
              <p className="text-amber-800 text-sm">You can close this page and come back later — we’ll have it ready when they’re done.</p>
              )}
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
          <div className="mb-4 p-3 sm:p-4 bg-theme-red/10 border border-theme-red/30 rounded-lg flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <span className="text-theme-red text-sm whitespace-pre-wrap min-w-0 break-words">{uploadError}</span>
            <button
              onClick={() => { setUploadResult(null); setUploadError(null) }}
              className="text-sm text-theme-red hover:underline self-start sm:self-center min-h-[44px] sm:min-h-0"
            >
              Dismiss
            </button>
          </div>
        )}
        {/* 401 后已自动刷新 token，提示用户再试一次 */}
        {sessionRefreshedHint && (
          <div className="mb-4 p-3 sm:p-4 bg-theme-light-gray/50 border border-theme-orange/30 rounded-lg flex items-center justify-between gap-2">
            <span className="text-theme-blue text-sm">Session updated. Please try again.</span>
            <button
              type="button"
              onClick={() => setSessionRefreshedHint(false)}
              className="text-theme-orange hover:underline text-sm shrink-0"
            >
              Got it
            </button>
          </div>
        )}

        {/* Spending Analysis */}
        <DataAnalysisSection token={token} />

        {/* Receipt history */}
        <div id="receipt-history-section" className="bg-white rounded-xl shadow p-4 sm:p-6 mb-6 sm:mb-8 overflow-hidden scroll-mt-4 w-full">
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
              // Parse a date string as LOCAL time to avoid UTC-midnight → timezone-shift bug.
              // new Date("2026-01-07") is treated as UTC midnight → shows Jan 6 in PST.
              const parseDateLocal = (d: string): Date => {
                const m = d.match(/^(\d{4})-(\d{2})-(\d{2})/)
                if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
                return new Date(d)
              }
              const getStatusLabel = (r: ReceiptListItem): string => {
                if (r.current_status === 'success') {
                  if (r.current_stage === 'vision_store_specific') return 'Success after secondary check'
                  if (r.current_stage === 'vision_escalation') return 'Success after escalation'
                  return 'Success'
                }
                if (r.current_status === 'needs_review') return 'Needs review'
                if (r.current_status === 'failed') return 'Failed'
                return r.current_status || 'Processing'
              }
              const getDateKey = (r: ReceiptListItem) => {
                const d = r.receipt_date || r.uploaded_at
                if (!d) return 'Unknown'
                const date = parseDateLocal(d)
                return isNaN(date.getTime()) ? 'Unknown' : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
              }
              const formatDisplayDate = (r: ReceiptListItem) => {
                const d = r.receipt_date || r.uploaded_at
                if (!d) return r.id.slice(0, 8)
                const date = parseDateLocal(d)
                if (isNaN(date.getTime())) return r.id.slice(0, 8)
                return date.toLocaleDateString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit' })
              }
              const monthLabels: Record<string, string> = {}
              const byMonth = receiptList.reduce<Record<string, ReceiptListItem[]>>((acc, r) => {
                const key = getDateKey(r)
                if (!monthLabels[key] && key !== 'Unknown') {
                  const date = parseDateLocal(r.receipt_date || r.uploaded_at || '')
                  monthLabels[key] = date.toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
                } else if (key === 'Unknown') monthLabels[key] = 'Unknown'
                if (!acc[key]) acc[key] = []
                acc[key].push(r)
                return acc
              }, {})
              const orderedMonths = Object.keys(byMonth).sort((a, b) => (a === 'Unknown' ? 1 : b === 'Unknown' ? -1 : b.localeCompare(a)))
              const flattenedByDate = receiptList.slice().sort((a, b) => {
                const da = new Date(a.receipt_date || a.uploaded_at || 0).getTime()
                const db = new Date(b.receipt_date || b.uploaded_at || 0).getTime()
                return db - da
              })
              const visibleOnMobile = flattenedByDate.slice(0, mobileReceiptVisibleCount)
              const hasMoreOnMobile = flattenedByDate.length > mobileReceiptVisibleCount
              const byMonthVisible: Record<string, typeof receiptList> = {}
              visibleOnMobile.forEach((r) => {
                const key = getDateKey(r)
                if (!byMonthVisible[key]) byMonthVisible[key] = []
                byMonthVisible[key].push(r)
              })
              const visibleMonths = orderedMonths.filter((m) => (byMonthVisible[m]?.length ?? 0) > 0)

              // Desktop pagination: only render first N receipts
              const visibleOnDesktop = flattenedByDate.slice(0, desktopReceiptVisibleCount)
              const hasMoreOnDesktop = flattenedByDate.length > desktopReceiptVisibleCount
              const visibleDesktopIds = new Set(visibleOnDesktop.map((r) => r.id))
              return (
                <div className="space-y-6">
                  {/* 手机端：按月份分组，带分割线，仅展示最近 N 条，每次展开 5 个 */}
                  <div className="block md:hidden space-y-6">
                    {processingCount > 0 && (
                      <div className="space-y-3">
                        <div className="flex items-center gap-3 mb-2">
                          <span className="text-sm font-semibold text-theme-dark/90">Processing</span>
                          <div className="flex-1 h-px bg-theme-light-gray" />
                        </div>
                        {Array.from({ length: processingCount }, (_, i) => (
                          <div key={`processing-${i}`} className="border border-theme-light-gray rounded-lg overflow-hidden">
                            <div className="w-full px-4 py-3 flex items-center gap-3 text-left" style={{ backgroundColor: '#F0F0EB' }}>
                              <span className="inline-block animate-spin text-lg shrink-0" aria-hidden>⏳</span>
                              <span className="text-theme-mid font-medium">Processing…</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {visibleMonths.map((monthKey) => (
                      <div key={monthKey} className="space-y-3">
                        <div className="flex items-center gap-3 mb-2">
                          <span className="text-sm font-semibold text-theme-dark/90">{monthLabels[monthKey]}</span>
                          <div className="flex-1 h-px bg-theme-light-gray" />
                        </div>
                        {byMonthVisible[monthKey].map((r) => (
                      <div key={r.id} className="border border-theme-light-gray rounded-lg overflow-hidden">
                        <button
                          type="button"
                          className="w-full px-4 py-3 flex items-center justify-between text-left hover:opacity-90 transition"
                              style={{ backgroundColor: '#F0F0EB' }}
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
                          <div className="flex flex-col gap-0.5 text-left">
                            <span className="font-medium text-theme-dark">
                              {(() => { const raw = (r.chain_name || r.store_name || '').trim(); return raw ? toTitleCaseStore(raw) : 'Unknown store'; })()}
                            </span>
                            <span className="text-xs text-theme-mid">
                              {formatDisplayDate(r)}
                              <span className={`ml-1.5 px-1.5 py-0.5 rounded ${r.current_status === 'success' ? 'bg-green-100 text-green-800' : r.current_status === 'failed' || r.current_status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-theme-light-gray/50 text-theme-dark/90'}`}>
                                {getStatusLabel(r)}
                              </span>
                            </span>
                          </div>
                            <span className="text-theme-mid shrink-0">{expandedReceiptIds.has(r.id) ? '▼' : '▶'}</span>
                        </button>
                        {expandedReceiptIds.has(r.id) && !expandedReceiptData[r.id] && (
                          <div className="border-t border-theme-light-gray bg-white p-6 flex items-center justify-center min-h-[120px]">
                            <div className="animate-spin w-8 h-8 border-2 border-theme-mid border-t-transparent rounded-full" aria-hidden />
                          </div>
                        )}
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
                                      return Number.isFinite(n) ? n.toFixed(2) : String(v)
                                    }
                                    if (!rec && items.length === 0) return <span>(No data)</span>
                                    const rawFromApi = rec?.merchant_name ?? ''
                                    const displayName = chainName || (rawFromApi ? toTitleCaseStore(rawFromApi) : '') || rawFromApi || ''
                                    const rawAddress = $(rec?.merchant_address)
                                    const address = formatAddressForDisplay(rawAddress || '')
                                    return (
                                      <React.Fragment>
                                      {/* 手机端：needs_review 时 reasoning 置顶，可折叠，右侧 Review complete */}
                                      {r.current_status === 'needs_review' && (
                                        <div className="mx-4 mt-4 mb-2 p-4 rounded-lg border border-amber-200 bg-amber-50 flex flex-col gap-3">
                                          <p className="text-sm text-amber-900">Unfortunately, the senior processor couldn&apos;t resolve all questions. Please review the result and make any adjustments. Thank you.</p>
                                          {escalationReceiptId === r.id ? (
                                            <div className="flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                                              <label className="text-xs font-medium text-amber-800">Escalation notes (admin will see):</label>
                                              <textarea className="w-full min-h-[72px] border border-amber-300 rounded px-2 py-1.5 text-sm text-theme-dark" value={escalationNotes} onChange={(e) => setEscalationNotes(e.target.value)} placeholder="Describe what’s wrong or what to fix…" />
                                              <div className="flex gap-2">
                                                <button type="button" disabled={escalationSubmitting} onClick={async () => { if (!r.id || !token) return; setEscalationSubmitting(true); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/escalate`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ notes: escalationNotes }) }); const data = await res.json().catch(() => ({})); if (res.ok && data.success) { setEscalationReceiptId(null); setEscalationNotes(''); await refetchReceiptDetail(r.id); fetchReceiptList(); alert('Escalated. Admin will review.'); } else { alert(data.detail || data.message || 'Escalation failed'); } } catch { alert('Network error'); } finally { setEscalationSubmitting(false); } }} className="text-xs font-medium text-white bg-theme-orange hover:bg-theme-orange/90 px-2 py-1.5 rounded disabled:opacity-50">Submit escalation</button>
                                                <button type="button" onClick={() => { setEscalationReceiptId(null); setEscalationNotes(''); }} className="text-xs font-medium text-amber-800 bg-amber-100 hover:bg-amber-200 px-2 py-1.5 rounded border border-amber-300">Cancel</button>
                                              </div>
                                            </div>
                                          ) : (
                                          <div className="flex items-center justify-between gap-2 flex-wrap">
                                            <button type="button" onClick={(e) => { e.stopPropagation(); toggleReviewReasoningCollapsed(r.id) }} className="text-left flex-1 min-w-0 flex items-center gap-2 text-sm font-medium text-amber-800">
                                              {collapsedReviewReasoningReceiptIds.has(r.id) ? (
                                                <span aria-hidden>▶</span>
                                              ) : (
                                                <span aria-hidden>▼</span>
                                              )}
                                              <span>AI Smart Reasoning</span>
                                            </button>
                                            <button type="button" disabled={reviewCompleteLoading === r.id} onClick={async (e) => { e.stopPropagation(); if (!r.id || !token || reviewCompleteLoading) return; setReviewCompleteLoading(r.id); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/review-complete`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }); const data = await res.json().catch(() => ({})); if (res.ok && data.success) { await refetchReceiptDetail(r.id); fetchReceiptList() } else alert(data.detail || data.message || 'Failed to complete review'); } catch { alert('Network error'); } finally { setReviewCompleteLoading(null); } }} className="shrink-0 text-xs font-medium text-white bg-green-600 hover:bg-green-700 px-2 py-1.5 rounded border border-green-700 disabled:opacity-50 disabled:cursor-not-allowed">{reviewCompleteLoading === r.id ? '…' : 'Review complete'}</button>
                                          </div>
                                          )}
                                          {!collapsedReviewReasoningReceiptIds.has(r.id) && (
                                            <div className="text-sm text-amber-900 space-y-1.5">
                                              {expandedReceiptData[r.id]?.review_metadata?.reasoning && (() => {
                                                const { title, bullets } = parseReasoningBullets(String(expandedReceiptData[r.id].review_metadata.reasoning ?? ''))
                                                return (
                                                  <div>
                                                    <p className="font-medium text-amber-800">{title}</p>
                                                    {bullets.length > 0 && <ul className="list-none pl-0 space-y-0.5">{bullets.map((line: string, i: number) => <li key={i}>• {line}</li>)}</ul>}
                                                  </div>
                                                )
                                              })()}
                                              {expandedReceiptData[r.id]?.review_metadata?.sum_check_notes && expandedReceiptData[r.id].review_metadata.sum_check_notes !== (expandedReceiptData[r.id].review_metadata.reasoning || '') && <p><span className="font-medium text-amber-800">Sum check:</span> <span className="whitespace-pre-wrap">{expandedReceiptData[r.id].review_metadata.sum_check_notes}</span></p>}
                                              {(expandedReceiptData[r.id]?.review_metadata?.item_count_on_receipt != null || expandedReceiptData[r.id]?.review_metadata?.item_count_extracted != null) && <p><span className="font-medium text-amber-800">Item count:</span> receipt says {String(expandedReceiptData[r.id].review_metadata.item_count_on_receipt ?? '—')}, extracted {String(expandedReceiptData[r.id].review_metadata.item_count_extracted ?? '—')}</p>}
                                              {!(expandedReceiptData[r.id]?.review_metadata && Object.keys(expandedReceiptData[r.id].review_metadata).length > 0) && <p className="whitespace-pre-wrap">{expandedReceiptData[r.id]?.review_feedback || 'Model requested manual review.'}</p>}
                                            </div>
                                          )}
                                          {!collapsedReviewReasoningReceiptIds.has(r.id) && (
                                            <div className="flex items-center gap-3">
                                              <button type="button" onClick={(e) => { e.stopPropagation(); toggleReviewReasoningCollapsed(r.id) }} className="text-xs text-amber-700 hover:text-amber-900 underline">Collapse</button>
                                              <button type="button" onClick={(e) => { e.stopPropagation(); setEscalationReceiptId(r.id); setEscalationNotes(''); }} className="text-xs text-red-600 hover:text-red-700 hover:underline">Escalate</button>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                      <div className="p-4">
                                        <div className="bg-white rounded-lg text-sm text-theme-dark overflow-hidden p-4 space-y-4" style={{ fontFamily: "'Space Mono', 'Courier New', monospace" }}>
                                          <div className="flex items-start justify-between gap-2">
                                            <div className="flex-1 min-w-0 text-theme-dark/90 text-sm whitespace-pre-line leading-5">
                                              {editModeReceiptId === r.id && editingSection?.receiptId === r.id && editingSection?.section === 'store' ? (
                                                <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editStoreName} onChange={(e) => setEditStoreName(e.target.value)} placeholder="Store name" />
                                                  <input type="tel" className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="Telephone 000-000-0000" />
                                                </div>
                                              ) : editModeReceiptId === r.id && editingSection?.receiptId === r.id && editingSection?.section === 'address' ? (
                                                <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressLine1} onChange={(e) => setEditAddressLine1(e.target.value)} placeholder="Address line 1" />
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressLine2} onChange={(e) => setEditAddressLine2(e.target.value)} placeholder="Address line 2" />
                                                  <div className="grid gap-1" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                                                    <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressCity} onChange={(e) => setEditAddressCity(e.target.value)} placeholder="City" />
                                                    <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressState} onChange={(e) => setEditAddressState(e.target.value)} placeholder="ST" />
                                                    <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressZip} onChange={(e) => setEditAddressZip(e.target.value)} placeholder="ZIP" />
                                                  </div>
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressCountry} onChange={(e) => setEditAddressCountry(e.target.value)} placeholder="Country" />
                                                  <input type="tel" className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="Telephone 000-000-0000" />
                                                </div>
                                              ) : (
                                                <>
                                                  {editModeReceiptId === r.id ? (
                                                    <div className="space-y-1">
                                                      <div role="button" tabIndex={0} className="cursor-pointer rounded p-1 -m-1" onClick={(e) => { e.stopPropagation(); setEditingSection({ receiptId: r.id, section: 'store' }) }} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setEditingSection({ receiptId: r.id, section: 'store' }) } }}>{displayName || <span className="text-theme-mid">Store name</span>}</div>
                                                      <div role="button" tabIndex={0} className="cursor-pointer rounded p-1 -m-1" onClick={(e) => { e.stopPropagation(); setEditingSection({ receiptId: r.id, section: 'address' }) }} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setEditingSection({ receiptId: r.id, section: 'address' }) } }}>
                                                        {address || <span className="text-theme-mid">Address</span>}
                                                        {rec?.merchant_phone && (!editingSection || editingSection.receiptId !== r.id || (editingSection.section !== 'store' && editingSection.section !== 'address')) && <div className="text-theme-dark/90">Tel: {rec.merchant_phone}</div>}
                                                      </div>
                                                    </div>
                                                  ) : (
                                                    <>
                                                      {displayName && <div className="font-semibold text-theme-dark">{displayName}</div>}
                                                      {address && <div className="whitespace-pre-line text-theme-dark/90">{address}</div>}
                                                      {rec?.merchant_phone && <div className="text-theme-dark/90 mt-0.5">Tel: {rec.merchant_phone}</div>}
                                                      {!displayName && !address && !rec?.merchant_phone && <span className="text-theme-mid">No address or phone</span>}
                                                    </>
                                                  )}
                                                </>
                                              )}
                                            </div>
                                            <div className="shrink-0 flex items-center gap-2">
                                              <span className="text-xs text-theme-mid whitespace-nowrap">Edit</span>
                                              <button
                                                type="button"
                                                role="switch"
                                                aria-checked={editModeReceiptId === r.id}
                                                className={`relative inline-flex h-7 w-11 shrink-0 rounded-full border transition-colors touch-manipulation ${editModeReceiptId === r.id ? 'bg-theme-orange border-theme-orange' : 'bg-theme-light-gray border-theme-mid'}`}
                                                onClick={(e) => {
                                                  e.stopPropagation()
                                                  if (editModeReceiptId === r.id) {
                                                    setEditModeReceiptId(null)
                                                    setEditingSection(null)
                                                    setClassificationEditingItemIds(new Set())
                                                    setPendingCategoryByItemId({})
                                                    setEditingItemIndicesByReceipt((prev) => { const next = { ...prev }; delete next[r.id]; return next })
                                                  } else {
                                                    setEditModeReceiptId(r.id)
                                                    setEditingSection(null)
                                                    initEditFormFromJson(expandedReceiptData[r.id])
                                                  }
                                                }}
                                              >
                                                <span className={`inline-block h-6 w-6 rounded-full bg-white border border-theme-mid transform transition-transform ${editModeReceiptId === r.id ? 'translate-x-5' : 'translate-x-0.5'}`} style={{ marginTop: 1 }} />
                                              </button>
                                            </div>
                                          </div>
                                          {editModeReceiptId === r.id && (
                                            <p className="text-xs text-theme-mid">Tap a line to modify</p>
                                          )}
                                          <div className="flex flex-col gap-1">
                                            <div className="flex rounded-lg border border-theme-mid p-0.5 bg-theme-light-gray/50">
                                              <button type="button" className={`flex-1 py-1.5 text-sm font-medium rounded-md transition ${mobileReceiptViewMode === 'receipt' ? 'bg-white shadow text-theme-dark' : 'text-theme-dark/90'}`} onClick={() => setMobileReceiptViewMode('receipt')}>Receipt</button>
                                              <button type="button" className={`flex-1 py-1.5 text-sm font-medium rounded-md transition ${mobileReceiptViewMode === 'classification' ? 'bg-white shadow text-theme-dark' : 'text-theme-dark/90'}`} onClick={() => setMobileReceiptViewMode('classification')}>Classification</button>
                                            </div>
                                          </div>
                                          <div className="space-y-0">
                                            {(() => {
                                              // In edit mode, iterate over editItems so add/delete/reorder updates are immediately visible
                                              const displayRows = editModeReceiptId === r.id ? editItems : items
                                              if (displayRows.length === 0) return <p className="text-theme-mid text-sm">No items</p>
                                              return displayRows.map((rawIt: ReceiptItem | EditableReceiptItem, i: number) => {
                                                // For display data (category paths, etc.) look up original item by id
                                                const it = editModeReceiptId === r.id
                                                  ? (items.find((orig: ReceiptItem) => orig.id && orig.id === rawIt.id) ?? rawIt)
                                                  : rawIt
                                                const editRow = editModeReceiptId === r.id ? rawIt : null
                                                const name = editRow?.product_name || (it.product_name ?? it.original_product_name ?? '')
                                                const displayLineTotal = editRow?.line_total ?? it.line_total
                                                const qty = it.quantity != null ? (typeof it.quantity === 'number' ? it.quantity : Number(it.quantity)) : 1
                                                const u = it.unit_price != null ? (money(it.unit_price) ?? it.unit_price) : ''
                                                const unit = (it.unit ?? '').trim() || 'each'
                                                const p = displayLineTotal != null ? (money(displayLineTotal) ?? displayLineTotal) : ''
                                                const path = (it.user_category_path ?? it.category_path ?? '').trim()
                                                const parts = path ? path.split(/\s*[\/>\|]\s*/).map((s: string) => s.trim()).filter(Boolean) : []
                                                const catLine = parts.length ? parts.join(' / ') : '—'
                                                const catL1L2 = parts.length >= 2 ? parts.slice(0, 2).join(' / ') : catLine
                                                const catL3 = parts.length >= 3 ? parts[2] : ''
                                                const showQtyUnit = Number.isFinite(qty) && qty > 1 && (u && u !== '');
                                                const isMobileEditingItem = editModeReceiptId === r.id && (editingItemIndicesByReceipt[r.id]?.includes(i) ?? false)
                                                const mobileRowItem = editModeReceiptId === r.id && editItems[i] != null ? editItems[i] : null
                                                const activateItemRowEditMobile = () => {
                                                  setEditingItemIndicesByReceipt((prev) => ({ ...prev, [r.id]: prev[r.id]?.includes(i) ? prev[r.id] : [...(prev[r.id] || []), i] }))
                                                  setEditingSection((prev) => (prev?.receiptId === r.id && prev?.section === 'item' ? prev : { receiptId: r.id, section: 'item' }))
                                                }
                                                const isEditMode = editModeReceiptId === r.id
                                                const handleConfirmDelete = (e: React.MouseEvent) => {
                                                  e.stopPropagation()
                                                  setEditItems((prev) => prev.filter((_, idx) => idx !== i))
                                                  setEditingItemIndicesByReceipt((prev) => {
                                                    const idxs = (prev[r.id] || []).filter((x) => x !== i).map((x) => (x > i ? x - 1 : x))
                                                    return { ...prev, [r.id]: idxs }
                                                  })
                                                  setEditingSection({ receiptId: r.id, section: 'item' })
                                                  setDeleteConfirmItemIndex(null)
                                                }
                                                const handleMoveUp = (e: React.MouseEvent) => {
                                                  e.stopPropagation()
                                                  setEditItems((prev) => { const next = [...prev]; [next[i - 1], next[i]] = [next[i], next[i - 1]]; return next })
                                                  setEditingItemIndicesByReceipt((prev) => ({ ...prev, [r.id]: (prev[r.id] || []).map((x) => (x === i ? i - 1 : x === i - 1 ? i : x)) }))
                                                  setEditingSection({ receiptId: r.id, section: 'item' })
                                                }
                                                const handleMoveDown = (e: React.MouseEvent) => {
                                                  e.stopPropagation()
                                                  setEditItems((prev) => { const next = [...prev]; [next[i], next[i + 1]] = [next[i + 1], next[i]]; return next })
                                                  setEditingItemIndicesByReceipt((prev) => ({ ...prev, [r.id]: (prev[r.id] || []).map((x) => (x === i ? i + 1 : x === i + 1 ? i : x)) }))
                                                  setEditingSection({ receiptId: r.id, section: 'item' })
                                                }
                                                return (
                                                  <div key={rawIt._key ?? rawIt.id ?? i} className="flex items-start gap-2 border-b border-theme-light-gray/50 pb-2 last:border-0">
                                                    {/* iOS-style delete + reorder controls */}
                                                    {isEditMode && !isMobileEditingItem && (
                                                      <div className="shrink-0 flex flex-col items-center gap-0.5 pt-0.5" onClick={(e) => e.stopPropagation()}>
                                                        {deleteConfirmItemIndex === i ? (
                                                          <>
                                                            <button
                                                              type="button"
                                                              className="w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center text-xs font-bold leading-none touch-manipulation"
                                                              onClick={handleConfirmDelete}
                                                              aria-label="Confirm delete"
                                                              title="Confirm delete"
                                                            >✓</button>
                                                            <button
                                                              type="button"
                                                              className="text-[9px] text-theme-mid leading-none touch-manipulation"
                                                              onClick={(e) => { e.stopPropagation(); setDeleteConfirmItemIndex(null) }}
                                                            >esc</button>
                                                          </>
                                                        ) : (
                                                          <button
                                                            type="button"
                                                            className="w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center text-base font-bold leading-none touch-manipulation"
                                                            onClick={(e) => { e.stopPropagation(); setDeleteConfirmItemIndex(i) }}
                                                            aria-label="Remove item"
                                                          >−</button>
                                                        )}
                                                        {i > 0 && deleteConfirmItemIndex !== i && (
                                                          <button
                                                            type="button"
                                                            className="text-theme-mid hover:text-theme-dark text-xs leading-none touch-manipulation"
                                                            onClick={handleMoveUp}
                                                            aria-label="Move up"
                                                          >↑</button>
                                                        )}
                                                        {i < editItems.length - 1 && deleteConfirmItemIndex !== i && (
                                                          <button
                                                            type="button"
                                                            className="text-theme-mid hover:text-theme-dark text-xs leading-none touch-manipulation"
                                                            onClick={handleMoveDown}
                                                            aria-label="Move down"
                                                          >↓</button>
                                                        )}
                                                      </div>
                                                    )}
                                                    {/* Item content */}
                                                    <div
                                                      className={`flex-1 min-w-0 ${isEditMode && !isMobileEditingItem ? 'cursor-pointer rounded active:bg-theme-light-gray/30' : ''}`}
                                                      role={isEditMode && !isMobileEditingItem ? 'button' : undefined}
                                                      tabIndex={isEditMode && !isMobileEditingItem ? 0 : undefined}
                                                      onClick={(e) => { if (isEditMode && !isMobileEditingItem) { e.stopPropagation(); activateItemRowEditMobile(); } }}
                                                      onKeyDown={(e) => { if (isEditMode && !isMobileEditingItem && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); activateItemRowEditMobile(); } }}
                                                    >
                                                      {isMobileEditingItem && mobileRowItem ? (
                                                        <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                                                          <input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm inline-block box-border max-w-full" style={{ width: `${Math.max(12, Math.min(28, (mobileRowItem.product_name?.length || 0) + 2))}ch` }} value={mobileRowItem.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], product_name: e.target.value }; return n })} placeholder="Product name" />
                                                          <div className="flex flex-wrap gap-2">
                                                            <input type="text" inputMode="numeric" className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm inline-block box-border w-14" style={{ minWidth: '3ch' }} value={mobileRowItem.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], quantity: e.target.value }; return n })} placeholder="Qty" />
                                                            <input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm inline-block box-border w-16" style={{ minWidth: '4ch' }} value={mobileRowItem.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], unit_price: e.target.value }; return n })} placeholder="Unit $" />
                                                            <input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm inline-block box-border w-16" style={{ minWidth: '4ch' }} value={mobileRowItem.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], line_total: e.target.value }; return n })} placeholder="Amount" />
                                                          </div>
                                                        </div>
                                                      ) : mobileReceiptViewMode === 'receipt' ? (
                                                        <>
                                                          <div className="flex justify-between items-baseline gap-2">
                                                            <span className={`min-w-0 truncate ${deleteConfirmItemIndex === i ? 'line-through text-theme-mid' : 'text-theme-dark'}`}>{name || '—'}</span>
                                                            {!showQtyUnit && <span className="shrink-0 tabular-nums">{p ? `$${p}` : ''}</span>}
                                                          </div>
                                                          {showQtyUnit && (
                                                            <div className="flex justify-between items-baseline gap-2 mt-0.5 text-sm text-theme-dark/90">
                                                              <span>{qty} @ ${u} / {unit}</span>
                                                              <span className="shrink-0 tabular-nums">{p ? `$${p}` : ''}</span>
                                                            </div>
                                                          )}
                                                        </>
                                                      ) : (
                                                        <>
                                                          <div className="flex justify-between items-baseline gap-2">
                                                            <span className={`min-w-0 truncate ${deleteConfirmItemIndex === i ? 'line-through text-theme-mid' : 'text-theme-dark'}`}>{name || '—'}</span>
                                                            <span className="shrink-0 flex items-center gap-1">
                                                              {(it.category_source === 'llm' || it.category_source === 'rule_exact' || it.category_source === 'rule_fuzzy') && (
                                                                <span className="inline-flex items-center justify-center w-5 h-5 rounded-sm bg-black text-white text-[9px] font-bold shrink-0" title="AI 分类">AI</span>
                                                              )}
                                                              <span className="tabular-nums">{p ? `$${p}` : ''}</span>
                                                            </span>
                                                          </div>
                                                          <div className="mt-0.5 flex flex-col sm:flex-row sm:justify-between sm:items-center gap-0.5 text-xs text-theme-mid">
                                                            <span className="sm:flex-1">{catL1L2}</span>
                                                            <span className="sm:shrink-0">{catL3}</span>
                                                          </div>
                                                        </>
                                                      )}
                                                    </div>
                                                  </div>
                                                )
                                              })
                                            })()}
                                            {/* Green plus button to add a new item in edit mode */}
                                            {editModeReceiptId === r.id && (
                                              <div className="pt-2" onClick={(e) => e.stopPropagation()}>
                                                <button
                                                  type="button"
                                                  className="flex items-center gap-1.5 text-sm text-green-700 hover:text-green-800 touch-manipulation"
                                                  onClick={(e) => {
                                                    e.stopPropagation()
                                                    setEditItems((prev) => [...prev, { _key: `new_${Date.now()}_${Math.random()}`, id: undefined, product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])
                                                    setEditingSection({ receiptId: r.id, section: 'item' })
                                                  }}
                                                >
                                                  <span className="w-5 h-5 rounded-full bg-green-500 text-white flex items-center justify-center text-base font-bold leading-none">+</span>
                                                  <span>Add item</span>
                                                </button>
                                              </div>
                                            )}
                                          </div>
                                          {rec && (
                                            <>
                                              <div className="border-t border-dashed border-theme-mid pt-2 space-y-0.5">
                                                {items.length > 0 && (() => {
                                                  const toCents = (v: any): number => { const n = Number(v); if (!Number.isFinite(n)) return 0; return (Number.isInteger(n) && n >= 100) ? n : Math.round(n * 100) }
                                                  const editDisplayItems = editModeReceiptId === r.id ? editItems : items
                                                  const itemsSumCents = editDisplayItems.reduce((s: number, it: any) => {
                                                    const raw = editModeReceiptId === r.id ? it.line_total : it.line_total
                                                    return s + toCents(raw)
                                                  }, 0)
                                                  const subNum = rec.subtotal != null ? Number(rec.subtotal) : NaN
                                                  const subtotalCents = (subNum >= 100 && Number.isInteger(subNum)) ? subNum : (Number.isFinite(subNum) ? Math.round(subNum * 100) : NaN)
                                                  const mismatch = Number.isFinite(subtotalCents) && Math.abs(itemsSumCents - subtotalCents) > 3
                                                  const showRedSumRow = r.current_status === 'needs_review' && mismatch
                                                  return (
                                                    <>
                                                      {showRedSumRow && (
                                                        <div className="text-xs font-medium text-red-600 tabular-nums space-y-0.5">
                                                          <div className="flex justify-between">
                                                            <span>Items sum (computed)</span>
                                                            <span>${money(itemsSumCents)}</span>
                                                          </div>
                                                          <div className="flex justify-between">
                                                            <span>diff</span>
                                                            <span>{itemsSumCents - subtotalCents >= 0 ? '+' : ''}${((itemsSumCents - subtotalCents) / 100).toFixed(2)}</span>
                                                          </div>
                                                        </div>
                                                      )}
                                                      {!showRedSumRow && mismatch && (
                                                        <div className="flex justify-between text-xs text-amber-700">
                                                          <span>Items sum (computed)</span>
                                                          <span className="tabular-nums">${money(itemsSumCents)}</span>
                                                        </div>
                                                      )}
                                                    </>
                                                  )
                                                })()}
                                                <div className="flex justify-between"><span>Subtotal</span><span className="tabular-nums">{rec.subtotal != null ? `$${money(rec.subtotal)}` : ''}</span></div>
                                                <div className="flex justify-between"><span>Tax</span><span className="tabular-nums">{rec.tax != null ? `$${money(rec.tax)}` : ''}</span></div>
                                                <div className="flex justify-between font-medium"><span>Total</span><span className="tabular-nums">{rec.total != null ? `$${money(rec.total)}` : ''}</span></div>
                                              </div>
                                              {editModeReceiptId === r.id && editingSection?.receiptId === r.id && editingSection?.section === 'payment_date' ? (
                                                <div className="mt-2 space-y-2 pt-2 border-t border-dashed border-theme-mid" onClick={(e) => e.stopPropagation()}>
                                                  <div><span className="text-xs text-theme-mid">Payment</span><br /><input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editPaymentMethod} onChange={(e) => setEditPaymentMethod(e.target.value)} placeholder="Visa" /></div>
                                                  <div><span className="text-xs text-theme-mid">Card last 4</span><br /><input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm max-w-[5rem]" inputMode="numeric" maxLength={4} value={editPaymentLast4} onChange={(e) => setEditPaymentLast4(e.target.value)} placeholder="3719" /></div>
                                                  <div><span className="text-xs text-theme-mid">Date</span><br /><input type="date" className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editReceiptDate} onChange={(e) => setEditReceiptDate(e.target.value)} /></div>
                                                  <div><span className="text-xs text-theme-mid">Time (24h)</span><br /><input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm font-mono w-20" placeholder="17:37" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} maxLength={5} inputMode="numeric" /></div>
                                                </div>
                                              ) : editModeReceiptId === r.id ? (
                                                <div
                                                  role="button"
                                                  tabIndex={0}
                                                  className="mt-2 pt-2 border-t border-dashed border-theme-mid cursor-pointer rounded active:bg-theme-light-gray/30 space-y-0.5"
                                                  onClick={(e) => { e.stopPropagation(); setEditingSection({ receiptId: r.id, section: 'payment_date' }) }}
                                                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setEditingSection({ receiptId: r.id, section: 'payment_date' }) } }}
                                                >
                                                  {$(rec.payment_method) && <div>Payment: {rec.payment_method}</div>}
                                                  {$(rec.card_last4) && <div>Card: ****{String(rec.card_last4).replace(/\D/g, '').slice(-4)}</div>}
                                                  {$(rec.purchase_date) && <div>Date: {rec.purchase_date}{rec.purchase_date_is_estimated && <span className="ml-1.5 inline-flex items-center rounded px-1 py-0 text-[10px] font-medium bg-amber-100 text-amber-700 border border-amber-300" title="Date was estimated — no date found on receipt">est.</span>}</div>}
                                                  <div>Time: {editPurchaseTime?.trim() || $(rec.purchase_time) ? formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '') : '—'}</div>
                                                </div>
                                              ) : (
                                                <>
                                                  {$(rec.payment_method) && <div>Payment: {rec.payment_method}</div>}
                                                  {$(rec.card_last4) && <div>Card: ****{String(rec.card_last4).replace(/\D/g, '').slice(-4)}</div>}
                                                  {$(rec.purchase_date) && <div>Date: {rec.purchase_date}{rec.purchase_date_is_estimated && <span className="ml-1.5 inline-flex items-center rounded px-1 py-0 text-[10px] font-medium bg-amber-100 text-amber-700 border border-amber-300" title="Date was estimated — no date found on receipt">est.</span>}</div>}
                                                  <div>Time: {editPurchaseTime?.trim() || $(rec.purchase_time) ? formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '') : '—'}</div>
                                                </>
                                              )}
                                            </>
                                          )}
                                          <div className="border-t border-theme-ivory-dark pt-3 flex flex-col gap-2">
                                            <p className="text-xs font-medium text-theme-mid uppercase tracking-wide">Smart Categorization</p>
                                            {r.current_status === 'needs_review' ? (
                                              <p className="text-xs text-amber-700 leading-snug">Please complete the receipt review first before running categorization.</p>
                                            ) : (
                                            <div className="flex flex-col gap-1.5 w-full">
                                              <button type="button" disabled={smartCategorizeLoading} onClick={async () => { if (!r.id || !token) return; setSmartCategorizeLoading(true); setSmartCategorizeMessage(null); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/smart-categorize`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({}) }); const data = await res.json().catch(() => ({})); if (res.ok) { setSmartCategorizeMessage(data.updated_count != null ? `Updated ${data.updated_count} item(s)` : (data.message || 'Done')); await refetchReceiptDetail(r.id) } else setSmartCategorizeMessage(data.detail || 'Failed'); } catch { setSmartCategorizeMessage('Network error'); } finally { setSmartCategorizeLoading(false); } }} className="w-full text-sm text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 py-2 rounded border border-theme-mid disabled:opacity-50 disabled:cursor-not-allowed">{smartCategorizeLoading ? 'Running…' : 'All'}</button>
                                              <button type="button" disabled={smartCategorizeLoading || selectedIdsForReceipt(r.id).size === 0} onClick={async () => { if (!r.id || !token || selectedIdsForReceipt(r.id).size === 0) return; setSmartCategorizeLoading(true); setSmartCategorizeMessage(null); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/smart-categorize`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ item_ids: Array.from(selectedIdsForReceipt(r.id)) }) }); const data = await res.json().catch(() => ({})); if (res.ok) { setSmartCategorizeMessage(data.updated_count != null ? `Updated ${data.updated_count} item(s)` : (data.message || 'Done')); setSmartCategorizeSelectedIds((prev) => ({ ...prev, [r.id]: new Set() })); await refetchReceiptDetail(r.id) } else setSmartCategorizeMessage(data.detail || 'Failed'); } catch { setSmartCategorizeMessage('Network error'); } finally { setSmartCategorizeLoading(false); } }} className="w-full text-sm text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 py-2 rounded border border-theme-mid disabled:opacity-50 disabled:cursor-not-allowed">{smartCategorizeLoading ? 'Running…' : 'Selected Only'}</button>
                                            </div>
                                            )}
                                            {(categoryUpdateMessage || smartCategorizeMessage) && (
                                              <p className={`text-xs ${(categoryUpdateMessage || smartCategorizeMessage) === 'Saved' || (smartCategorizeMessage?.startsWith?.('Updated')) ? 'text-green-600' : 'text-theme-red'}`}>{categoryUpdateMessage || smartCategorizeMessage}</p>
                                            )}
                                          </div>
                                          {editModeReceiptId === r.id && (editingSection?.receiptId === r.id || items.some((it: { id?: string }) => it.id && classificationEditingItemIds.has(it.id))) && (
                                            <div className="mt-4 pt-4 border-t border-theme-light-gray">
                                              {correctMessage && (
                                                <div className={`mb-2 p-2 rounded text-sm ${correctMessage.startsWith('Saved') ? 'bg-green-100 text-green-800' : 'bg-theme-red/15 text-theme-red'}`}>{correctMessage}</div>
                                              )}
                                              <button
                                                type="button"
                                                className="w-full px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm font-medium touch-manipulation safe-area-pb"
                                                disabled={correctSubmitting}
                                                onClick={async (e) => {
                                                  e.stopPropagation()
                                                  if (!token || !r.id) return
                                                  setCorrectSubmitting(true)
                                                  setCorrectMessage(null)
                                                  setCategoryUpdateMessage(null)
                                                  try {
                                                    const receiptItemIds = items.map((it: { id?: string }) => it.id).filter(Boolean) as string[]
                                                    const toSaveCat = receiptItemIds.filter((id) => classificationEditingItemIds.has(id))
                                                    if (toSaveCat.length > 0) {
                                                      const batchRes = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/items/categories`, {
                                                        method: 'PATCH',
                                                        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                        body: JSON.stringify({
                                                          updates: toSaveCat.map((itemId) => ({ item_id: itemId, user_category_id: pendingCategoryByItemId[itemId] ?? null })),
                                                        }),
                                                      })
                                                      if (!batchRes.ok) {
                                                        const err = await batchRes.json().catch(() => ({}))
                                                        setCategoryUpdateMessage(err?.detail ?? 'Save failed')
                                                        return
                                                      }
                                                      setCategoryUpdateMessage('Saved')
                                                      await refetchReceiptDetail(r.id)
                                                      setClassificationEditingItemIds((prev) => { const n = new Set(prev); toSaveCat.forEach((id) => n.delete(id)); return n })
                                                      setPendingCategoryByItemId((prev) => { const o = { ...prev }; toSaveCat.forEach((id) => delete o[id]); return o })
                                                      if (editingSection?.receiptId === r.id && editingSection?.section === 'classification') setEditingSection(null)
                                                    }
                                                    if (editingSection?.receiptId === r.id && editingSection?.section !== 'classification') {
                                                      const totalNum = editTotal.trim() ? parseFloat(editTotal) : NaN
                                                      if (isNaN(totalNum)) { setCorrectMessage('Please enter Total'); setCorrectSubmitting(false); return }
                                                      const summary = {
                                                        store_name: editStoreName.trim() || undefined,
                                                        store_address: [editAddressLine1, editAddressLine2, [editAddressCity, editAddressState, editAddressZip].filter(Boolean).join(editAddressCity && editAddressState ? ', ' : ' ').replace(/, $/, '').trim(), editAddressCountry].filter(Boolean).join('\n').trim() || undefined,
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
                                                          original_price: it.original_price?.trim() ? parseFloat(it.original_price) : undefined,
                                                          discount_amount: it.discount_amount?.trim() ? parseFloat(it.discount_amount) : undefined,
                                                        }))
                                                      const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/correct`, {
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
                                                      const detailRes = await fetch(`${apiBaseUrl}/api/receipt/${r.id}`, { headers: { Authorization: `Bearer ${token}` } })
                                                      if (detailRes.ok) {
                                                        const detailJson = await detailRes.json()
                                                        setExpandedReceiptData((prev) => ({ ...prev, [r.id]: detailJson }))
                                                      }
                                                      setEditingSection(null)
                                                      setEditingItemIndicesByReceipt((prev) => { const next = { ...prev }; delete next[r.id]; return next })
                                                    }
                                                  } catch (err) {
                                                    setCorrectMessage(err instanceof Error ? err.message : 'Submit failed')
                                                  } finally {
                                                    setCorrectSubmitting(false)
                                                  }
                                                }}
                                              >
                                                {correctSubmitting ? 'Saving…' : 'Confirm modification'}
                                              </button>
                                            </div>
                                          )}
                                        </div>
                                      </div>
                                      {/* 手机列表展开时也渲染 Edit 面板与底部操作，与桌面共用同一 state */}
                                      <div
                                        className={`absolute left-0 right-0 top-0 bottom-0 z-10 flex flex-col bg-white border-l border-theme-ivory-dark shadow-lg transition-transform duration-200 ease-out ${correctionOpenReceiptId === r.id ? 'translate-x-0' : 'translate-x-full'}`}
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        <div className="flex items-center justify-between px-3 py-2 border-b border-theme-ivory-dark bg-theme-cream shrink-0">
                                          <span className="text-sm font-medium text-theme-dark/90">Edit receipt</span>
                                          <button type="button" className="p-1.5 text-theme-mid hover:text-theme-dark hover:bg-theme-light-gray rounded" onClick={(e) => { e.stopPropagation(); setCorrectionOpenReceiptId(null) }} title="Close">▶</button>
                                        </div>
                                        <div className="p-4 space-y-4 overflow-y-auto flex-1 min-h-0 pb-safe">
                                          {correctMessage && (
                                            <div className={`p-2 rounded text-sm ${correctMessage.startsWith('Saved') ? 'bg-green-100 text-green-800' : 'bg-theme-red/15 text-theme-red'}`}>
                                              {correctMessage}
                                            </div>
                                          )}
                                          <div className="grid grid-cols-1 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Store name</span>
                                              <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editStoreName} onChange={(e) => setEditStoreName(e.target.value)} placeholder="Store name" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Address line 1</span>
                                              <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editAddressLine1} onChange={(e) => setEditAddressLine1(e.target.value)} placeholder="Street address" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Address line 2</span>
                                              <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editAddressLine2} onChange={(e) => setEditAddressLine2(e.target.value)} placeholder="Unit / Suite" />
                                            </label>
                                            <div className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">City / State / ZIP</span>
                                              <div className="grid gap-1.5" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editAddressCity} onChange={(e) => setEditAddressCity(e.target.value)} placeholder="City" />
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editAddressState} onChange={(e) => setEditAddressState(e.target.value)} placeholder="ST" />
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editAddressZip} onChange={(e) => setEditAddressZip(e.target.value)} placeholder="ZIP" />
                                              </div>
                                            </div>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Country</span>
                                              <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editAddressCountry} onChange={(e) => setEditAddressCountry(e.target.value)} placeholder="US" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Phone</span>
                                              <input className="border rounded px-2 py-2 text-sm touch-manipulation" type="tel" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="425-640-2648" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Purchase date</span>
                                              <input type="date" className="border rounded px-2 py-2 text-sm touch-manipulation" value={editReceiptDate} onChange={(e) => setEditReceiptDate(e.target.value)} />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Purchase time (optional, 24h e.g. 15:34)</span>
                                              <input type="text" className="border rounded px-2 py-2 text-sm font-mono touch-manipulation" placeholder="15:34" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} maxLength={5} inputMode="numeric" />
                                            </label>
                                            <div className="grid grid-cols-3 gap-2">
                                              <label className="flex flex-col gap-0.5">
                                                <span className="text-xs text-theme-mid">Subtotal</span>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" inputMode="decimal" value={editSubtotal} onChange={(e) => setEditSubtotal(e.target.value)} placeholder="0.00" />
                                              </label>
                                              <label className="flex flex-col gap-0.5">
                                                <span className="text-xs text-theme-mid">Tax</span>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" inputMode="decimal" value={editTax} onChange={(e) => setEditTax(e.target.value)} placeholder="0.00" />
                                              </label>
                                              <label className="flex flex-col gap-0.5">
                                                <span className="text-xs text-theme-mid">Total *</span>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" inputMode="decimal" value={editTotal} onChange={(e) => setEditTotal(e.target.value)} placeholder="0.00" />
                                              </label>
                                            </div>
                                            <div className="grid grid-cols-2 gap-2">
                                              <label className="flex flex-col gap-0.5">
                                                <span className="text-xs text-theme-mid">Currency</span>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editCurrency} onChange={(e) => setEditCurrency(e.target.value)} placeholder="USD" />
                                              </label>
                                              <label className="flex flex-col gap-0.5">
                                                <span className="text-xs text-theme-mid">Payment method</span>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" value={editPaymentMethod} onChange={(e) => setEditPaymentMethod(e.target.value)} placeholder="AMEX Credit" />
                                              </label>
                                              <label className="flex flex-col gap-0.5">
                                                <span className="text-xs text-theme-mid">Card last 4</span>
                                                <input className="border rounded px-2 py-2 text-sm touch-manipulation" inputMode="numeric" maxLength={4} value={editPaymentLast4} onChange={(e) => setEditPaymentLast4(e.target.value)} placeholder="5030" />
                                              </label>
                                            </div>
                                          </div>
                                          <div>
                                            <p className="text-xs text-theme-dark/90 mb-2">Item lines</p>
                                            <div className="max-h-56 overflow-auto border border-theme-light-gray rounded-lg divide-y divide-theme-light-gray/50 overscroll-contain">
                                              {editItems.map((row, idx) => (
                                                <div key={row._key ?? idx} className="p-2.5 space-y-2 bg-white first:rounded-t-lg last:rounded-b-lg">
                                                  <div>
                                                    <label className="text-xs text-theme-mid block mb-0.5">Product name</label>
                                                    <input className="w-full border rounded px-2 py-2 text-sm touch-manipulation" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} />
                                                  </div>
                                                  <div className="grid grid-cols-3 gap-2">
                                                    <div>
                                                      <label className="text-xs text-theme-mid block mb-0.5">Qty</label>
                                                      <input type="text" inputMode="numeric" className="w-full border rounded px-2 py-2 text-sm touch-manipulation" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} />
                                                    </div>
                                                    <div>
                                                      <label className="text-xs text-theme-mid block mb-0.5">Unit pr</label>
                                                      <input className="w-full border rounded px-2 py-2 text-sm touch-manipulation" inputMode="decimal" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} />
                                                    </div>
                                                    <div>
                                                      <label className="text-xs text-theme-mid block mb-0.5">$ Amount</label>
                                                      <input className="w-full border rounded px-2 py-2 text-sm touch-manipulation" inputMode="decimal" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} />
                                                    </div>
                                                  </div>
                                                </div>
                                              ))}
                                            </div>
                                            <button type="button" className="mt-2 w-full py-2.5 text-sm font-medium text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/20 rounded-lg border border-theme-mid touch-manipulation" onClick={() => setEditItems((prev) => [...prev, { _key: `new_${Date.now()}_${Math.random()}`, product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])}>
                                              + Add row
                                            </button>
                                          </div>
                                          <button
                                            type="button"
                                            className="w-full px-4 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm font-medium touch-manipulation safe-area-pb"
                                            disabled={correctSubmitting || !editTotal.trim()}
                                            onClick={async (e) => {
                                              e.stopPropagation()
                                              if (!token || !r.id) return
                                              setCorrectSubmitting(true)
                                              setCorrectMessage(null)
                                              try {
                                                const totalNum = editTotal.trim() ? parseFloat(editTotal) : NaN
                                                if (isNaN(totalNum)) { setCorrectMessage('Please enter Total'); setCorrectSubmitting(false); return }
                                                const summary = {
                                                  store_name: editStoreName.trim() || undefined,
                                                  store_address: [editAddressLine1, editAddressLine2, [editAddressCity, editAddressState, editAddressZip].filter(Boolean).join(editAddressCity && editAddressState ? ', ' : ' ').replace(/, $/, '').trim(), editAddressCountry].filter(Boolean).join('\n').trim() || undefined,
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
                                                    original_price: it.original_price?.trim() ? parseFloat(it.original_price) : undefined,
                                                    discount_amount: it.discount_amount?.trim() ? parseFloat(it.discount_amount) : undefined,
                                                  }))
                                                const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/correct`, {
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
                                      <div className="mt-4 flex flex-wrap items-center gap-2 px-4 pb-2">
                                        {(userClass === 7 || userClass === 9) && (
                                          <>
                                            <button type="button" className="text-sm text-theme-dark/90 hover:text-theme-dark underline" onClick={(e) => { e.stopPropagation(); setShowRawJson((v) => !v) }}>{showRawJson ? 'Hide' : 'Show'} raw JSON</button>
                                            <button type="button" className="text-sm text-theme-dark/90 hover:text-theme-dark underline" onClick={(e) => { e.stopPropagation(); if (expandedReceiptData[r.id]) navigator.clipboard.writeText(JSON.stringify(expandedReceiptData[r.id], null, 2)); alert('Copied'); }}>Copy</button>
                                          </>
                                        )}
                                        {r.current_status === 'success' && (
                                          <button type="button" className="text-sm text-theme-red hover:text-theme-red hover:underline" onClick={(e) => { e.stopPropagation(); setEscalationReceiptId(r.id); setEscalationNotes(''); }}>Open a review</button>
                                        )}
                                        <button type="button" className="text-sm text-theme-red hover:text-theme-red hover:underline" onClick={(e) => { e.stopPropagation(); if (token && r.id) setDeleteConfirmReceiptId(r.id) }}>Delete this receipt</button>
                                      </div>
                                      {r.current_status === 'success' && escalationReceiptId === r.id && (
                                        <div className="px-4 pb-4 flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                                          <label className="text-xs font-medium text-theme-dark/90">Escalation notes (admin will see):</label>
                                          <textarea className="w-full min-h-[72px] border border-theme-mid rounded px-2 py-1.5 text-sm text-theme-dark" value={escalationNotes} onChange={(e) => setEscalationNotes(e.target.value)} placeholder="Describe what’s wrong or what to fix…" />
                                          <div className="flex gap-2">
                                            <button type="button" disabled={escalationSubmitting} onClick={async () => { if (!r.id || !token) return; setEscalationSubmitting(true); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/escalate`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ notes: escalationNotes }) }); const data = await res.json().catch(() => ({})); if (res.ok && data.success) { setEscalationReceiptId(null); setEscalationNotes(''); await refetchReceiptDetail(r.id); fetchReceiptList(); alert('Escalated. Admin will review.'); } else { alert(data.detail || data.message || 'Escalation failed'); } } catch { alert('Network error'); } finally { setEscalationSubmitting(false); } }} className="text-xs font-medium text-white bg-theme-orange hover:bg-theme-orange/90 px-2 py-1.5 rounded disabled:opacity-50">Submit escalation</button>
                                            <button type="button" onClick={() => { setEscalationReceiptId(null); setEscalationNotes(''); }} className="text-xs font-medium text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 px-2 py-1.5 rounded border border-theme-mid">Cancel</button>
                                          </div>
                                        </div>
                                      )}
                                </React.Fragment>
                                );
                                  })()}
                              </div>
                        )}
                      </div>
                        ))}
                      </div>
                    ))}
                    {hasMoreOnMobile && (
                      <button
                        type="button"
                        onClick={() => setMobileReceiptVisibleCount((c) => c + 5)}
                        className="w-full py-3 text-sm font-medium text-theme-dark/90 bg-theme-light-gray/50 hover:bg-theme-light-gray rounded-lg border border-theme-light-gray transition"
                      >
                        Expand 5
                      </button>
                    )}
                  </div>

                  {/* 桌面端：按月份分组 */}
                  <div className="hidden md:block space-y-6">
                  {processingCount > 0 && (
                    <div>
                      <div className="flex items-center gap-3 mb-3">
                        <span className="text-sm font-semibold text-theme-dark/90">Processing</span>
                        <div className="flex-1 h-px bg-theme-light-gray" />
                      </div>
                      <div className="space-y-3">
                        {Array.from({ length: processingCount }, (_, i) => (
                          <div key={`processing-${i}`} className="border border-theme-light-gray rounded-lg overflow-hidden">
                            <div className="w-full px-4 py-3 flex items-center gap-3 text-left" style={{ backgroundColor: '#FAFAF7' }}>
                              <span className="inline-block animate-spin text-lg shrink-0" aria-hidden>⏳</span>
                              <span className="text-theme-mid font-medium">Processing…</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {orderedMonths.map((monthKey) => {
                    const visibleInMonth = byMonth[monthKey].filter((r) => visibleDesktopIds.has(r.id))
                    if (visibleInMonth.length === 0) return null
                    return (
                    <div key={monthKey}>
                      <div className="flex items-center gap-3 mb-3">
                        <span className="text-sm font-semibold text-theme-dark/90">{monthLabels[monthKey]}</span>
                        <div className="flex-1 h-px bg-theme-light-gray" />
                      </div>
                      <div className="space-y-3">
                        {visibleInMonth.map((r) => (
                          <div
                            key={r.id}
                            className="border border-theme-light-gray rounded-lg overflow-hidden"
                          >
                            <button
                              type="button"
                              className="w-full px-4 py-3 flex items-center justify-between text-left hover:opacity-90 transition"
                              style={{ backgroundColor: '#FAFAF7' }}
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
                                <span className="font-medium text-theme-dark">
                                  {(() => { const raw = (r.chain_name || r.store_name || '').trim(); return raw ? toTitleCaseStore(raw) : 'Unknown store'; })()}
                                </span>
                                <span className="text-xs text-theme-mid">
                                  {formatDisplayDate(r)}
                                </span>
                                <span className={`text-xs px-2 py-0.5 rounded ${
                                  r.current_status === 'success' ? 'bg-green-100 text-green-800' :
                                  r.current_status === 'failed' || r.current_status === 'needs_review' ? 'bg-amber-100 text-amber-800' : 'bg-theme-light-gray/50 text-theme-dark/90'
                                }`}>
                                  {getStatusLabel(r)}
                                </span>
                              </div>
                              <span className="text-theme-mid">{expandedReceiptIds.has(r.id) ? '▼' : '▶'}</span>
                            </button>
                            {expandedReceiptIds.has(r.id) && !expandedReceiptData[r.id] && (
                              <div className="border-t border-theme-light-gray bg-white p-6 flex items-center justify-center min-h-[120px]">
                                <div className="animate-spin w-8 h-8 border-2 border-theme-mid border-t-transparent rounded-full" aria-hidden />
                              </div>
                            )}
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
                                      return Number.isFinite(n) ? n.toFixed(2) : String(v)
                                    }
                                    if (!rec && items.length === 0) return <span>(No data)</span>
                                    // 左侧店名与编辑框一致：统一用 toTitleCaseStore，避免 API 未 title case 时仍显示全大写
                                    const rawFromApi = rec?.merchant_name ?? ''
                                    const displayName = chainName || (rawFromApi ? toTitleCaseStore(rawFromApi) : '') || rawFromApi || ''
                                    const rawAddress = $(rec?.merchant_address)
                                    const address = formatAddressForDisplay(rawAddress || '')
                                    return (
                                      <React.Fragment>
                                      {/* 桌面端：灰色层 + 白底双栏 */}
                                      <div className="hidden md:block border-t border-theme-ivory-dark bg-theme-cream p-4">
                                        <div className="relative bg-white border border-theme-light-gray rounded-lg overflow-hidden flex flex-col min-h-0">
                                        {/*
                                          桌面：视觉两栏 grid
                                          [左上: 店铺信息] [右上: 分类头] | [中间: 表] | [左下: 小计] [右下: Smart]
                                        */}
                                        <div className="hidden md:block">
                                        <div
                                          className="grid overflow-x-auto"
                                          style={{ gridTemplateColumns: 'minmax(0,1.5fr) 5.5rem 5.5rem 5.5rem 8px minmax(0,0.9fr) minmax(0,1.5fr) 1.75rem 2rem 2.5rem' }}
                                        >
                                          {/* ① 左上：店铺信息 + Edit mode toggle | sep | 右上：Classification + Smart */}
                                          <div className="col-span-4 p-4 border-b border-theme-light-gray flex items-start justify-between gap-2">
                                            <div className="text-theme-dark whitespace-pre-line leading-5 min-w-0 flex-1 min-w-0">
                                              {editModeReceiptId === r.id && editingSection?.receiptId === r.id && editingSection?.section === 'store' ? (
                                                <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editStoreName} onChange={(e) => setEditStoreName(e.target.value)} placeholder="Store name" />
                                                  <input type="tel" className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="Telephone 000-000-0000" />
                                                </div>
                                              ) : (
                                                <div
                                                  role="button"
                                                  tabIndex={0}
                                                  onClick={(e) => { e.stopPropagation(); if (editModeReceiptId === r.id) setEditingSection({ receiptId: r.id, section: 'store' }) }}
                                                  onKeyDown={(e) => { if (editModeReceiptId === r.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setEditingSection({ receiptId: r.id, section: 'store' }) } }}
                                                  className={editModeReceiptId === r.id ? 'cursor-pointer rounded ring-offset-1 hover:ring-2 hover:ring-theme-mid/30' : ''}
                                                >
                                                  {displayName && <span className="font-semibold">{displayName}</span>}
                                                </div>
                                              )}
                                              {editModeReceiptId === r.id && editingSection?.receiptId === r.id && editingSection?.section === 'address' ? (
                                                <div className="mt-2 space-y-2" onClick={(e) => e.stopPropagation()}>
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressLine1} onChange={(e) => setEditAddressLine1(e.target.value)} placeholder="Address line 1" />
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressLine2} onChange={(e) => setEditAddressLine2(e.target.value)} placeholder="Address line 2" />
                                                  <div className="grid gap-1" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                                                    <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressCity} onChange={(e) => setEditAddressCity(e.target.value)} placeholder="City" />
                                                    <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressState} onChange={(e) => setEditAddressState(e.target.value)} placeholder="ST" />
                                                    <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressZip} onChange={(e) => setEditAddressZip(e.target.value)} placeholder="ZIP" />
                                                  </div>
                                                  <input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editAddressCountry} onChange={(e) => setEditAddressCountry(e.target.value)} placeholder="Country" />
                                                  <input type="tel" className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="Telephone 000-000-0000" />
                                                </div>
                                              ) : (
                                                <div
                                                  role="button"
                                                  tabIndex={0}
                                                  onClick={(e) => { e.stopPropagation(); if (editModeReceiptId === r.id) setEditingSection({ receiptId: r.id, section: 'address' }) }}
                                                  onKeyDown={(e) => { if (editModeReceiptId === r.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setEditingSection({ receiptId: r.id, section: 'address' }) } }}
                                                  className={editModeReceiptId === r.id ? 'cursor-pointer rounded ring-offset-1 hover:ring-2 hover:ring-theme-mid/30 mt-0.5' : ''}
                                                >
                                                  {address && <span className="text-theme-dark/90">{address}</span>}
                                                  {rec?.merchant_phone && <div className="text-theme-dark/90 mt-0.5">Tel: {rec.merchant_phone}</div>}
                                                </div>
                                              )}
                                            </div>
                                            <div className="shrink-0 flex items-center gap-2 ml-2">
                                              <span className="text-xs text-theme-mid whitespace-nowrap">Edit mode</span>
                                              <button
                                                type="button"
                                                role="switch"
                                                aria-checked={editModeReceiptId === r.id}
                                                className={`relative inline-flex h-6 w-10 shrink-0 rounded-full border transition-colors ${editModeReceiptId === r.id ? 'bg-theme-orange border-theme-orange' : 'bg-theme-light-gray border-theme-mid'}`}
                                                onClick={(e) => {
                                                  e.stopPropagation()
                                                  if (editModeReceiptId === r.id) {
                                                    setEditModeReceiptId(null)
                                                    setEditingSection(null)
                                                    setClassificationEditingItemIds(new Set())
                                                    setPendingCategoryByItemId({})
                                                    setEditingItemIndicesByReceipt((prev) => { const next = { ...prev }; delete next[r.id]; return next })
                                                  } else {
                                                    setEditModeReceiptId(r.id)
                                                    setEditingSection(null)
                                                    initEditFormFromJson(expandedReceiptData[r.id])
                                                  }
                                                }}
                                              >
                                                <span className={`inline-block h-5 w-5 rounded-full bg-white border border-theme-mid transform transition-transform ${editModeReceiptId === r.id ? 'translate-x-4' : 'translate-x-0.5'}`} style={{ marginTop: 1 }} />
                                              </button>
                                            </div>
                                          </div>
                                          <div className="border-b border-l border-r border-theme-cream bg-theme-cream" />
                                          <div className="col-span-5 p-4 border-b border-theme-light-gray bg-theme-cream/50 flex flex-row justify-between items-start gap-4">
                                            <div className="flex flex-col gap-1">
                                              <p className="text-xs font-medium text-theme-mid uppercase tracking-wide">Classification</p>
                                              {r.current_status === 'needs_review' ? (
                                                <span className="text-xs text-amber-700 max-w-56 leading-snug">Please complete the receipt review first before running categorization.</span>
                                              ) : (
                                                <span className="text-sm text-theme-black font-medium">Run Smart Categorization on</span>
                                              )}
                                            </div>
                                            <div className="flex flex-col gap-1.5 items-end shrink-0 min-w-[7.5rem]">
                                              {r.current_status === 'needs_review' ? null : (
                                                <>
                                                <button
                                                  type="button"
                                                  disabled={smartCategorizeLoading}
                                                  onClick={async () => {
                                                    if (!r.id || !token) return
                                                    setSmartCategorizeLoading(true); setSmartCategorizeMessage(null)
                                                    try {
                                                      const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/smart-categorize`, {
                                                        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                        body: JSON.stringify({}),
                                                      })
                                                      const data = await res.json().catch(() => ({}))
                                                      if (res.ok) { setSmartCategorizeMessage(data.updated_count != null ? `Updated ${data.updated_count} item(s)` : (data.message || 'Done')); await refetchReceiptDetail(r.id) }
                                                      else setSmartCategorizeMessage(data.detail || 'Failed')
                                                    } catch { setSmartCategorizeMessage('Network error') }
                                                    finally { setSmartCategorizeLoading(false) }
                                                  }}
                                                  className="w-full text-sm text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 px-3 py-1 rounded border border-theme-mid disabled:opacity-50 disabled:cursor-not-allowed text-center"
                                                >
                                                  {smartCategorizeLoading ? 'Running…' : 'All'}
                                                </button>
                                                <button
                                                  type="button"
                                                  disabled={smartCategorizeLoading || selectedIdsForReceipt(r.id).size === 0}
                                                  onClick={async () => {
                                                    if (!r.id || !token || selectedIdsForReceipt(r.id).size === 0) return
                                                    setSmartCategorizeLoading(true); setSmartCategorizeMessage(null)
                                                    try {
                                                      const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/smart-categorize`, {
                                                        method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                        body: JSON.stringify({ item_ids: Array.from(selectedIdsForReceipt(r.id)) }),
                                                      })
                                                      const data = await res.json().catch(() => ({}))
                                                      if (res.ok) { setSmartCategorizeMessage(data.updated_count != null ? `Updated ${data.updated_count} item(s)` : (data.message || 'Done')); setSmartCategorizeSelectedIds((prev) => ({ ...prev, [r.id]: new Set() })); await refetchReceiptDetail(r.id) }
                                                      else setSmartCategorizeMessage(data.detail || 'Failed')
                                                    } catch { setSmartCategorizeMessage('Network error') }
                                                    finally { setSmartCategorizeLoading(false) }
                                                  }}
                                                  className="w-full text-sm text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 px-3 py-1 rounded border border-theme-mid disabled:opacity-50 disabled:cursor-not-allowed text-center"
                                                >
                                                  {smartCategorizeLoading ? 'Running…' : 'Selected Only'}
                                                </button>
                                                </>
                                              )}
                                            </div>
                                          </div>

                                          {/* ② 列标签行：大写加粗，无分割线 */}
                                          <div className="py-1.5 px-3 text-xs text-theme-dark/90 font-semibold uppercase">Product</div>
                                          <div className="py-1.5 pl-3 pr-2 text-xs text-theme-dark/90 font-semibold uppercase text-center">Qty</div>
                                          <div className="py-1.5 pl-3 pr-2 text-xs text-theme-dark/90 font-semibold uppercase text-right">Unit $</div>
                                          <div className="py-1.5 pl-3 pr-2 text-xs text-theme-dark/90 font-semibold uppercase text-right">$ Amount</div>
                                          <div className="bg-theme-cream" />
                                          <div className="py-1.5 px-3 text-xs text-theme-dark/90 font-semibold uppercase">System Category</div>
                                          <div className="py-1.5 px-2 text-xs text-theme-dark/90 font-semibold uppercase">Sub Categories</div>
                                          <div className="py-1.5 px-0.5 flex items-center justify-center" title="AI guessed category" />
                                          <div className="py-1.5 px-1 flex items-center justify-center" title="Select for Smart Categorization" />
                                          <div />

                                          {/* ③ item 行：每个 React.Fragment 贡献 8 个 grid 子元素 */}
                                          {(editModeReceiptId === r.id ? editItems : items).length === 0 && (
                                            <React.Fragment>
                                              <div className="col-span-4 px-3 py-3 text-theme-mid text-sm">No items</div>
                                              <div className="bg-theme-cream" />
                                              <div className="col-span-5" />
                                            </React.Fragment>
                                          )}
                                          {(editModeReceiptId === r.id ? editItems : items).map((rawIt: any, i: number) => {
                                            const it = editModeReceiptId === r.id ? (items.find((orig: any) => orig.id === rawIt.id) ?? rawIt) : rawIt
                                            const name = rawIt.product_name ?? rawIt.original_product_name ?? ''
                                            const qty = rawIt.quantity != null ? (typeof rawIt.quantity === 'number' ? rawIt.quantity : Number(rawIt.quantity)) : 1
                                            const u = rawIt.unit_price != null ? (money(rawIt.unit_price) ?? rawIt.unit_price) : ''
                                            const p = rawIt.line_total != null ? (money(rawIt.line_total) ?? rawIt.line_total) : ''
                                            const path = (it.user_category_path ?? it.category_path ?? '').trim()
                                            const parts = path ? path.split(/\s*[\/>\|]\s*/).map((s: string) => s.trim()).filter(Boolean) : []
                                            const sysCat = parts[0] ?? ''
                                            const subCat = parts.length > 1 ? parts.slice(1).join(' / ') : ''
                                            const itemId = it.id ?? rawIt.id
                                            const isEditingCat = Boolean(itemId && classificationEditingItemIds.has(itemId))
                                            const onOpenClassificationSection = () => {
                                              if (editModeReceiptId !== r.id || !itemId) return
                                              setEditingSection({ receiptId: r.id, section: 'classification', index: i })
                                              setClassificationEditingItemIds((prev) => new Set(prev).add(itemId))
                                              setPendingCategoryByItemId((prev) => (itemId in prev ? prev : { ...prev, [itemId]: it.user_category_id ?? it.category_id ?? null }))
                                            }
                                            const deactivateClassificationRow = () => {
                                              if (itemId) {
                                                setClassificationEditingItemIds((prev) => { const n = new Set(prev); n.delete(itemId); return n })
                                                setPendingCategoryByItemId((prev) => { const o = { ...prev }; delete o[itemId]; return o })
                                              }
                                            }
                                            const isEditingItemRow = editModeReceiptId === r.id && (editingItemIndicesByReceipt[r.id]?.includes(i) ?? false)
                                            const rowItem = editModeReceiptId === r.id && editItems[i] != null ? editItems[i] : null
                                            const activateItemRowEdit = () => {
                                              setEditingItemIndicesByReceipt((prev) => ({ ...prev, [r.id]: prev[r.id]?.includes(i) ? prev[r.id] : [...(prev[r.id] || []), i] }))
                                              setEditingSection((prev) => (prev?.receiptId === r.id && prev?.section === 'item' ? prev : { receiptId: r.id, section: 'item' }))
                                            }
                                            const deactivateItemRowEdit = () => {
                                              setEditingItemIndicesByReceipt((prev) => {
                                                const arr = (prev[r.id] || []).filter((x) => x !== i)
                                                if (arr.length === 0) { const next = { ...prev }; delete next[r.id]; return next }
                                                return { ...prev, [r.id]: arr }
                                              })
                                            }
                                            return (
                                              <React.Fragment key={rawIt._key ?? itemId ?? i}>
                                                {isEditingItemRow && rowItem ? (
                                                  <>
                                                    <div className="py-1 px-2 w-fit max-w-full justify-self-start" onClick={(e) => e.stopPropagation()}>
                                                      <input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm inline-block box-border" style={{ width: `${Math.max(10, Math.min(36, (rowItem.product_name?.length || 0) + 2))}ch`, maxWidth: '100%' }} value={rowItem.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], product_name: e.target.value }; return n })} placeholder="Product" />
                                                    </div>
                                                    <div className="py-1 pl-2 pr-2 text-center w-fit max-w-full justify-self-center" onClick={(e) => e.stopPropagation()}>
                                                      <input type="text" inputMode="numeric" className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm text-center inline-block box-border" style={{ width: `${Math.max(3, (rowItem.quantity?.length || 0) + 1)}ch`, maxWidth: '100%' }} value={rowItem.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], quantity: e.target.value }; return n })} />
                                                    </div>
                                                    <div className="py-1 pl-2 pr-2 text-right w-fit max-w-full justify-self-end" onClick={(e) => e.stopPropagation()}>
                                                      <input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm text-right inline-block box-border" style={{ width: `${Math.max(5, (rowItem.unit_price?.length || 0) + 2)}ch`, maxWidth: '100%' }} value={rowItem.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], unit_price: e.target.value }; return n })} />
                                                    </div>
                                                    <div className="py-1 pl-2 pr-2 text-right w-fit max-w-full justify-self-end" onClick={(e) => e.stopPropagation()}>
                                                      <input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm text-right inline-block box-border" style={{ width: `${Math.max(5, (rowItem.line_total?.length || 0) + 2)}ch`, maxWidth: '100%' }} value={rowItem.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[i] = { ...n[i], line_total: e.target.value }; return n })} />
                                                    </div>
                                                  </>
                                                ) : (
                                                  <>
                                                    <div role="button" tabIndex={0} className={`py-1.5 px-3 min-w-0 text-theme-dark flex items-center gap-1 ${editModeReceiptId === r.id ? 'cursor-pointer rounded hover:ring-2 hover:ring-theme-mid/30' : ''}`} title={name} onClick={(e) => { e.stopPropagation(); if (editModeReceiptId === r.id && deleteConfirmItemIndex !== i) activateItemRowEdit(); }} onKeyDown={(e) => { if (editModeReceiptId === r.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); if (deleteConfirmItemIndex !== i) activateItemRowEdit(); } }}>
                                                      {editModeReceiptId === r.id && deleteConfirmItemIndex !== i && (
                                                        <span className="flex flex-col shrink-0 -my-0.5 mr-0.5" onClick={(e) => e.stopPropagation()}>
                                                          <button type="button" disabled={i === 0} className="text-[10px] leading-none text-theme-mid hover:text-theme-dark disabled:opacity-30 px-0.5" onClick={(e) => { e.stopPropagation(); if (i === 0) return; setEditItems((prev: any[]) => { const n = [...prev]; [n[i-1], n[i]] = [n[i], n[i-1]]; return n }); setEditingItemIndicesByReceipt((prev) => { const arr = (prev[r.id] || []).map((x: number) => x === i ? i-1 : x === i-1 ? i : x); return { ...prev, [r.id]: arr } }); setEditingSection({ receiptId: r.id, section: 'item' }); }}>▲</button>
                                                          <button type="button" disabled={i === editItems.length - 1} className="text-[10px] leading-none text-theme-mid hover:text-theme-dark disabled:opacity-30 px-0.5" onClick={(e) => { e.stopPropagation(); if (i === editItems.length - 1) return; setEditItems((prev: any[]) => { const n = [...prev]; [n[i+1], n[i]] = [n[i], n[i+1]]; return n }); setEditingItemIndicesByReceipt((prev) => { const arr = (prev[r.id] || []).map((x: number) => x === i ? i+1 : x === i+1 ? i : x); return { ...prev, [r.id]: arr } }); setEditingSection({ receiptId: r.id, section: 'item' }); }}>▼</button>
                                                        </span>
                                                      )}
                                                      <span className={`truncate ${deleteConfirmItemIndex === i ? 'line-through text-theme-mid' : ''}`}>{name}</span>
                                                    </div>
                                                    <div role="button" tabIndex={0} className={`py-1.5 pl-3 pr-2 text-center tabular-nums ${deleteConfirmItemIndex === i ? 'line-through text-theme-mid' : ''} ${editModeReceiptId === r.id ? 'cursor-pointer rounded hover:ring-2 hover:ring-theme-mid/30' : ''}`} onClick={(e) => { e.stopPropagation(); if (editModeReceiptId === r.id && deleteConfirmItemIndex !== i) activateItemRowEdit(); }} onKeyDown={(e) => { if (editModeReceiptId === r.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); if (deleteConfirmItemIndex !== i) activateItemRowEdit(); } }}>{Number.isFinite(qty) ? qty : ''}</div>
                                                    <div role="button" tabIndex={0} className={`py-1.5 pl-3 pr-2 text-right tabular-nums ${deleteConfirmItemIndex === i ? 'line-through text-theme-mid' : ''} ${editModeReceiptId === r.id ? 'cursor-pointer rounded hover:ring-2 hover:ring-theme-mid/30' : ''}`} onClick={(e) => { e.stopPropagation(); if (editModeReceiptId === r.id && deleteConfirmItemIndex !== i) activateItemRowEdit(); }} onKeyDown={(e) => { if (editModeReceiptId === r.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); if (deleteConfirmItemIndex !== i) activateItemRowEdit(); } }}>{u}</div>
                                                    <div role="button" tabIndex={0} className={`py-1.5 pl-3 pr-2 text-right tabular-nums ${deleteConfirmItemIndex === i ? 'line-through text-theme-mid' : ''} ${editModeReceiptId === r.id ? 'cursor-pointer rounded hover:ring-2 hover:ring-theme-mid/30' : ''}`} onClick={(e) => { e.stopPropagation(); if (editModeReceiptId === r.id && deleteConfirmItemIndex !== i) activateItemRowEdit(); }} onKeyDown={(e) => { if (editModeReceiptId === r.id && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); if (deleteConfirmItemIndex !== i) activateItemRowEdit(); } }}>{p}</div>
                                                  </>
                                                )}
                                                <div className="bg-theme-cream" />
                                                {/* System Category + Sub Categories: col-span-2 when editing, split when displaying */}
                                                {isEditingCat ? (
                                                  <>
                                                    <div className="col-span-2 py-1 px-1 min-w-0 flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                                                      <div className="min-w-0 flex-1">
                                                        <SystemCategorySubSelector
                                                          categories={categoriesList}
                                                          value={pendingCategoryByItemId[itemId] ?? it.user_category_id ?? it.category_id ?? null}
                                                          onChange={(val) => setPendingCategoryByItemId((prev) => ({ ...prev, [itemId]: val }))}
                                                          onRefetchCategories={fetchCategories}
                                                          onCreateCategory={createCategory}
                                                          onCategoryCreated={(cat) => setCategoriesList((prev) => [...prev, cat])}
                                                        />
                                                      </div>
                                                      <button type="button" className="p-1 text-theme-mid hover:text-theme-red rounded shrink-0" onClick={(e) => { e.stopPropagation(); deactivateClassificationRow(); }} title="Remove from batch">✕</button>
                                                    </div>
                                                  </>
                                                ) : (
                                                  <>
                                                    <div className="py-1.5 px-2 min-w-0" onClick={(e) => e.stopPropagation()}>
                                                      <button
                                                        type="button"
                                                        className={`text-left w-full text-xs text-theme-dark truncate ${itemId ? 'hover:text-theme-orange cursor-pointer' : 'cursor-default'}`}
                                                        title={sysCat || 'No category'}
                                                        onClick={(e) => { e.stopPropagation(); if (!itemId) return; if (editModeReceiptId !== r.id) { setEditModeReceiptId(r.id); initEditFormFromJson(expandedReceiptData[r.id]); } setEditingSection({ receiptId: r.id, section: 'classification', index: i }); setClassificationEditingItemIds((prev) => new Set(prev).add(itemId)); setPendingCategoryByItemId((prev) => (itemId in prev ? prev : { ...prev, [itemId]: it.user_category_id ?? it.category_id ?? null })); }}
                                                      >
                                                        {sysCat || <span className="text-theme-mid">—</span>}
                                                      </button>
                                                    </div>
                                                    <div className="py-1.5 px-2 min-w-0" onClick={(e) => e.stopPropagation()}>
                                                      <button
                                                        type="button"
                                                        className={`text-left w-full text-xs text-theme-dark truncate ${itemId ? 'hover:text-theme-orange cursor-pointer' : 'cursor-default'}`}
                                                        title={subCat || ''}
                                                        onClick={(e) => { e.stopPropagation(); if (!itemId) return; if (editModeReceiptId !== r.id) { setEditModeReceiptId(r.id); initEditFormFromJson(expandedReceiptData[r.id]); } setEditingSection({ receiptId: r.id, section: 'classification', index: i }); setClassificationEditingItemIds((prev) => new Set(prev).add(itemId)); setPendingCategoryByItemId((prev) => (itemId in prev ? prev : { ...prev, [itemId]: it.user_category_id ?? it.category_id ?? null })); }}
                                                      >
                                                        {subCat || <span className="text-theme-mid">—</span>}
                                                      </button>
                                                    </div>
                                                  </>
                                                )}
                                                <div className="py-1.5 px-0.5 flex items-center justify-center">
                                                  {(it.category_source === 'llm' || it.category_source === 'rule_exact' || it.category_source === 'rule_fuzzy') ? (
                                                    <span className="inline-flex items-center justify-center w-5 h-5 rounded-sm bg-black text-white text-[9px] font-bold shrink-0" title="AI 分类">AI</span>
                                                  ) : null}
                                                </div>
                                                <div className="py-1.5 px-1 flex items-center justify-center">
                                                  {isEditingCat ? (
                                                    <span className="text-theme-mid text-xs">Editing</span>
                                                  ) : (
                                                    <label className={`relative flex items-center justify-center w-5 h-5 rounded border border-theme-mid bg-white has-[:checked]:bg-theme-orange has-[:checked]:border-theme-orange ${itemId ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}`} title={!itemId ? 'Item not saved yet' : undefined} onClick={(e) => e.stopPropagation()}>
                                                      <input
                                                        type="checkbox"
                                                        disabled={!itemId}
                                                        checked={selectedIdsForReceipt(r.id).has(itemId)}
                                                        onChange={(e) => {
                                                          if (!itemId) return
                                                          setSelectedIdsForReceipt(r.id, (prev) => {
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
                                                  )}
                                                </div>
                                                <div className="py-1.5 px-2 flex items-center justify-center">
                                                  {editModeReceiptId === r.id ? (
                                                    deleteConfirmItemIndex === i ? (
                                                      <span className="flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
                                                        <button type="button" className="w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center text-xs font-bold hover:bg-red-600" title="Confirm delete" onClick={(e) => { e.stopPropagation(); setDeleteConfirmItemIndex(null); setEditItems((prev: any[]) => prev.filter((_: any, idx: number) => idx !== i)); setEditingItemIndicesByReceipt((prev) => { const arr = (prev[r.id] || []).filter((x: number) => x !== i).map((x: number) => x > i ? x - 1 : x); if (arr.length === 0) { const next = { ...prev }; delete next[r.id]; return next } return { ...prev, [r.id]: arr } }); setEditingSection({ receiptId: r.id, section: 'item' }); }}>✓</button>
                                                        <button type="button" className="text-xs text-theme-mid hover:text-theme-dark px-0.5" title="Cancel" onClick={(e) => { e.stopPropagation(); setDeleteConfirmItemIndex(null); }}>esc</button>
                                                      </span>
                                                    ) : (
                                                      <button type="button" className="w-5 h-5 rounded-full border-2 border-red-500 text-red-500 flex items-center justify-center text-base font-bold leading-none hover:bg-red-50" title="Delete item" onClick={(e) => { e.stopPropagation(); setDeleteConfirmItemIndex(i); }}>−</button>
                                                    )
                                                  ) : isEditingCat ? (
                                                    <button type="button" className="p-1 bg-theme-light-gray text-theme-dark/90 rounded hover:bg-theme-mid/30 w-5 h-5 flex items-center justify-center" onClick={(e) => { e.stopPropagation(); deactivateClassificationRow(); }} title="Remove from batch">✕</button>
                                                  ) : (
                                                    <button type="button" className={`p-1 rounded w-5 h-5 flex items-center justify-center ${itemId ? 'text-theme-dark/90 hover:text-theme-dark hover:bg-theme-light-gray' : 'text-theme-mid cursor-not-allowed opacity-50'}`} onClick={(e) => { e.stopPropagation(); if (!itemId) return; if (editModeReceiptId !== r.id) { setEditModeReceiptId(r.id); initEditFormFromJson(expandedReceiptData[r.id]); } setEditingSection({ receiptId: r.id, section: 'classification', index: i }); setClassificationEditingItemIds((prev) => new Set(prev).add(itemId)); setPendingCategoryByItemId((prev) => (itemId in prev ? prev : { ...prev, [itemId]: it.user_category_id ?? it.category_id ?? null })); }} title={itemId ? 'Edit category' : r.current_status === 'needs_review' ? 'Complete the receipt review first before editing categories' : 'Category data not yet initialized — click "All" in Smart Categorization above to set up'}>✏️</button>
                                                  )}
                                                </div>
                                              </React.Fragment>
                                            )
                                          })}
                                          {editModeReceiptId === r.id && (
                                            <div className="col-span-10 px-3 py-1.5 border-t border-theme-light-gray/50" onClick={(e) => e.stopPropagation()}>
                                              <button type="button" className="flex items-center gap-2 text-sm text-theme-dark/70 hover:text-theme-dark" onClick={(e) => { e.stopPropagation(); setEditItems((prev: any[]) => [...prev, { _key: `new_${Date.now()}_${Math.random()}`, id: undefined, product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }]); setEditingSection({ receiptId: r.id, section: 'item' }); }}>
                                                <span className="w-5 h-5 rounded-full bg-green-500 text-white flex items-center justify-center text-base font-bold leading-none shrink-0">+</span>
                                                <span>Add item</span>
                                              </button>
                                            </div>
                                          )}

                                          {/* ④ 左下：小计/支付 | sep | ⑤ 右下：消息/空 */}
                                          <div className="col-span-4 p-4 border-t border-theme-ivory-dark">
                                            {rec && (
                                              <>
                                                {/* 用与左侧4列相同的列宽做子网格，让数字对齐 $ Amount 列 */}
                                                {items.length > 0 && (() => {
                                                  const toCents = (v: any): number => { const n = Number(v); if (!Number.isFinite(n)) return 0; return (Number.isInteger(n) && n >= 100) ? n : Math.round(n * 100) }
                                                  const editDisplayItems = editModeReceiptId === r.id ? editItems : items
                                                  const itemsSumCents = editDisplayItems.reduce((s: number, it: any) => s + toCents(it.line_total), 0)
                                                  const subNum = rec.subtotal != null ? Number(rec.subtotal) : NaN
                                                  const subtotalCents = (subNum >= 100 && Number.isInteger(subNum)) ? subNum : (Number.isFinite(subNum) ? Math.round(subNum * 100) : NaN)
                                                  const mismatch = Number.isFinite(subtotalCents) && Math.abs(itemsSumCents - subtotalCents) > 3
                                                  const showRedSumRow = r.current_status === 'needs_review' && mismatch
                                                  if (showRedSumRow) return (
                                                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.5fr) 3rem 4rem 5.5rem' }} className="text-xs font-medium text-red-600 tabular-nums mb-1">
                                                      <div>Items sum (computed)</div><div /><div />
                                                      <div className="text-right">${money(itemsSumCents)}</div>
                                                      <div>diff</div><div /><div />
                                                      <div className="text-right">{itemsSumCents - subtotalCents >= 0 ? '+' : ''}${((itemsSumCents - subtotalCents) / 100).toFixed(2)}</div>
                                                    </div>
                                                  )
                                                  if (!mismatch) return null
                                                  return (
                                                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.5fr) 3rem 4rem 5.5rem' }} className="text-xs text-amber-700 tabular-nums mb-1">
                                                      <div>Items sum (computed)</div><div /><div />
                                                      <div className="text-right">${money(itemsSumCents)}</div>
                                                    </div>
                                                  )
                                                })()}
                                                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.5fr) 3rem 4rem 5.5rem' }}>
                                                  <div>Subtotal</div><div /><div />
                                                  <div className="text-right tabular-nums">{rec.subtotal != null ? `$${money(rec.subtotal) ?? rec.subtotal}` : ''}</div>
                                                  <div>Tax</div><div /><div />
                                                  <div className="text-right tabular-nums">{rec.tax != null ? `$${money(rec.tax) ?? rec.tax}` : ''}</div>
                                                  <div className="font-medium">Total</div><div /><div />
                                                  <div className="text-right tabular-nums font-medium">{rec.total != null ? `$${money(rec.total) ?? rec.total}` : ''}</div>
                                                </div>
                                                <div className="border-t border-dashed border-theme-mid my-2 pt-2" />
                                                {editModeReceiptId === r.id && editingSection?.receiptId === r.id && editingSection?.section === 'payment_date' ? (
                                                  <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
                                                    <div><span className="text-xs text-theme-mid">Payment</span><br /><input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editPaymentMethod} onChange={(e) => setEditPaymentMethod(e.target.value)} placeholder="Visa" /></div>
                                                    <div><span className="text-xs text-theme-mid">Card last 4</span><br /><input className="w-full border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm max-w-[5rem]" inputMode="numeric" maxLength={4} value={editPaymentLast4} onChange={(e) => setEditPaymentLast4(e.target.value)} placeholder="3719" /></div>
                                                    <div><span className="text-xs text-theme-mid">Date</span><br /><input type="date" className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm" value={editReceiptDate} onChange={(e) => setEditReceiptDate(e.target.value)} /></div>
                                                    <div><span className="text-xs text-theme-mid">Time (24h)</span><br /><input className="border border-theme-light-gray rounded bg-theme-cream/50 px-1.5 py-0.5 text-sm font-mono w-16" placeholder="17:37" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} maxLength={5} inputMode="numeric" /></div>
                                                  </div>
                                                ) : (
                                                  <>
                                                    {editModeReceiptId === r.id ? (
                                                      <div
                                                        role="button"
                                                        tabIndex={0}
                                                        className="cursor-pointer rounded ring-offset-1 hover:ring-2 hover:ring-theme-mid/30 space-y-0.5"
                                                        onClick={(e) => { e.stopPropagation(); setEditingSection({ receiptId: r.id, section: 'payment_date' }) }}
                                                        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setEditingSection({ receiptId: r.id, section: 'payment_date' }) } }}
                                                      >
                                                        {$(rec.payment_method) && <div>Payment: {rec.payment_method}</div>}
                                                        {$(rec.card_last4) && <div>Payment Card: {rec.payment_method ? `${rec.payment_method} ` : ''}****{String(rec.card_last4).replace(/\D/g, '').slice(-4) || rec.card_last4}</div>}
                                                        {$(rec.purchase_date) && <div>Date: {rec.purchase_date}{rec.purchase_date_is_estimated && <span className="ml-1.5 inline-flex items-center rounded px-1 py-0 text-[10px] font-medium bg-amber-100 text-amber-700 border border-amber-300" title="Date was estimated — no date found on receipt">est.</span>}</div>}
                                                        <div>Time: {editPurchaseTime?.trim() || $(rec.purchase_time) ? formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '') : '—'}</div>
                                                      </div>
                                                    ) : (
                                                      <>
                                                        {$(rec.payment_method) && <div>Payment: {rec.payment_method}</div>}
                                                        {$(rec.card_last4) && <div>Payment Card: {rec.payment_method ? `${rec.payment_method} ` : ''}****{String(rec.card_last4).replace(/\D/g, '').slice(-4) || rec.card_last4}</div>}
                                                        {$(rec.purchase_date) && <div>Date: {rec.purchase_date}{rec.purchase_date_is_estimated && <span className="ml-1.5 inline-flex items-center rounded px-1 py-0 text-[10px] font-medium bg-amber-100 text-amber-700 border border-amber-300" title="Date was estimated — no date found on receipt">est.</span>}</div>}
                                                        <div>Time: {editPurchaseTime?.trim() || $(rec.purchase_time) ? formatTimeToHHmm(editPurchaseTime?.trim() || rec.purchase_time || '') : '—'}</div>
                                                      </>
                                                    )}
                                                    <div className="flex items-center justify-between gap-2 mt-2">
                                                      <span />
                                                      <div className="flex items-center gap-3 shrink-0">
                                                        {r.current_status === 'success' && (
                                                          <button
                                                            type="button"
                                                            onClick={(e) => { e.stopPropagation(); setEscalationReceiptId(r.id); setEscalationNotes(''); }}
                                                            className="text-sm text-theme-red hover:text-theme-red hover:underline"
                                                          >
                                                            Open a review
                                                          </button>
                                                        )}
                                                        <button
                                                          type="button"
                                                          onClick={(e) => { e.stopPropagation(); if (token && r.id) setDeleteConfirmReceiptId(r.id) }}
                                                          className="text-sm text-theme-red hover:text-theme-red hover:underline"
                                                        >
                                                          Delete this receipt
                                                        </button>
                                                      </div>
                                                    </div>
                                                    {r.current_status === 'success' && escalationReceiptId === r.id && (
                                                      <div className="mt-3 pt-3 border-t border-theme-light-gray flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                                                        <label className="text-xs font-medium text-theme-dark/90">Escalation notes (admin will see):</label>
                                                        <textarea className="w-full min-h-[72px] border border-theme-mid rounded px-2 py-1.5 text-sm text-theme-dark" value={escalationNotes} onChange={(e) => setEscalationNotes(e.target.value)} placeholder="Describe what’s wrong or what to fix…" />
                                                        <div className="flex gap-2">
                                                          <button type="button" disabled={escalationSubmitting} onClick={async () => { if (!r.id || !token) return; setEscalationSubmitting(true); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/escalate`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ notes: escalationNotes }) }); const data = await res.json().catch(() => ({})); if (res.ok && data.success) { setEscalationReceiptId(null); setEscalationNotes(''); await refetchReceiptDetail(r.id); fetchReceiptList(); alert('Escalated. Admin will review.'); } else { alert(data.detail || data.message || 'Escalation failed'); } } catch { alert('Network error'); } finally { setEscalationSubmitting(false); } }} className="text-xs font-medium text-white bg-theme-orange hover:bg-theme-orange/90 px-2 py-1.5 rounded disabled:opacity-50">Submit escalation</button>
                                                          <button type="button" onClick={() => { setEscalationReceiptId(null); setEscalationNotes(''); }} className="text-xs font-medium text-theme-dark/90 bg-theme-light-gray hover:bg-theme-mid/30 px-2 py-1.5 rounded border border-theme-mid">Cancel</button>
                                                        </div>
                                                      </div>
                                                    )}
                                                  </>
                                                )}
                                              </>
                                            )}
                                            {editModeReceiptId === r.id && (editingSection?.receiptId === r.id || items.some((it: { id?: string }) => it.id && classificationEditingItemIds.has(it.id))) && (
                                              <div className="mt-4 pt-4 border-t border-theme-light-gray">
                                                {correctMessage && (
                                                  <div className={`mb-2 p-2 rounded text-sm ${correctMessage.startsWith('Saved') ? 'bg-green-100 text-green-800' : 'bg-theme-red/15 text-theme-red'}`}>{correctMessage}</div>
                                                )}
                                                <button
                                                  type="button"
                                                  className="w-full px-4 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
                                                  disabled={correctSubmitting}
                                                  onClick={async (e) => {
                                                    e.stopPropagation()
                                                    if (!token || !r.id) return
                                                    setCorrectSubmitting(true)
                                                    setCorrectMessage(null)
                                                    setCategoryUpdateMessage(null)
                                                    try {
                                                      const receiptItemIds = items.map((it: { id?: string }) => it.id).filter(Boolean) as string[]
                                                      const toSaveCat = receiptItemIds.filter((id) => classificationEditingItemIds.has(id))
                                                      if (toSaveCat.length > 0) {
                                                        const batchRes = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/items/categories`, {
                                                          method: 'PATCH',
                                                          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
                                                          body: JSON.stringify({
                                                            updates: toSaveCat.map((itemId) => ({ item_id: itemId, user_category_id: pendingCategoryByItemId[itemId] ?? null })),
                                                          }),
                                                        })
                                                        if (!batchRes.ok) {
                                                          const err = await batchRes.json().catch(() => ({}))
                                                          setCategoryUpdateMessage(err?.detail ?? 'Save failed')
                                                          return
                                                        }
                                                        setCategoryUpdateMessage('Saved')
                                                        await refetchReceiptDetail(r.id)
                                                        setClassificationEditingItemIds((prev) => { const n = new Set(prev); toSaveCat.forEach((id) => n.delete(id)); return n })
                                                        setPendingCategoryByItemId((prev) => { const o = { ...prev }; toSaveCat.forEach((id) => delete o[id]); return o })
                                                        if (editingSection?.receiptId === r.id && editingSection?.section === 'classification') setEditingSection(null)
                                                      }
                                                      if (editingSection?.receiptId === r.id && editingSection?.section !== 'classification') {
                                                        const totalNum = editTotal.trim() ? parseFloat(editTotal) : NaN
                                                        if (isNaN(totalNum)) { setCorrectMessage('Please enter Total'); setCorrectSubmitting(false); return }
                                                        const summary = {
                                                          store_name: editStoreName.trim() || undefined,
                                                          store_address: [editAddressLine1, editAddressLine2, [editAddressCity, editAddressState, editAddressZip].filter(Boolean).join(editAddressCity && editAddressState ? ', ' : ' ').replace(/, $/, '').trim(), editAddressCountry].filter(Boolean).join('\n').trim() || undefined,
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
                                                            original_price: it.original_price?.trim() ? parseFloat(it.original_price) : undefined,
                                                            discount_amount: it.discount_amount?.trim() ? parseFloat(it.discount_amount) : undefined,
                                                          }))
                                                        const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/correct`, {
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
                                                        const detailRes = await fetch(`${apiBaseUrl}/api/receipt/${r.id}`, { headers: { Authorization: `Bearer ${token}` } })
                                                        if (detailRes.ok) {
                                                          const detailJson = await detailRes.json()
                                                          setExpandedReceiptData((prev) => ({ ...prev, [r.id]: detailJson }))
                                                        }
                                                        setEditingSection(null)
                                                        setEditingItemIndicesByReceipt((prev) => { const next = { ...prev }; delete next[r.id]; return next })
                                                      }
                                                    } catch (err) {
                                                      setCorrectMessage(err instanceof Error ? err.message : 'Submit failed')
                                                    } finally {
                                                      setCorrectSubmitting(false)
                                                    }
                                                  }}
                                                >
                                                  {correctSubmitting ? 'Saving…' : 'Confirm modification'}
                                                </button>
                                              </div>
                                            )}
                                          </div>
                                          <div className="border-t border-theme-cream bg-theme-cream" />
                                          <div className="col-span-5 p-4 border-t border-theme-ivory-dark flex flex-col gap-2">
                                            {(categoryUpdateMessage || smartCategorizeMessage) && (
                                              <div className={`text-xs ${(categoryUpdateMessage || smartCategorizeMessage) === 'Saved' || (smartCategorizeMessage && smartCategorizeMessage.startsWith('Updated')) ? 'text-green-600' : 'text-theme-red'}`}>
                                                {categoryUpdateMessage || smartCategorizeMessage}
                                              </div>
                                            )}
                                            {r.current_status === 'needs_review' && (
                                              <div className="p-4 rounded-lg border border-amber-200 bg-amber-50 flex flex-col gap-3">
                                                <p className="text-sm text-amber-900">Unfortunately, the senior processor couldn&apos;t resolve all questions. Please review the result and make any adjustments. Thank you.</p>
                                                {escalationReceiptId === r.id ? (
                                                  <div className="flex flex-col gap-2" onClick={(e) => e.stopPropagation()}>
                                                    <label className="text-xs font-medium text-amber-800">Escalation notes (admin will see):</label>
                                                    <textarea className="w-full min-h-[72px] border border-amber-300 rounded px-2 py-1.5 text-sm text-theme-dark" value={escalationNotes} onChange={(e) => setEscalationNotes(e.target.value)} placeholder="Describe what’s wrong or what to fix…" />
                                                    <div className="flex gap-2">
                                                      <button type="button" disabled={escalationSubmitting} onClick={async () => { if (!r.id || !token) return; setEscalationSubmitting(true); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/escalate`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }, body: JSON.stringify({ notes: escalationNotes }) }); const data = await res.json().catch(() => ({})); if (res.ok && data.success) { setEscalationReceiptId(null); setEscalationNotes(''); await refetchReceiptDetail(r.id); fetchReceiptList(); alert('Escalated. Admin will review.'); } else { alert(data.detail || data.message || 'Escalation failed'); } } catch { alert('Network error'); } finally { setEscalationSubmitting(false); } }} className="text-xs font-medium text-white bg-theme-orange hover:bg-theme-orange/90 px-2 py-1.5 rounded disabled:opacity-50">Submit escalation</button>
                                                      <button type="button" onClick={() => { setEscalationReceiptId(null); setEscalationNotes(''); }} className="text-xs font-medium text-amber-800 bg-amber-100 hover:bg-amber-200 px-2 py-1.5 rounded border border-amber-300">Cancel</button>
                                                    </div>
                                                  </div>
                                                ) : (
                                                <div className="flex items-center justify-between gap-2">
                                                  <button type="button" onClick={(e) => { e.stopPropagation(); toggleReviewReasoningCollapsed(r.id) }} className="text-left flex-1 min-w-0 flex items-center gap-2 text-sm font-medium text-amber-800">
                                                    {collapsedReviewReasoningReceiptIds.has(r.id) ? <span aria-hidden>▶</span> : <span aria-hidden>▼</span>}
                                                    <span>AI Smart Reasoning</span>
                                                  </button>
                                                  <button type="button" disabled={reviewCompleteLoading === r.id} onClick={async (e) => { e.stopPropagation(); if (!r.id || !token || reviewCompleteLoading) return; setReviewCompleteLoading(r.id); try { const res = await fetch(`${apiBaseUrl}/api/receipt/${r.id}/review-complete`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } }); const data = await res.json().catch(() => ({})); if (res.ok && data.success) { await refetchReceiptDetail(r.id); fetchReceiptList() } else alert(data.detail || data.message || 'Failed to complete review'); } catch { alert('Network error'); } finally { setReviewCompleteLoading(null); } }} className="shrink-0 text-xs font-medium text-white bg-green-600 hover:bg-green-700 px-2 py-1.5 rounded border border-green-700 disabled:opacity-50 disabled:cursor-not-allowed">{reviewCompleteLoading === r.id ? '…' : 'Review complete'}</button>
                                                </div>
                                                )}
                                                {!collapsedReviewReasoningReceiptIds.has(r.id) && (
                                                  <div className="text-sm text-amber-900 space-y-1.5">
                                                    {expandedReceiptData[r.id]?.review_metadata?.reasoning && (() => {
                                                      const { title, bullets } = parseReasoningBullets(String(expandedReceiptData[r.id].review_metadata.reasoning ?? ''))
                                                      return (
                                                        <div>
                                                          <p className="font-medium text-amber-800">{title}</p>
                                                          {bullets.length > 0 && <ul className="list-none pl-0 space-y-0.5">{bullets.map((line: string, i: number) => <li key={i}>• {line}</li>)}</ul>}
                                                        </div>
                                                      )
                                                    })()}
                                                    {expandedReceiptData[r.id]?.review_metadata?.sum_check_notes && expandedReceiptData[r.id].review_metadata.sum_check_notes !== (expandedReceiptData[r.id].review_metadata.reasoning || '') && <p><span className="font-medium text-amber-800">Sum check:</span> <span className="whitespace-pre-wrap">{expandedReceiptData[r.id].review_metadata.sum_check_notes}</span></p>}
                                                    {(expandedReceiptData[r.id]?.review_metadata?.item_count_on_receipt != null || expandedReceiptData[r.id]?.review_metadata?.item_count_extracted != null) && <p><span className="font-medium text-amber-800">Item count:</span> receipt says {String(expandedReceiptData[r.id].review_metadata.item_count_on_receipt ?? '—')}, extracted {String(expandedReceiptData[r.id].review_metadata.item_count_extracted ?? '—')}</p>}
                                                    {!(expandedReceiptData[r.id]?.review_metadata && Object.keys(expandedReceiptData[r.id].review_metadata).length > 0) && <p className="whitespace-pre-wrap">{expandedReceiptData[r.id]?.review_feedback || 'Model requested manual review.'}</p>}
                                                  </div>
                                                )}
                                                {!collapsedReviewReasoningReceiptIds.has(r.id) && (
                                                  <div className="flex items-center gap-3">
                                                    <button type="button" onClick={(e) => { e.stopPropagation(); toggleReviewReasoningCollapsed(r.id) }} className="text-xs text-amber-700 hover:text-amber-900 underline">Collapse</button>
                                                    <button type="button" onClick={(e) => { e.stopPropagation(); setEscalationReceiptId(r.id); setEscalationNotes(''); }} className="text-xs text-red-600 hover:text-red-700 hover:underline">Escalate</button>
                                                  </div>
                                                )}
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                        </div>
                                        </div>
                                        {/* Edit panel: 桌面覆盖右半，手机全宽 */}
                                        <div
                                          className={`absolute left-0 ${'md:left-1/2'} top-0 right-0 bottom-0 z-10 flex flex-col bg-white border-l border-theme-ivory-dark shadow-lg transition-transform duration-200 ease-out ${correctionOpenReceiptId === r.id ? 'translate-x-0' : 'translate-x-full'}`}
                                          onClick={(e) => e.stopPropagation()}
                                        >
                                      <div className="flex items-center justify-between px-3 py-2 border-b border-theme-ivory-dark bg-theme-cream shrink-0">
                                        <span className="text-sm font-medium text-theme-dark/90">Edit receipt</span>
                                        <button
                                          type="button"
                                          className="p-1.5 text-theme-mid hover:text-theme-dark hover:bg-theme-light-gray rounded"
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
                                            <span className="text-xs text-theme-mid">Store name</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editStoreName} onChange={(e) => setEditStoreName(e.target.value)} placeholder="Store name" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">Address line 1</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressLine1} onChange={(e) => setEditAddressLine1(e.target.value)} placeholder="Street address" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">Address line 2</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressLine2} onChange={(e) => setEditAddressLine2(e.target.value)} placeholder="Unit / Suite" />
                                          </label>
                                          <div className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">City / State / ZIP</span>
                                            <div className="grid gap-1" style={{ gridTemplateColumns: '2fr 1fr 1fr' }}>
                                              <input className="border rounded px-2 py-1 text-sm" value={editAddressCity} onChange={(e) => setEditAddressCity(e.target.value)} placeholder="City" />
                                              <input className="border rounded px-2 py-1 text-sm" value={editAddressState} onChange={(e) => setEditAddressState(e.target.value)} placeholder="ST" />
                                              <input className="border rounded px-2 py-1 text-sm" value={editAddressZip} onChange={(e) => setEditAddressZip(e.target.value)} placeholder="ZIP" />
                                            </div>
                                          </div>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">Country</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editAddressCountry} onChange={(e) => setEditAddressCountry(e.target.value)} placeholder="US" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">Phone</span>
                                            <input className="border rounded px-2 py-1 text-sm" value={editMerchantPhone} onChange={(e) => setEditMerchantPhone(e.target.value)} placeholder="425-640-2648" />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">Purchase date</span>
                                            <input type="date" className="border rounded px-2 py-1 text-sm" value={editReceiptDate} onChange={(e) => setEditReceiptDate(e.target.value)} />
                                          </label>
                                          <label className="flex flex-col gap-0.5">
                                            <span className="text-xs text-theme-mid">Purchase time (optional, 24-hour only, e.g. 15:34)</span>
                                            <input type="text" className="border rounded px-2 py-1 text-sm font-mono" placeholder="15:34" value={editPurchaseTime} onChange={(e) => setEditPurchaseTime(e.target.value)} maxLength={5} pattern="([01]?[0-9]|2[0-3]):[0-5][0-9]" title="Please enter time in 24-hour HH:MM format" />
                                          </label>
                                          <div className="grid grid-cols-3 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Subtotal</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editSubtotal} onChange={(e) => setEditSubtotal(e.target.value)} placeholder="0.00" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Tax</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editTax} onChange={(e) => setEditTax(e.target.value)} placeholder="0.00" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Total *</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editTotal} onChange={(e) => setEditTotal(e.target.value)} placeholder="0.00" />
                                            </label>
                                          </div>
                                          <div className="grid grid-cols-2 gap-2">
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Currency</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editCurrency} onChange={(e) => setEditCurrency(e.target.value)} placeholder="USD" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Payment method</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editPaymentMethod} onChange={(e) => setEditPaymentMethod(e.target.value)} placeholder="AMEX Credit" />
                                            </label>
                                            <label className="flex flex-col gap-0.5">
                                              <span className="text-xs text-theme-mid">Card last 4</span>
                                              <input className="border rounded px-2 py-1 text-sm" value={editPaymentLast4} onChange={(e) => setEditPaymentLast4(e.target.value)} placeholder="5030" maxLength={4} />
                                            </label>
                                          </div>
                                        </div>
                                        <div>
                                          <p className="text-xs text-theme-dark/90 mb-2">Item lines</p>
                                          {/* 手机：每条两行（name 一行，Qty/Unit pr/Amount 一行），无 table */}
                                          <div className="md:hidden max-h-48 overflow-auto border border-theme-light-gray rounded divide-y divide-theme-light-gray/50">
                                            {editItems.map((row, idx) => (
                                              <div key={row._key ?? idx} className="p-2 space-y-2">
                                                <div>
                                                  <label className="text-xs text-theme-mid block mb-0.5">Product name</label>
                                                  <input className="w-full border rounded px-2 py-1.5 text-sm" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} />
                                                </div>
                                                <div className="grid grid-cols-3 gap-2">
                                                  <div>
                                                    <label className="text-xs text-theme-mid block mb-0.5">Qty</label>
                                                    <input type="text" inputMode="numeric" className="w-full border rounded px-2 py-1.5 text-sm" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} />
                                                  </div>
                                                  <div>
                                                    <label className="text-xs text-theme-mid block mb-0.5">Unit pr</label>
                                                    <input className="w-full border rounded px-2 py-1.5 text-sm" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} />
                                                  </div>
                                                  <div>
                                                    <label className="text-xs text-theme-mid block mb-0.5">$ Amount</label>
                                                    <input className="w-full border rounded px-2 py-1.5 text-sm" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} />
                                                  </div>
                                                </div>
                                              </div>
                                            ))}
                                          </div>
                                          {/* 桌面：原 table */}
                                          <div className="hidden md:block max-h-48 overflow-auto border border-theme-light-gray rounded">
                                            <table className="w-full border-collapse text-sm">
                                              <thead>
                                                <tr className="text-xs text-theme-mid font-medium bg-theme-cream border-b border-theme-ivory-dark">
                                                  <th className="text-left py-1.5 px-2 font-normal">Product name</th>
                                                  <th className="text-left py-1.5 px-2 w-16">Qty</th>
                                                  <th className="text-left py-1.5 px-2 w-20">Unit pr</th>
                                                  <th className="text-left py-1.5 px-2 w-20">$ Amount</th>
                                                </tr>
                                              </thead>
                                              <tbody>
                                                {editItems.map((row, idx) => (
                                                  <tr key={row._key ?? idx} className="border-b border-theme-light-gray/50 last:border-0">
                                                    <td className="py-1 px-2"><input className="w-full min-w-[120px] border rounded px-1.5 py-0.5" placeholder="Product name" value={row.product_name} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], product_name: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input type="text" inputMode="numeric" className="w-full border rounded px-1.5 py-0.5" value={row.quantity} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], quantity: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input className="w-full border rounded px-1.5 py-0.5" value={row.unit_price} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], unit_price: e.target.value }; return n })} /></td>
                                                    <td className="py-1 px-2"><input className="w-full border rounded px-1.5 py-0.5" value={row.line_total} onChange={(e) => setEditItems((prev) => { const n = [...prev]; n[idx] = { ...n[idx], line_total: e.target.value }; return n })} /></td>
                                                  </tr>
                                                ))}
                                              </tbody>
                                            </table>
                                          </div>
                                          <button type="button" className="mt-2 text-sm text-theme-blue hover:underline" onClick={() => setEditItems((prev) => [...prev, { _key: `new_${Date.now()}_${Math.random()}`, product_name: '', quantity: '1', unit: '', unit_price: '', line_total: '', on_sale: false, original_price: '', discount_amount: '' }])}>
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
                                                store_address: [editAddressLine1, editAddressLine2, [editAddressCity, editAddressState, editAddressZip].filter(Boolean).join(editAddressCity && editAddressState ? ', ' : ' ').replace(/, $/, '').trim(), editAddressCountry].filter(Boolean).join('\n').trim() || undefined,
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
                                              setUploadResult(null)
                                              setUploadError(null)
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
                                {(userClass === 7 || userClass === 9) && (
                                  <div className="mt-4 flex flex-wrap items-center gap-2">
                                    <button
                                      type="button"
                                      onClick={(e) => { e.stopPropagation(); setShowRawJson((v) => !v) }}
                                      className="text-sm text-theme-dark/90 hover:text-theme-dark underline"
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
                                      className="text-sm text-theme-dark/90 hover:text-theme-dark underline"
                                    >
                                      Copy
                                    </button>
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
                                      className="text-sm text-theme-blue hover:opacity-90 underline"
                                    >
                                      View workflow
                                    </button>
                                  </div>
                                )}
                                {showRawJson && expandedReceiptData[r.id] && (
                                  <div className="mt-2 rounded overflow-hidden border border-theme-light-gray">
                                    <div className="bg-theme-slate px-3 py-1.5 text-xs text-theme-gray-919">Processing result JSON</div>
                                    <div className="bg-theme-black p-3 max-h-64 overflow-auto">
                                      <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap">
                                        {JSON.stringify(expandedReceiptData[r.id], null, 2)}
                                      </pre>
                                    </div>
                                  </div>
                                )}
                                </React.Fragment>
                                );
                                  })()}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                    )
                  })}
                  {hasMoreOnDesktop && (
                    <button
                      type="button"
                      className="w-full py-3 text-sm text-theme-orange hover:underline font-medium"
                      onClick={() => setDesktopReceiptVisibleCount((c) => c + 10)}
                    >
                      Show more receipts ({flattenedByDate.length - desktopReceiptVisibleCount} remaining)
                    </button>
                  )}
                </div>
                </div>
              );
            })()
          )}
        </div>

        {/* Delete receipt confirmation modal */}
        {deleteConfirmReceiptId && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={() => { if (!deleteConfirmLoading) setDeleteConfirmReceiptId(null) }}
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-receipt-title"
          >
            <div
              className="bg-white rounded-lg shadow-xl max-w-md w-full p-5"
              onClick={(e) => e.stopPropagation()}
            >
              <h3 id="delete-receipt-title" className="font-semibold text-theme-dark text-lg mb-2">Delete receipt?</h3>
              <p className="text-theme-dark/90 text-sm mb-5">
                This will permanently remove this receipt. This cannot be undone.
              </p>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  disabled={deleteConfirmLoading}
                  onClick={() => setDeleteConfirmReceiptId(null)}
                  className="px-4 py-2 text-sm font-medium text-theme-dark/90 bg-theme-light-gray/50 hover:bg-theme-light-gray rounded-lg border border-theme-mid disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={deleteConfirmLoading}
                  onClick={async () => {
                    if (!token || !deleteConfirmReceiptId) return
                    setDeleteConfirmLoading(true)
                    try {
                      const res = await fetch(`${apiBaseUrl}/api/receipt/${deleteConfirmReceiptId}`, {
                        method: 'DELETE',
                        headers: { Authorization: `Bearer ${token}` },
                      })
                      if (!res.ok) {
                        const data = await res.json().catch(() => ({}))
                        throw new Error(data.detail || 'Delete failed')
                      }
                      if (expandedReceiptIds.has(deleteConfirmReceiptId)) {
                        setExpandedReceiptIds((prev) => { const next = new Set(prev); next.delete(deleteConfirmReceiptId); return next })
                        setExpandedReceiptData((prev) => { const next = { ...prev }; delete next[deleteConfirmReceiptId]; return next })
                        if (correctionOpenReceiptId === deleteConfirmReceiptId) setCorrectionOpenReceiptId(null)
                      }
                      setDeleteConfirmReceiptId(null)
                      fetchReceiptList()
                    } catch (err) {
                      alert(err instanceof Error ? err.message : 'Delete failed')
                    } finally {
                      setDeleteConfirmLoading(false)
                    }
                  }}
                  className="px-4 py-2 text-sm font-medium text-white bg-theme-red hover:bg-theme-red/90 rounded-lg disabled:opacity-50"
                >
                  {deleteConfirmLoading ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Processing runs modal (admin only) */}
        {processingRunsModalReceiptId && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => { setProcessingRunsModalReceiptId(null); setProcessingRunsData(null) }}>
            <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col" onClick={(e) => e.stopPropagation()}>
              <div className="px-4 py-3 border-b flex justify-between items-center">
                <h3 className="font-semibold text-theme-dark">Processing workflow — Receipt {processingRunsModalReceiptId.slice(0, 8)}…</h3>
                <button type="button" onClick={() => { setProcessingRunsModalReceiptId(null); setProcessingRunsData(null) }} className="text-theme-mid hover:text-theme-dark/90 text-lg leading-none">×</button>
              </div>
              <div className="p-4 overflow-auto flex-1 min-h-0">
                {processingRunsLoading ? (
                  <p className="text-theme-mid">Loading…</p>
                ) : processingRunsData ? (
                  <>
                    <div className="mb-4 p-3 bg-theme-light-gray/50 rounded">
                      <p className="text-sm font-medium text-theme-dark/90">Track</p>
                      <p className="text-sm text-theme-dark">
                        {processingRunsData.track === 'specific_rule' ? (
                          <>Specific rule (method: <code className="bg-white px-1 rounded">{processingRunsData.track_method ?? '—'}</code>)</>
                        ) : processingRunsData.track === 'general' ? (
                          <>General track (no store-specific rule matched)</>
                        ) : processingRunsData.track === 'vision_store_specific' ? (
                          <>Vision store-specific (e.g. Costco second round) — pipeline: <code className="bg-white px-1 rounded">{(processingRunsData as { pipeline_version?: string }).pipeline_version ?? 'vision_b'}</code></>
                        ) : processingRunsData.track === 'vision_escalation' ? (
                          <>Vision escalation — pipeline: <code className="bg-white px-1 rounded">{(processingRunsData as { pipeline_version?: string }).pipeline_version ?? 'vision_b'}</code></>
                        ) : processingRunsData.track === 'vision_primary' ? (
                          <>Vision primary — pipeline: <code className="bg-white px-1 rounded">{(processingRunsData as { pipeline_version?: string }).pipeline_version ?? 'vision_b'}</code></>
                        ) : (
                          <>
                            Unknown (no rule_based_cleaning or vision run recorded).
                            {(processingRunsData as { pipeline_version?: string | null }).pipeline_version && (
                              <span className="block mt-1 text-theme-dark/90">
                                Pipeline: <code className="bg-white px-1 rounded">{(processingRunsData as { pipeline_version?: string }).pipeline_version}</code>
                              </span>
                            )}
                          </>
                        )}
                      </p>
                    </div>
                    {Array.isArray(processingRunsData.workflow_steps) && processingRunsData.workflow_steps.length > 0 && (
                      <div className="mb-4">
                        <p className="text-sm font-medium text-theme-dark/90 mb-2">Workflow path ({processingRunsData.workflow_steps.length} steps)</p>
                        <div className="rounded border border-theme-light-gray bg-theme-cream p-2 flex flex-wrap gap-2">
                          {(processingRunsData.workflow_steps as Array<Record<string, unknown>>).map((s: Record<string, unknown>, i: number) => {
                            const r = String(s.result ?? '')
                            const resultClass = r === 'pass' || r === 'ok' || r === 'yes' ? 'text-green-600' : r === 'fail' || r === 'no' ? 'text-theme-red' : 'text-theme-dark/90'
                            return (
                              <span key={String(s.id ?? i)} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-mono bg-white border border-theme-light-gray" title={s.details ? JSON.stringify(s.details) : undefined}>
                                <span className="text-theme-mid">{Number(s.sequence) + 1}.</span>
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
                    <p className="text-sm font-medium text-theme-dark/90 mb-2 mt-2">Runs ({processingRunsData.runs.length})</p>
                    <div className="space-y-3">
                      {processingRunsData.runs.map((run: Record<string, unknown>, idx: number) => (
                        <ProcessingRunCard key={String(run.id ?? idx)} run={run} />
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="text-theme-mid">No data</p>
                )}
              </div>
            </div>
          </div>
        )}
      {/* Back to top: only on tap; overscroll-behavior in globals prevents bounce-to-top when reaching bottom */}
      <div className="flex justify-center pb-8 pt-2">
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          className="text-xs text-theme-mid hover:text-theme-dark flex items-center gap-1 hover:underline"
        >
          ↑ Back to top
        </button>
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
    <div className="border rounded p-3 bg-theme-cream">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{stage}</span>
        <span className={status === 'pass' ? 'text-green-600' : 'text-theme-red'}>{status}</span>
        {validation && <span className="text-theme-mid">validation: {validation}</span>}
        {provider && <span className="text-theme-mid">{provider}{model ? ` / ${model}` : ''}</span>}
        <span className="text-theme-mid" suppressHydrationWarning>{created}</span>
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
