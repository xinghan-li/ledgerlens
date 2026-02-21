'use client'

import { useState, useCallback, useEffect } from 'react'

/**
 * Hook to request and release a camera stream (getUserMedia).
 * Prefer environment (back) camera on mobile for receipt scanning.
 */
export function useCameraStream() {
  const [stream, setStream] = useState<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'requesting' | 'active' | 'error'>('idle')

  const start = useCallback(async () => {
    setError(null)
    setStatus('requesting')
    try {
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
        const msg =
          'Camera is only available on HTTPS or localhost. This page is open over HTTP from another device. Use an HTTPS URL (e.g. ngrok) to test camera on your phone.'
        setError(msg)
        setStatus('error')
        throw new Error(msg)
      }
      const media = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'environment', // back camera on phone
          width: { ideal: 1280 },
          height: { ideal: 720 },
        },
        audio: false,
      })
      setStream(media)
      setStatus('active')
      return media
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Could not access camera'
      setError(message)
      setStatus('error')
      throw e
    }
  }, [])

  const stop = useCallback(() => {
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      setStream(null)
    }
    setStatus('idle')
    setError(null)
  }, [stream])

  useEffect(() => {
    return () => {
      if (stream) stream.getTracks().forEach((t) => t.stop())
    }
  }, [stream])

  return { stream, error, status, start, stop }
}
