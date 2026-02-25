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
      setMessage('此链接不是有效的登录链接，或已使用过。请从登录页重新请求链接。')
      return
    }

    let email = typeof window !== 'undefined' ? window.localStorage.getItem(EMAIL_FOR_SIGNIN_KEY) : null
    if (!email) {
      setStatus('error')
      setMessage('请在同一台设备上打开此链接，或重新在登录页输入邮箱获取新链接。')
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
          ? '链接已过期或已使用，请重新请求登录链接。'
          : (err.message || '登录失败')
        setMessage(msg)
      })
  }, [router])

  if (status === 'checking') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-gray-600">正在完成登录…</p>
        </div>
      </div>
    )
  }

  if (status === 'success') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-gray-600">登录成功，正在跳转…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-4">
      <div className="max-w-md w-full bg-white rounded-xl shadow-lg p-8 text-center">
        <p className="text-red-600 mb-4">{message}</p>
        <a href="/login" className="text-blue-600 hover:underline">返回登录页</a>
      </div>
    </div>
  )
}
