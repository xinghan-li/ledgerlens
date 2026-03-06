/**
 * Shared UI utilities for dashboard (time formatting, store name display).
 */

/** 统一为 24 小时制 HH:mm；支持 "15:34"、"15:34:00" 或 "3:34 PM" 等输入 */
export function formatTimeToHHmm(t: string): string {
  if (!t || typeof t !== 'string') return ''
  const s = t.trim()
  const match24 = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?(\s|$|:)/)
  if (match24) {
    const h = parseInt(match24[1], 10)
    const m = match24[2]
    if (h >= 0 && h <= 23 && m.length === 2) return `${String(h).padStart(2, '0')}:${m}`
  }
  const match12 = s.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)/i)
  if (match12) {
    let h = parseInt(match12[1], 10)
    const m = match12[2]
    const pm = match12[3].toUpperCase() === 'PM'
    if (pm && h !== 12) h += 12
    if (!pm && h === 12) h = 0
    return `${String(h).padStart(2, '0')}:${m}`
  }
  return s.slice(0, 5)
}

/**
 * 店名显示：首字母大写，但保留 T&T 中第二个 T、US/UK 等缩写为大写。
 * 例如 "T&T Supermarket US" 不变成 "T&t Supermarket Us"。
 */
export function toTitleCaseStore(name: string): string {
  if (!name || typeof name !== 'string') return name
  return name.trim().split(/\s+/).map((w) => {
    if (!w) return w
    // 两字母词（如 US, UK）保持全大写
    if (w.length === 2 && /^[A-Za-z]{2}$/.test(w)) return w.toUpperCase()
    // 三字母常见缩写（USA, UAE 等）保持全大写
    if (w.length === 3 && /^[A-Za-z]{3}$/.test(w)) return w.toUpperCase()
    // 含 & 的写法（如 T&T）：首字母与 & 后首字母大写
    if (w.includes('&')) {
      return w.split('&').map((part, i) => {
        if (!part) return i > 0 ? '&' : ''
        const first = part.charAt(0).toUpperCase()
        const rest = part.slice(1).toLowerCase()
        return (i > 0 ? '&' : '') + first + rest
      }).join('')
    }
    return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
  }).join(' ')
}
