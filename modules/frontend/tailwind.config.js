/** @type {import('tailwindcss').Config} */

// Every colour is an HSL triplet CSS variable defined in src/index.css, wrapped
// so opacity modifiers keep working (bg-success/10).
const c = (v) => `hsl(var(--${v}) / <alpha-value>)`

export default {
  darkMode: ['class'],
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Geist', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"Geist Mono"', 'Menlo', 'Monaco', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // UI scale used by the redesign (px / line-height)
        '2xs': ['11px', '15px'],
        xs:   ['12px', '16px'],
        sm:   ['12.5px', '18px'],
        base: ['13px', '19px'],
        md:   ['13.5px', '21px'],
        lg:   ['15px', '22px'],
        xl:   ['17px', '26px'],
        '2xl': ['22px', '28px'],
        '3xl': ['24px', '30px'],
      },
      colors: {
        border: c('border'),
        input: c('input'),
        ring: c('ring'),
        background: c('background'),
        foreground: c('foreground'),
        primary:     { DEFAULT: c('primary'),     foreground: c('primary-foreground') },
        secondary:   { DEFAULT: c('secondary'),   foreground: c('secondary-foreground') },
        destructive: { DEFAULT: c('destructive'), foreground: c('destructive-foreground') },
        muted:       { DEFAULT: c('muted'),       foreground: c('muted-foreground') },
        accent:      { DEFAULT: c('accent'),      foreground: c('accent-foreground') },
        popover:     { DEFAULT: c('popover'),     foreground: c('popover-foreground') },

        well: c('well'),
        panel: { DEFAULT: c('panel'), border: c('panel-border') },
        raised: { DEFAULT: c('raised'), 2: c('raised-2') },
        field: c('field'),
        hover: c('hover'),
        sidebar: { DEFAULT: c('sidebar'), active: c('sidebar-active') },
        line: c('line'),
        'border-strong': c('border-strong'),
        'border-hover': c('border-hover'),
        'canvas-dot': c('canvas-dot'),

        'text-2': c('text-2'),
        'text-3': c('text-3'),
        subtle: c('subtle'),
        faint: c('faint'),

        brand: { DEFAULT: c('brand'), text: c('brand-text') },
        success: c('success'),
        warning: c('warning'),
        danger: c('danger'),
        info: c('info'),
        violet: c('violet'),
      },
      borderRadius: {
        panel: '14px',   // floating panels
        card: '10px',    // cards inside panels, list rows, inputs
        control: '7px',  // buttons
        chip: '6px',     // segmented items, small icon buttons
        sm: '5px',
        md: '8px',
        lg: 'var(--radius)',
      },
      boxShadow: {
        node: 'var(--shadow-node)',  // workflow editor nodes
      },
      spacing: { gutter: '8px' },  // gap between floating panels
      keyframes: {
        // Plan 41 §3.5a — card entry animation. Cards fade+slide in when
        // they mount in a new column (status transition or initial load).
        // Short enough (150ms) not to feel heavy during a run with many
        // cards moving.
        'card-enter': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-dot': { '0%,100%': { opacity: '1' }, '50%': { opacity: '.35' } },
        'shimmer-x': { '0%': { transform: 'translateX(-100%)' }, '100%': { transform: 'translateX(250%)' } },
      },
      animation: {
        'card-enter': 'card-enter 0.15s ease-out both',
        'pulse-dot': 'pulse-dot 1.6s ease-in-out infinite',
        'shimmer-x': 'shimmer-x 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
