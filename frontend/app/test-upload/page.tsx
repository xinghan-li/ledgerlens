'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase'

export default function TestUploadPage() {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const supabase = createClient()

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      console.log('文件选择:', selectedFile.name, selectedFile.type, selectedFile.size)
    }
  }

  const handleUpload = async () => {
    if (!file) {
      alert('Please select a file first')
      return
    }

    setLoading(true)
    setResult('')

    try {
      // 获取 token
      const { data: { session } } = await supabase.auth.getSession()
      
      if (!session) {
        setResult('❌ Not signed in')
        return
      }

      const token = session.access_token
      console.log('Token:', token.substring(0, 50) + '...')

      // 准备 FormData
      const formData = new FormData()
      formData.append('file', file)

      console.log('FormData entries:')
      for (const [key, value] of formData.entries()) {
        console.log(`  ${key}:`, value)
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
      console.log('请求 URL:', `${apiUrl}/api/receipt/workflow`)

      // 发送请求
      const response = await fetch(`${apiUrl}/api/receipt/workflow`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          // 注意：不要手动设置 Content-Type，让浏览器自动设置 multipart/form-data 边界
        },
        body: formData,
      })

      console.log('响应状态:', response.status, response.statusText)
      console.log('响应头:', Object.fromEntries(response.headers.entries()))

      const text = await response.text()
      console.log('响应体:', text)

      let resultData
      try {
        resultData = JSON.parse(text)
      } catch {
        resultData = text
      }

      if (response.ok) {
        setResult(`✅ Success!\n\n${JSON.stringify(resultData, null, 2)}`)
      } else {
        setResult(`❌ Failed (${response.status})\n\n${JSON.stringify(resultData, null, 2)}`)
      }

    } catch (error) {
      console.error('错误:', error)
      setResult(`❌ Error: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">Upload test</h1>

        <div className="bg-white rounded-xl shadow p-6 space-y-6">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Select receipt file
            </label>
            <input
              type="file"
              accept="image/*,.pdf"
              onChange={handleFileChange}
              className="block w-full text-sm text-gray-500
                file:mr-4 file:py-2 file:px-4
                file:rounded-lg file:border-0
                file:text-sm file:font-semibold
                file:bg-blue-50 file:text-blue-700
                hover:file:bg-blue-100"
            />
          </div>

          {file && (
            <div className="p-4 bg-gray-50 rounded-lg">
              <p className="text-sm">
                <strong>File name:</strong> {file.name}
              </p>
              <p className="text-sm">
                <strong>Type:</strong> {file.type}
              </p>
              <p className="text-sm">
                <strong>Size:</strong> {(file.size / 1024).toFixed(2)} KB
              </p>
            </div>
          )}

          <button
            onClick={handleUpload}
            disabled={!file || loading}
            className="w-full px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed font-semibold"
          >
            {loading ? 'Uploading…' : 'Upload'}
          </button>

          {result && (
            <div className="p-4 bg-gray-900 rounded-lg">
              <pre className="text-sm text-gray-100 whitespace-pre-wrap overflow-x-auto">
                {result}
              </pre>
            </div>
          )}
        </div>

        <div className="mt-8 p-4 bg-blue-50 rounded-lg">
          <p className="text-sm text-blue-800">
            💡 <strong>Tip:</strong> Open browser console (F12) for detailed logs
          </p>
        </div>
      </div>
    </div>
  )
}
