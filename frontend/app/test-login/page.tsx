'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function TestLoginPage() {
  const router = useRouter()

  useEffect(() => {
    // 测试 Token（7天有效期）
    const token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3OTgxYzBhMS02MDE3LTRhOGMtYjU1MS0zZmI0MTE4Y2Q3OTgiLCJlbWFpbCI6InhpbmdoYW4uc2RlQGdtYWlsLmNvbSIsImF1ZCI6ImF1dGhlbnRpY2F0ZWQiLCJyb2xlIjoiYXV0aGVudGljYXRlZCIsImV4cCI6MTc3MTQ1MTc2NCwiaWF0IjoxNzcwODQ2OTY0fQ.xyGiHedWqatwXlq2f_ww5CnV7Wv1CjHcPGIByWWIeEI"

    const session = {
      access_token: token,
      token_type: "bearer",
      expires_in: 604800,
      expires_at: 1771451764,
      refresh_token: token,
      user: {
        id: "7981c0a1-6017-4a8c-b551-3fb4118cd798",
        email: "xinghan.sde@gmail.com",
        aud: "authenticated",
        role: "authenticated"
      }
    }

    // 保存到 localStorage
    const storageKey = `sb-pqbftyvnkihpqyqfjbyz-auth-token`
    localStorage.setItem(storageKey, JSON.stringify(session))

    console.log("✅ Session 已设置！正在跳转到 Dashboard...")

    // 延迟 500ms 后跳转到 Dashboard
    setTimeout(() => {
      router.push('/dashboard')
    }, 500)
  }, [router])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-blue-50 to-white">
      <div className="text-center space-y-4">
        <div className="text-6xl animate-spin">⏳</div>
        <h2 className="text-2xl font-bold text-gray-900">
          正在设置测试登录...
        </h2>
        <p className="text-gray-600">
          即将跳转到 Dashboard
        </p>
      </div>
    </div>
  )
}
