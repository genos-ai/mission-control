# Plan — Mission Control UI redesign (handoff)

> **Status:** Ready to implement
> **Scope:** `frontend/` only. Visual and layout changes; no route, API or store contract changes except where noted in §9 (new data).
> **Visual reference:** `Mission Control - Redesign.dc.html` (open in a browser; Tweaks → Theme switches `dark` / `warm-white`; Tweaks → Start screen jumps to any screen).
> **Themes shipped:** `dark` (default) and `warm-white` (light). Both must be fully supported on every screen.

---

## 0. Summary of changes

| Area | Today | After |
|---|---|---|
| Palette | shadcn slate (`222 84% 5%` navy-black), cool | Neutral near-black (dark) / warm cream (light), one brand accent |
| Font | System stack 13px, Menlo mono | **Geist** 13px, **Geist Mono** for ids / costs / timestamps / tool names |
| Layout surfaces | Full-height 1px dividers, `border-b` header strips | **Floating panels**: rounded 14px panels on a darker "well", 8px gaps, no full-bleed rules |
| Global nav | 240px sidebar on Dashboard, 48px icon rail inside missions, 12-tab bar, 32px status bar | One 236px sidebar everywhere; active mission expands with grouped sub-nav; status bar removed (run indicator moves into sidebar footer) |
| Mission header | Name + brief + 5–6 buttons + tab bar | 52px breadcrumb bar: `Missions / name / Section` + status pill + plan pill + Pause / ⋯ / Run |
| Status display | Rectangular badges, many variants | Pill with dot (`StatusPill`), one colour per semantic state |
| Plan cards | Uppercase agent badge, hash id, status icon | Domain dot + agent, description, mono meta, **inline Approve / Reject** on proposed, inline Retry on failed, running shimmer bar |
| Theme | `class="dark"` hard-coded in `index.html` | `dark` / `warm-white` toggle, persisted, no flash |

---

## 1. Implementation order (one PR each)

1. **PR1 – Tokens, fonts, theme switch** (§2, §3) — app keeps working, just recolours.
2. **PR2 – UI primitives** (§4) — Button, Badge→StatusPill, Card→Panel, Segmented, IconTile, ProgressBar, Switch, Kbd.
3. **PR3 – Shell** (§5) — AppShell, Sidebar, MissionLayout header, remove StatusBar / tab bar.
4. **PR4 – Chat** (§6.4)
5. **PR5 – Plan board** (§6.5)
6. **PR6 – Runs + Run live** (§6.6, §6.7)
7. **PR7 – Workflow editor** (§6.9)
8. **PR8 – Dashboard, New mission, Overview, Login** (§6.1–6.3, §6.0)
9. **PR9 – Team, Narrative, Context, Knowledge, Artifacts, Console, Costs** (§6.8, §6.10–6.15)
10. **PR10 – Catalog, Admin** (§6.16, §6.17)
11. **PR11 – QA sweep** (§10)

Each PR must pass the §10 checklist in **both themes** before merge.

---

## 2. Design tokens

### 2.1 Replace `src/index.css`

All values are HSL triplets (no `hsl()` wrapper) so Tailwind opacity modifiers work (`bg-success/10`).
Existing shadcn variable names are **kept** so untouched components keep rendering; new variables are added below them.

```css
@import '@fontsource/geist/400.css';
@import '@fontsource/geist/500.css';
@import '@fontsource/geist/600.css';
@import '@fontsource/geist-mono/400.css';
@import '@fontsource/geist-mono/500.css';

@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  /* ───────────── Warm white (light) — also the :root fallback ───────────── */
  :root,
  .warm-white {
    /* shadcn-compatible names */
    --background: 36 35.7% 94.5%;          /* #f6f2ec  app root */
    --foreground: 32.7 19.3% 11.2%;        /* #221d17 */
    --card: 37.5 50% 96.9%;                /* #fbf8f3  = panel */
    --card-foreground: 32.7 19.3% 11.2%;
    --popover: 37.5 50% 96.9%;
    --popover-foreground: 32.7 19.3% 11.2%;
    --primary: 32.7 19.3% 11.2%;           /* #221d17  primary button bg */
    --primary-foreground: 40 60% 98%;      /* #fdfbf7 */
    --secondary: 36.9 37.1% 93.1%;         /* #f4efe7  = raised */
    --secondary-foreground: 32.7 19.3% 11.2%;
    --muted: 36.9 37.1% 93.1%;
    --muted-foreground: 32.7 11.7% 36.9%;  /* #695f53 */
    --accent: 37.9 32.2% 88.4%;            /* #ebe4d8  hover/selected bg (shadcn meaning) */
    --accent-foreground: 32.7 19.3% 11.2%;
    --destructive: 3.2 60% 49%;            /* #c83a32 */
    --destructive-foreground: 0 0% 100%;
    --border: 37.9 27.5% 86.5%;            /* #e6dfd3 */
    --input: 37.5 23.5% 80%;               /* #d8cfc0 */
    --ring: 21.3 62.3% 46.9%;              /* = brand */
    --radius: 0.625rem;                    /* 10px */

    /* surfaces */
    --well: 35.3 34.7% 90.4%;              /* #efe8de  behind floating panels */
    --panel: 37.5 50% 96.9%;               /* #fbf8f3 */
    --panel-border: 37.1 30.4% 86.5%;      /* #e7dfd2 */
    --raised: 36.9 37.1% 93.1%;            /* #f4efe7  inset blocks inside panels */
    --raised-2: 37.5 32% 90.2%;            /* #eee8de  progress tracks */
    --field: 40 60% 98%;                   /* #fdfbf7  inputs, secondary buttons */
    --hover: 36.9 35.1% 92.7%;             /* #f3eee6  row hover */
    --sidebar: 37.5 50% 96.9%;             /* #fbf8f3 */
    --sidebar-active: 37.9 32.2% 88.4%;    /* #ebe4d8 */
    --line: 37.1 25.3% 83.7%;              /* #e0d8cb  timeline connectors */
    --border-strong: 37.5 23.5% 80%;       /* #d8cfc0  input + secondary button border */
    --border-hover: 37.2 21.8% 73.9%;      /* #cbc0ae */
    --canvas-dot: 36.5 28.4% 84.1%;        /* #e2d9cb  workflow canvas grid */

    /* text */
    --text-2: 34.3 17.9% 15.3%;            /* #2e2820  body copy in messages */
    --text-3: 34.7 15.7% 23.7%;            /* #463e33  secondary emphasised */
    --subtle: 32.5 9.7% 48.6%;             /* #887d70  labels, meta, timestamps */
    --faint: 36 18.5% 68.2%;               /* #bdb19f  separators "/", disabled */

    /* brand + semantic */
    --brand: 21.3 62.3% 46.9%;             /* #c2622d  terracotta */
    --brand-text: 22.2 69% 39.2%;          /* #a9521f  brand on light bg (counts, links) */
    --success: 145.1 49.2% 36.3%;          /* #2f8a55 */
    --warning: 35.7 100% 32.9%;            /* #a86400 */
    --danger: 3.2 60% 49%;                 /* #c83a32 */
    --info: 200.7 73.2% 38%;               /* #1a77a8 */
    --violet: 261.1 53% 54.9%;             /* #7a4fc9 */

    color-scheme: light;
  }

  /* ───────────────────────────── Dark ───────────────────────────── */
  .dark {
    --background: 240 4.8% 4.1%;           /* #0a0a0b */
    --foreground: 240 5.9% 93.3%;          /* #ededef */
    --card: 240 6.3% 6.3%;                 /* #0f0f11 */
    --card-foreground: 240 5.9% 93.3%;
    --popover: 240 6.7% 5.9%;              /* #0e0e10 */
    --popover-foreground: 240 5.9% 93.3%;
    --primary: 240 5.9% 93.3%;             /* #ededef */
    --primary-foreground: 240 4.8% 4.1%;   /* #0a0a0b */
    --secondary: 240 6.1% 9.6%;            /* #17171a */
    --secondary-foreground: 240 5.9% 93.3%;
    --muted: 240 6.1% 9.6%;
    --muted-foreground: 240 4.4% 64.3%;    /* #a0a0a8 */
    --accent: 240 7.1% 11%;                /* #1a1a1e */
    --accent-foreground: 240 5.9% 93.3%;
    --destructive: 358.1 85.8% 64.1%;      /* #f2555a */
    --destructive-foreground: 0 0% 100%;
    --border: 240 6.7% 11.8%;              /* #1c1c20 */
    --input: 240 6.2% 15.9%;               /* #26262b */
    --ring: 229.8 100% 78%;

    --well: 240 6.7% 2.9%;                 /* #070708 */
    --panel: 240 6.3% 6.3%;                /* #0f0f11 */
    --panel-border: 240 6.3% 6.3%;         /* same as panel → invisible edge in dark */
    --raised: 240 6.1% 9.6%;               /* #17171a */
    --raised-2: 240 5.9% 10%;              /* #18181b */
    --field: 240 5.6% 7.1%;                /* #111113 */
    --hover: 240 7.7% 7.6%;                /* #121215 */
    --sidebar: 240 6.7% 5.9%;              /* #0e0e10 */
    --sidebar-active: 240 7.1% 11%;        /* #1a1a1e */
    --line: 240 6.7% 14.7%;                /* #232328 */
    --border-strong: 240 6.2% 15.9%;       /* #26262b */
    --border-hover: 240 6.1% 19.2%;        /* #2e2e34 */
    --canvas-dot: 240 7.5% 13.1%;          /* #1f1f24 */

    --text-2: 240 6.1% 87.1%;              /* #dcdce0 */
    --text-3: 240 5.8% 79.6%;              /* #c8c8ce */
    --subtle: 240 4% 43.7%;                /* #6b6b74 */
    --faint: 240 4.9% 23.9%;               /* #3a3a40 */

    --brand: 229.8 100% 78%;               /* #8fa2ff  periwinkle */
    --brand-text: 230.6 100% 82.5%;        /* #a6b4ff */
    --success: 153.1 60.2% 52.7%;          /* #3ecf8e */
    --warning: 37 91.3% 55.1%;             /* #f5a524 */
    --danger: 358.1 85.8% 64.1%;           /* #f2555a */
    --info: 200.4 100% 64.9%;              /* #4cc2ff */
    --violet: 259.3 100% 77.5%;            /* #b18cff */

    color-scheme: dark;
  }
}

@layer base {
  * { @apply border-border; }
  html, body, #root { height: 100%; }
  body {
    @apply bg-background text-foreground font-sans antialiased;
    font-size: 13px;
    font-feature-settings: 'ss01', 'cv11';
  }
  a { color: inherit; text-decoration: none; }
  a:hover { opacity: .85; }
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb {
    background: hsl(var(--subtle) / .35);
    border-radius: 10px; border: 3px solid transparent; background-clip: padding-box;
  }
}

@layer utilities {
  .tabular { font-variant-numeric: tabular-nums; }
}
```

Add the mono font package: `npm i @fontsource/geist-mono` (`@fontsource/geist` is already a dependency).

### 2.2 Replace `tailwind.config.js` `theme.extend`

```js
const c = (v) => `hsl(var(--${v}) / <alpha-value>)`

export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
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
        '2xl':['22px', '28px'],
        '3xl':['24px', '30px'],
      },
      colors: {
        border: c('border'), input: c('input'), ring: c('ring'),
        background: c('background'), foreground: c('foreground'),
        primary:     { DEFAULT: c('primary'),     foreground: c('primary-foreground') },
        secondary:   { DEFAULT: c('secondary'),   foreground: c('secondary-foreground') },
        destructive: { DEFAULT: c('destructive'), foreground: c('destructive-foreground') },
        muted:       { DEFAULT: c('muted'),       foreground: c('muted-foreground') },
        accent:      { DEFAULT: c('accent'),      foreground: c('accent-foreground') },
        popover:     { DEFAULT: c('popover'),     foreground: c('popover-foreground') },
        card:        { DEFAULT: c('card'),        foreground: c('card-foreground') },

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

        'text-2': c('text-2'), 'text-3': c('text-3'), subtle: c('subtle'), faint: c('faint'),

        brand: { DEFAULT: c('brand'), text: c('brand-text') },
        success: c('success'), warning: c('warning'), danger: c('danger'),
        info: c('info'), violet: c('violet'),
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
      spacing: { gutter: '8px' },  // gap between floating panels
      keyframes: {
        'card-enter': { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
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
```

> **Note on `darkMode: ['class']`** – keep it. `dark:` variants still key off `.dark`. Warm-white is the non-dark state, so `dark:` utilities written for the old theme keep working.

### 2.3 Token usage rules

| Use | Class |
|---|---|
| App root (behind sidebar + main) | `bg-background` |
| Main content area (behind panels) | `bg-well` |
| Floating panel | `bg-panel border border-panel-border rounded-panel` |
| Block **inside** a panel (message box, output item, plan card, list item, inspector field) | `bg-raised rounded-card` (no border) |
| Input / secondary button | `bg-field border border-border-strong` |
| Row hover | `hover:bg-hover` (dark) / same token in light |
| Selected nav item | `bg-sidebar-active text-foreground` |
| Body text | `text-foreground`; long-form message/report copy `text-text-2` |
| Secondary text | `text-muted-foreground` |
| Labels / meta / timestamps | `text-subtle` |
| Mono values (ids, costs, durations, tool names, versions) | `font-mono text-2xs`/`text-xs` + `tabular` |
| Brand highlight (progress fill, selection ring, count badges, toggles on) | `bg-brand`, `text-brand-text`, `ring-brand/15` |
| Status tint backgrounds | `bg-{success|warning|danger|info|violet|brand}/10`, text same hue |

**Never** use: full-height `border-r`/`border-l` between columns, `border-b` header strips across a panel, uppercase tracking-wide labels, raw hex colours, `slate-*`/`zinc-*`/`amber-*` Tailwind palette classes (replace with semantic tokens).

---

## 3. Theme switching

### 3.1 `src/stores/theme.ts` (new)

```ts
import { create } from 'zustand'

export type Theme = 'dark' | 'warm-white'
const KEY = 'mc.theme'
const THEMES: Theme[] = ['dark', 'warm-white']

function apply(theme: Theme) {
  const el = document.documentElement
  el.classList.remove(...THEMES)
  el.classList.add(theme)
}

export const useTheme = create<{ theme: Theme; setTheme: (t: Theme) => void; toggle: () => void }>((set, get) => ({
  theme: (localStorage.getItem(KEY) as Theme) || 'dark',
  setTheme: (theme) => { localStorage.setItem(KEY, theme); apply(theme); set({ theme }) },
  toggle: () => get().setTheme(get().theme === 'dark' ? 'warm-white' : 'dark'),
}))
```

### 3.2 `index.html` — no-flash boot

Replace `<html lang="en" class="dark">` with:

```html
<html lang="en">
  <head>
    <script>
      (function () {
        var t = localStorage.getItem('mc.theme') || 'dark';
        document.documentElement.classList.add(t);
      })();
    </script>
```

### 3.3 Toggle placement

- Sidebar footer, between the bell and log-out: icon button (`Sun` when dark, `Moon` when warm-white), title "Switch to light mode" / "Switch to dark mode".
- Login page: same icon button absolutely positioned `top-4 right-4`.
- Profile page: optional `Segmented` "Dark / Warm white".

### 3.4 Toaster

`App.tsx` `<Toaster toastOptions={{ className: 'bg-panel text-foreground border border-panel-border rounded-card shadow-lg text-sm' }} />`

---

## 4. UI primitives (`src/components/ui/`)

### 4.1 `button.tsx` — replace variants

```ts
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40',
  {
    variants: {
      variant: {
        default:     'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary:   'bg-field text-foreground border border-border-strong hover:bg-hover',
        outline:     'bg-field text-foreground border border-border-strong hover:bg-hover', // alias, keeps old call-sites working
        ghost:       'text-muted-foreground hover:bg-raised hover:text-foreground',
        destructive: 'bg-danger/10 text-danger border border-danger/30 hover:bg-danger/15',
        pill:        'bg-raised text-text-3 rounded-full hover:text-foreground',
        link:        'text-brand-text underline-offset-4 hover:underline',
      },
      size: {
        sm:   'h-[26px] px-2.5 text-xs rounded-chip',
        default: 'h-[30px] px-3 text-sm rounded-control',
        lg:   'h-[34px] px-3.5 text-base rounded-control',
        xl:   'h-[38px] px-4 text-md rounded-md',    // login / forms
        icon: 'h-[30px] w-[30px] rounded-control',
        'icon-sm': 'h-6 w-6 rounded-chip',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)
```

Icons inside buttons: 13px (`h-[13px] w-[13px]`), stroke default. Remove `mr-1.5` from icons at call-sites (gap handles it).

**Important:** "Stop plan" / "Cancel run" use `destructive` (tinted), not solid red.

### 4.2 `status-pill.tsx` (new) — replaces most `Badge` usage for state

```tsx
type Tone = 'success' | 'warning' | 'danger' | 'info' | 'brand' | 'violet' | 'neutral'
const tone: Record<Tone, string> = {
  success: 'bg-success/10 text-success',
  warning: 'bg-warning/10 text-warning',
  danger:  'bg-danger/10 text-danger',
  info:    'bg-info/10 text-info',
  brand:   'bg-brand/10 text-brand-text',
  violet:  'bg-violet/10 text-violet',
  neutral: 'bg-raised text-muted-foreground',
}
export function StatusPill({ tone: t = 'neutral', dot = true, pulse, children, className }: {...}) {
  return (
    <span className={cn('inline-flex h-5 items-center gap-1.5 rounded-full px-2 text-xs font-medium whitespace-nowrap', tone[t], className)}>
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full bg-current', pulse && 'animate-pulse-dot')} />}
      {children}
    </span>
  )
}
```

Keep `badge.tsx` for non-state labels (`platform`, `v3`, artifact type) but restyle:
`default: 'bg-raised text-muted-foreground'`, `outline: 'border border-border-strong text-muted-foreground'`, base `h-[18px] px-1.5 rounded-sm text-2xs font-medium`. Version badges use `font-mono`.

### 4.3 `card.tsx` → `Panel`

```tsx
export const Panel = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(({ className, ...p }, ref) => (
  <div ref={ref} className={cn('rounded-panel border border-panel-border bg-panel', className)} {...p} />
))
export const PanelHeader = ({ title, meta, actions, className }: {...}) => (
  <div className={cn('flex items-center gap-2 px-4 pt-3.5 pb-2', className)}>
    <span className="text-base font-medium">{title}</span>
    {meta && <span className="text-xs text-subtle">{meta}</span>}
    {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
  </div>
)
```

- Keep `Card*` exports as thin aliases of `Panel` (so existing pages compile) — `Card = Panel`, `CardHeader` → `px-4 pt-3.5 pb-2`, `CardTitle` → `text-base font-medium` (not `text-2xl`), `CardContent` → `px-4 pb-4`.
- **No `border-b` under panel headers.** Where a list inside a panel needs separation, use `divide-y divide-border/60` on rows, or `gap-1.5` between `bg-raised` blocks.

### 4.4 `segmented.tsx` (new)

```tsx
export function Segmented<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string; count?: number }[]
}) {
  return (
    <div className="flex shrink-0 rounded-md bg-raised p-0.5">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={cn('flex h-6 items-center gap-1.5 rounded-chip px-2.5 text-xs whitespace-nowrap',
            o.value === value ? 'bg-panel text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground')}>
          {o.label}
          {o.count != null && <span className="font-mono text-2xs text-subtle">{o.count}</span>}
        </button>
      ))}
    </div>
  )
}
```

Used for: dashboard mission filter, plan gate mode, costs range, narrative filter, console category, catalog type, profile theme.

### 4.5 `icon-tile.tsx` (new) — avatar for agents / step types

```tsx
export function IconTile({ icon: Icon, tone = 'neutral', size = 'md', shape = 'round', live }: {...}) {
  // size: sm 24px / md 28px / lg 32px ; icon 12/14/15px
  // shape: 'round' (agents, chat) | 'square' (workflow step types: rounded-md)
  // tone → bg-{tone}/12 text-{tone}; neutral → bg-raised text-muted-foreground
  // live → 8px dot bottom-right in tone colour with 2px ring of the parent surface colour
}
```

Agent → tone mapping (replaces `chat-constants.ts` icon colours):

| Agent / domain | Icon (lucide) | Tone |
|---|---|---|
| `mission.director` / director | `Brain` | brand |
| `research.*` | `Bot` / `Search` | warning |
| `security.*` | `Shield` | danger |
| `software.*` | `Layers` / `ShieldCheck` | info |
| `system.planning` | `ListTodo` | neutral |
| `system.synthesis` | `Sparkles` | violet |
| `system.verification` | `CheckCircle2` | success |
| writer / other | `FileText` | success |

### 4.6 Other small primitives

- `progress.tsx`: `h-[3px]` (cards) or `h-1` (tables) `rounded-full bg-raised-2`, fill `bg-brand` (budget), `bg-success` (plan progress), `bg-warning` (running run).
- `switch.tsx`: track `h-4 w-7 rounded-full`, on `bg-brand`, off `bg-border-strong`; knob `h-3 w-3 rounded-full bg-white` (white in **both** themes).
- `kbd.tsx`: `font-mono text-2xs border border-border-strong rounded px-1.5 text-muted-foreground`.
- `input.tsx` / `textarea.tsx`: `h-[38px] rounded-md bg-field border border-border-strong px-3 text-md placeholder:text-subtle focus:border-brand/60 focus:ring-2 focus:ring-brand/15 outline-none`. Inside panels (inspector fields) use `bg-raised border-panel-border rounded-card`.
- `stat-card.tsx`: `Panel` with `p-4 flex flex-col gap-2`; label `text-xs text-subtle`; value `text-3xl font-medium tracking-[-0.03em]`; sub `text-xs text-subtle`.
- `empty-state.tsx`: centered, `IconTile size=lg`, title `text-md text-muted-foreground`, body `text-sm text-subtle`, optional action button.
- `spinner.tsx`: `Loader2 animate-spin text-subtle`.

---

## 5. Shell

### 5.1 `components/layout/app-shell.tsx`

```tsx
<div className="flex h-screen min-h-[640px] overflow-hidden bg-background text-foreground">
  <Sidebar />
  <main className="flex min-w-0 flex-1 flex-col bg-well">
    <Outlet />
  </main>
</div>
```

- **Delete `<StatusBar />`** and `status-bar.tsx` (its info moves to the sidebar run indicator, §5.2).
- Pages that are "documents" (Dashboard, New mission, Catalog, Profile, Admin, mission Overview/Team/Narrative/Knowledge/Runs/Costs) render a top bar (§5.3) then `<div className="flex-1 overflow-auto"><div className="mx-auto max-w-[1160px] px-8 pb-10 pt-1 flex flex-col gap-3">…</div></div>`.
- Pages that are "workspaces" (Chat, Plan, Run live, Workflow editor, Context, Artifacts, Console) render a top bar then `<div className="flex min-h-0 flex-1 gap-gutter px-2 pb-2">…panels…</div>`.

### 5.2 `components/layout/sidebar.tsx` — rewrite

Width **236px**, `bg-sidebar border-r border-border` (the only full-height rule in the app), `flex flex-col`.
**Remove the 48px collapsed rail** used inside missions — the sidebar is identical on every route.

Structure top → bottom:

1. **Brand row** `h-[52px] px-3.5 flex items-center gap-2.5`: 22px rounded-md tile `bg-primary text-primary-foreground font-mono text-[8.5px] font-semibold` "MC" + `text-md font-semibold tracking-tight` "Mission Control".
2. **Search / jump** (`px-2.5 pb-1.5`): `h-8 rounded-md bg-raised border border-panel-border px-2.5 text-sm text-subtle` with `Search` 14px, "Search or jump to…", `<Kbd>⌘K</Kbd>`. (Opens existing command palette if any; otherwise a TODO stub — out of scope.)
3. **Primary nav** (`nav flex-1 overflow-y-auto overflow-x-hidden px-2.5 pt-1.5 pb-3 flex flex-col gap-px`):
   - `Home` (`LayoutDashboard`/`Home`), `Catalog` (`BookOpen`), `Admin` (`Shield`, admin only).
   - Item: `h-[30px] shrink-0 flex items-center gap-2.5 px-2.5 rounded-[7px] text-base`, inactive `text-muted-foreground hover:text-foreground`, active `bg-sidebar-active text-foreground`. Icons 15px stroke 1.75.
4. **Missions section** label row `pt-[18px] pb-1.5 px-2.5 text-xs font-medium text-subtle flex justify-between` with `+` icon button → `/missions/new`.
   - One row per mission (same item style): 7px status dot (active `bg-success`, paused `bg-warning`, other `bg-muted-foreground/35`) · name (truncate) · optional pending-approval count `min-w-[18px] h-[18px] rounded-full bg-brand/15 text-brand-text font-mono text-2xs` (§9.1).
   - **Active mission expands** a sub-nav: `ml-[17px] pl-[9px] border-l border-line flex flex-col gap-px my-0.5 mb-1.5`. Items `h-[27px] shrink-0 px-2 rounded-chip text-sm gap-2.5`, icons 14px. Groups separated by `mt-2` on the group's first item:
     - **Work:** Overview `Activity`, Chat `MessageSquare`, Plan `Kanban` (+ pending count in `text-brand-text font-mono text-2xs`), Runs `ListChecks`, Artifacts `Package`
     - **Setup:** Team `Users`, Workflows `GitBranch`, Context `FileText`, Knowledge `Lightbulb`
     - **Observe:** Narrative `Radio`, Costs `DollarSign`, Console `Terminal`
   - Use `NavLink` with the existing routes (`/missions/:id/<tab>`). Keep the `missions.lastTab.<id>` localStorage write.
5. **Footer** (`border-t border-border p-2.5 flex flex-col gap-1.5`):
   - **Run indicator** (only if `useExecutions` has ≥1 running): `rounded-[7px] bg-raised border border-panel-border px-2.5 py-[7px] text-xs text-text-3 flex items-center gap-2` → pulsing 7px `bg-warning` dot · "1 run in progress" / "N runs in progress" · elapsed `font-mono text-2xs text-subtle`. Click → the run's `runs/:runId`.
   - **User row**: 26px round avatar `bg-line text-text-3 text-[10.5px] font-semibold` initials · name `text-sm font-medium` / role `text-2xs text-subtle` · bell icon button (existing `NotificationDropdown`, unread dot `bg-brand` 6px with `ring-[1.5px] ring-sidebar`) · **theme toggle** · log-out (hover `text-danger`). Settings/profile is reached by clicking the user name.

Optional (behind a constant `NAV_STYLE = 'sidebar' | 'tabs'`): keep the tab layout as a floating pill bar under the top bar (`mx-2 mb-2 px-2.5 rounded-panel bg-panel border border-panel-border flex gap-0.5`, tabs `px-2 py-[11px] text-sm border-b-[1.5px]`). Default **sidebar**; the tab bar is only for teams who want it.

### 5.3 Top bar (`components/layout/top-bar.tsx`, new)

`header h-[52px] shrink-0 flex items-center gap-3 px-5` — **no bottom border**, sits on `bg-well`.

- **Left:** breadcrumb `flex items-center gap-2 text-base min-w-0 overflow-hidden`. Segments `text-muted-foreground` (clickable), last `text-foreground font-medium`, separator `/` `text-faint`. Each segment `truncate`.
  - Home: `Home` · New: `New mission` · Catalog / Admin: single segment
  - Mission: `Missions / {name} / {Section}` (+ `/ {runId8}` on Run live) followed by `StatusPill` for mission status (`shrink-0`).
- **Right** (`ml-auto flex items-center gap-2 shrink-0 whitespace-nowrap`):
  - Mission: plan pill when plan is autonomous/running — `h-[26px] rounded-full border border-warning/25 bg-warning/5 text-warning text-xs px-2.5 gap-1.5` with spinning `Loader2` 12px and "Plan running · 2 of 8" (below 1100px viewport: just "2/8"). Background tasks (`bgTaskCount`) fold into this pill's tooltip.
  - `Pause` / `Resume` (secondary) · `⋯` icon button (opens existing `MissionSettingsDrawer`; Archive moves into its menu) · `Run` (primary, opens existing `RunModal`).
  - "Stop plan" moves to the Plan screen toolbar (§6.5).
  - Dashboard: `New mission` primary button.

### 5.4 `pages/mission/layout.tsx` changes

- Delete the header block (name/brief/buttons) and the **tab bar** `<div className="flex border-b px-4">…`. Render `<TopBar …/>` then `<div className="min-h-0 flex-1 overflow-y-auto"><Outlet/></div>`.
- The **brief** moves to the Overview page (§6.3) where `InlineBrief` is reused.
- Keep SSE context, settings drawer (restyle: `bg-panel border-l border-panel-border rounded-l-panel`, backdrop `bg-background/60 backdrop-blur-sm`), RunModal.
- Keep `tabs` array but restructure into the three groups (export it from `lib/constants.ts` so Sidebar can import it).

---

## 6. Screens

Notation: **P** = `Panel` (`rounded-panel bg-panel border border-panel-border`). **R** = raised block (`rounded-card bg-raised`). Breakpoints are **viewport** widths (`min-[960px]:`, etc.).

### 6.0 Login — `pages/login.tsx`
- Full-screen `bg-background`, centered column `max-w-[360px] w-full flex flex-col gap-7`.
- 32px rounded-[9px] `bg-primary text-primary-foreground font-mono text-[11px]` "MC" tile; H1 `text-2xl font-semibold tracking-[-0.02em]` "Sign in to Mission Control"; sub `text-md text-muted-foreground`.
- Email / Password: label `text-sm font-medium text-text-3`, input xl (§4.6). Sign-in `Button size="xl"` full width.
- Dev quick login: divider with centered `text-2xs text-subtle` "Development quick login"; 3-col grid of secondary buttons (`h-[34px]`) each prefixed by a 6px role dot (sysadmin `bg-danger`, admin `bg-warning`, user `bg-subtle`).
- Theme toggle top-right (§3.3).

### 6.1 Dashboard — `pages/dashboard.tsx`
Document layout. Top bar: `Home` + `New mission`.
1. Greeting: H1 `text-3xl font-semibold tracking-[-0.025em]` "Good morning, {first}" (time-of-day aware) + `text-md text-muted-foreground` summary "3 missions active · 1 run in progress · 2 tasks waiting on you".
2. **Needs your attention** (§9.1) — section label `text-xs font-medium text-subtle`, then one **P** with `divide-y divide-border/60` rows: `IconTile sm square` (proposed tasks: brand `Check`; human input: warning `User`) · title `text-base` + sub `text-xs text-subtle` (mission · detail) · age `font-mono text-2xs text-subtle` · secondary `sm` button "Review"/"Respond". Row hover `bg-hover`. Hidden when empty.
3. **Missions**: label row with `Segmented` All / Active / Paused / Archived (+counts). Grid `grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3`.
   - Card = **P** `p-4 flex flex-col gap-3.5 hover:border-border-hover cursor-pointer`: name `text-md font-medium` · `platform` badge (outline warning) · `StatusPill` right · description `text-base text-muted-foreground line-clamp-2 min-h-[38px]` · footer: "`$212.40` of $500" (mono spent in `text-text-3`) left, last activity right ("Running now", "2h ago"), then 3px progress `bg-brand` (§9.2).
   - Archive/Delete move to a `⋯` menu on hover (top-right), not always-visible icons.
   - Last tile: dashed "New mission" tile `border border-dashed border-border-strong rounded-panel min-h-[150px] text-subtle hover:text-foreground`.

### 6.2 New mission — `pages/mission/new.tsx`
Document layout, `max-w-[600px]`.
- Stepper: "1 Details — 2 Team" (18px circles; active `bg-primary text-primary-foreground`, upcoming `border border-border-x`). Step 2 is the existing team picker if present; otherwise just show step 1 and drop the stepper.
- H1 "New mission", sub "Give agents a purpose and a budget. You'll pick the team next."
- Fields (gap 5): **Name** — input with `missions/` mono prefix, mono value, live validation `^[a-z][a-z0-9_-]*$` (help text turns `text-danger`); **Description**; **Brief · optional** textarea (5 rows) + help; 2-col grid **Budget ceiling** (`$` prefix, `USD` suffix, placeholder "No limit") and **Repository · optional**.
- Footer `border-t border-border pt-5 flex justify-end gap-2`: Cancel (secondary) · "Continue to team →" / "Create mission" (primary).

### 6.3 Overview — `pages/mission/overview.tsx`
Document layout.
1. **Brief**: label `text-xs text-subtle` "Brief" + `InlineBrief` rendered at `text-xl leading-[26px] tracking-[-0.01em] max-w-[760px]` (editable for owner).
2. **Facts strip**: one **P** `grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))]` cells `px-4 py-3.5` separated by `border-l border-border/60` — Status · Environment · Budget (`$212 / $500`) · Agents · Workflows. Label `text-xs text-subtle`, value `text-[18px] font-medium tracking-[-0.02em]`.
3. **Active run card** (if running — reuse `components/mission/active-run-card.tsx`, restyle): `rounded-panel border border-warning/25 bg-warning/[0.03] p-4 flex flex-col gap-3.5`: pulsing dot · "Run in progress" · run id mono · elapsed + cost mono right · chevron; 3px progress `bg-warning`; current step line: `Wrench` · agent · `→` · tool (mono `text-warning`) · "Step 3 of 7". Whole card links to Run live.
4. Two-column `grid-cols-[repeat(auto-fit,minmax(340px,1fr))] gap-4`:
   - **Recent runs** P: header "Recent runs" + "View all" link; 4 rows `px-4 py-2.5 text-sm`: status icon · id mono · workflow name (truncate) · cost mono · relative time.
   - **Team** P: header "Team" + "6 agents"; rows: `IconTile sm` · name · live state right (`Planning` brand, tool name warning, `Done` success, `Idle` subtle) (§9.3).

### 6.4 Chat — `pages/mission/tabs/chat-tab.tsx` (+ `chat-conversation.tsx`, `chat-artifacts-panel.tsx`)
Workspace layout: `flex h-full gap-gutter px-2 pb-2`.

- **Roster P** `w-[228px] shrink-0 hidden min-[960px]:flex flex-col px-2 py-3 gap-0.5 overflow-y-auto`:
  - Label `px-2 pb-2 text-xs text-subtle` "Talk to". Director pinned first.
  - Row `flex items-start gap-2.5 p-2 rounded-card hover:bg-raised`, selected `bg-sidebar-active`: `IconTile sm round` with `live` dot when working · name `text-sm` truncate · sub `text-2xs` (role, or current tool in tone colour, or "Idle" `text-subtle`). Non-chat task agents `opacity-55 cursor-default`.
  - Replace the current "Team" `border-b` header and the separate pinned-director strip.
- **Conversation P** `flex-1 min-w-[320px] flex flex-col overflow-hidden`:
  - Header `h-12 px-5 pt-1 flex items-center gap-2.5` (no border): agent name `text-base font-medium` · **thread picker pill** `h-6 rounded-full bg-raised px-2.5 text-xs text-muted-foreground` "Mission Chat · today 08:14 ▾" · right: pill button "+ New thread".
  - Messages `flex-1 overflow-y-auto` inner `max-w-[720px] mx-auto px-6 py-7 flex flex-col gap-[18px]`:
    - **User**: right-aligned bubble `max-w-[82%] rounded-[14px_14px_4px_14px] bg-active border border-line px-3.5 py-2.5 text-md`.
    - **Agent**: `IconTile sm` + column: name `text-xs font-medium` + `font-mono text-2xs text-subtle` "08:14 · $0.0184"; body `text-md text-text-2` (markdown via existing renderer); artifact attachment as **R** `max-w-[380px] flex items-center gap-2.5 px-3 py-2.5` with violet `IconTile` + title + "Report · 1,240 words" + `ArrowUpRight`.
    - **Event lines** (thinking / tool call / run started / artifact found): `pl-9 flex items-center gap-2 text-xs text-subtle` icon (tone) · text · tool name mono in tone · `flex-1 h-px bg-border/60` · timestamp mono. Replaces the boxed `bg-muted/30` event rows.
  - **Composer** `px-6 pb-5`: **R** `max-w-[720px] mx-auto rounded-panel px-3.5 pt-3 pb-2.5 flex flex-col gap-2` (border `border-panel-border`): borderless textarea 2 rows · footer `text-xs text-subtle`: `<Kbd>/</Kbd>` "commands" · "⌘↵ to send" right · 28px send button `rounded-[7px] bg-primary text-primary-foreground` (`bg-faint` when empty), icon `ArrowUp`. Keep slash-command popover.
- **Outputs P** `w-[288px] shrink-0 hidden min-[1200px]:flex flex-col`:
  - Header `h-12 px-4 pt-1` "Outputs" + count + collapse icon `PanelRightClose`.
  - Items **R** `rounded-card overflow-hidden`: top row `px-3 py-2.5` `Zap` warning · tool name mono `text-xs` · time mono; result preview `px-3 pb-2.5 font-mono text-2xs leading-[17px] text-muted-foreground whitespace-pre-wrap`.
- Remove all `border-r`/`border-l`/`border-b h-9` strips from the current 3-panel layout; `use-resizable` drag handles may stay but must be invisible until hover (`hover:bg-brand/30 w-1`).

### 6.5 Plan — `pages/mission/tabs/plan-tab.tsx`, `components/workspace/plan-board*.tsx`
Workspace layout, vertical: `flex flex-col h-full gap-gutter px-2 pb-2`.

- **Toolbar P** (`plan-board-top-bar.tsx`) `px-3.5 py-2.5 flex items-center gap-3.5 flex-wrap`:
  - "Plan" `text-base font-medium` + version badge mono outline `v3`
  - Gate mode `Segmented`: Manual / AI-assisted / Autonomous (maps to existing `manual | ai_assisted | autonomous`)
  - Progress: 96px `h-1` track, fill `bg-success`, mono "2 of 8"
  - Right: "Refine with Director" (secondary, `Sparkles`) · "Stop plan" (destructive tinted, `Square` icon) / "Resume plan" · "Run approved" (primary) when applicable.
- **Board**: `flex-1 overflow-auto` → `grid grid-cols-4 gap-gutter min-w-[1040px] min-h-full items-stretch`.
- **Column P** `flex flex-col gap-2 px-2.5 py-3`:
  - Header `px-1 pb-1 flex items-center gap-2`: icon (Proposed `CircleDashed` muted · Approved `Circle` brand · Running `Loader2` warning · Done `CheckCircle2` success) · label `text-sm font-medium` · count mono `text-subtle`. **Done column also holds failed tasks.** (Skipped/vetoed can live in Done with muted styling.)
  - "+ Add task" ghost row at the bottom of each column (`h-[34px] rounded-md text-xs text-subtle hover:bg-raised`).
  - Drag-and-drop (`@hello-pangea/dnd`) unchanged; drop-target highlight `ring-2 ring-brand/30`.
- **Task card** (`plan-board-task-card.tsx`) = **R** `rounded-card p-3 flex flex-col gap-2.5 relative overflow-hidden border` with border:
  - running `border-warning/35`, failed `border-danger/30`, else `border-panel-border`.
  - Row 1 `text-2xs text-muted-foreground flex items-center gap-1.5`: 7px square `rounded-[2px]` **domain dot** (tone per §4.5) · agent name · right: veto-countdown chip (approved + countdown) `h-[18px] rounded-sm bg-warning/10 text-warning font-mono text-[10.5px]` with `Clock` "42s".
  - Description `text-base leading-[19px] text-pretty`.
  - Running: tool line `font-mono text-2xs text-warning` with `Wrench` "cluster_indicators".
  - Failed: reason `text-xs text-danger`.
  - Footer `font-mono text-[11px] text-subtle flex items-center gap-2.5`: short id `3c9e…` · deps `GitMerge` "1 dep" · cost/duration "$0.0412 · 38s" · spacer · actions:
    - **Proposed:** icon button `X` (secondary sm, hover `text-danger`) "Reject" + primary sm "✓ Approve" — calls existing approve/reject mutations directly (no detail panel needed).
    - **Failed:** secondary sm "↺ Retry".
  - Running: 2px bottom bar `bg-warning/12` with 40% `bg-warning` segment `animate-shimmer-x`.
  - Remove: uppercase agent badges, `MoreVertical` always-visible (show on hover only), hash on its own line.
- Detail panel (`plan-board-detail-panel.tsx`) opens as a right **P** `w-[360px]` inside the same gutter row, not a full-height bordered drawer.

### 6.6 Runs — `pages/mission/tabs/runs-tab.tsx`, `components/workspace/runs-panel.tsx`
Document layout.
- Filter chips row: pill buttons `h-7 rounded-full border px-2.5 text-xs` (selected `bg-raised border-border-hover text-foreground`, else `border-border-card text-muted-foreground`) — All / Running / Completed / Failed with mono counts.
- Table in **P** `overflow-x-auto`; header + rows share `grid grid-cols-[104px_84px_minmax(120px,1fr)_118px_70px_72px] gap-3 min-w-[640px]`:
  - Header `px-4 py-2.5 text-2xs text-subtle`: Status · Run · Workflow · Started · Duration (right) · Cost (right)
  - Rows `px-4 py-[11px] text-sm border-t border-row hover:bg-hover cursor-pointer`: status icon+label in tone · id mono `text-text-3` · workflow (truncate) · started `text-muted-foreground` · duration mono right · cost mono right.
  - Status: completed `CheckCircle2` success · failed `XCircle` danger · running `Loader2` warning · cancelled `CircleSlash` subtle.

### 6.7 Run live — `pages/mission/run-live.tsx`, `components/live/*`
Workspace layout, vertical.
- **Summary P** `px-[18px] py-2.5 flex items-center gap-6 flex-wrap`: pulsing 8px dot · workflow name `text-md font-medium` · run id mono `text-subtle` · stats inline (label `text-xs text-subtle` + value `font-mono text-base font-medium`): Elapsed · Cost · Tokens · Steps "2 / 7" · right: "Cancel run" destructive tinted.
- Row `flex-1 flex gap-gutter`:
  - **Activity P** (`live-activity-panel.tsx`) `w-[360px] overflow-y-auto p-5`: label "Activity"; vertical timeline — 22px circle `border bg-panel` with icon (done `Check` success ring `success/35`; running `Loader2` warning ring `warning/45`; pending `Circle` subtle ring `border-strong`), 1px connector `bg-line`; title `text-base` (pending in `text-muted-foreground`) + right meta mono (duration) + agent/tool `text-xs text-subtle`.
  - **Result P** (`live-results-panel.tsx`) `flex-1 overflow-y-auto` inner `max-w-[720px] mx-auto px-8 pt-7 pb-12`: status row "Streaming result" + right "● writing" warning; H2 `text-[20px] font-semibold tracking-[-0.02em]`; section labels `text-xs font-medium text-subtle`; paragraphs `text-[14px] leading-[23px] text-text-2`; streaming skeleton lines `h-3 rounded bg-raised`.
- Remove `live-footer.tsx` bordered bar (stats moved to Summary P). Panel toggle buttons stay as icon buttons in the Summary P.

### 6.8 Workflows list — `pages/mission/tabs/workflows-tab.tsx`, `components/workspace/workflows-panel.tsx`
Document layout. Grid of **P** cards (`minmax(300px,1fr)`): `IconTile square` `GitBranch` · name · trigger summary (cron in human words via `lib/cron.ts`) · steps count · last run `StatusPill` · actions on hover (Edit, Run, Schedule). Top-right primary "New workflow".

### 6.9 Workflow editor — `pages/mission/workflow-edit.tsx`, `components/workflow/*`
Workspace layout, vertical.
- **Toolbar P** (`workflow-editor-toolbar.tsx`) `py-2 pl-4 pr-2.5 flex items-center gap-3`: name `text-base font-medium` · "7 steps · edited 2m ago" `text-xs text-subtle` · right: Schedule (secondary, `Clock`) · Save (secondary) · "Run workflow" (primary).
- Row `flex-1 flex gap-gutter`:
  - **Palette P** (`node-palette.tsx`) `w-[220px] px-2 py-3.5 hidden min-[1100px]:flex flex-col gap-0.5`: label "Add step"; items `p-2 rounded-card hover:bg-raised cursor-grab flex gap-2.5`: `IconTile sm square` (keep the existing per-type colours from `workflow-editor-types.ts`) · label `text-sm` + description `text-2xs text-subtle`.
  - **Canvas P** `flex-1 min-w-[360px] overflow-hidden` — React Flow (`@xyflow/react`): `<Background variant="dots" gap={20} size={1} color="hsl(var(--canvas-dot))" />`, wrapper `bg-panel`. Edges `stroke: hsl(var(--border-hover)); strokeWidth: 1.5`; running edge `hsl(var(--warning) / .6)`. Controls/minimap restyled `bg-panel border-panel-border rounded-card`.
  - **Node** (`workflow-editor-node.tsx`): `rounded-[12px] bg-raised border px-3 py-2.5 flex items-center gap-2.5 shadow-[0_1px_2px_rgba(0,0,0,.4)]` (light theme: `shadow-sm`); border `border-panel-border`, selected `border-brand ring-[3px] ring-brand/15`, running `border-warning/45`. `IconTile` 26px square · title `text-sm font-medium` truncate · sub `font-mono text-2xs text-subtle` (agent id / tool / trigger). Fork/Join nodes narrower (120px). Handles 8px `bg-border-hover`, hover `bg-brand`.
  - **Inspector P** (`step-detail.tsx`) `w-[300px] hidden min-[960px]:flex flex-col overflow-y-auto`: header `px-4 pt-4 pb-1` IconTile + step title + type `text-xs text-subtle`; body `p-4 flex flex-col gap-4`: labelled fields (`text-xs text-muted-foreground` labels) using inspector inputs (§4.6, mono for agent id and prompt); variable tokens `{{steps.x.output}}` highlighted `text-brand-text` (existing `variable-autocomplete.tsx`); toggles (`Switch`) for Pass context / Retry on failure / Require approval; Timeout.

### 6.10 Team — `pages/mission/team.tsx`
Document layout.
- Header row: title "Team" `text-lg font-semibold` + sub "6 agents · 4 can chat · each agent gets the mission brief plus its own instructions"; right: "Browse catalog" (secondary → `/catalog`) + "Add agent" (primary).
- Grid `minmax(340px,1fr) gap-gutter` of **P** `p-4 flex flex-col gap-3`:
  - `IconTile lg round` · name `text-md font-medium` + role `text-xs text-subtle` · `Switch` (enabled/disabled; disabled card `opacity-60`).
  - Mission prompt **R** `px-3 py-2.5 text-sm text-text-3 min-h-[58px]` (click to edit inline — existing edit flow).
  - Footer: capability pills `h-[22px] rounded-full bg-raised text-2xs text-muted-foreground` · `prompt v3` mono `whitespace-nowrap` · `History` icon button (opens `prompt-history-panel.tsx`) · `Trash2` (hover `text-danger`).
- Empty state: `EmptyState` "No agents yet" + "Add all agents".

### 6.11 Narrative — `pages/mission/tabs/narrative-tab.tsx`, `components/research/narrative-feed.tsx`
Document layout, `max-w-[820px]`.
- Header: "Narrative" + "The mission's story so far, in plain language"; right `Segmented` All / Agents / Runs / Decisions.
- One **P** per run/session `px-5 py-[18px]`: header title + mono meta (run id · start · duration · cost) + `StatusPill` right.
- Timeline items: 20px round tinted icon + connector `bg-line`; sentence `text-md text-text-2` with **actor in `font-medium text-foreground`**; timestamp mono right; optional excerpt **R** `px-3 py-2.5 text-sm text-muted-foreground`.

### 6.12 Context — `pages/mission/tabs/context-tab.tsx`, `components/workspace/context-panel.tsx`
Workspace layout, horizontal.
- **Main P** `flex-1 flex flex-col`: header `px-5 pt-3.5 pb-1.5` "Mission context" `text-md font-semibold` + "Shared memory every agent reads. Builds automatically as tasks finish." ; right: version badge mono `v12`, size mono "18.4 / 32 KB", 80px `h-1` bar (`bg-warning` > 50%, `bg-danger` > 85%).
- Sections as collapsible **R** `rounded-card` blocks (`gap-2`): header `px-3.5 py-[11px]` chevron · title `text-base font-medium` · count · right "by {agent} · {time}" `text-2xs text-subtle`; body bullets `pl-[38px] pr-3.5 pb-3.5 text-base text-text-2`.
- **History P** `w-[300px] hidden min-[960px]:flex`: "Change history"; rows `p-2 rounded-md hover:bg-raised`: `IconTile sm` · "**agent** updated Section" · mono "v12 · 08:16 · +1.2 KB". Click → diff (existing behaviour if any).

### 6.13 Knowledge — `pages/mission/tabs/knowledge-tab.tsx`, `components/knowledge/intent-strip.tsx`
Document layout.
- **Intent P** `px-5 py-[18px] flex gap-3.5`: `IconTile lg` brand `Target` · label "Mission intent" + "set by Director · today 08:14" · statement `text-lg leading-[23px]`.
- Two columns `minmax(360px,1fr)`:
  - **Learnings P**: header "Learnings" + count; items **R** `px-3.5 py-3 flex flex-col gap-2`: type pill (tinted, icon) — Failure pattern (danger `ShieldAlert`), Success pattern (success `TrendingUp`), Anti-pattern (warning `ShieldAlert`), Retry strategy (info `Zap`), Capability gap (violet `Brain`) · platform-promoted `ArrowUpCircle` warning · "seen 4×" mono `whitespace-nowrap` right · recommendation `text-base` · evidence `text-xs text-subtle`.
  - **Recent failures P**: rows `p-2.5 rounded-card hover:bg-raised`: `XCircle` danger · task title + "agent · reason" `text-xs text-subtle` · time mono.
- Existing knowledge search (`use-knowledge-search`) → search input at top of Learnings P.

### 6.14 Artifacts — `pages/mission/tabs/artifacts-tab.tsx`, `components/workspace/artifact-*.tsx`
Workspace layout, horizontal.
- **List P** `w-[300px]`: "Artifacts · 9"; filter input **R** `h-[30px]`; groups by type with header `text-2xs text-subtle` (icon · label · count): Reports `FileText`, Findings `Search`, Responses `MessageSquare`, Data `Database`, Code `Code`. Items `px-2.5 py-2 rounded-[9px] hover:bg-raised`, selected `bg-sidebar-active`: title `text-sm` + "agent · time · size" `text-2xs text-subtle`.
- **Viewer P** `flex-1`: header `px-5 py-3`: type pill (violet tint, `shrink-0`) · title (truncate) · meta (truncate, `shrink`) · right `shrink-0`: Copy · Download (secondary). Body `max-w-[700px] mx-auto px-8 pt-4 pb-10` markdown/code via existing `markdown-renderer` (`prose` classes mapped to tokens: `prose-headings:text-foreground prose-p:text-text-2 prose-code:font-mono`).
- `streaming-artifact-card.tsx` → **R** with shimmer bar like running plan cards.

### 6.15 Console — `pages/mission/console.tsx` (via `stream-tab.tsx`)
Workspace layout: single **P** `flex-1 flex flex-col`.
- Toolbar `px-3 py-2.5 flex items-center gap-2.5 flex-wrap`: `Segmented` All / Execution / Chat / System (with counts) · agent filter dropdown **R** "All agents ▾" · right "● Live · 11 events" (`bg-success` dot; paused state `bg-subtle`).
- Rows `grid grid-cols-[76px_74px_minmax(150px,210px)_minmax(110px,150px)_minmax(0,1fr)] gap-3 px-2 py-1.5 rounded-[7px] hover:bg-raised font-mono text-xs`: time `text-subtle` · category (execution `text-brand-text`, chat `text-violet`, system `text-subtle`) · event type (warnings `text-warning`, errors `text-danger`) · source `text-muted-foreground` · message in `font-sans text-sm text-text-3`. Warning rows `bg-warning/[0.06]`, error rows `bg-danger/[0.06]`. All truncate.
- Click row → existing event detail (`event-log-panel.tsx`) as right **P** `w-[360px]`.

### 6.16 Costs — `pages/mission/tabs/costs-tab.tsx`, `components/drawer/cost-breakdown-panel.tsx`
Document layout.
- Header "Mission costs" + `Segmented` 7 days / 30 days / All time.
- 4 `StatCard`s: Total cost (sub "of $500 budget") · LLM calls ("across 6 agents") · Avg per call ("−8% vs prior") · Cache hit rate.
- Two columns:
  - **Cost by agent P**: rows `py-2.5`: name · "812 calls" mono subtle · cost mono `w-[70px] text-right`; 4px bar `bg-raised-2` fill `bg-brand` (relative to max).
  - Right stack: **Cache performance P** rows: name · 90px bar · % mono (≥50% success, ≥30% warning, else danger). **Insight callout** `rounded-panel border border-warning/20 bg-warning/[0.03] px-4 py-3.5 flex gap-3`: `AlertTriangle` warning · title "Output efficiency" · text with agent name mono.

### 6.17 Catalog — `pages/catalog.tsx`
Document layout.
- H1 "Agent catalog" `text-2xl font-semibold` + sub.
- Controls: search field (**P** surface, `h-[34px] rounded-[9px]`, `Search` icon, filters as you type) · `Segmented` All / Director / Specialist / System.
- Grid `minmax(300px,1fr) gap-gutter` of **P** `p-4 flex flex-col gap-3`: `IconTile lg` · name (truncate) + type `text-xs text-subtle` · chat-enabled `MessageSquare` icon · description `text-sm text-muted-foreground min-h-[38px]` · tool pills mono · right action **R**-button "＋ Add to mission" or "✓ On team" (when browsing from a mission context).

### 6.18 Admin — `pages/admin/layout.tsx` + children
Document layout.
- Sub-nav: underline tabs `flex gap-0.5 border-b border-border` items `px-2.5 pt-2 pb-2.5 text-sm border-b-[1.5px] -mb-px` (active `border-foreground text-foreground`, else `border-transparent text-muted-foreground`) — Catalog · Metrics · Token Economics · Config · Health · Users. (This is the one place an underline tab row is kept; it's within page content, not full-bleed.)
- **Metrics**: 6 `StatCard`s (Users, Missions, Executions, Total cost, Workflows, Active sessions) in `minmax(150px,1fr)`; two columns: Cost by agent (same as §6.16) and **Agent utilisation** P bar chart (bars `rounded-[5px_5px_2px_2px] bg-border-strong`, value mono above, label below).
- **Health / Config / Users / Token economics / Admin catalog**: tables follow the Runs table pattern (§6.6) inside P; forms follow §4.6 inputs; status via `StatusPill`.

### 6.19 Profile — `pages/profile.tsx`
Document layout `max-w-[600px]`: P sections "Account", "Appearance" (theme `Segmented`: Dark / Warm white), "Notifications".

### 6.20 Not found — `pages/not-found.tsx`
`EmptyState` with `Compass` icon, "Page not found", primary "Back to Home".

---

## 7. Status → token map (single source)

Create `src/lib/status-tone.ts` and use it everywhere instead of per-file colour maps:

```ts
export const missionTone = { active: 'success', paused: 'warning', archived: 'neutral' } as const
export const taskTone = {
  proposed: 'neutral', approved: 'brand', running: 'warning',
  completed: 'success', failed: 'danger', skipped: 'neutral', vetoed: 'neutral',
} as const
export const runTone = { running: 'warning', completed: 'success', failed: 'danger', cancelled: 'neutral', pending: 'neutral' } as const
export const consoleCategoryTone = { execution: 'brand', chat: 'violet', system: 'neutral' } as const
```

Replace hard-coded colour maps in: `plan-board-types.ts`, `chat-constants.ts`, `dashboard.tsx` (`STATUS_BADGE`), `runs-panel.tsx`, `run-detail-panel.tsx`, `console.tsx`, `knowledge-tab.tsx`, `badge.tsx` variants.

---

## 8. Motion

- Pulsing dot (`animate-pulse-dot`): running run indicator, active run card, run live summary, "writing" status.
- Shimmer bar (`animate-shimmer-x`): running plan card, streaming artifact.
- `Loader2 animate-spin`: plan pill, running column icon, running timeline step.
- `animate-card-enter`: keep on plan cards.
- Hover transitions: `transition-colors duration-150` only. No scale/translate on hover.
- Respect `prefers-reduced-motion`: add `motion-reduce:animate-none` to pulse/shimmer/spin.

---

## 9. New or changed data (backend / hooks)

| # | Need | Where | Suggested source |
|---|---|---|---|
| 9.1 | **Attention items** across missions: proposed plan tasks awaiting approval, workflows paused for human input, failed tasks needing retry. Also per-mission pending count for the sidebar badge. | Dashboard, Sidebar | New `GET /api/attention` → `{ mission_id, mission_name, kind: 'approval'|'human_input'|'retry', title, detail, created_at, href }[]`; or derive client-side from `use-mission-plan` + `use-workflow-run-status` per mission (acceptable for v1, N calls). Hook: `hooks/use-attention.ts`. |
| 9.2 | **Budget spent per mission** | Dashboard cards, Overview facts | Add `spent_usd` to mission list response (`types/mission.ts`), or reuse costs endpoint aggregated. |
| 9.3 | **Live agent state** (idle / thinking / tool name / done) | Overview Team, Chat roster | Already partly in SSE (`mission-stream.tsx` tool_call events used by roster). Expose a `useAgentStates(missionId)` selector from the stream context. |
| 9.4 | Greeting summary counts | Dashboard | Derived from missions + executions + 9.1. |
| 9.5 | Theme preference | Profile | Local only (`mc.theme`). Optional later: persist on user profile. |

Everything else maps to existing hooks: `use-missions`, `use-executions`, `use-mission-plan`, `use-team`, `use-context`, `use-mission-learnings`, `use-mission-intent`, `use-mission-artifacts`, `use-console`, `use-workflows`, `use-catalog`, `use-admin`.

---

## 10. QA checklist (run per PR, both themes)

**Themes**
- [ ] Toggle in sidebar footer and login switches instantly; persists on reload; no flash of wrong theme.
- [ ] No hard-coded hex / `slate-*` / `zinc-*` / `amber-*` / `emerald-*` classes left in touched files (`grep -rE "slate-|zinc-|#[0-9a-f]{6}" src/`).
- [ ] Warm-white: panels read as cream (`#fbf8f3`) on sand well (`#efe8de`) with a faint `#e7dfd2` edge; no pure white surfaces.
- [ ] Dark: panels `#0f0f11` on well `#070708`, no visible panel border.
- [ ] Switch knobs white in both themes; primary button text readable in both.

**Contrast** (WCAG AA 4.5:1 body, 3:1 large)
- [ ] `text-subtle` only for meta/labels ≥ 11px; never for body.
- [ ] Status text on `/10` tints passes in both themes (warm-white uses the deeper semantic values for this reason).

**Layout**
- [ ] No full-height `border-l/-r` except the sidebar edge; no `border-b` header strips inside workspaces.
- [ ] Panel gaps are 8px everywhere (`gap-gutter`, `px-2 pb-2`).
- [ ] At 1024 / 1280 / 1440 / 1920 widths: Chat hides roster < 960 and outputs < 1200; Workflow hides palette < 1100 and inspector < 960; Context hides history < 960; Runs table scrolls horizontally instead of collapsing; top-bar plan pill shortens < 1100; breadcrumb truncates and never overlaps actions.
- [ ] Sidebar items never compress (all `shrink-0`); sidebar nav scrolls vertically only.
- [ ] Mono used for every id, cost, duration, token count, timestamp, version, tool name.

**Behaviour parity**
- [ ] All existing routes still resolve; `missions/:id` still redirects to last tab.
- [ ] Plan approve/reject from card calls the same mutations as the detail panel; drag-and-drop still works.
- [ ] Chat threads, slash commands, ⌘↵ send unchanged.
- [ ] Run modal, settings drawer, notifications dropdown open and are restyled.
- [ ] Workflow editor: drag from palette, connect, select, save, run, schedule unchanged.

---

## 11. File change index

| File | Change |
|---|---|
| `index.html` | Remove `class="dark"`; add theme boot script |
| `package.json` | + `@fontsource/geist-mono` |
| `tailwind.config.js` | Replace `extend` (§2.2) |
| `src/index.css` | Replace (§2.1) |
| `src/stores/theme.ts` | **New** |
| `src/lib/status-tone.ts` | **New** |
| `src/lib/constants.ts` | Export grouped mission nav |
| `src/components/ui/button.tsx` | New variants/sizes |
| `src/components/ui/badge.tsx` | Restyle; state usage → StatusPill |
| `src/components/ui/card.tsx` | Panel + aliases |
| `src/components/ui/status-pill.tsx` | **New** |
| `src/components/ui/segmented.tsx` | **New** |
| `src/components/ui/icon-tile.tsx` | **New** |
| `src/components/ui/progress.tsx`, `switch.tsx`, `kbd.tsx` | **New** |
| `src/components/ui/input.tsx`, `textarea.tsx`, `stat-card.tsx`, `empty-state.tsx`, `avatar.tsx` | Restyle |
| `src/components/layout/app-shell.tsx` | Remove StatusBar; `bg-well` main |
| `src/components/layout/status-bar.tsx` | **Delete** |
| `src/components/layout/sidebar.tsx` | Rewrite (§5.2) |
| `src/components/layout/top-bar.tsx` | **New** (§5.3) |
| `src/components/layout/right-drawer.tsx`, `notification-dropdown.tsx` | Restyle to Panel |
| `src/pages/mission/layout.tsx` | Remove header + tab bar; use TopBar |
| `src/pages/**`, `src/components/{workspace,workflow,live,mission,knowledge,research,drawer,chat}/**` | Per §6 |
| `src/hooks/use-attention.ts` | **New** (§9.1) |

---

## 12. Out of scope / follow-ups

- ⌘K command palette behaviour (only the trigger is designed).
- Mobile (< 768px) layouts.
- A cool light theme (`light-neutral` exists in the design file but is not part of this plan).
- Persisting theme server-side.
