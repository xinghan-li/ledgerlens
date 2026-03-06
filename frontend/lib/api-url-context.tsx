'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'
import { getApiBaseUrl } from '@/lib/api-url'

type ApiUrlContextValue = string | null

const ApiUrlContext = createContext<ApiUrlContextValue>(null)

export function ApiUrlProvider({ children }: { children: React.ReactNode }) {
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    getApiBaseUrl().then(setUrl)
  }, [])

  if (url === null) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-gray-500 text-sm">Connecting to backend…</div>
      </div>
    )
  }

  return (
    <ApiUrlContext.Provider value={url}>
      {children}
    </ApiUrlContext.Provider>
  )
}

export function useApiUrl(): string {
  const url = useContext(ApiUrlContext)
  if (url == null) {
    throw new Error('useApiUrl must be used within ApiUrlProvider')
  }
  return url
}
