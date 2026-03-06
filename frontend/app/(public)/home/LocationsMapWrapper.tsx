'use client'

import dynamic from 'next/dynamic'
import type { LocationStat } from './LocationsMap'

const LocationsMap = dynamic(() => import('./LocationsMap'), { ssr: false })

type Props = { locations: LocationStat[] }

export default function LocationsMapWrapper({ locations }: Props) {
  return <LocationsMap locations={locations} />
}
