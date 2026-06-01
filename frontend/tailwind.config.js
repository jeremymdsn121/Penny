/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        sloane: {
          DEFAULT: '#7C3AED',
          dark: '#6D28D9',
          light: '#EDE9FE',
          // brighter accent that holds up on dark surfaces
          bright: '#A78BFA',
        },
        // Semantic surface tokens (CSS variables defined in index.css), so the
        // same utility works in light + dark. e.g. bg-surface, text-content.
        surface: 'rgb(var(--surface) / <alpha-value>)',
        'surface-2': 'rgb(var(--surface-2) / <alpha-value>)',
        'surface-3': 'rgb(var(--surface-3) / <alpha-value>)',
        // "ink" = text colors. (Avoid the name "content" — it collides with
        // Tailwind's built-in content utilities and breaks @apply.)
        ink: {
          DEFAULT: 'rgb(var(--content) / <alpha-value>)',
          muted: 'rgb(var(--content-muted) / <alpha-value>)',
          subtle: 'rgb(var(--content-subtle) / <alpha-value>)',
        },
        hairline: 'rgb(var(--hairline) / <alpha-value>)',
      },
      boxShadow: {
        soft: '0 1px 2px 0 rgb(0 0 0 / 0.04), 0 4px 16px -4px rgb(0 0 0 / 0.08)',
      },
    },
  },
  plugins: [],
}
