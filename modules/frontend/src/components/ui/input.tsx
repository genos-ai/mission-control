import * as React from 'react'
import { cn } from '@/lib/cn'

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => (
    <input
      type={type}
      className={cn(
        'flex h-[38px] w-full rounded-md border border-border-strong bg-field px-3 text-md outline-none transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-subtle focus:border-brand/60 focus:ring-2 focus:ring-brand/15 disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      ref={ref}
      {...props}
    />
  ),
)
Input.displayName = 'Input'

export { Input }
