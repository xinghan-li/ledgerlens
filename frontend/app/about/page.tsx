import Link from 'next/link'

export default function AboutPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-blue-50 to-white">
      <div className="max-w-4xl mx-auto px-4 py-16">
        {/* Header */}
        <div className="text-center mb-12">
          <h1 className="text-5xl font-bold mb-4 bg-clip-text text-transparent bg-gradient-to-r from-blue-600 to-cyan-600">
            关于 LedgerLens
          </h1>
          <p className="text-xl text-gray-600">
            让收据管理变得简单智能
          </p>
        </div>

        {/* Features */}
        <div className="grid md:grid-cols-3 gap-8 mb-12">
          <div className="bg-white p-6 rounded-xl shadow-lg">
            <div className="text-4xl mb-4">🤖</div>
            <h3 className="text-xl font-semibold mb-2">AI 识别</h3>
            <p className="text-gray-600">
              使用最先进的 OCR 和 LLM 技术，自动识别小票上的所有信息
            </p>
          </div>

          <div className="bg-white p-6 rounded-xl shadow-lg">
            <div className="text-4xl mb-4">⚡</div>
            <h3 className="text-xl font-semibold mb-2">快速准确</h3>
            <p className="text-gray-600">
              10 秒内完成识别，准确率超过 95%，支持多家连锁店
            </p>
          </div>

          <div className="bg-white p-6 rounded-xl shadow-lg">
            <div className="text-4xl mb-4">🔒</div>
            <h3 className="text-xl font-semibold mb-2">安全可靠</h3>
            <p className="text-gray-600">
              采用 Magic Link 登录，数据加密存储，保护您的隐私
            </p>
          </div>
        </div>

        {/* Supported Stores */}
        <div className="bg-white p-8 rounded-xl shadow-lg mb-12">
          <h2 className="text-2xl font-bold mb-6 text-center">支持的商店</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-center">
            <div className="p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl mb-2">🛒</div>
              <p className="font-medium">Costco</p>
              <p className="text-xs text-gray-500">US & CA</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl mb-2">🍊</div>
              <p className="font-medium">Trader Joe's</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl mb-2">🥬</div>
              <p className="font-medium">T&T Supermarket</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl mb-2">🏝️</div>
              <p className="font-medium">99 Ranch</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl mb-2">🌴</div>
              <p className="font-medium">Island Gourmet</p>
            </div>
            <div className="p-4 bg-gray-50 rounded-lg">
              <div className="text-2xl mb-2">✨</div>
              <p className="font-medium">更多商店</p>
              <p className="text-xs text-gray-500">持续添加中</p>
            </div>
          </div>
        </div>

        {/* CTA */}
        <div className="text-center">
          <Link
            href="/login"
            className="inline-block px-8 py-4 bg-blue-600 text-white text-lg font-semibold rounded-lg hover:bg-blue-700 transition shadow-lg hover:shadow-xl"
          >
            立即开始使用
          </Link>
        </div>
      </div>
    </div>
  )
}
