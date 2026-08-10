/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // System-grotesk stack — SF/Segoe/Inter, no external CDN (air-gap safe)
        sans: [
          'Inter', 'SF Pro Text', '-apple-system', 'BlinkMacSystemFont',
          'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif',
        ],
        mono: [
          'SF Mono', 'JetBrains Mono', 'Menlo', 'Consolas',
          'Liberation Mono', 'ui-monospace', 'monospace',
        ],
      },
      colors: {
        // Warm graphite — replaces the cold default slate across the whole app.
        slate: {
          50:  '#f7f7f8',
          100: '#eeeef0',
          200: '#dcdce0',
          300: '#b6b6bd',
          400: '#8e8e97',   // secondary text
          500: '#6a6a73',   // muted / placeholder
          600: '#42424a',
          700: '#2a2a30',   // hairline borders
          800: '#1a1a1f',   // cards / panels
          900: '#111114',   // canvas
          950: '#0a0a0c',
        },
        // Iris accent — replaces the default indigo (a touch warmer/brighter).
        indigo: {
          300: '#b3aaf8',
          400: '#9a8ff4',   // accent text on dark
          500: '#7c6ef0',
          600: '#5f4fe0',   // primary buttons (AA on white text)
          700: '#4c3cc6',
          800: '#3c30a0',
          900: '#2c2478',
        },
      },
      boxShadow: {
        'panel': '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.5)',
        'glow': '0 0 0 1px rgba(124,110,240,0.25), 0 8px 30px -8px rgba(124,110,240,0.35)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.35s cubic-bezier(0.22, 1, 0.36, 1) both',
      },
    },
  },
  plugins: [],
}
