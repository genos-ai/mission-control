/**
 * Tone → Tailwind classes. Whole class literals, because Tailwind (and the
 * no-custom-classname lint rule) can only see classes written out in full.
 * Colours come from the theme tokens in index.css; nothing here is a colour value.
 */

import type { Tone } from './status-tone'

/** Text colour for an icon or label in a tone. */
export const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  info: 'text-info',
  brand: 'text-brand-text',
  violet: 'text-violet',
  neutral: 'text-subtle',
}

/** Solid background for a small status dot. */
export const TONE_DOT: Record<Tone, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  brand: 'bg-brand',
  violet: 'bg-violet',
  neutral: 'bg-muted-foreground/35',
}

/** Faint tinted fill and edge for a callout box in a tone. */
export const TONE_BOX: Record<Tone, string> = {
  success: 'border-success/20 bg-success/5',
  warning: 'border-warning/20 bg-warning/5',
  danger: 'border-danger/20 bg-danger/5',
  info: 'border-info/20 bg-info/5',
  brand: 'border-brand/20 bg-brand/5',
  violet: 'border-violet/20 bg-violet/5',
  neutral: 'border-panel-border bg-raised',
}
