'use client'

import { useRef, useCallback, useState, useEffect } from 'react'
import { useCameraStream } from './useCameraStream'
import { useApiUrl } from '@/lib/api-url-context'
import { authFetch } from '@/lib/auth-context'

function normalizeNetworkError(msg: string, apiBaseUrl: string): string {
  if (msg === 'Load failed' || msg === 'Load failed.' || msg.includes('Failed to fetch')) {
    const tip = typeof window !== 'undefined' && (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1')
      ? '当前是从其他地址访问的，请把 .env.local 的 NEXT_PUBLIC_API_URL 设为后端真实地址（ngrok 或 http://后端电脑IP:8000）。'
      : '请确认后端在 ' + apiBaseUrl + ' 运行；若从手机访问请用 ngrok 并设置 NEXT_PUBLIC_API_URL。'
    return '无法连接后端。' + tip
  }
  return msg
}

type AuthCtx = { token: string | null; refreshToken: () => Promise<string | null> } | null

type Props = {
  token: string | null
  /** 若传入则 401 时自动刷新并重试一次 */
  auth?: AuthCtx
  disabled?: boolean
  /** 由父组件传入：整页处于「上传中」时为 true，相机按钮显示为沙漏 + Processing… 与 Upload receipt 一致 */
  showAsProcessing?: boolean
  /** 上传前检查队列：返回 { allowed, key }，不允许时（满 5 张或重复图）不发起上传 */
  onCheckQueue?: (blob: Blob) => Promise<{ allowed: boolean; key?: string }>
  /** 上传结束（成功或失败）时从队列移除，传入 onCheckQueue 返回的 key */
  onRemoveFromQueue?: (key: string) => void
  onUploadStart?: () => void
  onSuccess?: () => void
  onError?: (message: string) => void
  /** Optional ref to the trigger button so parent can call .click() to open camera (e.g. from header) */
  triggerRef?: React.RefObject<HTMLButtonElement | null>
}

/**
 * Button that opens a camera modal, captures a photo, shows preview (freeze), then user can Upload or Retake.
 * Intended for mobile (camera permission) but works on desktop with webcam.
 */
export default function CameraCaptureButton({ token, auth, disabled, showAsProcessing, onCheckQueue, onRemoveFromQueue, onUploadStart, onSuccess, onError, triggerRef }: Props) {
  const apiBaseUrl = useApiUrl()
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { stream, error: streamError, status, start, stop } = useCameraStream()
  const [open, setOpen] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [uploading, setUploading] = useState(false)
  /** 拍照后的预览：blob 用于上传，previewUrl 用于展示（需在关闭/重拍时 revoke） */
  const [capturedBlob, setCapturedBlob] = useState<Blob | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  /** 拍照后短暂屏蔽 Upload 点击，防止移动端幽灵点击（ghost click）在按钮位置交换时误触发上传 */
  const captureGuardRef = useRef(false)

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const attachStream = useCallback(
    (video: HTMLVideoElement | null) => {
      if (video && stream) {
        video.srcObject = stream
        video.play().catch(() => {})
      }
    },
    [stream]
  )

  const handleOpen = useCallback(async () => {
    if (!token || disabled) return
    setOpen(true)
    setCapturing(false)
    setUploading(false)
    setCapturedBlob(null)
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
      setPreviewUrl(null)
    }
    try {
      await start()
    } catch {
      onError?.('Camera access denied or not available.')
    }
  }, [token, disabled, start, onError, previewUrl])

  const handleClose = useCallback(() => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
      setPreviewUrl(null)
    }
    setCapturedBlob(null)
    stop()
    setOpen(false)
    setCapturing(false)
    setUploading(false)
  }, [stop, previewUrl])

  const handleCapture = useCallback(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !stream || !token) return

    setCapturing(true)
    const w = video.videoWidth
    const h = video.videoHeight
    if (w === 0 || h === 0) {
      onError?.('Video not ready. Try again.')
      setCapturing(false)
      return
    }
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      onError?.('Could not capture image.')
      setCapturing(false)
      return
    }
    ctx.drawImage(video, 0, 0)
    canvas.toBlob(
      (blob) => {
        setCapturing(false)
        if (!blob) {
          onError?.('Could not capture image.')
          return
        }
        if (previewUrl) URL.revokeObjectURL(previewUrl)
        setPreviewUrl(URL.createObjectURL(blob))
        setCapturedBlob(blob)
        // 设置短暂保护期，防止移动端幽灵点击在按钮切换时自动触发 Upload
        captureGuardRef.current = true
        setTimeout(() => { captureGuardRef.current = false }, 400)
      },
      'image/jpeg',
      0.9
    )
  }, [stream, token, onError, previewUrl])

  const handleRetake = useCallback(() => {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
      setPreviewUrl(null)
    }
    setCapturedBlob(null)
  }, [previewUrl])

  const handleUpload = useCallback(async () => {
    // 幽灵点击保护：拍照后 400ms 内忽略 Upload 触发，防止移动端按钮位置交换导致的自动上传
    if (captureGuardRef.current) return
    if (!capturedBlob) {
      onError?.('No photo to upload. Tap Retake to capture again.')
      return
    }
    if (!token) {
      onError?.('Not logged in. Please refresh the page and try again.')
      return
    }
    let queueKey: string | undefined
    if (onCheckQueue) {
      const result = await onCheckQueue(capturedBlob)
      if (!result.allowed) {
        onError?.('This image is already being uploaded or the queue is full (up to 5 at a time).')
        return
      }
      queueKey = result.key
    } else {
      onUploadStart?.()
    }
    setUploading(true)
    const formData = new FormData()
    formData.append('file', capturedBlob, 'capture.jpg')
    setOpen(false)
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
      setPreviewUrl(null)
    }
    setCapturedBlob(null)
    stop()
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 180000)
      const res = auth
        ? await authFetch(
            apiBaseUrl,
            '/api/receipt/workflow-vision',
            { method: 'POST', headers: {}, body: formData, signal: controller.signal },
            auth
          )
        : await fetch(`${apiBaseUrl}/api/receipt/workflow-vision`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
            body: formData,
            signal: controller.signal,
          })
      clearTimeout(timeoutId)
      if (res.ok) {
        const data = await res.json()
        if (data.success === false && data.error === 'duplicate_receipt') {
          onError?.('This receipt was already uploaded. If something is wrong, delete the existing receipt and upload a new photo.')
          return
        }
        onSuccess?.()
      } else {
        if (res.status === 401) {
          onError?.('Session updated. Please try again.')
        } else {
          const err = await res.json().catch(() => ({}))
          const msg = typeof err.detail === 'string' ? err.detail : err.detail?.detail ?? res.statusText
          onError?.(msg)
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        onError?.('Request timed out (3 min). Check My Receipts later in case it finished.')
      } else {
        onError?.(normalizeNetworkError(e instanceof Error ? e.message : 'Upload failed.', apiBaseUrl))
      }
    } finally {
      setUploading(false)
      if (queueKey) onRemoveFromQueue?.(queueKey)
    }
  }, [capturedBlob, token, onCheckQueue, onRemoveFromQueue, onUploadStart, onSuccess, onError, stop, previewUrl])

  if (showAsProcessing) {
    return (
      <div
        className="w-full flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium text-white bg-green-500 cursor-wait select-none min-h-[44px] sm:min-h-0"
        aria-busy="true"
        aria-label="Processing receipt"
      >
        <span className="inline-block animate-spin text-lg" aria-hidden>⏳</span>
        <span>Processing…</span>
      </div>
    )
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={handleOpen}
        disabled={disabled}
        className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium hover:opacity-85 disabled:opacity-50 disabled:cursor-not-allowed transition min-h-[44px] sm:min-h-0"
        style={{ backgroundColor: '#191919', color: '#FAFAF7' }}
        aria-label="Take photo of receipt"
      >
        <span aria-hidden>📷</span>
        <span>Camera</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-[99999] flex flex-col bg-black" style={{ touchAction: 'manipulation' }}>
          <div className="flex items-center justify-between py-2 px-3 sm:py-2 sm:px-4 bg-black/80 text-white shrink-0">
            <span className="text-xs sm:text-sm font-medium">Point camera at receipt</span>
            <button
              type="button"
              onClick={handleClose}
              className="p-1.5 rounded-full hover:bg-white/20 min-h-[32px] min-w-[32px] sm:min-h-[44px] sm:min-w-[44px] flex items-center justify-center"
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 relative flex items-center justify-center min-h-0 overflow-hidden">
            {streamError && (
              <p className="text-theme-red px-4 text-center text-sm">{streamError}</p>
            )}
            {status === 'requesting' && !previewUrl && (
              <p className="text-white text-sm">Requesting camera…</p>
            )}
            {previewUrl ? (
              <img
                src={previewUrl}
                alt="Captured receipt"
                className="max-h-full max-w-full object-contain w-full h-full"
              />
            ) : (
              stream && (
                <video
                  ref={(el) => {
                    videoRef.current = el
                    attachStream(el)
                  }}
                  playsInline
                  muted
                  className="max-h-full max-w-full object-contain w-full h-full"
                />
              )
            )}
          </div>

          <canvas ref={canvasRef} className="hidden" />

          <div className="p-3 sm:p-4 bg-black/80 flex flex-row gap-2 sm:gap-3 justify-center items-center shrink-0">
            {previewUrl ? (
              <>
                <button
                  type="button"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); handleUpload() }}
                  onPointerDown={(e) => e.stopPropagation()}
                  disabled={uploading}
                  className="flex-1 min-w-0 px-4 py-2.5 sm:px-6 sm:py-3 rounded-lg font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px] sm:min-h-[48px] active:bg-green-800 select-none"
                  aria-label="Upload photo"
                >
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
                <button
                  type="button"
                  onClick={handleRetake}
                  disabled={uploading}
                  className="flex-1 min-w-0 px-4 py-2.5 sm:px-6 sm:py-3 rounded-lg font-medium text-white bg-theme-red hover:bg-red-700 min-h-[44px] sm:min-h-[48px] select-none"
                  aria-label="Retake photo"
                >
                  Retake
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleCapture}
                  disabled={!stream || capturing}
                  className="flex-1 min-w-0 px-4 py-2.5 sm:px-6 sm:py-3 rounded-lg font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed min-h-[44px] sm:min-h-[48px] select-none"
                >
                  {capturing ? 'Capturing…' : 'Take'}
                </button>
                <button
                  type="button"
                  onClick={handleClose}
                  className="flex-1 min-w-0 px-4 py-2.5 sm:px-6 sm:py-3 rounded-lg font-medium text-theme-gray-919 hover:bg-white/10 min-h-[44px] sm:min-h-[48px] select-none"
                  aria-label="Cancel"
                >
                  Cancel
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  )
}
