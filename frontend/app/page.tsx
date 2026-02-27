import Link from 'next/link'
import { redirect } from 'next/navigation'

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  // Supabase 在 token 过期/无效时会重定向到 Site URL 并带 error 参数，统一转到登录页并带上错误类型
  const params = await searchParams
  const error = typeof params?.error === 'string' ? params.error : undefined
  const errorCode = typeof params?.error_code === 'string' ? params.error_code : undefined
  if (error === 'access_denied' || errorCode === 'otp_expired') {
    redirect(`/login?error=otp_expired`)
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24 bg-gradient-to-b from-blue-50 to-white">
      <div className="max-w-2xl text-center space-y-8">
        <h1 className="text-6xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-cyan-600">
          LedgerLens
        </h1>
        
        <p className="text-2xl text-gray-600">
          Smart receipt recognition
        </p>
        
        <p className="text-lg text-gray-500">
          Use AI to scan and manage your receipts
        </p>
        
        <div className="flex gap-4 justify-center pt-8">
          <Link
            href="/login"
            className="px-8 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-semibold"
          >
            Sign in
          </Link>
          
          <Link
            href="/about"
            className="px-8 py-3 border-2 border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 transition font-semibold"
          >
            Learn more
          </Link>
        </div>
      </div>
    </main>
  )
}
