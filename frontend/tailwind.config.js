/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
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
        // LIGHT theme. The app was authored dark (bg-slate-900 canvas, text-white),
        // so `slate` is inverted: high numbers = light surfaces, low numbers = dark text.
        slate: {
          50:  '#101828',   // near-black — headings / primary (replaces text-white)
          100: '#1d2939',   // strong text
          200: '#344054',   // primary body text
          300: '#475467',   // body text
          400: '#667085',   // secondary text
          500: '#98a2b3',   // muted / placeholder
          600: '#b6bdc9',   // very muted ("—")
          700: '#e6e8ef',   // hairline borders / dividers
          800: '#ffffff',   // cards / panels
          900: '#edeef4',   // canvas — cool lavender-grey (InvestX)
          950: '#ffffff',   // elevated (sidebar)
        },
        // InvestX signal green — vibrant, used prominently as the hero accent.
        indigo: {
          300: '#86efac',
          400: '#1eb854',   // accent text / icons on white — vibrant + readable
          500: '#22c55e',   // bright green (tints, charts, active)
          600: '#16a34a',   // primary buttons (white text, AA-large)
          700: '#15803d',
          800: '#166534',
          900: '#14532d',
        },
      },
      boxShadow: {
        'card': '0 1px 2px 0 rgba(16,24,40,0.04), 0 1px 3px 0 rgba(16,24,40,0.06)',
        'panel': '0 4px 16px -6px rgba(16,24,40,0.10)',
        'glow': '0 6px 16px -6px rgba(34,197,94,0.45)',
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
