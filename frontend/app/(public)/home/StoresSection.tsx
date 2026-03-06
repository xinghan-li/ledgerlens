'use client'

import { useState } from 'react'
import Link from 'next/link'

const PAGE_SIZE = 10

type Store = { id: string; name: string; normalized_name: string; receipt_count: number }

export default function StoresSection({
  top5ForGrid,
  allStoresByCount,
}: {
  top5ForGrid: Store[]
  allStoresByCount: Store[]
}) {
  const [expanded, setExpanded] = useState(false)
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  const totalStores = allStoresByCount.length
  const visibleStores = allStoresByCount.slice(0, visibleCount)
  const hasMore = visibleCount < totalStores

  return (
    <div className="bg-white p-8 rounded-xl shadow-lg mb-12 border border-theme-light-gray/50">
      <h2 className="font-heading text-2xl font-bold mb-2 text-left text-theme-dark">
        Stores We Have Samples From
      </h2>
      <p className="text-theme-dark/80 text-sm sm:text-base mb-6 text-left">
        The more our community contributes, the more accurate insights we provide. We support any store—these are where we already have receipt data. Names and counts come from store chains in our system.
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4 text-left">
        {top5ForGrid.map((store) => (
          <div
            key={store.id}
            className="p-4 bg-theme-light-gray/50 rounded-lg flex items-center justify-between gap-3 min-h-18"
          >
            <div className="min-w-0">
              <p className="font-medium text-theme-dark">{store.name}</p>
            </div>
            <div className="shrink-0 text-right">
              <span className="text-sm font-medium text-theme-dark tabular-nums" title="Receipts in our system">
                {store.receipt_count} <span className="text-theme-mid font-normal">receipts</span>
              </span>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="p-4 bg-theme-light-gray/50 rounded-lg flex items-center justify-center gap-2 border border-dashed border-theme-mid/40 text-theme-dark font-medium hover:bg-theme-light-gray/70 transition-colors min-h-18"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      </div>

      {expanded && (
        <div className="mt-6 pt-6 border-t border-theme-light-gray/50">
          <h3 className="font-heading font-semibold text-theme-dark mb-4 text-left">
            Top Stores by Receipts Count
          </h3>
          <ol className="list-decimal list-inside space-y-2 text-left">
            {visibleStores.map((store, index) => (
              <li
                key={store.id}
                className="flex items-center justify-between gap-4 py-2 px-3 rounded-lg bg-theme-light-gray/30 min-h-10"
              >
                <span className="font-medium text-theme-dark">{store.name}</span>
                <span className="text-sm text-theme-dark tabular-nums shrink-0">
                  {store.receipt_count} receipt{store.receipt_count !== 1 ? 's' : ''}
                </span>
              </li>
            ))}
          </ol>
          {hasMore && (
            <button
              type="button"
              onClick={() => setVisibleCount((n) => Math.min(n + PAGE_SIZE, totalStores))}
              className="mt-4 w-full py-3 rounded-lg border border-theme-mid/40 text-theme-dark font-medium hover:bg-theme-light-gray/50 transition-colors"
            >
              Show 10 more
              {totalStores - visibleCount <= PAGE_SIZE
                ? ` (${totalStores - visibleCount} left)`
                : ` (${visibleCount} of ${totalStores})`}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
