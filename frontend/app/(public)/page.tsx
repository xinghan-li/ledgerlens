import { redirect } from 'next/navigation'

export default async function RootPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const error = typeof params?.error === 'string' ? params.error : undefined
  const errorCode = typeof params?.error_code === 'string' ? params.error_code : undefined
  if (error === 'access_denied' || errorCode === 'otp_expired') {
    redirect(`/login?error=otp_expired`)
  }
  redirect('/home')
}
