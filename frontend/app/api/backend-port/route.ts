import { NextResponse } from 'next/server'
import path from 'path'
import fs from 'fs'

/**
 * 返回后端实际端口（由 run_backend.py 写入的 backend-port.json）。
 * 前端在 localhost 下会先请求此接口，再用返回的 URL 探测 /health，避免后端因 8000 占用改到 8081 时仍请求 8000。
 */
export async function GET() {
  try {
    const cwd = process.cwd()
    const candidates = [
      path.join(cwd, '..', 'backend-port.json'),
      path.join(cwd, 'backend-port.json'),
    ]
    for (const file of candidates) {
      if (fs.existsSync(file)) {
        const raw = fs.readFileSync(file, 'utf-8')
        const data = JSON.parse(raw) as { port?: number; url?: string }
        if (data?.url) {
          return NextResponse.json({ port: data.port, url: data.url })
        }
      }
    }
  } catch {
    // ignore
  }
  return NextResponse.json({ port: 8000, url: 'http://localhost:8000' })
}
