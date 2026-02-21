'use client'

import { useState, useEffect, Suspense } from 'react'
import { createClient } from '@/lib/supabase'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

function LoginForm() {
  const searchParams = useSearchParams()
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const urlError = searchParams.get('error')
    if (urlError === 'auth_failed') {
      setError('登录失败：Magic Link 可能已过期或已使用。请重新请求登录链接。')
    }
  }, [searchParams])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    try {
      const supabase = createClient()
      // 使用 NEXT_PUBLIC_APP_URL 或当前页面 origin，保证手机点邮件链接时跳回正确 host（如 10.0.0.51:3000）
      const baseUrl =
        (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_APP_URL) ||
        (typeof window !== 'undefined' ? window.location.origin : '')
      const redirectTo = `${baseUrl.replace(/\/$/, '')}/auth/callback`

      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: redirectTo,
        },
      })

      if (error) {
        setError(error.message)
        console.error('登录错误:', error)
      } else {
        setSent(true)
      }
    } catch (err) {
      setError('发生未知错误，请重试')
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
              邮件已发送！
            </h2>
            <p className="text-gray-600">
              我们已经向 <span className="font-semibold text-blue-600">{email}</span> 发送了登录链接
            </p>
            <div className="bg-blue-50 p-4 rounded-lg text-sm text-gray-700 space-y-2">
              <p className="font-semibold">接下来的步骤：</p>
              <ol className="text-left list-decimal list-inside space-y-1">
                <li>检查你的邮箱</li>
                <li>查找来自 LedgerLens 的邮件</li>
                <li>点击"登录"按钮</li>
                <li>自动返回应用 ✨</li>
              </ol>
            </div>
            <p className="text-sm text-gray-500 pt-4">
              没收到邮件？检查垃圾邮件文件夹
            </p>
            <button
              onClick={() => setSent(false)}
              className="text-blue-600 hover:text-blue-700 text-sm font-medium"
            >
              ← 返回重新发送
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
            🔐 登录
          </h2>
          <p className="text-gray-600">
            输入邮箱，我们会发送登录链接
          </p>
        </div>

        <form onSubmit={handleLogin} className="mt-8 space-y-6">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-gray-700 mb-2">
              邮箱地址
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
                发送中...
              </span>
            ) : (
              '发送登录链接'
            )}
          </button>
        </form>

        <div className="text-center space-y-2">
          <p className="text-sm text-gray-500">
            无需密码，安全快捷 ✨
          </p>
          <Link
            href="/"
            className="text-sm text-blue-600 hover:text-blue-700 font-medium"
          >
            ← 返回首页
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
          <h2 className="text-4xl font-bold text-gray-900">🔐 登录</h2>
          <p className="text-gray-600">输入邮箱，我们会发送登录链接</p>
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
