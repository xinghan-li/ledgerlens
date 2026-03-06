'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getFirebaseAuth } from '@/lib/firebase'
import { isSignInWithEmailLink, signInWithEmailLink } from 'firebase/auth'

const EMAIL_FOR_SIGNIN_KEY = 'emailForSignIn'

export default function AuthCallbackPage() {
  const router = useRouter()
  const [status, setStatus] = useState<'checking' | 'success' | 'error'>('checking')
  const [message, setMessage] = useState('')

  useEffect(() => {
    const auth = getFirebaseAuth()
    const href = typeof window !== 'undefined' ? window.location.href : ''

    if (!isSignInWithEmailLink(auth, href)) {
      setStatus('error')
      setMessage('This link is not a valid sign-in link or has already been used. Request a new link from the sign-in page.')
      return
    }

    let email = typeof window !== 'undefined' ? window.localStorage.getItem(EMAIL_FOR_SIGNIN_KEY) : null
    if (!email) {
      setStatus('error')
      setMessage('Open this link on the same device where you requested it, or enter your email on the sign-in page to get a new link.')
      return
    }

    signInWithEmailLink(auth, email, href)
      .then(() => {
        window.localStorage.removeItem(EMAIL_FOR_SIGNIN_KEY)
        setStatus('success')
        router.replace('/dashboard')
      })
      .catch((err: { code?: string; message?: string }) => {
        setStatus('error')
        const msg = err.code === 'auth/invalid-action-code'
          ? 'Link expired or already used. Request a new sign-in link.'
          : (err.message || 'Sign-in failed')
        setMessage(msg)
      })
  }, [router])

  if (status === 'checking') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-cream">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-theme-dark/90">Completing sign-in…</p>
        </div>
      </div>
    )
  }

  if (status === 'success') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-theme-cream">
        <div className="text-center">
          <p className="text-theme-dark/90">Sign-in successful. Redirecting…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-theme-cream p-4">
      <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center">
        <p className="text-theme-red mb-4">{message}</p>
        <a href="/login" className="text-theme-orange hover:underline">Back to sign-in</a>
      </div>
    </div>
  )
}
