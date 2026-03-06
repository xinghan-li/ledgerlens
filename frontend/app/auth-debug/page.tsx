'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@/lib/supabase'
import Link from 'next/link'
import { useApiUrl } from '@/lib/api-url-context'

export default function AuthDebugPage() {
  const apiBaseUrl = useApiUrl()
  const [config, setConfig] = useState<any>(null)
  const [session, setSession] = useState<any>(null)
  const [cookies, setCookies] = useState<string>('')

  useEffect(() => {
    // 检查配置
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
    const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

    setConfig({
      supabaseUrl: supabaseUrl || 'NOT SET',
      supabaseKey: supabaseKey ? `${supabaseKey.substring(0, 20)}...` : 'NOT SET',
      apiUrl: apiBaseUrl,
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
  }, [apiBaseUrl])

  const testSupabaseConnection = async () => {
    try {
      const supabase = createClient()
      const { data, error } = await supabase.auth.getSession()
      
      if (error) {
        alert(`❌ Supabase connection failed:\n${error.message}`)
      } else {
        alert(`✅ Supabase connected!\nSession: ${data.session ? 'Active' : 'None'}`)
      }
    } catch (e: any) {
      alert(`❌ Error:\n${e.message}`)
    }
  }

  const clearAll = () => {
    localStorage.clear()
    document.cookie.split(";").forEach((c) => {
      document.cookie = c.replace(/^ +/, "").replace(/=.*/, `=;expires=${new Date().toUTCString()};path=/`)
    })
    alert('✅ Cleared all localStorage and cookies')
    window.location.reload()
  }

  return (
    <div className="min-h-screen bg-theme-cream p-8">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="bg-white rounded-lg shadow p-6">
          <h1 className="text-3xl font-bold mb-2">🔍 Auth debug</h1>
          <p className="text-theme-dark/90">Check Supabase auth config and session</p>
          <Link href="/login" className="text-theme-orange hover:underline text-sm mt-2 inline-block">
            ← Back to sign-in
          </Link>
        </div>

        {/* Configuration */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">📋 Configuration</h2>
          {config && (
            <div className="space-y-2 font-mono text-sm">
              <div className="flex">
                <span className="w-48 font-semibold">Supabase URL:</span>
                <span className={config.supabaseUrl === 'NOT SET' ? 'text-theme-red' : 'text-green-600'}>
                  {config.supabaseUrl}
                </span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Supabase Key:</span>
                <span className={config.supabaseKey === 'NOT SET' ? 'text-theme-red' : 'text-green-600'}>
                  {config.supabaseKey}
                </span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Backend API URL:</span>
                <span className={config.apiUrl === 'NOT SET' ? 'text-theme-red' : 'text-green-600'}>
                  {config.apiUrl}
                </span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Redirect URL:</span>
                <span className="text-theme-orange">{config.redirectUrl}</span>
              </div>
              <div className="flex">
                <span className="w-48 font-semibold">Current URL:</span>
                <span className="text-theme-dark/90 break-all">{config.currentUrl}</span>
              </div>
            </div>
          )}
        </div>

        {/* Session Status */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">👤 Session</h2>
          {session ? (
            <div className="space-y-2">
              <div className="text-green-600 font-semibold">✅ Signed in</div>
              <div className="bg-theme-cream p-4 rounded font-mono text-sm">
                <div><strong>User ID:</strong> {session.user.id}</div>
                <div><strong>Email:</strong> {session.user.email}</div>
                <div><strong>Expires:</strong> {new Date(session.expires_at! * 1000).toLocaleString()}</div>
              </div>
            </div>
          ) : (
            <div className="text-theme-dark/90">❌ Not signed in</div>
          )}
        </div>

        {/* Cookies */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">🍪 Cookies</h2>
          <div className="bg-theme-cream p-4 rounded font-mono text-xs break-all">
            {cookies}
          </div>
        </div>

        {/* Actions */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-xl font-bold mb-4">🔧 Actions</h2>
          <div className="space-x-4">
            <button
              onClick={testSupabaseConnection}
              className="px-4 py-2 btn-primary"
            >
              Test Supabase connection
            </button>
            <button
              onClick={clearAll}
              className="px-4 py-2 bg-theme-red text-white rounded hover:bg-theme-red/90"
            >
              Clear all data
            </button>
          </div>
        </div>

        {/* Checklist */}
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
          <h2 className="text-xl font-bold mb-4">✅ Supabase config checklist</h2>
          <ol className="space-y-2 list-decimal list-inside">
            <li>
              Supabase Dashboard → Authentication → URL Configuration
            </li>
            <li>
              Ensure <strong>Redirect URLs</strong> includes:
              <div className="mt-1 ml-6 bg-white p-2 rounded font-mono text-sm">
                {config?.redirectUrl}
              </div>
            </li>
            <li>
              Ensure <strong>Site URL</strong> is set to:
              <div className="mt-1 ml-6 bg-white p-2 rounded font-mono text-sm">
                {config && `${window.location.origin}`}
              </div>
            </li>
            <li>
              Ensure email template uses <code>{'{{ .ConfirmationURL }}'}</code> correctly
            </li>
            <li>
              Wait 1–2 minutes after saving config for changes to apply
            </li>
          </ol>
        </div>

        {/* Documentation Link */}
        <div className="bg-theme-light-gray/50 border border-theme-orange/30 rounded-lg p-6">
          <h2 className="text-lg font-bold mb-2">📚 Debug guide</h2>
          <p className="text-theme-dark/90 mb-2">
            See the troubleshooting doc:
          </p>
          <code className="bg-white px-2 py-1 rounded">
            frontend/MAGIC_LINK_DEBUG.md
          </code>
        </div>
      </div>
    </div>
  )
}
