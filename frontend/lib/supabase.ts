/**
 * Supabase Client Configuration
 * 
 * 提供两种客户端：
 * 1. Browser Client - 用于客户端组件
 * 2. Server Client - 用于服务器端组件和 API routes
 */

import { createBrowserClient } from '@supabase/ssr'

/**
 * 创建浏览器端 Supabase 客户端
 * 用于客户端组件（'use client'）
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  )
}
