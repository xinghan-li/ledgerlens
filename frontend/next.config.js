/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // Disable client-side router cache for dynamic routes so navigating back
    // to /dashboard always re-mounts page components and re-fetches fresh data.
    staleTimes: {
      dynamic: 0,
    },
  },
}

module.exports = nextConfig
