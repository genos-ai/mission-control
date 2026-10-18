import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

// Badge is for labels (a type, a version, a count). A state — success, failure,
// running — is a StatusPill, which carries a tone.
const badgeVariants = cva(
  'inline-flex h-[18px] items-center gap-1 rounded-sm px-1.5 text-2xs font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        default: 'bg-raised text-muted-foreground',
        outline: 'border border-border-strong text-muted-foreground',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}
