/**
 * API 基地址解析：优先尝试 localhost:8000，不可达则使用 .env 中的 NEXT_PUBLIC_API_URL（如 ngrok）。
 * 这样本地开发不用改 .env，手机测 ngrok 时也无需改回。
 */

const LOCAL = 'http://localhost:8000'
const PROBE_TIMEOUT_MS = 2000

let cached: string | null = null
let resolvePromise: Promise<string> | null = null

function fallbackUrl(): string {
  return (
    (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL) ||
    'https://ledgerlens-be.ngrok-free.app'
  )
}

/**
 * 探测 localhost:8000 是否可达；仅执行一次，结果缓存。
 * 用于浏览器端：先试 8000，失败则用 .env 里的 NEXT_PUBLIC_API_URL。
 */
export function getApiBaseUrl(): Promise<string> {
  if (cached !== null) return Promise.resolve(cached)
  if (resolvePromise !== null) return resolvePromise

  resolvePromise = (async () => {
    if (typeof window === 'undefined') {
      return fallbackUrl()
    }
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)
      const res = await fetch(`${LOCAL}/health`, {
        signal: ctrl.signal,
        cache: 'no-store',
      })
      clearTimeout(t)
      if (res.ok) {
        cached = LOCAL
        return LOCAL
      }
    } catch {
      /* ignore */
    }
    cached = fallbackUrl()
    return cached
  })()

  return resolvePromise
}

/** 同步获取已解析的 base URL（仅当已 resolve 过时有值，否则返回 fallback 用于显示） */
export function getApiBaseUrlSync(): string {
  return cached ?? fallbackUrl()
}
