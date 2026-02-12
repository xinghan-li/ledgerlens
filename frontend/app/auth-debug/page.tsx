'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase'
import Link from 'next/link'

export default function AuthDebugPage() {
  const [config, setConfig] = useState<any>(null)
  const [session, setSession] = useState<any>(null)
  const [cookies, setCookies] = useState<string>('')

  useEffect(() => {
    // 检查配置
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
    const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
    const apiUrl = process.env.NEXT_PUBLIC_API_URL

    setConfig({
      supabaseUrl: supabaseUrl || 'NOT SET',
      supabaseKey: supabaseKey ? `${supabaseKey.substring(0, 20)}...` : 'NOT SET',
      apiUrl: apiUrl || 'NOT SET',
      redirectUrl: `${window.location.origin}/auth/callback`,
      currentUrl: window.location.href,
    })

    // 检查 session
    const supabase = createClient()
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
    })

    // 获取 cookies
    setCookies(document.cookie || '(empty)')
  }, [])

  const testSupabaseConnection = async () => {
    try {
      const supabase = createClient()
      const { data, error } = await supabase.auth.getSession()
      
      if (error) {
        alert(`❌ Supabase 连接失败:\n${error.message}`)
      } else {
        alert(`✅ Supabase 连接成功!\nSession: ${data.session ? 'Active' : 'None'}`)
      }
    } catch (e: any) {
      alert(`❌ 错误:\n${e.message}`)
    }
  }

  const clearAll = () => {
    localStorage.clear()
    document.cookie.split(";").forEach((c) => {
      document.cookie = c.replace(/^ +/, "").replace(/=.*/, `=;expires=${new Date().toUTCString()};path=/`)
    })
    alert('✅ 已清除所有 localStorage 和 Cookies')
    window.location.reload()
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="bg-white rounded-lg shadow p-6">
          <h1 className="text-3xl font-bold mb-2">🔍 Auth 调试工具</h1>
          <p className="text-gray-600">检查 Supabase 认证配置和状态</p>
          <Link href="/login" className="text-blue-600 hover:underline text-sm mt-2 inline-block">
            ← 返回登录
          </Link>
        </div>

        {/* Configuration */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">📋 配置信息</h2>
          {config && (
            <div className="space-y-2 font-mono text-sm">
              <div className="flex">
                <span className="w-48 font-semibold">Supabase URL:</span>
                <span className={config.supabaseUrl === 'NOT SET' ? 'text-red-600' : 'text-green-600'}>
                  {config.supabaseUrl}
                </span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Supabase Key:</span>
                <span className={config.supabaseKey === 'NOT SET' ? 'text-red-600' : 'text-green-600'}>
                  {config.supabaseKey}
                </span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Backend API URL:</span>
                <span className={config.apiUrl === 'NOT SET' ? 'text-red-600' : 'text-green-600'}>
                  {config.apiUrl}
                </span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Redirect URL:</span>
                <span className="text-blue-600">{config.redirectUrl}</span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Current URL:</span>
                <span className="text-gray-600 break-all">{config.currentUrl}</span>
              </div>
            </div>
          )}
        </div>

        {/* Session Status */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">👤 Session 状态</h2>
          {session ? (
            <div className="space-y-2">
              <div className="text-green-600 font-semibold">✅ 已登录</div>
              <div className="bg-gray-50 p-4 rounded font-mono text-sm">
                <div><strong>User ID:</strong> {session.user.id}</div>
                <div><strong>Email:</strong> {session.user.email}</div>
                <div><strong>Expires:</strong> {new Date(session.expires_at! * 1000).toLocaleString()}</div>
              </div>
            </div>
          ) : (
            <div className="text-gray-600">❌ 未登录</div>
          )}
        </div>

        {/* Cookies */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">🍪 Cookies</h2>
          <div className="bg-gray-50 p-4 rounded font-mono text-xs break-all">
            {cookies}
          </div>
        </div>

        {/* Actions */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">🔧 操作</h2>
          <div className="space-x-4">
            <button
              onClick={testSupabaseConnection}
              className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              测试 Supabase 连接
            </button>
            <button
              onClick={clearAll}
              className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
            >
              清除所有数据
            </button>
          </div>
        </div>

        {/* Checklist */}
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
          <h2 className="text-xl font-bold mb-4">✅ Supabase 配置检查清单</h2>
          <ol className="space-y-2 list-decimal list-inside">
            <li>
              Supabase Dashboard → Authentication → URL Configuration
            </li>
            <li>
              确认 <strong>Redirect URLs</strong> 包含:
              <div className="mt-1 ml-6 bg-white p-2 rounded font-mono text-sm">
                {config?.redirectUrl}
              </div>
            </li>
            <li>
              确认 <strong>Site URL</strong> 设置为:
              <div className="mt-1 ml-6 bg-white p-2 rounded font-mono text-sm">
                {config && `${window.location.origin}`}
              </div>
            </li>
            <li>
              确认邮件模板中的 <code>{'{{ .ConfirmationURL }}'}</code> 正确
            </li>
            <li>
              保存配置后等待 1-2 分钟生效
            </li>
          </ol>
        </div>

        {/* Documentation Link */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h2 className="text-lg font-bold mb-2">📚 完整调试指南</h2>
          <p className="text-gray-700 mb-2">
            请查看详细的故障排查文档:
          </p>
          <code className="bg-white px-2 py-1 rounded">
            frontend/MAGIC_LINK_DEBUG.md
          </code>
        </div>
      </div>
    </div>
  )
}
