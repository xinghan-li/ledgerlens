'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase'
import { useApiUrl } from '@/lib/api-url-context'

export default function TestUploadPage() {
  const apiBaseUrl = useApiUrl()
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const supabase = createClient()

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      console.log('File selected:', selectedFile.name, selectedFile.type, selectedFile.size)
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

      console.log('Request URL:', `${apiBaseUrl}/api/receipt/workflow`)

      // 发送请求
      const response = await fetch(`${apiBaseUrl}/api/receipt/workflow`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          // 注意：不要手动设置 Content-Type，让浏览器自动设置 multipart/form-data 边界
        },
        body: formData,
      })

      console.log('Response status:', response.status, response.statusText)
      console.log('Response headers:', Object.fromEntries(response.headers.entries()))

      const text = await response.text()
      console.log('Response body:', text)

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
      console.error('Error:', error)
      setResult(`❌ Error: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-theme-cream p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-3xl font-bold mb-8">Upload test</h1>

        <div className="bg-white rounded-xl shadow p-6 space-y-6">
          <div>
            <label className="block text-sm font-medium text-theme-dark/90 mb-2">
              Select receipt file
            </label>
            <input
              type="file"
              accept="image/*,.pdf"
              onChange={handleFileChange}
              className="block w-full text-sm text-theme-mid
                file:mr-4 file:py-2 file:px-4
                file:rounded-lg file:border-0
                file:text-sm file:font-semibold
                file:bg-theme-light-gray/50 file:text-theme-orange
                hover:file:bg-theme-light-gray"
            />
          </div>

          {file && (
            <div className="p-4 bg-theme-cream rounded-lg">
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
            className="w-full px-6 py-3 btn-primary disabled:bg-theme-mid disabled:cursor-not-allowed font-semibold"
          >
            {loading ? 'Uploading…' : 'Upload'}
          </button>

          {result && (
            <div className="p-4 bg-theme-dark rounded-lg">
              <pre className="text-sm text-theme-cream whitespace-pre-wrap overflow-x-auto">
                {result}
              </pre>
            </div>
          )}
        </div>

        <div className="mt-8 p-4 bg-theme-light-gray/50 rounded-lg">
          <p className="text-sm text-theme-dark">
            💡 <strong>Tip:</strong> Open browser console (F12) for detailed logs
          </p>
        </div>
      </div>
    </div>
  )
}
