'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { onAuthStateChanged } from 'firebase/auth'
import { getFirebaseAuth } from '@/lib/firebase'

const navLink =
  'font-heading text-sm font-medium text-theme-dark/90 hover:text-theme-dark transition-colors'

const ctaButtonClass =
  'font-heading text-sm font-semibold bg-theme-dark text-white py-2 px-4 rounded-md hover:opacity-90 transition-opacity'

export function PublicNav() {
  const pathname = usePathname()
  const isCommunications = pathname?.startsWith('/communications')
  const [isLoggedIn, setIsLoggedIn] = useState<boolean | null>(null)

  useEffect(() => {
    const auth = getFirebaseAuth()
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setIsLoggedIn(!!user)
    })
    return () => unsubscribe()
  }, [])

  return (
    <nav className="flex items-center gap-6">
      <Link
        href={isCommunications ? '/home' : '/communications'}
        className={navLink}
      >
        {isCommunications ? 'About' : 'Communications'}
      </Link>
      {isLoggedIn === true ? (
        <Link href="/dashboard" className={ctaButtonClass}>
          Dashboard
        </Link>
      ) : (
        <Link href="/login" className={ctaButtonClass}>
          Sign in
        </Link>
      )}
    </nav>
  )
}
