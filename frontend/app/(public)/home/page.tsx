import Link from 'next/link'
import type { LocationStat } from './LocationsMap'
import LocationsMapWrapper from './LocationsMapWrapper'
import StoresSection from './StoresSection'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export default async function HomePage() {
  // Single source: one request so store cards and map always show consistent data
  let stores: { id: string; name: string; normalized_name: string; receipt_count: number }[] = []
  let locations: LocationStat[] = []
  try {
    const res = await fetch(`${API_BASE}/api/public/home-stats`, { next: { revalidate: 60 } })
    if (res.ok) {
      const data = await res.json()
      stores = data.stores ?? []
      locations = data.locations ?? []
    }
  } catch {
    // leave empty
  }
  const storesByCount = [...stores]
    .filter((s) => (s.receipt_count ?? 0) > 0)
    .sort((a, b) => (b.receipt_count ?? 0) - (a.receipt_count ?? 0))
  const top5ForGrid = storesByCount.slice(0, 5)

  return (
    <div className="flex flex-col bg-theme-cream min-h-full">
      <section className="w-full bg-theme-cream">
        <div className="max-w-4xl mx-auto px-[0.667rem] sm:px-4 py-12 sm:py-16 text-left">
          <h1 className="font-heading text-4xl sm:text-5xl font-bold mb-3 text-theme-dark leading-tight">
            <span className="underline decoration-2 decoration-theme-dark underline-offset-4">LedgerLens</span>
            {' '}breaks down everyday receipts into structured financial insight.
          </h1>
          <p className="text-lg sm:text-xl text-theme-dark/90 mt-4">
            We help you understand what you spend and what things really cost down to{' '}
            <span className="underline decoration-2 decoration-theme-dark underline-offset-4">item level</span>.
          </p>
        </div>
      </section>
      <div className="max-w-4xl mx-auto px-[0.667rem] sm:px-4 py-16 w-full flex-1 bg-theme-cream">

        <div className="grid md:grid-cols-3 gap-8 mb-12">
          <div className="bg-white p-6 rounded-xl shadow-lg border border-theme-light-gray/50">
            <h3 className="font-heading text-xl font-semibold mb-2 text-theme-dark">Smart Recognition</h3>
            <p className="text-theme-dark/90">
              Leveraging AI and LLM Models to accurately extract line items on your receipts
            </p>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-lg border border-theme-light-gray/50">
            <h3 className="font-heading text-xl font-semibold mb-2 text-theme-dark">Spending Analysis</h3>
            <p className="text-theme-dark/90">
              Breaking down bulk spendings into categories. Providing insights on what things really costs
            </p>
          </div>
          <div className="bg-white p-6 rounded-xl shadow-lg border border-theme-light-gray/50">
            <h3 className="font-heading text-xl font-semibold mb-2 text-theme-dark">Fast & Secure</h3>
            <p className="text-theme-dark/90">
              Fast sign-in via email link. No password required.
            </p>
          </div>
        </div>

        <StoresSection top5ForGrid={top5ForGrid} allStoresByCount={storesByCount} />

        <div className="bg-white p-8 rounded-xl shadow-lg mb-12 border border-theme-light-gray/50">
          <LocationsMapWrapper locations={locations} />
        </div>
      </div>

      <div className="text-center pb-16 bg-theme-cream">
        <Link
          href="/login"
          className="btn-primary inline-block text-lg py-4 px-8 shadow-lg hover:shadow-xl"
        >
          Get started
        </Link>
      </div>
    </div>
  )
}
