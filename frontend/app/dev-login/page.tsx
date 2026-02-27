'use client'

import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase'

/**
 * Dev-only: 通过 URL 中的 access_token 和 refresh_token 完成登录
 * 由 login.mjs 脚本生成的 URL 跳转到这里
 */
export default function DevLoginPage() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const accessToken = searchParams.get('access_token')
    const refreshToken = searchParams.get('refresh_token')

    if (!accessToken) {
      setStatus('error')
      setError('Missing access_token. Use node login.mjs <user_id> to generate the correct URL')
      return
    }

    const run = async () => {
      try {
        const supabase = createClient()
        // 后端 JWT 无 refresh_token，用 access_token 占位（7 天内不会 refresh）
        const { error: err } = await supabase.auth.setSession({
          access_token: accessToken,
          refresh_token: refreshToken ?? accessToken,
        })

        if (err) {
          setStatus('error')
          setError(err.message)
          return
        }

        setStatus('ok')
        router.replace('/dashboard')
      } catch (e) {
        setStatus('error')
        setError(e instanceof Error ? e.message : 'Unknown error')
      }
    }

    run()
  }, [searchParams, router])

  if (status === 'loading') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-4xl mb-4">⏳</div>
          <p className="text-gray-600">Signing in…</p>
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
        <div className="max-w-md w-full p-6 bg-white rounded-xl shadow">
          <h2 className="text-xl font-semibold text-red-600 mb-2">Sign-in failed</h2>
          <p className="text-gray-700 mb-4">{error}</p>
          <a
            href="/login"
            className="text-blue-600 hover:underline"
          >
            ← Back to sign-in
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <p className="text-gray-600">Redirecting to dashboard…</p>
    </div>
  )
}
