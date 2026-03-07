/**
 * API 基地址解析：优先用后端实际端口（/api/backend-port），再试 localhost:8000，不可达则用 .env 的 NEXT_PUBLIC_API_URL（如 ngrok）。
 */

const LOCAL = 'http://localhost:8000'
const PROBE_TIMEOUT_MS = 2000

let cached: string | null = null
let resolvePromise: Promise<string> | null = null

function fallbackUrl(): string {
  return (
    (typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL) ||
    ''
  )
}

/** 在 localhost 下先向 Next 请求后端端口（run_backend.py 写入的 backend-port.json），避免后端改到 8081 时仍请求 8000 */
async function getLocalBackendUrl(): Promise<string> {
  try {
    const r = await fetch('/api/backend-port', { cache: 'no-store' })
    if (r.ok) {
      const data = (await r.json()) as { url?: string }
      if (data?.url) return data.url
    }
  } catch {
    /* ignore */
  }
  return LOCAL
}

/**
 * 探测后端是否可达；仅执行一次，结果缓存。
 * 浏览器端在 localhost 下：先取实际端口 → 再请求该 URL/health → 失败则用 .env 的 NEXT_PUBLIC_API_URL。
 */
export function getApiBaseUrl(): Promise<string> {
  if (cached !== null) return Promise.resolve(cached)
  if (resolvePromise !== null) return resolvePromise

  resolvePromise = (async () => {
    if (typeof window === 'undefined') {
      return fallbackUrl()
    }
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      const base = await getLocalBackendUrl()
      try {
        const ctrl = new AbortController()
        const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS)
        const res = await fetch(`${base.replace(/\/$/, '')}/health`, {
          signal: ctrl.signal,
          cache: 'no-store',
        })
        clearTimeout(t)
        if (res.ok) {
          cached = base.replace(/\/$/, '')
          return cached
        }
      } catch {
        /* ignore */
      }
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
