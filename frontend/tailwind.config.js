/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // 主题色板（见 frontend/COLOR_THEME.md）
        'theme-black': '#000000',
        'theme-slate': '#191919',
        'theme-dark-262': '#262625',
        'theme-dark-404': '#40403e',
        'theme-gray-666': '#666663',
        'theme-gray-919': '#91918d',
        'theme-cloud': '#bfbfba',
        'theme-ivory-dark': '#e5e4df',
        'theme-cream-f0': '#f0f0eb',
        'theme-ivory': '#fafaf7',
        'book-cloth': '#cc785c',
        'theme-orange-mid': '#d4a27f',
        manilla: '#ebdbbc',
        'theme-blue': '#61aaf2',
        'theme-red': '#bf4d43',
        // LedgerLens theme (main UI)
        'theme-dark': '#141413',
        'theme-cream': '#faf9f5',
        'theme-cream-alt': '#f5f4f0',
        'theme-mid': '#b0aea5',
        'theme-light-gray': '#e8e6dc',
        'theme-orange': '#d97757',
        'theme-orange-hover': '#c4694a',
        'theme-orange-muted': '#e8b5a5',
        'slate-dark': '#191919',
        'ivory-light': '#fafaf7',
        primary: {
          DEFAULT: '#d97757',
          50: '#fdf5f3',
          100: '#fae8e3',
          200: '#f5d1c7',
          300: '#e8b5a5',
          400: '#d97757',
          500: '#c4694a',
          600: '#a8553d',
          700: '#8b4534',
          800: '#72392c',
          900: '#5e3026',
        },
      },
      fontFamily: {
        body: ['var(--font-lora)', 'Georgia', 'serif'],
        heading: ['var(--font-poppins)', 'Arial', 'sans-serif'],
      },
      keyframes: {
        'processing-pulse': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.75' },
        },
        'sandglass-tilt': {
          '0%, 100%': { transform: 'rotate(0deg)' },
          '25%': { transform: 'rotate(-8deg)' },
          '75%': { transform: 'rotate(8deg)' },
        },
      },
      animation: {
        'processing-pulse': 'processing-pulse 2s ease-in-out infinite',
        'sandglass-tilt': 'sandglass-tilt 2.5s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
