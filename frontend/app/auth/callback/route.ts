import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

/**
 * Auth Callback Route
 * 
 * 处理 Magic Link 登录后的回调
 * 将 code 交换为 session，然后重定向到 dashboard
 */
export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url)
  const code = requestUrl.searchParams.get('code')
  const origin = requestUrl.origin

  console.log('[Auth Callback] Request URL:', requestUrl.toString())
  console.log('[Auth Callback] Code:', code ? `${code.substring(0, 10)}...` : 'null')

  if (code) {
    const cookieStore = await cookies()
    
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          get(name: string) {
            return cookieStore.get(name)?.value
          },
          set(name: string, value: string, options: any) {
            try {
              cookieStore.set({ name, value, ...options })
            } catch (e) {
              console.error('[Auth Callback] Cookie set error:', e)
            }
          },
          remove(name: string, options: any) {
            try {
              cookieStore.delete({ name, ...options })
            } catch (e) {
              console.error('[Auth Callback] Cookie delete error:', e)
            }
          },
        },
      }
    )

    console.log('[Auth Callback] Exchanging code for session...')
    const { data, error } = await supabase.auth.exchangeCodeForSession(code)

    if (error) {
      console.error('[Auth Callback] Exchange failed:', error.message)
      console.error('[Auth Callback] Error details:', JSON.stringify(error, null, 2))
    } else {
      console.log('[Auth Callback] Exchange successful!')
      console.log('[Auth Callback] User:', data.user?.email)
      // 登录成功，重定向到 dashboard
      return NextResponse.redirect(`${origin}/dashboard`)
    }
  } else {
    console.error('[Auth Callback] No code provided')
  }

  // 如果失败或没有 code，重定向回登录页
  console.log('[Auth Callback] Redirecting to login with error')
  return NextResponse.redirect(`${origin}/login?error=auth_failed`)
}
