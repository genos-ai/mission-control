import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'border border-border-strong bg-field text-foreground hover:bg-hover',
        ghost: 'text-muted-foreground hover:bg-raised hover:text-foreground',
        destructive: 'border border-danger/30 bg-danger/10 text-danger hover:bg-danger/15',
        link: 'text-brand-text underline-offset-4 hover:underline',
        pill: 'bg-raised text-text-3 hover:text-foreground',
      },
      size: {
        sm: 'h-[26px] rounded-chip px-2.5 text-xs',
        default: 'h-[30px] rounded-control px-3 text-sm',
        lg: 'h-[34px] rounded-control px-3.5 text-base',
        xl: 'h-[38px] rounded-md px-4 text-md',
        icon: 'h-[30px] w-[30px] rounded-control',
        'icon-sm': 'h-6 w-6 rounded-chip',
      },
    },
    // The pill is fully round; it must come after `size`, which sets its own radius.
    compoundVariants: [{ variant: 'pill', class: 'rounded-full' }],
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      className={cn(buttonVariants({ variant, size, className }))}
      ref={ref}
      {...props}
    />
  ),
)
Button.displayName = 'Button'

// eslint-disable-next-line react-refresh/only-export-components
export { Button, buttonVariants }
