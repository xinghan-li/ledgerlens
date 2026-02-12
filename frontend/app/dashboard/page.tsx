'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase'
import { useRouter } from 'next/navigation'
import type { User } from '@supabase/supabase-js'

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState<any>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const router = useRouter()
  const supabase = createClient()

  useEffect(() => {
    // 获取当前用户和 session
    const getSession = async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession()
        
        if (session) {
          setUser(session.user)
          setToken(session.access_token)
        } else {
          // 未登录，重定向到登录页
          router.push('/login')
        }
      } catch (error) {
        console.error('获取 session 失败:', error)
        router.push('/login')
      } finally {
        setLoading(false)
      }
    }

    getSession()

    // 监听认证状态变化
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        console.log('Auth state changed:', event)
        
        if (session) {
          setUser(session.user)
          setToken(session.access_token)
        } else {
          setUser(null)
          setToken(null)
          router.push('/login')
        }
      }
    )

    return () => {
      subscription.unsubscribe()
    }
  }, [router, supabase])

  const handleLogout = async () => {
    await supabase.auth.signOut()
    router.push('/')
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file || !token) return

    // 重置状态
    setUploading(true)
    setUploadResult(null)
    setUploadError(null)

    const formData = new FormData()
    formData.append('file', file)

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      console.log('上传到:', `${apiUrl}/api/receipt/workflow`)
      console.log('Token:', token?.substring(0, 50) + '...')
      console.log('文件:', file.name, file.type, file.size)
      
      // 创建带超时的 fetch（60秒超时）
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 60000) // 60秒超时
      
      try {
        const response = await fetch(`${apiUrl}/api/receipt/workflow`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`,
          },
          body: formData,
          signal: controller.signal,
        })

        clearTimeout(timeoutId)
        console.log('响应状态:', response.status, response.statusText)

      if (response.ok) {
        const data = await response.json()
        console.log('✅ 上传成功:', data)
        setUploadResult(data)
      } else {
        // 尝试解析错误响应
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`
        try {
          const errorData = await response.json()
          console.error('❌ 错误响应:', errorData)
          
          // 提取错误信息
          if (typeof errorData.detail === 'string') {
            errorMessage = errorData.detail
          } else if (typeof errorData.detail === 'object') {
            errorMessage = JSON.stringify(errorData.detail)
          } else if (errorData.message) {
            errorMessage = errorData.message
          }
        } catch (parseError) {
          const text = await response.text()
          console.error('原始错误响应:', text)
          errorMessage = text || errorMessage
        }
        
        setUploadError(errorMessage)
        }
      } catch (fetchError) {
        clearTimeout(timeoutId)
        throw fetchError
      }
    } catch (error) {
      console.error('❌ 上传错误:', error)
      
      // 更详细的错误提示
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          setUploadError('请求超时（60秒）。请检查：\n1. 后端服务是否正常运行\n2. 网络连接是否稳定\n3. 图片大小是否过大')
        } else if (error.message.includes('Failed to fetch')) {
          setUploadError('无法连接到后端服务。请检查：\n1. 后端是否在 ' + (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000') + ' 运行\n2. 防火墙设置\n3. CORS 配置')
        } else {
          setUploadError(error.message)
        }
      } else {
        setUploadError('网络错误，请重试')
      }
    } finally {
      setUploading(false)
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="animate-spin text-6xl">⏳</div>
          <p className="mt-4 text-gray-600">加载中...</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return null // 会被重定向到登录页
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8 flex justify-between items-center">
          <h1 className="text-2xl font-bold text-gray-900">
            LedgerLens Dashboard
          </h1>
          <button
            onClick={handleLogout}
            className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition"
          >
            登出
          </button>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* User Info Card */}
        <div className="bg-white rounded-xl shadow p-6 mb-8">
          <h2 className="text-xl font-semibold mb-4">欢迎回来！</h2>
          <div className="space-y-2 text-sm">
            <p>
              <span className="text-gray-600">邮箱：</span>
              <span className="font-medium">{user.email}</span>
            </p>
            <p>
              <span className="text-gray-600">用户 ID：</span>
              <span className="font-mono text-xs">{user.id}</span>
            </p>
            <details className="pt-2">
              <summary className="cursor-pointer text-blue-600 hover:text-blue-700">
                查看 JWT Token（用于测试）
              </summary>
              <div className="mt-2 p-3 bg-gray-50 rounded text-xs font-mono break-all">
                {token}
              </div>
            </details>
          </div>
        </div>

        {/* Upload Section */}
        <div className="bg-white rounded-xl shadow p-6">
          <h2 className="text-xl font-semibold mb-4">上传小票</h2>
          
          {/* Upload Area or Results */}
          {uploading ? (
            // Loading State
            <div className="border-2 border-blue-300 bg-blue-50 rounded-lg p-12 text-center">
              <div className="animate-spin text-6xl mb-4">⏳</div>
              <p className="text-lg font-medium text-blue-900 mb-2">
                正在处理中...
              </p>
              <p className="text-sm text-blue-600">
                OCR 识别 → LLM 解析 → 数据验证
              </p>
            </div>
          ) : uploadResult ? (
            // Success Result
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 bg-green-50 border border-green-200 rounded-lg">
                <div className="flex items-center gap-3">
                  <span className="text-3xl">✅</span>
                  <div>
                    <p className="font-semibold text-green-900">处理成功！</p>
                    <p className="text-sm text-green-600">
                      状态: {uploadResult.status || 'completed'}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    setUploadResult(null)
                    setUploadError(null)
                  }}
                  className="px-4 py-2 text-sm bg-white border border-green-300 text-green-700 rounded-lg hover:bg-green-50"
                >
                  重新上传
                </button>
              </div>

              {/* JSON Result Display */}
              <div className="border-2 border-gray-200 rounded-lg overflow-hidden">
                <div className="bg-gray-800 px-4 py-2 flex items-center justify-between">
                  <span className="text-sm font-mono text-gray-300">处理结果 JSON</span>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(JSON.stringify(uploadResult, null, 2))
                      alert('已复制到剪贴板')
                    }}
                    className="px-3 py-1 text-xs bg-gray-700 text-white rounded hover:bg-gray-600"
                  >
                    复制
                  </button>
                </div>
                <div className="bg-gray-900 p-4 max-h-96 overflow-auto">
                  <pre className="text-sm text-green-400 font-mono whitespace-pre-wrap">
                    {JSON.stringify(uploadResult, null, 2)}
                  </pre>
                </div>
              </div>
            </div>
          ) : uploadError ? (
            // Error State
            <div className="space-y-4">
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <div className="flex items-start gap-3 mb-3">
                  <span className="text-3xl">❌</span>
                  <div className="flex-1">
                    <p className="font-semibold text-red-900 mb-1">处理失败</p>
                    <p className="text-sm text-red-600 whitespace-pre-wrap">
                      {uploadError}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    setUploadResult(null)
                    setUploadError(null)
                  }}
                  className="w-full px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
                >
                  重新上传
                </button>
              </div>
            </div>
          ) : (
            // Initial Upload Area
            <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center hover:border-blue-500 transition">
              <input
                type="file"
                accept="image/*,.pdf"
                onChange={handleUpload}
                className="hidden"
                id="receipt-upload"
                disabled={uploading}
              />
              <label
                htmlFor="receipt-upload"
                className="cursor-pointer block"
              >
                <div className="text-6xl mb-4">📸</div>
                <p className="text-lg font-medium text-gray-900 mb-2">
                  点击上传小票
                </p>
                <p className="text-sm text-gray-500">
                  支持 JPG, PNG, PDF 格式
                </p>
              </label>
            </div>
          )}

          {/* Info Box - Only show when no result */}
          {!uploadResult && !uploadError && !uploading && (
            <div className="mt-4 p-4 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
              <p className="font-semibold">🚧 功能开发中</p>
              <p className="mt-1">
                上传功能已连接到后端 API，结果会显示在此处。
                完整的 UI 界面即将推出！
              </p>
            </div>
          )}
        </div>

        {/* API Test Section */}
        <div className="mt-8 bg-blue-50 rounded-xl p-6">
          <h3 className="text-lg font-semibold text-blue-900 mb-3">
            🧪 API 测试信息
          </h3>
          <div className="space-y-2 text-sm text-blue-800">
            <p>
              <span className="font-semibold">后端 API：</span>
              {process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}
            </p>
            <p>
              <span className="font-semibold">认证状态：</span>
              <span className="text-green-600 font-semibold">✓ 已认证</span>
            </p>
            <p className="pt-2 text-xs text-blue-600">
              打开浏览器控制台 (F12) 查看详细的 API 响应
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
