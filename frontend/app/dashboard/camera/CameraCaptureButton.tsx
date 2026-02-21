'use client'

import { useRef, useCallback, useState } from 'react'
import { useCameraStream } from './useCameraStream'

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

type Props = {
  token: string | null
  disabled?: boolean
  onSuccess?: () => void
  onError?: (message: string) => void
}

/**
 * Button that opens a camera modal, captures a photo, and uploads it to the receipt workflow.
 * Intended for mobile (camera permission) but works on desktop with webcam.
 */
export default function CameraCaptureButton({ token, disabled, onSuccess, onError }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const { stream, error: streamError, status, start, stop } = useCameraStream()
  const [open, setOpen] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [uploading, setUploading] = useState(false)

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
    try {
      await start()
    } catch {
      onError?.('Camera access denied or not available.')
    }
  }, [token, disabled, start, onError])

  const handleClose = useCallback(() => {
    stop()
    setOpen(false)
    setCapturing(false)
    setUploading(false)
  }, [stop])

  const handleCapture = useCallback(async () => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !stream || !token) return

    setCapturing(true)
    try {
      const w = video.videoWidth
      const h = video.videoHeight
      if (w === 0 || h === 0) {
        onError?.('Video not ready. Try again.')
        return
      }
      canvas.width = w
      canvas.height = h
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        onError?.('Could not capture image.')
        return
      }
      ctx.drawImage(video, 0, 0)
      canvas.toBlob(
        async (blob) => {
          if (!blob || !token) return
          setUploading(true)
          try {
            const formData = new FormData()
            formData.append('file', blob, 'capture.jpg')
            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 180000) // 3 min (LLM pipeline)
            const res = await fetch(`${apiUrl()}/api/receipt/workflow`, {
              method: 'POST',
              headers: { Authorization: `Bearer ${token}` },
              body: formData,
              signal: controller.signal,
            })
            clearTimeout(timeoutId)
            if (res.ok) {
              const data = await res.json()
              onSuccess?.()
              handleClose()
            } else {
              const err = await res.json().catch(() => ({}))
              const msg = typeof err.detail === 'string' ? err.detail : err.detail?.detail ?? res.statusText
              onError?.(msg)
            }
          } catch (e) {
            if ((e as Error).name === 'AbortError') {
              onError?.('Request timed out (3 min). Check My Receipts later in case it finished.')
            } else {
              onError?.(e instanceof Error ? e.message : 'Upload failed.')
            }
          } finally {
            setUploading(false)
            setCapturing(false)
          }
        },
        'image/jpeg',
        0.9
      )
    } catch (e) {
      onError?.(e instanceof Error ? e.message : 'Capture failed.')
      setCapturing(false)
    }
  }, [stream, token, onSuccess, onError, handleClose])

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        disabled={disabled}
        className="inline-flex items-center justify-center gap-2 px-4 py-2.5 sm:px-5 sm:py-2.5 rounded-lg font-medium text-white bg-gray-600 hover:bg-gray-700 disabled:opacity-50 transition min-h-[44px] sm:min-h-0"
        aria-label="Take photo of receipt"
      >
        <span aria-hidden>📷</span>
        <span className="hidden sm:inline">Camera</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex flex-col bg-black">
          <div className="flex items-center justify-between p-3 sm:p-4 bg-black/80 text-white shrink-0">
            <span className="text-sm font-medium">Point camera at receipt</span>
            <button
              type="button"
              onClick={handleClose}
              className="p-2 rounded-full hover:bg-white/20 min-h-[44px] min-w-[44px] flex items-center justify-center"
              aria-label="Close"
            >
              ✕
            </button>
          </div>

          <div className="flex-1 relative flex items-center justify-center min-h-0">
            {streamError && (
              <p className="text-red-400 px-4 text-center text-sm">{streamError}</p>
            )}
            {status === 'requesting' && (
              <p className="text-white text-sm">Requesting camera…</p>
            )}
            {stream && (
              <video
                ref={(el) => {
                  videoRef.current = el
                  attachStream(el)
                }}
                playsInline
                muted
                className="max-h-full max-w-full object-contain w-full h-full"
              />
            )}
          </div>

          <canvas ref={canvasRef} className="hidden" />

          <div className="p-4 sm:p-6 bg-black/80 flex flex-col sm:flex-row gap-3 justify-center items-stretch sm:items-center">
            <button
              type="button"
              onClick={handleCapture}
              disabled={!stream || capturing || uploading}
              className="px-6 py-3 rounded-lg font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed min-h-[48px]"
            >
              {uploading ? 'Uploading…' : capturing ? 'Capturing…' : 'Take photo'}
            </button>
            <button
              type="button"
              onClick={handleClose}
              className="px-6 py-3 rounded-lg font-medium text-gray-200 hover:bg-white/10 min-h-[48px]"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </>
  )
}
