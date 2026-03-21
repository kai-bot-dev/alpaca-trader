/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        teal: {
          300: '#5EEAD4',
          400: '#0ECFB3',
          500: '#0BB89E',
          600: '#099A84',
        },
        amber: {
          400: '#F8A43A',
          500: '#F59E0B',
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'monospace'],
        display: ['Syne', 'sans-serif'],
      },
      backgroundImage: {
        'grid-teal': `
          linear-gradient(rgba(14, 207, 179, 0.04) 1px, transparent 1px),
          linear-gradient(90deg, rgba(14, 207, 179, 0.04) 1px, transparent 1px)
        `,
      },
      backgroundSize: {
        'grid': '32px 32px',
      },
    },
  },
  plugins: [],
}
