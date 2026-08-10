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
          50:  '#0f1419',   // near-black — headings / primary (replaces text-white)
          100: '#1a212b',   // strong text
          200: '#2c3440',   // primary body text
          300: '#414b58',   // body text
          400: '#67717f',   // secondary text
          500: '#8b95a3',   // muted / placeholder
          600: '#aab3bf',   // very muted ("—")
          700: '#e6e9ef',   // hairline borders / dividers
          800: '#ffffff',   // cards / panels
          900: '#eef1f6',   // canvas
          950: '#ffffff',   // elevated (sidebar)
        },
        // Emerald/green accent (replaces indigo) — the InvestX-style signal green.
        indigo: {
          300: '#86efac',
          400: '#15a34a',   // accent text / icons on white
          500: '#22c55e',   // bright green (tints, charts)
          600: '#16a34a',   // primary buttons (white text)
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
