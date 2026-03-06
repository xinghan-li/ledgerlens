import Link from 'next/link'
import { PublicNav } from './PublicNav'

export default function PublicLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="min-h-screen flex flex-col bg-theme-cream">
      <header className="sticky top-0 z-10 border-b border-theme-light-gray/60 bg-white font-heading">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 flex items-center justify-between h-14">
          <Link href="/home" className="text-lg font-semibold text-theme-dark">
            LedgerLens
          </Link>
          <PublicNav />
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  )
}
