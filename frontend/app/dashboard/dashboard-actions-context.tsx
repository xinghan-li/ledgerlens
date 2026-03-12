'use client'

import { createContext, useContext, useState, type ReactNode } from 'react'

export type DashboardHeaderActions = {
  onReceiptHistory: () => void
  onUpload: () => void
  onCamera: () => void
} | null

const DashboardActionsContext = createContext<{
  actions: DashboardHeaderActions
  setActions: (a: DashboardHeaderActions) => void
  bannerInView: boolean
  setBannerInView: (v: boolean) => void
  unclassifiedCount: number | null
  setUnclassifiedCount: (n: number | null) => void
}>({ actions: null, setActions: () => {}, bannerInView: true, setBannerInView: () => {}, unclassifiedCount: null, setUnclassifiedCount: () => {} })

export function DashboardActionsProvider({ children }: { children: ReactNode }) {
  const [actions, setActions] = useState<DashboardHeaderActions>(null)
  const [bannerInView, setBannerInView] = useState(true)
  const [unclassifiedCount, setUnclassifiedCount] = useState<number | null>(null)
  return (
    <DashboardActionsContext.Provider value={{ actions, setActions, bannerInView, setBannerInView, unclassifiedCount, setUnclassifiedCount }}>
      {children}
    </DashboardActionsContext.Provider>
  )
}

export function useDashboardActions() {
  return useContext(DashboardActionsContext)
}
