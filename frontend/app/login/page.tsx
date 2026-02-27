'use client'

import { useState, useEffect, Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { getFirebaseAuth } from '@/lib/firebase'
import { sendSignInLinkToEmail } from 'firebase/auth'

function LoginForm() {
  const searchParams = useSearchParams()
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!mounted) return
    const urlError = searchParams.get('error')
    const errorCode = searchParams.get('error_code')
    if (urlError === 'auth_failed' || errorCode === 'otp_expired' || urlError === 'access_denied') {
      setError('The sign-in link has expired or was already used (each link works once). Enter your email below to get a new link.')
    }
  }, [mounted, searchParams])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const origin = window.location.origin
      const actionCodeSettings = {
        url: `${origin.replace(/\/$/, '')}/auth/callback`,
        handleCodeInApp: true,
      }

      const auth = getFirebaseAuth()
      await sendSignInLinkToEmail(auth, email, actionCodeSettings)
      window.localStorage.setItem('emailForSignIn', email)
      setSent(true)
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'message' in err ? String((err as { message: string }).message) : 'An unexpected error occurred. Please try again.'
      setError(msg)
      console.error('登录异常:', err)
    } finally {
      setLoading(false)
    }
  }

  // 邮件已发送状态
  if (sent) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-blue-50 to-white p-4">
        <div className="max-w-md w-full space-y-8 p-8 bg-white rounded-xl shadow-lg">
          <div className="text-center space-y-4">
            <div className="text-6xl">📧</div>
            <h2 className="text-3xl font-bold text-gray-900">
              Email sent!
            </h2>
            <p className="text-gray-600">
              We sent a sign-in link to <span className="font-semibold text-blue-600">{email}</span>.
            </p>
            <div className="bg-blue-50 p-4 rounded-lg text-sm text-gray-700 space-y-2">
              <p className="font-semibold">Next steps:</p>
              <ol className="text-left list-decimal list-inside space-y-1">
                <li>Check your inbox</li>
                <li>Look for an email from LedgerLens</li>
                <li>Click the sign-in link</li>
                <li>You’ll be brought back here ✨</li>
              </ol>
            </div>
            <p className="text-sm text-gray-500 pt-4">
              Didn’t get it? Check your spam folder.
            </p>
            <button
              onClick={() => setSent(false)}
              className="text-blue-600 hover:text-blue-700 text-sm font-medium"
            >
              ← Back to send again
            </button>
          </div>
        </div>
      </div>
    )
  }

  // 登录表单
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-blue-50 to-white p-4">
      <div className="max-w-md w-full space-y-8 p-8 bg-white rounded-xl shadow-lg">
        <div className="text-center space-y-2">
          <h2 className="text-4xl font-bold text-gray-900">
            🔐 Sign in
          </h2>
          <p className="text-gray-600">
            Enter your email and we’ll send you a sign-in link.
          </p>
        </div>

        <form onSubmit={handleLogin} className="mt-8 space-y-6">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
              Email address
            </label>
            <input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="appearance-none rounded-lg relative block w-full px-4 py-3 border border-gray-300 placeholder-gray-400 text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              placeholder="your@email.com"
            />
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
              ❌ {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="group relative w-full flex justify-center py-3 px-4 border border-transparent text-base font-medium rounded-lg text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin">⏳</span>
                Sending…
              </span>
            ) : (
              'Send sign-in link'
            )}
          </button>
        </form>

        <div className="text-center space-y-2">
          <p className="text-sm text-gray-500">
            No password needed — quick and secure ✨
          </p>
          <Link
            href="/"
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            ← Back to home
          </Link>
        </div>
      </div>
    </div>
  )
}

function LoginFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-blue-50 to-white p-4">
      <div className="max-w-md w-full space-y-8 p-8 bg-white rounded-xl shadow-lg">
        <div className="text-center space-y-2">
          <h2 className="text-4xl font-bold text-gray-900">🔐 Sign in</h2>
          <p className="text-gray-600">Enter your email and we’ll send you a sign-in link.</p>
        </div>
        <div className="flex justify-center py-8">
          <span className="animate-spin text-2xl text-gray-400">⏳</span>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  )
}
