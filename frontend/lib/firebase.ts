/**
 * Firebase SDK (Auth). Used for email link sign-in and API token.
 */
import { initializeApp, getApps, type FirebaseApp } from 'firebase/app'
import { getAuth, type Auth } from 'firebase/auth'

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || 'ledgerlens-484819.firebaseapp.com',
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || 'ledgerlens-484819',
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
}

function getApp(): FirebaseApp {
  const apps = getApps()
  if (apps.length > 0) return apps[0] as FirebaseApp
  return initializeApp(firebaseConfig)
}

export function getFirebaseAuth(): Auth {
  return getAuth(getApp())
}

/** Returns current Firebase ID token for API calls, or null if not signed in. Pass true to force refresh (e.g. after 401). */
export async function getAuthToken(forceRefresh?: boolean): Promise<string | null> {
  const user = getAuth(getApp()).currentUser
  if (!user) return null
  return user.getIdToken(forceRefresh === true)
}
