import type { Metadata } from 'next'
import { Lora, Poppins, Space_Mono } from 'next/font/google'
import './globals.css'
import { ApiUrlProvider } from '@/lib/api-url-context'

const lora = Lora({
  subsets: ['latin'],
  variable: '--font-lora',
  display: 'swap',
})

const poppins = Poppins({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-poppins',
  display: 'swap',
})

const spaceMono = Space_Mono({
  subsets: ['latin'],
  weight: ['400', '700'],
  variable: '--font-space-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'LedgerLens - Smart receipt recognition',
  description: 'Use AI to scan and manage your receipts',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${lora.variable} ${poppins.variable} ${spaceMono.variable}`}>
      <body className="font-body antialiased">
        <ApiUrlProvider>{children}</ApiUrlProvider>
      </body>
    </html>
  )
}
