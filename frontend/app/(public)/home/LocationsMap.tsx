'use client'

import { useMemo, useState } from 'react'
import {
  ComposableMap,
  Geographies,
  Geography,
  ZoomableGroup,
} from 'react-simple-maps'

/** US Census FIPS state id (string in topojson) -> 2-letter state code */
const US_FIPS_TO_CODE: Record<string, string> = {
  '01': 'AL', '02': 'AK', '04': 'AZ', '05': 'AR', '06': 'CA', '08': 'CO', '09': 'CT', '10': 'DE',
  '11': 'DC', '12': 'FL', '13': 'GA', '15': 'HI', '16': 'ID', '17': 'IL', '18': 'IN', '19': 'IA',
  '20': 'KS', '21': 'KY', '22': 'LA', '23': 'ME', '24': 'MD', '25': 'MA', '26': 'MI', '27': 'MN',
  '28': 'MS', '29': 'MO', '30': 'MT', '31': 'NE', '32': 'NV', '33': 'NH', '34': 'NJ', '35': 'NM',
  '36': 'NY', '37': 'NC', '38': 'ND', '39': 'OH', '40': 'OK', '41': 'OR', '42': 'PA',
  '44': 'RI', '45': 'SC', '46': 'SD', '47': 'TN', '48': 'TX', '49': 'UT', '50': 'VT',
  '51': 'VA', '53': 'WA', '54': 'WV', '55': 'WI', '56': 'WY',
}

/** GeoJSON province name (from codeforamerica dataset) -> 2-letter code */
const CA_NAME_TO_CODE: Record<string, string> = {
  'Alberta': 'AB',
  'British Columbia': 'BC',
  'Manitoba': 'MB',
  'New Brunswick': 'NB',
  'Newfoundland and Labrador': 'NL',
  'Nova Scotia': 'NS',
  'Northwest Territories': 'NT',
  'Nunavut': 'NU',
  'Ontario': 'ON',
  'Prince Edward Island': 'PE',
  'Quebec': 'QC',
  'Saskatchewan': 'SK',
  'Yukon': 'YT',
  'Yukon Territory': 'YT',
}

const CA_PROVINCE_NAMES: Record<string, string> = {
  AB: 'Alberta', BC: 'British Columbia', MB: 'Manitoba', NB: 'New Brunswick',
  NL: 'Newfoundland and Labrador', NS: 'Nova Scotia', NT: 'Northwest Territories',
  NU: 'Nunavut', ON: 'Ontario', PE: 'Prince Edward Island', QC: 'Quebec',
  SK: 'Saskatchewan', YT: 'Yukon',
}

const US_TOPOLOGY = 'https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json'
const CA_TOPOLOGY = 'https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/canada.geojson'

/** Inline SVG flags so they render on all platforms (emoji flags often fail on Windows) */
function FlagUS({ className }: { className?: string }) {
  return (
    <span className={className} role="img" aria-label="USA">
      <svg viewBox="0 0 60 30" className="w-5 h-[10px] inline-block" preserveAspectRatio="xMidYMid meet">
        <rect width="60" height="30" fill="#b22234" />
        {[1, 3, 5, 7, 9, 11].map((i) => (
          <rect key={i} width="60" height={2.31} y={i * 2.31} fill="#fff" />
        ))}
        <rect width="24" height="13.85" fill="#3c3b6e" />
        <g fill="#fff">
          {[0, 1, 2, 3, 4, 5].map((row) =>
            [0, 1, 2, 3, 4].map((col) => (
              <circle key={`${row}-${col}`} cx={3 + col * 4 + (row % 2) * 2} cy={2.5 + row * 2.2} r="0.8" />
            )),
          )}
        </g>
      </svg>
    </span>
  )
}
function FlagCA({ className }: { className?: string }) {
  return (
    <span className={className} role="img" aria-label="Canada">
      <svg viewBox="0 0 90 45" className="w-5 h-[10px] inline-block" preserveAspectRatio="xMidYMid meet">
        <rect width="90" height="45" fill="#fff" />
        <rect width="22.5" height="45" fill="#ff0000" />
        <rect x="67.5" width="22.5" height="45" fill="#ff0000" />
        {/* Simplified maple leaf */}
        <path
          fill="#ff0000"
          d="M45 6 L42 14 L38 20 L40 26 L39 32 L45 39 L51 32 L50 26 L52 20 L48 14 Z"
        />
      </svg>
    </span>
  )
}

/**
 * 10-step orange gradient: index 0 (lightest, 0–10th percentile) → index 9 (darkest, theme-orange)
 * Linearly interpolated from #fdf5f3 → #d97757
 */
const ORANGE_SCALE = [
  '#fdf5f3',
  '#f9e7e2',
  '#f5d9d1',
  '#f1cbbf',
  '#edbdae',
  '#e9af9d',
  '#e5a18b',
  '#e1937a',
  '#dd8569',
  '#d97757', // theme-orange — top 10%
]

/** Slightly darker hover version of each ORANGE_SCALE step */
const ORANGE_SCALE_HOVER = [
  '#f0e0db',
  '#ecd3c9',
  '#e6c4b9',
  '#e0b5a7',
  '#d7a895',
  '#d29985',
  '#c98b73',
  '#c67d64',
  '#c06f55',
  '#c4694a', // theme-orange-hover
]

const NO_DATA_FILL = '#f3f4f6'
const NO_DATA_HOVER = '#e5e7eb'

/**
 * Returns the fill color for a region based on its receipt count
 * relative to all other regions in the same country view (percentile bucketed into 10 steps).
 */
function getOrangeColor(count: number, allCounts: number[]): { fill: string; hover: string } {
  if (count === 0) return { fill: NO_DATA_FILL, hover: NO_DATA_HOVER }
  const withData = allCounts.filter((c) => c > 0).sort((a, b) => a - b)
  if (withData.length === 0) return { fill: NO_DATA_FILL, hover: NO_DATA_HOVER }
  const rank = withData.filter((c) => c <= count).length
  const percentile = rank / withData.length
  const idx = Math.min(Math.floor(percentile * 10), 9)
  return { fill: ORANGE_SCALE[idx], hover: ORANGE_SCALE_HOVER[idx] }
}

export type LocationStat = {
  country_code: string
  state_code: string
  /** Full name from backend (e.g. Washington, British Columbia). */
  state_display_name?: string
  receipt_count: number
  store_count?: number
}

type Props = {
  locations: LocationStat[]
}

type Region = 'US' | 'CA'

export default function LocationsMap({ locations }: Props) {
  const [region, setRegion] = useState<Region>('US')

  const countByUsState = useMemo(() => {
    const m: Record<string, { receipts: number; stores: number }> = {}
    for (const loc of locations) {
      if (loc.country_code !== 'US') continue
      if (!m[loc.state_code]) m[loc.state_code] = { receipts: 0, stores: 0 }
      m[loc.state_code].receipts += loc.receipt_count
      m[loc.state_code].stores += loc.store_count ?? 0
    }
    return m
  }, [locations])

  const countByCaProvince = useMemo(() => {
    const m: Record<string, { receipts: number; stores: number }> = {}
    for (const loc of locations) {
      if (loc.country_code !== 'CA') continue
      if (!m[loc.state_code]) m[loc.state_code] = { receipts: 0, stores: 0 }
      m[loc.state_code].receipts += loc.receipt_count
      m[loc.state_code].stores += loc.store_count ?? 0
    }
    return m
  }, [locations])

  const usReceiptCounts = useMemo(
    () => Object.values(countByUsState).map((d) => d.receipts),
    [countByUsState],
  )
  const caReceiptCounts = useMemo(
    () => Object.values(countByCaProvince).map((d) => d.receipts),
    [countByCaProvince],
  )

  const top5ByReceipts = useMemo(() => {
    return [...locations]
      .sort((a, b) => b.receipt_count - a.receipt_count)
      .slice(0, 5)
  }, [locations])

  const top5ByStores = useMemo(() => {
    return [...locations]
      .filter((l) => (l.store_count ?? 0) > 0)
      .sort((a, b) => (b.store_count ?? 0) - (a.store_count ?? 0))
      .slice(0, 5)
  }, [locations])

  const hasUs = Object.keys(countByUsState).length > 0
  const hasCa = Object.keys(countByCaProvince).length > 0

  const label = (loc: LocationStat) =>
    loc.state_display_name ?? CA_PROVINCE_NAMES[loc.state_code] ?? loc.state_code

  return (
    <div className="w-full">
      {/* Title row */}
      <div className="flex flex-wrap items-center justify-between gap-4 mb-2">
        <h2 className="font-heading text-2xl font-bold text-left text-theme-dark">
          Locations We Have Samples From
        </h2>
        <div className="flex rounded-lg border border-theme-light-gray bg-white p-0.5">
          <button
            type="button"
            onClick={() => setRegion('US')}
            className={`w-24 py-1.5 text-sm font-medium rounded-md transition-colors text-center flex items-center justify-center gap-1.5 ${region === 'US' ? 'bg-theme-dark text-white' : 'text-theme-dark/70 hover:bg-theme-light-gray/50'}`}
          >
            <FlagUS />
            <span>USA</span>
          </button>
          <button
            type="button"
            onClick={() => setRegion('CA')}
            className={`w-24 py-1.5 text-sm font-medium rounded-md transition-colors text-center flex items-center justify-center gap-1.5 ${region === 'CA' ? 'bg-theme-dark text-white' : 'text-theme-dark/70 hover:bg-theme-light-gray/50'}`}
          >
            <FlagCA />
            <span>CAN</span>
          </button>
        </div>
      </div>
      <p className="text-theme-dark/80 text-sm sm:text-base mb-6 text-left">
        US states and Canadian provinces where our community has contributed receipts. Hover for counts.
      </p>

      {/* US Map */}
      {region === 'US' && (
        <div className="rounded-xl overflow-hidden border border-theme-light-gray/50 bg-white mb-6">
          <ComposableMap
            projection="geoAlbersUsa"
            projectionConfig={{ scale: 1000 }}
            width={800}
            height={500}
            style={{ width: '100%', height: 'auto' }}
          >
            <ZoomableGroup center={[-96, 39]} zoom={1}>
              <Geographies geography={US_TOPOLOGY}>
                {({ geographies }) =>
                  geographies.map((geo) => {
                    const fips = geo.id != null ? String(geo.id) : ''
                    const code = US_FIPS_TO_CODE[fips] || null
                    const data = code ? countByUsState[code] : null
                    const count = data?.receipts ?? 0
                    const { fill, hover } = getOrangeColor(count, usReceiptCounts)
                    return (
                      <Geography
                        key={geo.rsmKey}
                        geography={geo}
                        fill={fill}
                        stroke="#e5e7eb"
                        strokeWidth={0.5}
                        style={{
                          default: { outline: 'none' },
                          hover: { outline: 'none', fill: hover },
                          pressed: { outline: 'none' },
                        }}
                      >
                        <title>
                          {code
                            ? `${code}: ${count} receipt${count !== 1 ? 's' : ''}${data?.stores ? `, ${data.stores} store(s)` : ''}`
                            : ''}
                        </title>
                      </Geography>
                    )
                  })
                }
              </Geographies>
            </ZoomableGroup>
          </ComposableMap>
        </div>
      )}

      {region === 'US' && !hasUs && (
        <p className="text-sm text-theme-mid mb-6 text-left">No US data yet—upload receipts to see states light up.</p>
      )}

      {/* Canada Map */}
      {region === 'CA' && (
        <div className="rounded-xl overflow-hidden border border-theme-light-gray/50 bg-white mb-6">
          <ComposableMap
            projection="geoConicConformal"
            projectionConfig={{
              rotate: [96, 0],
              scale: 620,
              center: [0, 62],
            }}
            width={800}
            height={500}
            style={{ width: '100%', height: 'auto' }}
          >
            <ZoomableGroup center={[-96, 62]} zoom={1}>
            <Geographies geography={CA_TOPOLOGY}>
              {({ geographies }) =>
                geographies.map((geo) => {
                  const name = geo.properties?.name ?? ''
                  const code = CA_NAME_TO_CODE[name] ?? ''
                  const data = code ? countByCaProvince[code] : null
                  const count = data?.receipts ?? 0
                  const displayName = CA_PROVINCE_NAMES[code] || name
                  const { fill, hover } = getOrangeColor(count, caReceiptCounts)
                  return (
                    <Geography
                      key={geo.rsmKey}
                      geography={geo}
                      fill={fill}
                      stroke="#e5e7eb"
                      strokeWidth={0.5}
                      style={{
                        default: { outline: 'none' },
                        hover: { outline: 'none', fill: hover },
                        pressed: { outline: 'none' },
                      }}
                    >
                      <title>
                        {displayName
                          ? `${displayName}: ${count} receipt${count !== 1 ? 's' : ''}${data?.stores ? `, ${data.stores} store(s)` : ''}`
                          : ''}
                      </title>
                    </Geography>
                  )
                })
              }
            </Geographies>
            </ZoomableGroup>
          </ComposableMap>
        </div>
      )}

      {region === 'CA' && !hasCa && (
        <p className="text-sm text-theme-mid mb-6 text-left">No Canada data yet—upload receipts from Canadian stores to see provinces light up.</p>
      )}

      {/* Top 5 rankings */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="rounded-xl border border-theme-light-gray/50 bg-white p-4">
          <h3 className="font-heading font-semibold text-theme-dark mb-3">Top 5 by Receipt Count</h3>
          {top5ByReceipts.length === 0 ? (
            <p className="text-sm text-theme-mid">No data yet.</p>
          ) : (
            <ol className="list-decimal list-inside space-y-1.5 text-sm">
              {top5ByReceipts.map((loc) => (
                <li key={`${loc.country_code}-${loc.state_code}`} className="text-theme-dark">
                  <span className="font-medium">{label(loc)}</span>
                  <span className="text-theme-mid ml-1">— {loc.receipt_count} receipt{loc.receipt_count !== 1 ? 's' : ''}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div className="rounded-xl border border-theme-light-gray/50 bg-white p-4">
          <h3 className="font-heading font-semibold text-theme-dark mb-3">Top 5 by Stores Sampled</h3>
          {top5ByStores.length === 0 ? (
            <p className="text-sm text-theme-mid">No data yet.</p>
          ) : (
            <ol className="list-decimal list-inside space-y-1.5 text-sm">
              {top5ByStores.map((loc) => (
                <li key={`${loc.country_code}-${loc.state_code}`} className="text-theme-dark">
                  <span className="font-medium">{label(loc)}</span>
                  <span className="text-theme-mid ml-1">— {loc.store_count} store{loc.store_count !== 1 ? 's' : ''}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>
    </div>
  )
}
