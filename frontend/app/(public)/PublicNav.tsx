'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const navLink =
  'font-heading text-sm font-medium text-theme-dark/90 hover:text-theme-dark transition-colors'

export function PublicNav() {
  const pathname = usePathname()
  const isCommunications = pathname?.startsWith('/communications')

  return (
    <nav className="flex items-center gap-6">
      <Link
        href={isCommunications ? '/home' : '/communications'}
        className={navLink}
      >
        {isCommunications ? 'About' : 'Communications'}
      </Link>
      <Link
        href="/login"
        className="font-heading text-sm font-semibold bg-theme-dark text-white py-2 px-4 rounded-md hover:opacity-90 transition-opacity"
      >
        Sign in
      </Link>
    </nav>
  )
}
