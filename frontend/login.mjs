#!/usr/bin/env node
/**
 * Dev-only: 用 super_admin 的 user_id 生成可直接登录的 URL
 * 用法: node login.mjs <user_id>
 * 示例: node login.mjs 41a37ceb-e65c-4cd3-adc4-78b8fbc6dd51
 *
 * 依赖: 后端需已启动，从 backend 获取 JWT（super_admin 7 天有效）
 */

import { readFileSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

function loadEnv() {
  const paths = [
    resolve(__dirname, '../backend/.env'),
    resolve(__dirname, '.env.local'),
  ]
  for (const p of paths) {
    if (existsSync(p)) {
      const content = readFileSync(p, 'utf8')
      for (const line of content.split('\n')) {
        const m = line.match(/^([^#=]+)=(.*)$/)
        if (m && !process.env[m[1].trim()]) {
          process.env[m[1].trim()] = m[2].trim().replace(/^["']|["']$/g, '')
        }
      }
    }
  }
}

loadEnv()

const userId = process.argv[2]

if (!userId) {
  console.error('用法: node login.mjs <super_admin_user_id>')
  console.error('示例: node login.mjs 41a37ceb-e65c-4cd3-adc4-78b8fbc6dd51')
  process.exit(1)
}

const origin = process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'
const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// 调用后端生成 JWT（使用 SUPABASE_JWT_SECRET，super_admin 7 天有效，不会像 Magic Link 那样几分钟过期）
const res = await fetch(`${apiUrl}/api/auth/authorization`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ user_id: userId }),
})

if (!res.ok) {
  const text = await res.text()
  console.error('获取 token 失败:', res.status, text)
  process.exit(1)
}

const data = await res.json()
const token = data.token

if (!token) {
  console.error('响应中缺少 token:', data)
  process.exit(1)
}

const loginUrl = `${origin}/dev-login?access_token=${encodeURIComponent(token)}`

console.log('')
console.log('复制下面 URL 到浏览器打开即可登录（7 天有效）：')
console.log('')
console.log(loginUrl)
console.log('')
