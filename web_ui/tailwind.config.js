/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        cyan: { 400: '#38bdf8', 500: '#0ea5e9' },
        violet: { 400: '#a78bfa', 500: '#8b5cf6' },
      },
    },
  },
  plugins: [],
}
