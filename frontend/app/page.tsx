import Link from 'next/link'

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24 bg-gradient-to-b from-blue-50 to-white">
      <div className="max-w-2xl text-center space-y-8">
        <h1 className="text-6xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-cyan-600">
          LedgerLens
        </h1>
        
        <p className="text-2xl text-gray-600">
          智能小票识别系统
        </p>
        
        <p className="text-lg text-gray-500">
          使用 AI 技术自动识别和管理您的收据
        </p>
        
        <div className="flex gap-4 justify-center pt-8">
          <Link
            href="/login"
            className="px-8 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-semibold"
          >
            登录
          </Link>
          
          <Link
            href="/about"
            className="px-8 py-3 border-2 border-blue-600 text-blue-600 rounded-lg hover:bg-blue-50 transition font-semibold"
          >
            了解更多
          </Link>
        </div>
      </div>
    </main>
  )
}
