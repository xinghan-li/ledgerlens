import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

/**
 * Middleware: Firebase Auth 使用 localStorage，服务端无法读取 session。
 * /dashboard 的访问放行，由 dashboard layout 内 onAuthStateChanged 做登录检查并重定向到 /login。
 */
export async function middleware(_request: NextRequest) {
  return NextResponse.next()
}

export const config = {
  matcher: ['/dashboard/:path*']
}
